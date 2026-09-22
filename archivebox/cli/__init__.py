__package__ = "archivebox.cli"
__command__ = "archivebox"
import os
import sys
from importlib import import_module

import rich_click as click
from rich.console import Console

from archivebox.config.version import VERSION

STDERR = Console(stderr=True)


if "--debug" in sys.argv:
    os.environ["DEBUG"] = "True"
    sys.argv.remove("--debug")

# Universal `--init` flag: when passed to ANY subcommand (e.g. `archivebox server --init`,
# `archivebox add --init`, `archivebox shell --init`), run a `quick` archivebox init before
# the subcommand executes. `--quick-init` is the old server spelling. Strip either from
# argv here so each subcommand's own click parser never sees it. Ignored for `help` and
# `init` themselves.
if "--init" in sys.argv or "--quick-init" in sys.argv:
    sys.argv = [arg for arg in sys.argv if arg not in ("--init", "--quick-init")]
    os.environ["ARCHIVEBOX_WANTS_INIT"] = "1"


class ArchiveBoxGroup(click.Group):
    """lazy loading click group for archivebox commands"""

    meta_commands = {
        "help": "archivebox.cli.archivebox_help.main",
        "version": "archivebox.cli.archivebox_version.main",
        "mcp": "archivebox.cli.archivebox_mcp.main",
        "oneshot": "archivebox.cli.archivebox_oneshot.main",
    }
    setup_commands = {
        "init": "archivebox.cli.archivebox_init.main",
        "install": "archivebox.cli.archivebox_install.main",
    }
    # Model commands (CRUD operations via subcommands)
    model_commands = {
        "crawl": "archivebox.cli.archivebox_crawl.main",
        "snapshot": "archivebox.cli.archivebox_snapshot.main",
        "archiveresult": "archivebox.cli.archivebox_archiveresult.main",
        "tag": "archivebox.cli.archivebox_tag.main",
        "binary": "archivebox.cli.archivebox_binary.main",
        "process": "archivebox.cli.archivebox_process.main",
        "machine": "archivebox.cli.archivebox_machine.main",
        "persona": "archivebox.cli.archivebox_persona.main",
    }
    archive_commands = {
        # High-level commands
        "add": "archivebox.cli.archivebox_add.main",
        "extract": "archivebox.cli.archivebox_extract.main",
        "list": "archivebox.cli.archivebox_list.main",
        "remove": "archivebox.cli.archivebox_remove.main",
        "run": "archivebox.cli.archivebox_run.main",
        "update": "archivebox.cli.archivebox_update.main",
        "status": "archivebox.cli.archivebox_status.main",
        "search": "archivebox.cli.archivebox_search.main",
        "config": "archivebox.cli.archivebox_config.main",
        "schedule": "archivebox.cli.archivebox_schedule.main",
        "server": "archivebox.cli.archivebox_server.main",
        "shell": "archivebox.cli.archivebox_shell.main",
        "manage": "archivebox.cli.archivebox_manage.main",
        # Introspection commands
        "pluginmap": "archivebox.cli.archivebox_pluginmap.main",
    }
    all_subcommands = {
        **meta_commands,
        **setup_commands,
        **model_commands,
        **archive_commands,
    }
    renamed_commands = {
        "setup": "install",
        "import": "add",
        "archive": "add",
    }

    @classmethod
    def get_canonical_name(cls, cmd_name):
        return cls.renamed_commands.get(cmd_name, cmd_name)

    @classmethod
    def _needs_django_for_lazy_import(cls, cmd_name: str) -> bool:
        wants_help = any(arg in ("-h", "--help", "--version") for arg in sys.argv[1:])
        return not wants_help and (cmd_name in cls.archive_commands or cmd_name in cls.model_commands)

    @classmethod
    def _setup_django_for_lazy_import(cls, cmd_name: str) -> None:
        if not cls._needs_django_for_lazy_import(cmd_name):
            return

        from django.apps import apps

        if apps.ready:
            return

        from archivebox.config.django import setup_django

        setup_django()

    def get_command(self, ctx, cmd_name):
        # handle renamed commands
        if cmd_name in self.renamed_commands:
            new_name = self.renamed_commands[cmd_name]
            STDERR.print(
                f" [violet]Hint:[/violet] `archivebox {cmd_name}` has been renamed to `archivebox {new_name}`",
            )
            cmd_name = new_name
            ctx.invoked_subcommand = cmd_name

        # handle lazy loading of commands
        if cmd_name in self.all_subcommands:
            self._setup_django_for_lazy_import(cmd_name)
            return self._lazy_load(cmd_name)

        # fall-back to using click's default command lookup
        return super().get_command(ctx, cmd_name)

    @classmethod
    def _lazy_load(cls, cmd_name_or_path):
        import_path = cls.all_subcommands.get(cmd_name_or_path)
        if import_path is None:
            import_path = cmd_name_or_path
        modname, funcname = import_path.rsplit(".", 1)

        mod = import_module(modname)
        func = vars(mod)[funcname]

        if func.__doc__ is None:
            raise ValueError(f"lazy loading of {import_path} failed - no docstring found on method")

        return func


