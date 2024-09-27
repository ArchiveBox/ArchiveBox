__package__ = 'archivebox.misc'

from benedict import benedict

import archivebox

from .logging import stderr, ANSI


def check_data_folder(config: benedict) -> None:
    output_dir = archivebox.DATA_DIR

    archive_dir_exists = (archivebox.CONSTANTS.ARCHIVE_DIR).exists()
    if not archive_dir_exists:
        stderr('[X] No archivebox index found in the current directory.', color='red')
        stderr(f'    {output_dir}', color='lightyellow')
        stderr()
        stderr('    {lightred}Hint{reset}: Are you running archivebox in the right folder?'.format(**ANSI))
        stderr('        cd path/to/your/archive/folder')
        stderr('        archivebox [command]')
        stderr()
        stderr('    {lightred}Hint{reset}: To create a new archive collection or import existing data in this folder, run:'.format(**ANSI))
        stderr('        archivebox init')
        raise SystemExit(2)


def check_migrations(config: benedict):
    output_dir = archivebox.DATA_DIR
    
    from ..index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]

    if pending_migrations:
        stderr('[X] This collection was created with an older version of ArchiveBox and must be upgraded first.', color='lightyellow')
        stderr(f'    {output_dir}')
        stderr()
        stderr(f'    To upgrade it to the latest version and apply the {len(pending_migrations)} pending migrations, run:')
        stderr('        archivebox init')
        raise SystemExit(3)

    archivebox.CONSTANTS.SOURCES_DIR.mkdir(exist_ok=True)
    archivebox.CONSTANTS.LOGS_DIR.mkdir(exist_ok=True)
    archivebox.CONSTANTS.CACHE_DIR.mkdir(exist_ok=True)
    (archivebox.CONSTANTS.LIB_DIR / 'bin').mkdir(exist_ok=True, parents=True)
    (archivebox.CONSTANTS.PERSONAS_DIR / 'Default').mkdir(exist_ok=True, parents=True)
