import os
import sys
from datetime import datetime

import click

from mtr.config import ConfigError, ConfigLoader
from mtr.logger import LogLevel, get_logger, setup_logging
from mtr.ssh import SSHClientWrapper, SSHError
from mtr.sync import RsyncSyncer, SftpSyncer, SyncError

DEFAULT_CONFIG_TEMPLATE = """# MTRemote Configuration
defaults:
  # 默认同步引擎
  # 选项: "rsync" (推荐), "sftp"
  sync: "rsync"

  # 是否尊重 .gitignore 文件（仅 rsync 模式支持）
  # 设置为 true 时，rsync 会自动读取项目根目录的 .gitignore 并排除匹配的文件
  # SFTP 模式不支持此选项，如启用会报错
  respect_gitignore: true

  exclude:
    - ".git/"
    - "__pycache__/"
    - "*.pyc"

  # 默认下载位置（可选，使用 --get 时生效）
  # download_dir: "./downloads"

servers:
  # === 服务器示例 ===
  dev-node:
    host: "192.168.1.100"
    user: "your_username"
    key_filename: "~/.ssh/id_rsa"
    remote_dir: "/home/your_username/projects/current_project"

    # 预设命令 (可选)
    # pre_cmd: "source ~/.bashrc && conda activate myenv"

    # 密码认证 (可选)
    # password: "secret"

    # 强制同步引擎 (可选)
    # sync: "sftp"

    # 该服务器的下载位置（可选，覆盖 defaults）
    # download_dir: "./backups/dev-node"
  """


