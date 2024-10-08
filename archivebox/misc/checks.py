__package__ = 'archivebox.misc'

import os
import sys

from rich import print

# DO NOT ADD ANY TOP-LEVEL IMPORTS HERE
# this file is imported by archivebox/__init__.py
# and any imports here will be imported by EVERYTHING else
# so this file should only be used for pure python checks
# that don't need to import other parts of ArchiveBox


def check_data_folder() -> None:
    from archivebox import DATA_DIR, ARCHIVE_DIR
    
    archive_dir_exists = os.access(ARCHIVE_DIR, os.R_OK) and ARCHIVE_DIR.is_dir()
    if not archive_dir_exists:
        print('[red][X] No archivebox index found in the current directory.[/red]', file=sys.stderr)
        print(f'    {DATA_DIR}', file=sys.stderr)
        print(file=sys.stderr)
        print('    [violet]Hint[/violet]: Are you running archivebox in the right folder?', file=sys.stderr)
        print('        cd path/to/your/archive/folder', file=sys.stderr)
        print('        archivebox [command]', file=sys.stderr)
        print(file=sys.stderr)
        print('    [violet]Hint[/violet]: To create a new archive collection or import existing data in this folder, run:', file=sys.stderr)
        print('        archivebox init', file=sys.stderr)
        raise SystemExit(2)
    
    
def check_migrations():
    from archivebox import DATA_DIR, CONSTANTS
    from ..index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]

    if pending_migrations:
        print('[red][X] This collection was created with an older version of ArchiveBox and must be upgraded first.[/red]')
        print(f'    {DATA_DIR}', file=sys.stderr)
        print(file=sys.stderr)
        print(f'    [violet]Hint:[/violet] To upgrade it to the latest version and apply the {len(pending_migrations)} pending migrations, run:', file=sys.stderr)
        print('        archivebox init', file=sys.stderr)
        raise SystemExit(3)

    CONSTANTS.SOURCES_DIR.mkdir(exist_ok=True)
    CONSTANTS.LOGS_DIR.mkdir(exist_ok=True)
    # CONSTANTS.CACHE_DIR.mkdir(exist_ok=True)
    (CONSTANTS.LIB_DIR / 'bin').mkdir(exist_ok=True, parents=True)
    (CONSTANTS.PERSONAS_DIR / 'Default').mkdir(exist_ok=True, parents=True)


def check_io_encoding():
    PYTHON_ENCODING = (sys.__stdout__ or sys.stdout or sys.__stderr__ or sys.stderr).encoding.upper().replace('UTF8', 'UTF-8')
            
    if PYTHON_ENCODING != 'UTF-8':
        print(f'[red][X] Your system is running python3 scripts with a bad locale setting: {PYTHON_ENCODING} (it should be UTF-8).[/red]', file=sys.stderr)
        print('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)', file=sys.stderr)
        print('    Or if you\'re using ubuntu/debian, run "dpkg-reconfigure locales"', file=sys.stderr)
        print('')
        print('    Confirm that it\'s fixed by opening a new shell and running:', file=sys.stderr)
        print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8', file=sys.stderr)
        raise SystemExit(2)
    
    # # hard errors: check python version
    # if sys.version_info[:3] < (3, 10, 0):
    #     print('[red][X] Python version is not new enough: {sys.version} (>3.10 is required)[/red]', file=sys.stderr)
    #     print('    See https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#python for help upgrading your Python installation.', file=sys.stderr)
    #     raise SystemExit(2)
    
    # # hard errors: check django version
    # if int(django.VERSION[0]) < 5:
    #     print('[red][X] Django version is not new enough: {django.VERSION[:3]} (>=5.0 is required)[/red]', file=sys.stderr)
    #     print('    Upgrade django using pip or your system package manager: pip3 install --upgrade django', file=sys.stderr)
    #     raise SystemExit(2)


def check_not_root():
    from archivebox.config.permissions import IS_ROOT, IN_DOCKER
    
    attempted_command = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else ''
    is_getting_help = '-h' in sys.argv or '--help' in sys.argv or 'help' in sys.argv[:2]
    is_getting_version = '--version' in sys.argv or 'version' in sys.argv[:2]
    is_installing = 'setup' in sys.argv[:2] or 'install' in sys.argv[:2]
    
    if IS_ROOT and not (is_getting_help or is_getting_version or is_installing):
        print('[red][!] ArchiveBox should never be run as root![/red]', file=sys.stderr)
        print('    For more information, see the security overview documentation:', file=sys.stderr)
        print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root', file=sys.stderr)
        
        if IN_DOCKER:
            print('[red][!] When using Docker, you must run commands with [green]docker run[/green] instead of [yellow3]docker exec[/yellow3], e.g.:', file=sys.stderr)
            print('        docker compose run archivebox {attempted_command}', file=sys.stderr)
            print(f'        docker run -it -v $PWD/data:/data archivebox/archivebox {attempted_command}', file=sys.stderr)
            print('        or:', file=sys.stderr)
            print(f'        docker compose exec --user=archivebox archivebox /bin/bash -c "archivebox {attempted_command}"', file=sys.stderr)
            print(f'        docker exec -it --user=archivebox <container id> /bin/bash -c "archivebox {attempted_command}"', file=sys.stderr)
        raise SystemExit(2)
