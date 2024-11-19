__package__ = 'archivebox.misc'

import os
import sys
from pathlib import Path

from rich import print
from rich.panel import Panel

# DO NOT ADD ANY TOP-LEVEL IMPORTS HERE to anything other than builtin python libraries
# this file is imported by archivebox/__init__.py
# and any imports here will be imported by EVERYTHING else
# so this file should only be used for pure python checks
# that don't need to import other parts of ArchiveBox

# if a check needs to import other parts of ArchiveBox,
# the imports should be done inside the check function
# and you should make sure if you need to import any django stuff
# that the check is called after django.setup() has been called


def check_data_folder() -> None:
    from archivebox import DATA_DIR, ARCHIVE_DIR
    from archivebox.config import CONSTANTS
    from archivebox.config.paths import create_and_chown_dir, get_or_create_working_tmp_dir, get_or_create_working_lib_dir
    
    archive_dir_exists = os.path.isdir(ARCHIVE_DIR)
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
    
    
    # Create data dir subdirs
    create_and_chown_dir(CONSTANTS.SOURCES_DIR)
    create_and_chown_dir(CONSTANTS.PERSONAS_DIR / 'Default')
    create_and_chown_dir(CONSTANTS.LOGS_DIR)
    # create_and_chown_dir(CONSTANTS.CACHE_DIR)
    
    # Create /tmp and /lib dirs if they don't exist
    get_or_create_working_tmp_dir(autofix=True, quiet=False)
    get_or_create_working_lib_dir(autofix=True, quiet=False)
    
    # Check data dir permissions, /tmp, and /lib permissions
    check_data_dir_permissions()

    
def check_migrations():
    from archivebox import DATA_DIR
    from ..index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]
    is_migrating = any(arg in sys.argv for arg in ['makemigrations', 'migrate', 'init'])

    if pending_migrations and not is_migrating:
        print('[red][X] This collection was created with an older version of ArchiveBox and must be upgraded first.[/red]')
        print(f'    {DATA_DIR}', file=sys.stderr)
        print(file=sys.stderr)
        print(f'    [violet]Hint:[/violet] To upgrade it to the latest version and apply the {len(pending_migrations)} pending migrations, run:', file=sys.stderr)
        print('        archivebox init', file=sys.stderr)
        raise SystemExit(3)


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
    is_getting_help = '-h' in sys.argv or '--help' in sys.argv or 'help' in sys.argv
    is_getting_version = '--version' in sys.argv or 'version' in sys.argv
    is_installing = 'setup' in sys.argv or 'install' in sys.argv
    
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


def check_data_dir_permissions():
    from archivebox import DATA_DIR
    from archivebox.misc.logging import STDERR
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, DEFAULT_PUID, DEFAULT_PGID, IS_ROOT, USER
    
    data_dir_stat = Path(DATA_DIR).stat()
    data_dir_uid, data_dir_gid = data_dir_stat.st_uid, data_dir_stat.st_gid
    data_owned_by_root = data_dir_uid == 0
    
    # data_owned_by_default_user = data_dir_uid == DEFAULT_PUID or data_dir_gid == DEFAULT_PGID
    data_owner_doesnt_match = (data_dir_uid != ARCHIVEBOX_USER and data_dir_gid != ARCHIVEBOX_GROUP) if not IS_ROOT else False
    data_not_writable = not (os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK))
    if data_owned_by_root:
        STDERR.print('\n[yellow]:warning: Warning: ArchiveBox [blue]DATA_DIR[/blue] is currently owned by [red]root[/red], it must be changed before archiving can run![/yellow]')
    elif data_owner_doesnt_match or data_not_writable:
        STDERR.print(f'\n[yellow]:warning: Warning: ArchiveBox [blue]DATA_DIR[/blue] is currently owned by [red]{data_dir_uid}:{data_dir_gid}[/red], but ArchiveBox user is [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue] ({USER})! (ArchiveBox may not be able to write to the data dir)[/yellow]')
        
    if data_owned_by_root or data_owner_doesnt_match or data_not_writable:
        STDERR.print(f'[violet]Hint:[/violet] Change the current ownership [red]{data_dir_uid}[/red]:{data_dir_gid} (PUID:PGID) to a non-root user & group that will run ArchiveBox, e.g.:')
        STDERR.print(f'    [grey53]sudo[/grey53] chown -R [blue]{DEFAULT_PUID}:{DEFAULT_PGID}[/blue] {DATA_DIR.resolve()}')
        STDERR.print()
        STDERR.print('[blue]More info:[/blue]')
        STDERR.print('    [link=https://github.com/ArchiveBox/ArchiveBox#storage-requirements]https://github.com/ArchiveBox/ArchiveBox#storage-requirements[/link]')
        STDERR.print('    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#permissions]https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#permissions[/link]')
        STDERR.print('    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid]https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid[/link]')
        STDERR.print('    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#filesystem-doesnt-support-fsync-eg-network-mounts]https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#filesystem-doesnt-support-fsync-eg-network-mounts[/link]')

    from archivebox.config.common import STORAGE_CONFIG

    # Check /tmp dir permissions
    check_tmp_dir(STORAGE_CONFIG.TMP_DIR, throw=False, must_exist=True)

    # Check /lib dir permissions
    check_lib_dir(STORAGE_CONFIG.LIB_DIR, throw=False, must_exist=True)
    
    os.umask(0o777 - int(STORAGE_CONFIG.DIR_OUTPUT_PERMISSIONS, base=8))                        # noqa: F821