def _init_config():
    """Initialize .mtr/config.yaml in current directory."""
    mtr_dir = os.path.join(os.getcwd(), ".mtr")
    config_file = os.path.join(mtr_dir, "config.yaml")

    if os.path.exists(config_file):
        click.secho(f"Configuration already exists at {config_file}", fg="yellow")
        return

    if not os.path.exists(mtr_dir):
        os.makedirs(mtr_dir)
        click.echo(f"Created directory: {mtr_dir}")

    with open(config_file, "w") as f:
        f.write(DEFAULT_CONFIG_TEMPLATE)

    click.secho(f"Created configuration: {config_file}", fg="green")
    click.echo("Please edit it to match your environment.")


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option("-s", "--server", help="Target server alias")
@click.option("--sync/--no-sync", default=True, help="Enable/Disable code sync")
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
@click.option("--tty/--no-tty", default=True, help="Force enable/disable TTY")
@click.option("--init", is_flag=True, help="Initialize a configuration file in current directory")
@click.option("--enable-log", is_flag=True, help="Enable logging to file")
@click.option("--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)")
@click.option("--log-file", help="Path to log file (default: ./.mtr/logs/mtr_YYYYMMDD_HHMMSS.log)")
@click.option("--get", "remote_get_path", help="Remote path to download from")
@click.option("--to", "local_dest_path", help="Local destination path for download (optional)")
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def cli(server, sync, dry_run, tty, init, enable_log, log_level, log_file, remote_get_path, local_dest_path, command):
    """MTRemote: Sync and Execute code on remote server."""

    # Get logger instance (will be no-op if not setup)
    logger = get_logger()

    # Setup logging if enabled
    if enable_log:
        if not log_file:
            # Generate default log file path: ./.mtr/logs/mtr_YYYYMMDD_HHMMSS.log
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(os.getcwd(), ".mtr/logs")
            log_file = os.path.join(log_dir, f"mtr_{timestamp}.log")

        try:
            level = LogLevel.from_string(log_level)
            setup_logging(log_file, level)
        except ValueError:
            click.secho(f"Warning: Invalid log level '{log_level}', using INFO", fg="yellow")
            setup_logging(log_file, LogLevel.INFO)

        # Re-get logger after setup to use the real logger instead of no-op
        logger = get_logger()

    if init:
        logger = get_logger()
        _init_config()
        logger.info("Initialized configuration file", module="mtr.cli")
        return

    # Handle --get mode
    cli_dest = local_dest_path

    if not command and not remote_get_path:
        click.echo(cli.get_help(click.get_current_context()))
        return

    # Join command parts back into a string
    remote_cmd = " ".join(command)

    logger.info(f"Starting mtr with command: {remote_cmd}", module="mtr.cli")
    logger.debug(f"Options: server={server}, sync={sync}, dry_run={dry_run}, tty={tty}", module="mtr.cli")

    # Check for interactive mode (TTY)
    # Interactive if: TTY is enabled by flag AND stdout is a real terminal
    is_interactive = tty and sys.stdout.isatty()

    # Import rich if interactive
    console = None
    if is_interactive:
        try:
            from rich.console import Console

            console = Console()
        except ImportError:
            is_interactive = False  # Fallback if rich is missing (should not happen with dependencies)

    # 1. Load Configuration
    try:
        loader = ConfigLoader()
        config = loader.load(server_name=server)
        logger.info(f"Loaded configuration, target server: {config.target_server}", module="mtr.config")
    except ConfigError as e:
        logger.error(f"Configuration error: {e}", module="mtr.config")
        if console:
            console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        else:
            click.secho(f"Configuration Error: {e}", fg="red", err=True)
        sys.exit(1)

    server_conf = config.server_config
    host = server_conf.get("host")
    port = server_conf.get("port", 22)
    user = server_conf.get("user")
    key_filename = server_conf.get("key_filename")
    password = server_conf.get("password")
    remote_dir = server_conf.get("remote_dir")
    pre_cmd = server_conf.get("pre_cmd")

    if not host or not user:
        logger.error("Missing required config: host or user", module="mtr.cli")
        click.secho(
            "Error: 'host' and 'user' are required in server config.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    auth_method = "key" if key_filename else ("password" if password else "none")
    logger.info(f"Connecting to {host} as {user} (auth: {auth_method})", module="mtr.ssh")

    if console:
        console.print(
            f"🎯 [bold green]Target:[/bold green] {user}@{host}\t 🔖 [bold green]Tag[/bold green]: {config.target_server} "
        )
    else:
        click.secho(f"Target: {user}@{host} [{config.target_server}]", fg="green")

    # 2. Sync Code
    if sync:
        local_dir = os.getcwd()
        # Ensure remote_dir is set
        if not remote_dir:
            click.secho("Error: 'remote_dir' is required for sync.", fg="red", err=True)
            sys.exit(1)

        # Resolve exclude
        exclude = config.global_defaults.get("exclude", []) + server_conf.get("exclude", [])

        # Get respect_gitignore setting
        respect_gitignore = config.get_respect_gitignore()

        # Determine engine
        engine = server_conf.get("sync", config.global_defaults.get("sync", "rsync"))

        if engine == "rsync":
            syncer = RsyncSyncer(
                local_dir=local_dir,
                remote_dir=remote_dir,
                host=host,
                user=user,
                key_filename=key_filename,
                password=password,
                port=port,
                exclude=exclude,
                respect_gitignore=respect_gitignore,
            )
        elif engine == "sftp":
            syncer = SftpSyncer(
                local_dir=local_dir,
                remote_dir=remote_dir,
                host=host,
                user=user,
                key_filename=key_filename,
                password=password,
                port=port,
                exclude=exclude,
                respect_gitignore=respect_gitignore,
            )
        else:
            click.secho(
                f"Warning: Sync engine '{engine}' not supported yet. Fallback/Skipping.",
                fg="yellow",
            )
            syncer = None

        if syncer:
            try:
                if dry_run:
                    click.echo(f"[DryRun] Would sync {local_dir} -> {remote_dir}")
                    logger.info(f"[DryRun] Would sync {local_dir} -> {remote_dir}", module="mtr.sync")
                else:
                    if is_interactive and console:
                        # TTY mode: single line real-time update using Rich Live
                        from rich.live import Live
                        from rich.text import Text

                        with Live(Text("Starting sync...", style="blue"), refresh_per_second=10) as live:

                            def show_sync_progress(filename):
                                # Get relative path for cleaner display
                                rel_path = os.path.relpath(filename, local_dir)
                                live.update(Text(f"Syncing: {rel_path}", style="blue"))

                            syncer.sync(show_progress=True, progress_callback=show_sync_progress)
                            live.update(Text("Sync completed!", style="green"))
                    else:
                        # no_tty mode: print each file on new line
                        def show_sync_progress(filename):
                            rel_path = os.path.relpath(filename, local_dir)
                            click.echo(f"Syncing: {rel_path}")

                        click.secho("Syncing code...", fg="blue")
                        syncer.sync(show_progress=True, progress_callback=show_sync_progress)
                        click.secho("Sync completed!", fg="green")
                    logger.info(f"Sync completed: {local_dir} -> {remote_dir}", module="mtr.sync")
            except SyncError as e:
                logger.error(f"Sync failed: {e}", module="mtr.sync")
                click.secho(f"Sync Failed: {e}", fg="red", err=True)
                sys.exit(1)

    # 3. Download from remote (if --get is specified)
    if remote_get_path:
        # Resolve relative remote path from remote_dir
        if not remote_get_path.startswith("/"):
            if not remote_dir:
                click.secho("Error: 'remote_dir' is required for relative --get path.", fg="red", err=True)
                sys.exit(1)
            remote_get_path = os.path.join(remote_dir, remote_get_path)

        # Resolve local destination path
        if cli_dest:
            local_dest = cli_dest
        else:
            # Use config: server > defaults > current directory
            download_base = server_conf.get("download_dir") or config.global_defaults.get("download_dir") or "."
            remote_basename = os.path.basename(remote_get_path.rstrip("/"))
            local_dest = os.path.join(download_base, remote_basename)

        # Expand user path
        local_dest = os.path.expanduser(local_dest)

        # Resolve exclude
        exclude = config.global_defaults.get("exclude", []) + server_conf.get("exclude", [])

        # Get respect_gitignore setting
        respect_gitignore = config.get_respect_gitignore()

        # Determine engine
        engine = server_conf.get("sync", config.global_defaults.get("sync", "rsync"))

        if engine == "rsync":
            syncer = RsyncSyncer(
                local_dir=".",  # Not used for download
                remote_dir=".",  # Not used for download
                host=host,
                user=user,
                key_filename=key_filename,
                password=password,
                port=port,
                exclude=exclude,
                respect_gitignore=respect_gitignore,
            )
        elif engine == "sftp":
            syncer = SftpSyncer(
                local_dir=".",  # Not used for download
                remote_dir=".",  # Not used for download
                host=host,
                user=user,
                key_filename=key_filename,
                password=password,
                port=port,
                exclude=exclude,
                respect_gitignore=respect_gitignore,
            )
        else:
            click.secho(
                f"Warning: Sync engine '{engine}' not supported yet.",
                fg="yellow",
            )
            sys.exit(1)

        try:
            if dry_run:
                click.echo(f"[DryRun] Would download {remote_get_path} -> {local_dest}")
                logger.info(f"[DryRun] Would download {remote_get_path} -> {local_dest}", module="mtr.sync")
            else:
                if is_interactive and console:
                    # TTY mode: single line real-time update using Rich Live
                    from rich.live import Live
                    from rich.text import Text

                    with Live(Text("Starting download...", style="blue"), refresh_per_second=10) as live:

                        def show_download_progress(filename):
                            live.update(Text(f"Downloading: {filename}", style="blue"))

                        syncer.download(
                            remote_get_path, local_dest, show_progress=True, progress_callback=show_download_progress
                        )
                        live.update(Text("Download completed!", style="green"))
                    console.print(f"✅ [green]Downloaded:[/green] {remote_get_path} -> {local_dest}")
                else:
                    # no_tty mode: print each file on new line
                    def show_download_progress(filename):
                        click.echo(f"Downloading: {filename}")

                    click.secho(f"Downloading {remote_get_path}...", fg="blue")
                    syncer.download(remote_get_path, local_dest, show_progress=True, progress_callback=show_download_progress)
                    click.secho(f"Download completed: {local_dest}", fg="green")
                logger.info(f"Download completed: {remote_get_path} -> {local_dest}", module="mtr.sync")
        except SyncError as e:
            logger.error(f"Download failed: {e}", module="mtr.sync")
            click.secho(f"Download Failed: {e}", fg="red", err=True)
            sys.exit(1)

        # Download mode doesn't execute commands
        return

    # 4. Execute Command
    if not is_interactive:
        click.secho(f"Executing: {remote_cmd}", fg="blue")

    if dry_run:
        click.echo(f"[DryRun] Would run on {host}: {remote_cmd} (workdir={remote_dir})")
        return

    ssh = SSHClientWrapper(host, user, port=port, key_filename=key_filename, password=password)
    try:
        ssh.connect()
        logger.info(f"SSH connection established to {host}", module="mtr.ssh")

        if is_interactive:
            # Run interactive shell (full TTY support)
            logger.info(f"Executing interactive command: {remote_cmd}", module="mtr.cli")
            exit_code = ssh.run_interactive_shell(remote_cmd, workdir=remote_dir, pre_cmd=pre_cmd)
            logger.info(f"Command completed with exit code: {exit_code}", module="mtr.cli")
            sys.exit(exit_code)
        else:
            # Run stream mode (for scripts/pipes)
            # pty=False ensures clean output for parsing (separates stdout/stderr if we implemented that,
            # but currently streams merged or just stdout. Let's keep pty=False to avoid control chars)
            logger.info(f"Executing command: {remote_cmd}", module="mtr.cli")
            stream = ssh.exec_command_stream(remote_cmd, workdir=remote_dir, pre_cmd=pre_cmd, pty=False)

            # Consume generator and print
            exit_code = 0
            try:
                while True:
                    line = next(stream)
                    click.echo(line, nl=False)
            except StopIteration as e:
                exit_code = e.value

            logger.info(f"Command completed with exit code: {exit_code}", module="mtr.cli")
            sys.exit(exit_code)

    except SSHError as e:
        logger.error(f"SSH error: {e}", module="mtr.ssh")
        click.secho(f"SSH Error: {e}", fg="red", err=True)
        sys.exit(1)
    finally:
        logger.info("Closing SSH connection", module="mtr.ssh")
        ssh.close()


if __name__ == "__main__":
    cli()
