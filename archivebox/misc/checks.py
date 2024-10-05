__package__ = 'archivebox.misc'

from archivebox.config import DATA_DIR, ARCHIVE_DIR, CONSTANTS, SHELL_CONFIG

from .logging import stderr


def check_data_folder() -> None:

    archive_dir_exists = ARCHIVE_DIR.exists()
    if not archive_dir_exists:
        stderr('[X] No archivebox index found in the current directory.', color='red')
        stderr(f'    {DATA_DIR}', color='lightyellow')
        stderr()
        stderr('    {lightred}Hint{reset}: Are you running archivebox in the right folder?'.format(**SHELL_CONFIG.ANSI))
        stderr('        cd path/to/your/archive/folder')
        stderr('        archivebox [command]')
        stderr()
        stderr('    {lightred}Hint{reset}: To create a new archive collection or import existing data in this folder, run:'.format(**SHELL_CONFIG.ANSI))
        stderr('        archivebox init')
        raise SystemExit(2)


def check_migrations():
    from ..index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]

    if pending_migrations:
        stderr('[X] This collection was created with an older version of ArchiveBox and must be upgraded first.', color='lightyellow')
        stderr(f'    {DATA_DIR}')
        stderr()
        stderr(f'    To upgrade it to the latest version and apply the {len(pending_migrations)} pending migrations, run:')
        stderr('        archivebox init')
        raise SystemExit(3)

    CONSTANTS.SOURCES_DIR.mkdir(exist_ok=True)
    CONSTANTS.LOGS_DIR.mkdir(exist_ok=True)
    # CONSTANTS.CACHE_DIR.mkdir(exist_ok=True)
    (CONSTANTS.LIB_DIR / 'bin').mkdir(exist_ok=True, parents=True)
    (CONSTANTS.PERSONAS_DIR / 'Default').mkdir(exist_ok=True, parents=True)
