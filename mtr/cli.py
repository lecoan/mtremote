import os
import sys

import click

from mtr.config import ConfigError, ConfigLoader
from mtr.ssh import SSHClientWrapper, SSHError
from mtr.sync import RsyncSyncer, SftpSyncer, SyncError

DEFAULT_CONFIG_TEMPLATE = """# MTRemote Configuration
defaults:
  # 默认同步引擎
  # 选项: "rsync" (推荐), "sftp"
  sync: "rsync"
  
  exclude:
    - ".git/"
    - "__pycache__/"
    - "*.pyc"

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
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def cli(server, sync, dry_run, tty, init, command):
    """MTRemote: Sync and Execute code on remote server."""

    if init:
        _init_config()
        return

    if not command:
        click.echo(cli.get_help(click.get_current_context()))
        return

    # Join command parts back into a string
    remote_cmd = " ".join(command)

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
    except ConfigError as e:
        if console:
            console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        else:
            click.secho(f"Configuration Error: {e}", fg="red", err=True)
        sys.exit(1)

    server_conf = config.server_config
    host = server_conf.get("host")
    user = server_conf.get("user")
    key_filename = server_conf.get("key_filename")
    password = server_conf.get("password")
    remote_dir = server_conf.get("remote_dir")
    pre_cmd = server_conf.get("pre_cmd")

    if not host or not user:
        click.secho(
            "Error: 'host' and 'user' are required in server config.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    if console:
        console.print(f"[bold green]Target:[/bold green] {user}@{host} [{config.target_server}]")
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
                exclude=exclude,
            )
        elif engine == "sftp":
            syncer = SftpSyncer(
                local_dir=local_dir,
                remote_dir=remote_dir,
                host=host,
                user=user,
                key_filename=key_filename,
                password=password,
                exclude=exclude,
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
                else:
                    if is_interactive and console:
                        with console.status("[bold blue]Syncing code...", spinner="dots"):
                            syncer.sync()
                    else:
                        click.secho("Syncing code...", fg="blue")
                        syncer.sync()
            except SyncError as e:
                click.secho(f"Sync Failed: {e}", fg="red", err=True)
                sys.exit(1)

    # 3. Execute Command
    if not is_interactive:
        click.secho(f"Executing: {remote_cmd}", fg="blue")

    if dry_run:
        click.echo(f"[DryRun] Would run on {host}: {remote_cmd} (workdir={remote_dir})")
        return

    ssh = SSHClientWrapper(host, user, key_filename=key_filename, password=password)
    try:
        ssh.connect()

        if is_interactive:
            # Run interactive shell (full TTY support)
            exit_code = ssh.run_interactive_shell(remote_cmd, workdir=remote_dir, pre_cmd=pre_cmd)
            sys.exit(exit_code)
        else:
            # Run stream mode (for scripts/pipes)
            # pty=False ensures clean output for parsing (separates stdout/stderr if we implemented that,
            # but currently streams merged or just stdout. Let's keep pty=False to avoid control chars)
            stream = ssh.exec_command_stream(remote_cmd, workdir=remote_dir, pre_cmd=pre_cmd, pty=False)

            # Consume generator and print
            exit_code = 0
            try:
                while True:
                    line = next(stream)
                    click.echo(line, nl=False)
            except StopIteration as e:
                exit_code = e.value

            sys.exit(exit_code)

    except SSHError as e:
        click.secho(f"SSH Error: {e}", fg="red", err=True)
        sys.exit(1)
    finally:
        ssh.close()


if __name__ == "__main__":
    cli()
