__package__ = 'archivebox.misc'

# TODO: migrate all of these to new plugantic/base_check.py Check system

import sys
from benedict import benedict
from pathlib import Path

from .logging import stderr, hint


def check_system_config(config: benedict) -> None:
    ### Check system environment
    if config['USER'] == 'root' or str(config['PUID']) == "0":
        stderr('[!] ArchiveBox should never be run as root!', color='red')
        stderr('    For more information, see the security overview documentation:')
        stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root')
        
        if config['IN_DOCKER']:
            attempted_command = ' '.join(sys.argv[:3])
            stderr('')
            stderr('    {lightred}Hint{reset}: When using Docker, you must run commands with {green}docker run{reset} instead of {lightyellow}docker exec{reset}, e.g.:'.format(**config['ANSI']))
            stderr(f'        docker compose run archivebox {attempted_command}')
            stderr(f'        docker run -it -v $PWD/data:/data archivebox/archivebox {attempted_command}')
            stderr('        or:')
            stderr(f'        docker compose exec --user=archivebox archivebox /bin/bash -c "archivebox {attempted_command}"')
            stderr(f'        docker exec -it --user=archivebox <container id> /bin/bash -c "archivebox {attempted_command}"')
        
        raise SystemExit(2)

    ### Check Python environment
    if sys.version_info[:3] < (3, 7, 0):
        stderr(f'[X] Python version is not new enough: {config["PYTHON_VERSION"]} (>3.6 is required)', color='red')
        stderr('    See https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#python for help upgrading your Python installation.')
        raise SystemExit(2)

    if int(config['DJANGO_VERSION'].split('.')[0]) < 3:
        stderr(f'[X] Django version is not new enough: {config["DJANGO_VERSION"]} (>3.0 is required)', color='red')
        stderr('    Upgrade django using pip or your system package manager: pip3 install --upgrade django')
        raise SystemExit(2)

    if config['PYTHON_ENCODING'] not in ('UTF-8', 'UTF8'):
        stderr(f'[X] Your system is running python3 scripts with a bad locale setting: {config["PYTHON_ENCODING"]} (it should be UTF-8).', color='red')
        stderr('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)')
        stderr('    Or if you\'re using ubuntu/debian, run "dpkg-reconfigure locales"')
        stderr('')
        stderr('    Confirm that it\'s fixed by opening a new shell and running:')
        stderr('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8')
        raise SystemExit(2)

    # stderr('[i] Using Chrome binary: {}'.format(shutil.which(CHROME_BINARY) or CHROME_BINARY))
    # stderr('[i] Using Chrome data dir: {}'.format(os.path.abspath(CHROME_USER_DATA_DIR)))
    if config['CHROME_USER_DATA_DIR'] is not None and Path(config['CHROME_USER_DATA_DIR']).exists():
        if not (Path(config['CHROME_USER_DATA_DIR']) / 'Default').exists():
            stderr('[X] Could not find profile "Default" in CHROME_USER_DATA_DIR.', color='red')
            stderr(f'    {config["CHROME_USER_DATA_DIR"]}')
            stderr('    Make sure you set it to a Chrome user data directory containing a Default profile folder.')
            stderr('    For more info see:')
            stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#CHROME_USER_DATA_DIR')
            if '/Default' in str(config['CHROME_USER_DATA_DIR']):
                stderr()
                stderr('    Try removing /Default from the end e.g.:')
                stderr('        CHROME_USER_DATA_DIR="{}"'.format(str(config['CHROME_USER_DATA_DIR']).split('/Default')[0]))
            
            # hard error is too annoying here, instead just set it to nothing
            # raise SystemExit(2)
            config['CHROME_USER_DATA_DIR'] = None
    else:
        config['CHROME_USER_DATA_DIR'] = None