def check_tmp_dir(tmp_dir=None, throw=False, quiet=False, must_exist=True):
    from archivebox.config.paths import assert_dir_can_contain_unix_sockets, dir_is_writable, get_or_create_working_tmp_dir
    from archivebox.misc.logging import STDERR
    from archivebox.misc.logging_util import pretty_path
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.config.common import STORAGE_CONFIG
    
    tmp_dir = tmp_dir or STORAGE_CONFIG.TMP_DIR
    socket_file = tmp_dir.absolute().resolve() / "supervisord.sock"

    if not must_exist and not os.path.isdir(tmp_dir):
        # just check that its viable based on its length (because dir may not exist yet, we cant check if its writable)
        return len(f'file://{socket_file}') <= 96

    tmp_is_valid = False
    try:
        tmp_is_valid = dir_is_writable(tmp_dir)
        tmp_is_valid = tmp_is_valid and assert_dir_can_contain_unix_sockets(tmp_dir)
        assert tmp_is_valid, f'ArchiveBox user PUID={ARCHIVEBOX_USER} PGID={ARCHIVEBOX_GROUP} is unable to write to TMP_DIR={tmp_dir}'            
        assert len(f'file://{socket_file}') <= 96, f'ArchiveBox TMP_DIR={tmp_dir} is too long, dir containing unix socket files must be <90 chars.'
        return True
    except Exception as e:
        if not quiet:
            STDERR.print()
            ERROR_TEXT = '\n'.join((
                '',
                f'[red]:cross_mark: ArchiveBox is unable to use TMP_DIR={pretty_path(tmp_dir)}[/red]',
                f'   [yellow]{e}[/yellow]',
                '',
                '[blue]Info:[/blue] [grey53]The TMP_DIR is used for the supervisord unix socket file and other temporary files.',
                '  - It [red]must[/red] be on a local drive (not inside a docker volume, remote network drive, or FUSE mount).',
                f'  - It [red]must[/red] be readable and writable by the ArchiveBox user (PUID={ARCHIVEBOX_USER}, PGID={ARCHIVEBOX_GROUP}).',
                '  - It [red]must[/red] be a *short* path (less than 90 characters) due to UNIX path length restrictions for sockets.',
                '  - It [yellow]should[/yellow] be able to hold at least 200MB of data (in-progress downloads can be large).[/grey53]',
                '',
                '[violet]Hint:[/violet] Fix it by setting TMP_DIR to a path that meets these requirements, e.g.:',
                f'      [green]archivebox config --set TMP_DIR={get_or_create_working_tmp_dir(autofix=False, quiet=True) or "/tmp/archivebox"}[/green]',
                '',
            ))
            STDERR.print(Panel(ERROR_TEXT, expand=False, border_style='red', title='[red]:cross_mark: Error with configured TMP_DIR[/red]', subtitle='Background workers may fail to start until fixed.'))
            STDERR.print()
        if throw:
            raise OSError(f'TMP_DIR={tmp_dir} is invalid, ArchiveBox is unable to use it and the server will fail to start!') from e
    return False


def check_lib_dir(lib_dir: Path | None = None, throw=False, quiet=False, must_exist=True):
    import archivebox
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.misc.logging import STDERR
    from archivebox.misc.logging_util import pretty_path
    from archivebox.config.paths import dir_is_writable, get_or_create_working_lib_dir
    from archivebox.config.common import STORAGE_CONFIG
    
    lib_dir = lib_dir or STORAGE_CONFIG.LIB_DIR
    
    assert lib_dir == archivebox.pm.hook.get_LIB_DIR(), "lib_dir is not the same as the one in the flat config"
    
    if not must_exist and not os.path.isdir(lib_dir):
        return True
    
    lib_is_valid = False
    try:
        lib_is_valid = dir_is_writable(lib_dir)
        assert lib_is_valid, f'ArchiveBox user PUID={ARCHIVEBOX_USER} PGID={ARCHIVEBOX_GROUP} is unable to write to LIB_DIR={lib_dir}'
        return True
    except Exception as e:
        if not quiet:
            STDERR.print()
            ERROR_TEXT = '\n'.join((
                '',
                f'[red]:cross_mark: ArchiveBox is unable to use LIB_DIR={pretty_path(lib_dir)}[/red]',
                f'   [yellow]{e}[/yellow]',
                '',
                '[blue]Info:[/blue] [grey53]The LIB_DIR is used to store ArchiveBox auto-installed plugin library and binary dependencies.',
                f'  - It [red]must[/red] be readable and writable by the ArchiveBox user (PUID={ARCHIVEBOX_USER}, PGID={ARCHIVEBOX_GROUP}).',
                '  - It [yellow]should[/yellow] be on a local (ideally fast) drive like an SSD or HDD (not on a network drive or external HDD).',
                '  - It [yellow]should[/yellow] be able to hold at least 1GB of data (some dependencies like Chrome can be large).[/grey53]',
                '',
                '[violet]Hint:[/violet] Fix it by setting LIB_DIR to a path that meets these requirements, e.g.:',
                f'      [green]archivebox config --set LIB_DIR={get_or_create_working_lib_dir(autofix=False, quiet=True) or "/usr/local/share/archivebox"}[/green]',
                '',
            ))
            STDERR.print(Panel(ERROR_TEXT, expand=False, border_style='red', title='[red]:cross_mark: Error with configured LIB_DIR[/red]', subtitle='[yellow]Dependencies may not auto-install properly until fixed.[/yellow]'))
            STDERR.print()
        if throw:
            raise OSError(f'LIB_DIR={lib_dir} is invalid, ArchiveBox is unable to use it and dependencies will fail to install.') from e
    return False
