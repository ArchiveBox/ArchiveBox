__package__ = 'archivebox.config'

import os
import sys

from datetime import datetime, timezone

from rich.progress import Progress
from rich.console import Console

import django

from archivebox.misc import logging

from . import CONSTANTS
from .common import SHELL_CONFIG


if not SHELL_CONFIG.USE_COLOR:
    os.environ['NO_COLOR'] = '1'
if not SHELL_CONFIG.SHOW_PROGRESS:
    os.environ['TERM'] = 'dumb'

# recreate rich console obj based on new config values
STDOUT = CONSOLE = Console()
STDERR = Console(stderr=True)
logging.CONSOLE = CONSOLE


INITIAL_STARTUP_PROGRESS = None
INITIAL_STARTUP_PROGRESS_TASK = 0

def bump_startup_progress_bar(advance=1):
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    if INITIAL_STARTUP_PROGRESS:
        INITIAL_STARTUP_PROGRESS.update(INITIAL_STARTUP_PROGRESS_TASK, advance=advance)   # type: ignore


def setup_django_minimal():
    # sys.path.append(str(CONSTANTS.PACKAGE_DIR))
    # os.environ.setdefault('ARCHIVEBOX_DATA_DIR', str(CONSTANTS.DATA_DIR))
    # os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    # django.setup()
    raise Exception('dont use this anymore')

DJANGO_SET_UP = False


def setup_django(check_db=False, in_memory_db=False) -> None:
    from rich.panel import Panel
    
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    global DJANGO_SET_UP

    if DJANGO_SET_UP:
        # raise Exception('django is already set up!')
        # TODO: figure out why CLI entrypoints with init_pending are running this twice sometimes
        return

    with Progress(transient=True, expand=True, console=STDERR) as INITIAL_STARTUP_PROGRESS:
        INITIAL_STARTUP_PROGRESS_TASK = INITIAL_STARTUP_PROGRESS.add_task("[green]Loading modules...", total=25, visible=True)
        
        from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, SudoPermission
    
        # if running as root, chown the data dir to the archivebox user to make sure it's accessible to the archivebox user
        if IS_ROOT and ARCHIVEBOX_USER != 0:
            with SudoPermission(uid=0):
                # running as root is a special case where it's ok to be a bit slower
                # make sure data dir is always owned by the correct user
                os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{CONSTANTS.DATA_DIR}" 2>/dev/null')
                os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{CONSTANTS.DATA_DIR}"/* 2>/dev/null')

        bump_startup_progress_bar()
        try:
            from django.core.management import call_command
                
            bump_startup_progress_bar()

            if in_memory_db:
                raise Exception('dont use this anymore')
            
                # some commands (e.g. oneshot) dont store a long-lived sqlite3 db file on disk.
                # in those cases we create a temporary in-memory db and run the migrations
                # immediately to get a usable in-memory-database at startup
                os.environ.setdefault("ARCHIVEBOX_DATABASE_NAME", ":memory:")
                django.setup()
                
                bump_startup_progress_bar()
                call_command("migrate", interactive=False, verbosity=0)
            else:
                # Otherwise use default sqlite3 file-based database and initialize django
                # without running migrations automatically (user runs them manually by calling init)
                try:
                    django.setup()
                except Exception as e:
                    bump_startup_progress_bar(advance=1000)
                    
                    is_using_meta_cmd = any(ignored_subcommand in sys.argv for ignored_subcommand in ('help', 'version', '--help', '--version'))
                    if not is_using_meta_cmd:
                        # show error message to user only if they're not running a meta command / just trying to get help
                        STDERR.print()
                        STDERR.print(Panel(
                            f'\n[red]{e.__class__.__name__}[/red]: [yellow]{e}[/yellow]\nPlease check your config and [blue]DATA_DIR[/blue] permissions.\n',
                            title='\n\n[red][X] Error while trying to load database![/red]',
                            subtitle='[grey53]NO WRITES CAN BE PERFORMED[/grey53]',
                            expand=False,
                            style='bold red',
                        ))
                        STDERR.print()
                        STDERR.print_exception(show_locals=False)
                    return
            
            bump_startup_progress_bar()

            from django.conf import settings
            
            # log startup message to the error log
            with open(settings.ERROR_LOG, "a", encoding='utf-8') as f:
                command = ' '.join(sys.argv)
                ts = datetime.now(timezone.utc).strftime('%Y-%m-%d__%H:%M:%S')
                f.write(f"\n> {command}; TS={ts} VERSION={CONSTANTS.VERSION} IN_DOCKER={SHELL_CONFIG.IN_DOCKER} IS_TTY={SHELL_CONFIG.IS_TTY}\n")

            if check_db:
                # make sure the data dir is owned by a non-root user
                if CONSTANTS.DATA_DIR.stat().st_uid == 0:
                    STDERR.print('[red][X] Error: ArchiveBox DATA_DIR cannot be owned by root![/red]')
                    STDERR.print(f'    {CONSTANTS.DATA_DIR}')
                    STDERR.print()
                    STDERR.print('[violet]Hint:[/violet] Are you running archivebox in the right folder? (and as a non-root user?)')
                    STDERR.print('    cd path/to/your/archive/data')
                    STDERR.print('    archivebox [command]')
                    STDERR.print()
                    raise SystemExit(9)
                
                # Create cache table in DB if needed
                try:
                    from django.core.cache import cache
                    cache.get('test', None)
                except django.db.utils.OperationalError:
                    call_command("createcachetable", verbosity=0)

                bump_startup_progress_bar()

                # if archivebox gets imported multiple times, we have to close
                # the sqlite3 whenever we init from scratch to avoid multiple threads
                # sharing the same connection by accident
                from django.db import connections
                for conn in connections.all():
                    conn.close_if_unusable_or_obsolete()

                sql_index_path = CONSTANTS.DATABASE_FILE
                assert os.access(sql_index_path, os.F_OK), (
                    f'No database file {sql_index_path} found in: {CONSTANTS.DATA_DIR} (Are you in an ArchiveBox collection directory?)')

                bump_startup_progress_bar()

                # https://docs.pydantic.dev/logfire/integrations/django/ Logfire Debugging
                # if settings.DEBUG_LOGFIRE:
                #     from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
                #     SQLite3Instrumentor().instrument()

                #     import logfire

                #     logfire.configure()
                #     logfire.instrument_django(is_sql_commentor_enabled=True)
                #     logfire.info(f'Started ArchiveBox v{CONSTANTS.VERSION}', argv=sys.argv)

        except KeyboardInterrupt:
            raise SystemExit(2)
        
    DJANGO_SET_UP = True

    INITIAL_STARTUP_PROGRESS = None
    INITIAL_STARTUP_PROGRESS_TASK = None