def check_dependencies(config: benedict, show_help: bool=True) -> None:
    invalid_dependencies = [
        (name, info) for name, info in config['DEPENDENCIES'].items()
        if info['enabled'] and not info['is_valid']
    ]
    if invalid_dependencies and show_help:
        stderr(f'[!] Warning: Missing {len(invalid_dependencies)} recommended dependencies', color='lightyellow')
        for dependency, info in invalid_dependencies:
            stderr(
                '    ! {}: {} ({})'.format(
                    dependency,
                    info['path'] or 'unable to find binary',
                    info['version'] or 'unable to detect version',
                )
            )
            if dependency in ('YOUTUBEDL_BINARY', 'CHROME_BINARY', 'SINGLEFILE_BINARY', 'READABILITY_BINARY', 'MERCURY_BINARY'):
                hint(('To install all packages automatically run: archivebox setup',
                    f'or to disable it and silence this warning: archivebox config --set SAVE_{dependency.rsplit("_", 1)[0]}=False',
                    ''), prefix='      ')
        stderr('')

    if config['TIMEOUT'] < 5:
        stderr(f'[!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={config["TIMEOUT"]} seconds)', color='red')
        stderr('    You must allow *at least* 5 seconds for indexing and archive methods to run succesfully.')
        stderr('    (Setting it to somewhere between 30 and 3000 seconds is recommended)')
        stderr()
        stderr('    If you want to make ArchiveBox run faster, disable specific archive methods instead:')
        stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles')
        stderr()

    elif config['USE_CHROME'] and config['TIMEOUT'] < 15:
        stderr(f'[!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={config["TIMEOUT"]} seconds)', color='red')
        stderr('    Chrome will fail to archive all sites if set to less than ~15 seconds.')
        stderr('    (Setting it to somewhere between 30 and 300 seconds is recommended)')
        stderr()
        stderr('    If you want to make ArchiveBox run faster, disable specific archive methods instead:')
        stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles')
        stderr()

    if config['USE_YOUTUBEDL'] and config['MEDIA_TIMEOUT'] < 20:
        stderr(f'[!] Warning: MEDIA_TIMEOUT is set too low! (currently set to MEDIA_TIMEOUT={config["MEDIA_TIMEOUT"]} seconds)', color='red')
        stderr('    youtube-dl/yt-dlp will fail to archive any media if set to less than ~20 seconds.')
        stderr('    (Setting it somewhere over 60 seconds is recommended)')
        stderr()
        stderr('    If you want to disable media archiving entirely, set SAVE_MEDIA=False instead:')
        stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#save_media')
        stderr()

        


def check_data_folder(config: benedict) -> None:
    output_dir = config['OUTPUT_DIR']

    archive_dir_exists = (Path(output_dir) / 'archive').exists()
    if not archive_dir_exists:
        stderr('[X] No archivebox index found in the current directory.', color='red')
        stderr(f'    {output_dir}', color='lightyellow')
        stderr()
        stderr('    {lightred}Hint{reset}: Are you running archivebox in the right folder?'.format(**config['ANSI']))
        stderr('        cd path/to/your/archive/folder')
        stderr('        archivebox [command]')
        stderr()
        stderr('    {lightred}Hint{reset}: To create a new archive collection or import existing data in this folder, run:'.format(**config['ANSI']))
        stderr('        archivebox init')
        raise SystemExit(2)


def check_migrations(config: benedict):
    output_dir = config['OUTPUT_DIR']
    
    from ..index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]

    if pending_migrations:
        stderr('[X] This collection was created with an older version of ArchiveBox and must be upgraded first.', color='lightyellow')
        stderr(f'    {output_dir}')
        stderr()
        stderr(f'    To upgrade it to the latest version and apply the {len(pending_migrations)} pending migrations, run:')
        stderr('        archivebox init')
        raise SystemExit(3)

    (Path(output_dir) / config['SOURCES_DIR_NAME']).mkdir(exist_ok=True)
    (Path(output_dir) / config['LOGS_DIR_NAME']).mkdir(exist_ok=True)
    (Path(output_dir) / config['CACHE_DIR_NAME']).mkdir(exist_ok=True)
    (Path(output_dir) / config['LIB_DIR_NAME'] / 'bin').mkdir(exist_ok=True, parents=True)
    (Path(output_dir) / config['PERSONAS_DIR_NAME'] / 'Default').mkdir(exist_ok=True, parents=True)