@click.group(cls=ArchiveBoxGroup, invoke_without_command=True)
@click.option("--help", "-h", is_flag=True, help="Show help")
@click.version_option(VERSION, "-v", "--version", package_name="archivebox", message="%(version)s")
@click.pass_context
def cli(ctx, help=False):
    """ArchiveBox: The self-hosted internet archive"""

    subcommand = ArchiveBoxGroup.get_canonical_name(ctx.invoked_subcommand)

    # if --help is passed or no subcommand is given, show custom help message
    if help or ctx.invoked_subcommand is None:
        ctx.invoke(ctx.command.get_command(ctx, "help"))

    # if the subcommand is in archive_commands or model_commands,
    # then we need to set up the django environment and check that we're in a valid data folder
    wants_help = any(arg in ("-h", "--help", "--version") for arg in sys.argv[1:])
    if not wants_help and (subcommand in ArchiveBoxGroup.archive_commands or subcommand in ArchiveBoxGroup.model_commands):
        try:
            if subcommand == "server":
                run_in_debug = "--reload" in sys.argv or os.environ.get("DEBUG") in ("1", "true", "True", "TRUE", "yes")
                if run_in_debug:
                    os.environ["ARCHIVEBOX_RUNSERVER"] = "1"
                    if "--reload" in sys.argv:
                        os.environ["ARCHIVEBOX_AUTORELOAD"] = "1"

            from archivebox.config.django import setup_django
            from archivebox.misc.checks import check_data_folder, check_migrations

            setup_django()
            if os.environ.get("ARCHIVEBOX_WANTS_INIT") == "1" and subcommand not in ("init", "help"):
                # Universal `--init` was passed: build/upgrade the data folder before
                # the regular preflight runs, so it succeeds on a fresh dir and an
                # out-of-date schema both. Drop the env var afterwards so spawned
                # subprocesses (supervisord workers, daphne, runner, etc.) inherit
                # a clean env and don't re-trigger init in every child.
                from archivebox.cli.archivebox_init import init as archivebox_init

                archivebox_init(quick=True)
                os.environ.pop("ARCHIVEBOX_WANTS_INIT", None)
            check_data_folder()
            if subcommand != "update":
                check_migrations(auto_apply=True)
        except Exception as e:
            STDERR.print(f"[red][X] Error setting up Django or checking data folder: {e}[/red]")
            if subcommand not in ("manage", "shell"):  # not all management commands need django to be setup beforehand
                raise


def main(args=None, prog_name=None):
    from archivebox.config.constants import CONSTANTS

    os.environ.setdefault("ABX_PLUGINS_DIR", str(CONSTANTS.USER_PLUGINS_DIR))

    # show `docker run archivebox xyz` in help messages if running in docker
    IN_DOCKER = os.environ.get("IN_DOCKER", False) in ("1", "true", "True", "TRUE", "yes")
    IS_TTY = sys.stdin.isatty()
    prog_name = prog_name or (f"docker compose run{'' if IS_TTY else ' -T'} archivebox" if IN_DOCKER else "archivebox")

    previous_unraisablehook = sys.unraisablehook

    def ignore_shutdown_unraisable(unraisable):
        if isinstance(unraisable.exc_value, (KeyboardInterrupt, SystemExit)):
            return
        previous_unraisablehook(unraisable)

    sys.unraisablehook = ignore_shutdown_unraisable
    try:
        cli(args=args, prog_name=prog_name, standalone_mode=False)
    except click.Abort:
        STDERR.print("\n[red][X] Got CTRL+C. Exiting...[/red]")
        raise SystemExit(130) from None
    except click.ClickException as err:
        err.show()
        raise SystemExit(err.exit_code) from None
    except click.exceptions.Exit as err:
        raise SystemExit(err.exit_code) from None
    except KeyboardInterrupt:
        STDERR.print("\n[red][X] Got CTRL+C. Exiting...[/red]")
        raise SystemExit(130) from None
    finally:
        sys.unraisablehook = previous_unraisablehook


if __name__ == "__main__":
    main()
