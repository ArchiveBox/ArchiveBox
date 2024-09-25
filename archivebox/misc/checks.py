__package__ = 'archivebox.misc'

# TODO: migrate all of these to new plugantic/base_check.py Check system

from benedict import benedict
from pathlib import Path

from .logging import stderr, hint


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
