__package__ = "archivebox.config"

import os
import sys
from datetime import UTC, datetime

import django
import django.db
from django.core.exceptions import ImproperlyConfigured
from rich.console import Console

from archivebox.misc import logging

from .common import get_config
from .constants import CONSTANTS

CONFIG = get_config()
os.environ.setdefault("ABXPKG_LIB_DIR", str(CONFIG.ABXPKG_LIB_DIR))

if not CONFIG.USE_COLOR:
    os.environ["NO_COLOR"] = "1"
if not CONFIG.SHOW_PROGRESS:
    os.environ["TERM"] = "dumb"

STDOUT = CONSOLE = Console()
STDERR = Console(stderr=True)
logging.CONSOLE = CONSOLE


DJANGO_SET_UP = False


def setup_django(check_db=False) -> None:
    from rich.panel import Panel

    from archivebox.misc.checks import check_not_inside_source_dir

    global DJANGO_SET_UP

    if DJANGO_SET_UP:
        # TODO: figure out why CLI entrypoints with init_pending are running this twice sometimes
        return

    check_not_inside_source_dir(CONSTANTS.DATA_DIR)

    # SQLite creates index.sqlite3 during django.setup()/migrate. Apply the
    # ArchiveBox file-mode policy before any DB connection can create the file,
    # otherwise a permissive parent umask can expose a just-created DB until a
    # later chmod runs.
    os.umask(0o777 - (int(CONFIG.OUTPUT_PERMISSIONS, base=8) | 0o111))

    # Third-party patches are only needed once Django/apps are about to load.
    # Keeping them out of archivebox.__init__ avoids paying Django/Daphne setup
    # cost for cheap CLI startup paths like `archivebox <cmd> --help`.
    import archivebox.misc.monkey_patches  # noqa: F401
    from archivebox.config.permissions import ARCHIVEBOX_GROUP, ARCHIVEBOX_USER, IS_ROOT, SudoPermission

    # if running as root, chown the data dir to the archivebox user to make sure it's accessible to the archivebox user
    if IS_ROOT and ARCHIVEBOX_USER != 0:
        with SudoPermission(uid=0):
            # running as root is a special case where it's ok to be a bit slower
            # make sure data dir is always owned by the correct user
            os.chown(CONSTANTS.DATA_DIR, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, follow_symlinks=False)
            if CONSTANTS.DATA_DIR.exists():
                for child in CONSTANTS.DATA_DIR.iterdir():
                    os.chown(child, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, follow_symlinks=False)

    # Suppress the "database access during app initialization" warning
    # This warning can be triggered during django.setup() but is safe to ignore
    # since we're doing intentional setup operations
    import warnings

    warnings.filterwarnings(
        "ignore",
        message=".*Accessing the database during app initialization.*",
        category=RuntimeWarning,
    )

    try:
        from django.core.management import call_command

        # Initialize the configured file-based database without running
        # migrations automatically; `archivebox init` owns migrations.
        try:
            django.setup()
        # User config and import errors are reported through one CLI message.
        except (ImproperlyConfigured, django.db.Error, ImportError, OSError, RuntimeError, ValueError) as e:
            is_using_meta_cmd = any(ignored_subcommand in sys.argv for ignored_subcommand in ("help", "version", "--help", "--version"))
            if not is_using_meta_cmd:
                # show error message to user only if they're not running a meta command / just trying to get help
                STDERR.print()
                STDERR.print(
                    Panel(
                        f"\n[red]{e.__class__.__name__}[/red]: [yellow]{e}[/yellow]\nPlease check your config and [blue]DATA_DIR[/blue] permissions.\n",
                        title="\n\n[red][X] Error while trying to load database![/red]",
                        subtitle="[grey53]NO WRITES CAN BE PERFORMED[/grey53]",
                        expand=False,
                        style="bold red",
                    ),
                )
                STDERR.print()
                import traceback

                traceback.print_exc()
            return

        from archivebox.core.settings_logging import ERROR_LOG as DEFAULT_ERROR_LOG

        # log startup message to the error log
        error_log = DEFAULT_ERROR_LOG
        with open(error_log, "a", encoding="utf-8") as f:
            command = " ".join(sys.argv)
            ts = datetime.now(UTC).strftime("%Y-%m-%d__%H:%M:%S")
            config = get_config()
            f.write(f"\n> {command}; TS={ts} VERSION={CONSTANTS.VERSION} IN_DOCKER={config.IN_DOCKER} IS_TTY={config.IS_TTY}\n")

        if check_db:
            # make sure the data dir is owned by a non-root user
            if CONSTANTS.DATA_DIR.stat().st_uid == 0 and not (IS_ROOT and ARCHIVEBOX_USER == 0):
                STDERR.print("[red][X] Error: ArchiveBox DATA_DIR cannot be owned by root![/red]")
                STDERR.print(f"    {CONSTANTS.DATA_DIR}")
                STDERR.print()
                STDERR.print("[violet]Hint:[/violet] Are you running archivebox in the right folder? (and as a non-root user?)")
                STDERR.print("    cd path/to/your/archive/data")
                STDERR.print("    archivebox [command]")
                STDERR.print()
                raise SystemExit(9)

            # Create cache table in DB if needed
            try:
                from django.core.cache import cache

                cache.get("test", None)
            except django.db.utils.OperationalError:
                call_command("createcachetable", verbosity=0)

            # if archivebox gets imported multiple times, we have to close
            # the sqlite3 whenever we init from scratch to avoid multiple threads
            # sharing the same connection by accident
            from django.db import connections

            for conn in connections.all():
                conn.close_if_unusable_or_obsolete()

            from archivebox.misc.db import database_display_location, database_exists

            assert database_exists(), (
                f"No database {database_display_location()} found for: {CONSTANTS.DATA_DIR} (Are you in an ArchiveBox collection directory?)"
            )

    except KeyboardInterrupt:
        DJANGO_SET_UP = False
        raise

    DJANGO_SET_UP = True
