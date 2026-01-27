import click
import os
import sys
from mtr.config import ConfigLoader, ConfigError
from mtr.ssh import SSHClientWrapper, SSHError
from mtr.sync import RsyncSyncer, SftpSyncer, SyncError

DEFAULT_CONFIG_TEMPLATE = """# MTRemote Configuration
defaults:
  sync: "rsync"
  exclude:
    - ".git/"
    - "__pycache__/"
    - "*.pyc"

servers:
  # Example Server
  dev-node:
    host: "192.168.1.100"
    user: "your_username"
    key_filename: "~/.ssh/id_rsa"
    remote_dir: "/home/your_username/projects/current_project"
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


@click.command(
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True)
)
@click.option("-s", "--server", help="Target server alias")
@click.option("--sync/--no-sync", default=True, help="Enable/Disable code sync")
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
@click.option(
    "--init", is_flag=True, help="Initialize a configuration file in current directory"
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def cli(server, sync, dry_run, init, command):
    """MTRemote: Sync and Execute code on remote server."""

    if init:
        _init_config()
        return

    if not command:
        click.echo(cli.get_help(click.get_current_context()))
        return

    # Join command parts back into a string
    remote_cmd = " ".join(command)

    # 1. Load Configuration
    try:
        loader = ConfigLoader()
        config = loader.load(server_name=server)
    except ConfigError as e:
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

    click.secho(f"Target: {user}@{host} [{config.target_server}]", fg="green")

    # 2. Sync Code
    if sync:
        click.secho("Syncing code...", fg="blue")
        local_dir = os.getcwd()
        # Ensure remote_dir is set
        if not remote_dir:
            # Fallback? Maybe ~/.mtr_workspace/{project_name}?
            # For now enforce it.
            click.secho("Error: 'remote_dir' is required for sync.", fg="red", err=True)
            sys.exit(1)

        # Resolve exclude
        exclude = config.global_defaults.get("exclude", []) + server_conf.get(
            "exclude", []
        )

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
                    syncer.sync()
            except SyncError as e:
                click.secho(f"Sync Failed: {e}", fg="red", err=True)
                sys.exit(1)

    # 3. Execute Command
    click.secho(f"Executing: {remote_cmd}", fg="blue")

    if dry_run:
        click.echo(f"[DryRun] Would run on {host}: {remote_cmd} (workdir={remote_dir})")
        return

    ssh = SSHClientWrapper(host, user, key_filename=key_filename, password=password)
    try:
        ssh.connect()

        # Stream output
        stream = ssh.exec_command_stream(
            remote_cmd, workdir=remote_dir, pre_cmd=pre_cmd
        )

        # Consume generator and print
        # Also catch return value
        exit_code = 0
        try:
            while True:
                line = next(stream)
                click.echo(line, nl=False)  # nl=False because line usually has \n
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
