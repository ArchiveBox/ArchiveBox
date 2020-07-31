__package__ = 'archivebox'

import os
import sys
import shutil

from typing import Dict, List, Optional, Iterable, IO, Union
from crontab import CronTab, CronSlices

from .cli import (
    list_subcommands,
    run_subcommand,
    display_first,
    meta_cmds,
    main_cmds,
    archive_cmds,
)
from .parsers import (
    save_text_as_source,
    save_file_as_source,
    parse_links_memory,
)
from .index.schema import Link
from .util import enforce_types                         # type: ignore
from .system import get_dir_size, dedupe_cron_jobs, CRON_COMMENT
from .index import (
    load_main_index,
    parse_links_from_source,
    dedupe_links,
    write_main_index,
    link_matches_filter,
    get_indexed_folders,
    get_archived_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_invalid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
    fix_invalid_folder_locations,
)
from .index.json import (
    parse_json_main_index,
    parse_json_links_details,
)
from .index.sql import (
    parse_sql_main_index,
    get_admins,
    apply_migrations,
    remove_from_sql_main_index,
)
from .index.html import parse_html_main_index
from .extractors import archive_links, archive_link, ignore_methods
from .config import (
    stderr,
    ConfigDict,
    ANSI,
    # IS_TTY,
    USER,
    ARCHIVEBOX_BINARY,
    ONLY_NEW,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    LOGS_DIR,
    CONFIG_FILE,
    ARCHIVE_DIR_NAME,
    SOURCES_DIR_NAME,
    LOGS_DIR_NAME,
    STATIC_DIR_NAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    SQL_INDEX_FILENAME,
    ROBOTS_TXT_FILENAME,
    FAVICON_FILENAME,
    check_dependencies,
    check_data_folder,
    write_config_file,
    setup_django,
    VERSION,
    CODE_LOCATIONS,
    EXTERNAL_LOCATIONS,
    DATA_LOCATIONS,
    DEPENDENCIES,
    load_all_config,
    CONFIG,
    USER_CONFIG,
    get_real_name,
)
from .logging_util import (
    TERM_WIDTH,
    TimedProgress,
    log_importing_started,
    log_crawl_started,
    log_removal_started,
    log_removal_finished,
    log_list_started,
    log_list_finished,
    printable_config,
    printable_folders,
    printable_filesize,
    printable_folder_status,
    printable_dependency_version,
)


ALLOWED_IN_OUTPUT_DIR = {
    '.DS_Store',
    '.venv',
    'venv',
    'virtualenv',
    '.virtualenv',
    ARCHIVE_DIR_NAME,
    SOURCES_DIR_NAME,
    LOGS_DIR_NAME,
    STATIC_DIR_NAME,
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    ROBOTS_TXT_FILENAME,
    FAVICON_FILENAME,
}

@enforce_types
def help(out_dir: str=OUTPUT_DIR) -> None:
    """Print the ArchiveBox help message and usage"""

    all_subcommands = list_subcommands()
    COMMANDS_HELP_TEXT = '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in meta_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in main_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in archive_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd not in display_first
    )


    if os.path.exists(os.path.join(out_dir, JSON_INDEX_FILENAME)):
        print('''{green}ArchiveBox v{}: The self-hosted internet archive.{reset}

{lightred}Active data directory:{reset}
    {}

{lightred}Usage:{reset}
    archivebox [command] [--help] [--version] [...args]

{lightred}Commands:{reset}
    {}

{lightred}Example Use:{reset}
    mkdir my-archive; cd my-archive/
    archivebox init
    archivebox status

    archivebox add https://example.com/some/page
    archivebox add --depth=1 ~/Downloads/bookmarks_export.html
    
    archivebox list --sort=timestamp --csv=timestamp,url,is_archived
    archivebox schedule --every=week https://example.com/some/feed.rss
    archivebox update --resume=15109948213.123

{lightred}Documentation:{reset}
    https://github.com/pirate/ArchiveBox/wiki
'''.format(VERSION, out_dir, COMMANDS_HELP_TEXT, **ANSI))
    
    else:
        print('{green}Welcome to ArchiveBox v{}!{reset}'.format(VERSION, **ANSI))
        print()
        print('To import an existing archive (from a previous version of ArchiveBox):')
        print('    1. cd into your data dir OUTPUT_DIR (usually ArchiveBox/output) and run:')
        print('    2. archivebox init')
        print()
        print('To start a new archive:')
        print('    1. Create an empty directory, then cd into it and run:')
        print('    2. archivebox init')
        print()
        print('For more information, see the documentation here:')
        print('    https://github.com/pirate/ArchiveBox/wiki')


@enforce_types
def version(quiet: bool=False,
            out_dir: str=OUTPUT_DIR) -> None:
    """Print the ArchiveBox version and dependency information"""

    if quiet:
        print(VERSION)
    else:
        print('ArchiveBox v{}'.format(VERSION))
        print()

        print('{white}[i] Dependency versions:{reset}'.format(**ANSI))
        for name, dependency in DEPENDENCIES.items():
            print(printable_dependency_version(name, dependency))
        
        print()
        print('{white}[i] Code locations:{reset}'.format(**ANSI))
        for name, folder in CODE_LOCATIONS.items():
            print(printable_folder_status(name, folder))

        print()
        print('{white}[i] External locations:{reset}'.format(**ANSI))
        for name, folder in EXTERNAL_LOCATIONS.items():
            print(printable_folder_status(name, folder))

        print()
        print('{white}[i] Data locations:{reset}'.format(**ANSI))
        for name, folder in DATA_LOCATIONS.items():
            print(printable_folder_status(name, folder))

        print()
        check_dependencies()


@enforce_types
def run(subcommand: str,
        subcommand_args: Optional[List[str]],
        stdin: Optional[IO]=None,
        out_dir: str=OUTPUT_DIR) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""
    run_subcommand(
        subcommand=subcommand,
        subcommand_args=subcommand_args,
        stdin=stdin,
        pwd=out_dir,
    )


@enforce_types
def init(force: bool=False, out_dir: str=OUTPUT_DIR) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    os.makedirs(out_dir, exist_ok=True)
    is_empty = not len(set(os.listdir(out_dir)) - ALLOWED_IN_OUTPUT_DIR)
    existing_index = os.path.exists(os.path.join(out_dir, JSON_INDEX_FILENAME))

    if is_empty and not existing_index:
        print('{green}[+] Initializing a new ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {out_dir}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    elif existing_index:
        print('{green}[*] Updating existing ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {out_dir}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    else:
        if force:
            stderr('[!] This folder appears to already have files in it, but no index.json is present.', color='lightyellow')
            stderr('    Because --force was passed, ArchiveBox will initialize anyway (which may overwrite existing files).')
        else:
            stderr(
                ("{red}[X] This folder appears to already have files in it, but no index.json is present.{reset}\n\n"
                "    You must run init in a completely empty directory, or an existing data folder.\n\n"
                "    {lightred}Hint:{reset} To import an existing data folder make sure to cd into the folder first, \n"
                "    then run and run 'archivebox init' to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                ).format(out_dir, **ANSI)
            )
            raise SystemExit(2)

    if existing_index:
        print('\n{green}[*] Verifying archive folder structure...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building archive folder structure...{reset}'.format(**ANSI))
    
    os.makedirs(SOURCES_DIR, exist_ok=True)
    print(f'    √ {SOURCES_DIR}')
    
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    print(f'    √ {ARCHIVE_DIR}')

    os.makedirs(LOGS_DIR, exist_ok=True)
    print(f'    √ {LOGS_DIR}')

    write_config_file({}, out_dir=out_dir)
    print(f'    √ {CONFIG_FILE}')
    
    if os.path.exists(os.path.join(out_dir, SQL_INDEX_FILENAME)):
        print('\n{green}[*] Verifying main SQL index and running migrations...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building main SQL index and running migrations...{reset}'.format(**ANSI))
    
    setup_django(out_dir, check_db=False)
    DATABASE_FILE = os.path.join(out_dir, SQL_INDEX_FILENAME)
    print(f'    √ {DATABASE_FILE}')
    print()
    for migration_line in apply_migrations(out_dir):
        print(f'    {migration_line}')


    assert os.path.exists(DATABASE_FILE)
    
    # from django.contrib.auth.models import User
    # if IS_TTY and not User.objects.filter(is_superuser=True).exists():
    #     print('{green}[+] Creating admin user account...{reset}'.format(**ANSI))
    #     call_command("createsuperuser", interactive=True)

    print()
    print('{green}[*] Collecting links from any existing indexes and archive folders...{reset}'.format(**ANSI))

    all_links: Dict[str, Link] = {}
    if existing_index:
        all_links = {
            link.url: link
            for link in load_main_index(out_dir=out_dir, warn=False)
        }
        print('    √ Loaded {} links from existing main index.'.format(len(all_links)))

    # Links in data folders that dont match their timestamp
    fixed, cant_fix = fix_invalid_folder_locations(out_dir=out_dir)
    if fixed:
        print('    {lightyellow}√ Fixed {} data directory locations that didn\'t match their link timestamps.{reset}'.format(len(fixed), **ANSI))
    if cant_fix:
        print('    {lightyellow}! Could not fix {} data directory locations due to conflicts with existing folders.{reset}'.format(len(cant_fix), **ANSI))

    # Links in JSON index but not in main index
    orphaned_json_links = {
        link.url: link
        for link in parse_json_main_index(out_dir)
        if link.url not in all_links
    }
    if orphaned_json_links:
        all_links.update(orphaned_json_links)
        print('    {lightyellow}√ Added {} orphaned links from existing JSON index...{reset}'.format(len(orphaned_json_links), **ANSI))

    # Links in SQL index but not in main index
    orphaned_sql_links = {
        link.url: link
        for link in parse_sql_main_index(out_dir)
        if link.url not in all_links
    }
    if orphaned_sql_links:
        all_links.update(orphaned_sql_links)
        print('    {lightyellow}√ Added {} orphaned links from existing SQL index...{reset}'.format(len(orphaned_sql_links), **ANSI))

    # Links in data dir indexes but not in main index
    orphaned_data_dir_links = {
        link.url: link
        for link in parse_json_links_details(out_dir)
        if link.url not in all_links
    }
    if orphaned_data_dir_links:
        all_links.update(orphaned_data_dir_links)
        print('    {lightyellow}√ Added {} orphaned links from existing archive directories.{reset}'.format(len(orphaned_data_dir_links), **ANSI))

    # Links in invalid/duplicate data dirs
    invalid_folders = {
        folder: link
        for folder, link in get_invalid_folders(all_links.values(), out_dir=out_dir).items()
    }
    if invalid_folders:
        print('    {lightyellow}! Skipped adding {} invalid link data directories.{reset}'.format(len(invalid_folders), **ANSI))
        print('        X ' + '\n        X '.join(f'{folder} {link}' for folder, link in invalid_folders.items()))
        print()
        print('    {lightred}Hint:{reset} For more information about the link data directories that were skipped, run:'.format(**ANSI))
        print('        archivebox status')
        print('        archivebox list --status=invalid')


    write_main_index(list(all_links.values()), out_dir=out_dir)

    print('\n{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    if existing_index:
        print('{green}[√] Done. Verified and updated the existing ArchiveBox collection.{reset}'.format(**ANSI))
    else:
        print('{green}[√] Done. A new ArchiveBox collection was initialized ({} links).{reset}'.format(len(all_links), **ANSI))
    print()
    print('    {lightred}Hint:{reset} To view your archive index, run:'.format(**ANSI))
    print('        archivebox server  # then visit http://127.0.0.1:8000')
    print()
    print('    To add new links, you can run:')
    print("        archivebox add ~/some/path/or/url/to/list_of_links.txt")
    print()
    print('    For more usage and examples, run:')
    print('        archivebox help')


@enforce_types
def status(out_dir: str=OUTPUT_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    check_data_folder(out_dir=out_dir)

    from core.models import Snapshot
    from django.contrib.auth import get_user_model
    User = get_user_model()

    print('{green}[*] Scanning archive main index...{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {out_dir}/*', ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(out_dir, recursive=False, pattern='index.')
    size = printable_filesize(num_bytes)
    print(f'    Index size: {size} across {num_files} files')
    print()

    links = list(load_main_index(out_dir=out_dir))
    num_json_links = len(links)
    num_sql_links = sum(1 for link in parse_sql_main_index(out_dir=out_dir))
    num_html_links = sum(1 for url in parse_html_main_index(out_dir=out_dir))
    num_link_details = sum(1 for link in parse_json_links_details(out_dir=out_dir))
    print(f'    > JSON Main Index: {num_json_links} links'.ljust(36),  f'(found in {JSON_INDEX_FILENAME})')
    print(f'    > SQL Main Index: {num_sql_links} links'.ljust(36), f'(found in {SQL_INDEX_FILENAME})')
    print(f'    > HTML Main Index: {num_html_links} links'.ljust(36), f'(found in {HTML_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_link_details} links'.ljust(36), f'(found in {ARCHIVE_DIR_NAME}/*/index.json)')

    if num_html_links != len(links) or num_sql_links != len(links):
        print()
        print('    {lightred}Hint:{reset} You can fix index count differences automatically by running:'.format(**ANSI))
        print('        archivebox init')
    
    print()
    print('{green}[*] Scanning archive data directories...{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {ARCHIVE_DIR}/*', ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')
    print(ANSI['black'])
    num_indexed = len(get_indexed_folders(links, out_dir=out_dir))
    num_archived = len(get_archived_folders(links, out_dir=out_dir))
    num_unarchived = len(get_unarchived_folders(links, out_dir=out_dir))
    print(f'    > indexed: {num_indexed}'.ljust(36), f'({get_indexed_folders.__doc__})')
    print(f'      > archived: {num_archived}'.ljust(36), f'({get_archived_folders.__doc__})')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), f'({get_unarchived_folders.__doc__})')
    
    num_present = len(get_present_folders(links, out_dir=out_dir))
    num_valid = len(get_valid_folders(links, out_dir=out_dir))
    print()
    print(f'    > present: {num_present}'.ljust(36), f'({get_present_folders.__doc__})')
    print(f'      > valid: {num_valid}'.ljust(36), f'({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(links, out_dir=out_dir)
    orphaned = get_orphaned_folders(links, out_dir=out_dir)
    corrupted = get_corrupted_folders(links, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(links, out_dir=out_dir)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > invalid: {num_invalid}'.ljust(36), f'({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')
        
    print(ANSI['reset'])

    if num_indexed:
        print('    {lightred}Hint:{reset} You can list link data directories by status like so:'.format(**ANSI))
        print('        archivebox list --status=<status>  (e.g. indexed, corrupted, archived, etc.)')

    if orphaned:
        print('    {lightred}Hint:{reset} To automatically import orphaned data directories into the main index, run:'.format(**ANSI))
        print('        archivebox init')

    if num_invalid:
        print('    {lightred}Hint:{reset} You may need to manually remove or fix some invalid data directories, afterwards make sure to run:'.format(**ANSI))
        print('        archivebox init')
    
    print()
    print('{green}[*] Scanning recent archive changes and user logins:{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {LOGS_DIR}/*', ANSI['reset'])
    users = get_admins().values_list('username', flat=True)
    print(f'    UI users {len(users)}: {", ".join(users)}')
    last_login = User.objects.order_by('last_login').last()
    if last_login:
        print(f'    Last UI login: {last_login.username} @ {str(last_login.last_login)[:16]}')
    last_updated = Snapshot.objects.order_by('updated').last()
    print(f'    Last changes: {str(last_updated.updated)[:16]}')

    if not users:
        print()
        print('    {lightred}Hint:{reset} You can create an admin user by running:'.format(**ANSI))
        print('        archivebox manage createsuperuser')

    print()
    for snapshot in Snapshot.objects.order_by('-updated')[:10]:
        if not snapshot.updated:
            continue
        print(
            ANSI['black'],
            (
                f'   > {str(snapshot.updated)[:16]} '
                f'[{snapshot.num_outputs} {("X", "√")[snapshot.is_archived]} {printable_filesize(snapshot.archive_size)}] '
                f'"{snapshot.title}": {snapshot.url}'
            )[:TERM_WIDTH()],
            ANSI['reset'],
        )
    print(ANSI['black'], '   ...', ANSI['reset'])


@enforce_types
def oneshot(url: str, out_dir: str=OUTPUT_DIR):
    """
    Create a single URL archive folder with an index.json and index.html, and all the archive method outputs.
    You can run this to archive single pages without needing to create a whole collection with archivebox init.
    """
    oneshot_link, _ = parse_links_memory([url])
    if len(oneshot_link) > 1:
        stderr(
                '[X] You should pass a single url to the oneshot command',
                color='red'
            )
        raise SystemExit(2)
    methods = ignore_methods(['title'])
    archive_link(oneshot_link[0], out_dir=out_dir, methods=methods, skip_index=True)
    return oneshot_link

@enforce_types
def add(urls: Union[str, List[str]],
        depth: int=0,
        update_all: bool=not ONLY_NEW,
        index_only: bool=False,
        out_dir: str=OUTPUT_DIR) -> List[Link]:
    """Add a new URL or list of URLs to your archive"""

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

    # Load list of links from the existing index
    check_data_folder(out_dir=out_dir)
    check_dependencies()
    all_links: List[Link] = []
    new_links: List[Link] = []
    all_links = load_main_index(out_dir=out_dir)

    log_importing_started(urls=urls, depth=depth, index_only=index_only)
    if isinstance(urls, str):
        # save verbatim stdin to sources
        write_ahead_log = save_text_as_source(urls, filename='{ts}-import.txt', out_dir=out_dir)
    elif isinstance(urls, list):
        # save verbatim args to sources
        write_ahead_log = save_text_as_source('\n'.join(urls), filename='{ts}-import.txt', out_dir=out_dir)
    
    new_links += parse_links_from_source(write_ahead_log)

    # If we're going one level deeper, download each link and look for more links
    new_links_depth = []
    if new_links and depth == 1:
        log_crawl_started(new_links)
        for new_link in new_links:
            downloaded_file = save_file_as_source(new_link.url, filename='{ts}-crawl-{basename}.txt', out_dir=out_dir)
            new_links_depth += parse_links_from_source(downloaded_file)
    all_links, new_links = dedupe_links(all_links, new_links + new_links_depth)
    write_main_index(links=all_links, out_dir=out_dir, finished=not new_links)

    if index_only:
        return all_links

    # Run the archive methods for each link
    to_archive = all_links if update_all else new_links
    archive_links(to_archive, out_dir=out_dir)

    # Step 4: Re-write links index with updated titles, icons, and resources
    if to_archive:
        all_links = load_main_index(out_dir=out_dir)
        write_main_index(links=list(all_links), out_dir=out_dir, finished=True)
    return all_links

@enforce_types
def remove(filter_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: str='exact',
           links: Optional[List[Link]]=None,
           after: Optional[float]=None,
           before: Optional[float]=None,
           yes: bool=False,
           delete: bool=False,
           out_dir: str=OUTPUT_DIR) -> List[Link]:
    """Remove the specified URLs from the archive"""
    
    check_data_folder(out_dir=out_dir)

    if links is None:
        if filter_str and filter_patterns:
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin, but not both.\n',
                color='red',
            )
            raise SystemExit(2)
        elif not (filter_str or filter_patterns):
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin.',
                color='red',
            )
            stderr()
            stderr('    {lightred}Hint:{reset} To remove all urls you can run:'.format(**ANSI))
            stderr("        archivebox remove --filter-type=regex '.*'")
            stderr()
            raise SystemExit(2)
        elif filter_str:
            filter_patterns = [ptn.strip() for ptn in filter_str.split('\n')]

        log_list_started(filter_patterns, filter_type)
        timer = TimedProgress(360, prefix='      ')
        try:
            links = list(list_links(
                filter_patterns=filter_patterns,
                filter_type=filter_type,
                after=after,
                before=before,
            ))
        finally:
            timer.end()


    if not len(links):
        log_removal_finished(0, 0)
        raise SystemExit(1)


    log_list_finished(links)
    log_removal_started(links, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        to_keep = []
        to_delete = []
        all_links = load_main_index(out_dir=out_dir)
        for link in all_links:
            should_remove = (
                (after is not None and float(link.timestamp) < after)
                or (before is not None and float(link.timestamp) > before)
                or link_matches_filter(link, filter_patterns or [], filter_type)
                or link in links
            )
            if should_remove:
                to_delete.append(link)

                if delete:
                    shutil.rmtree(link.link_dir, ignore_errors=True)
            else:
                to_keep.append(link)
    finally:
        timer.end()

    remove_from_sql_main_index(links=to_delete, out_dir=out_dir)
    write_main_index(links=to_keep, out_dir=out_dir, finished=True)
    log_removal_finished(len(all_links), len(to_keep))
    
    return to_keep

@enforce_types
def update(resume: Optional[float]=None,
           only_new: bool=ONLY_NEW,
           index_only: bool=False,
           overwrite: bool=False,
           filter_patterns_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: Optional[str]=None,
           status: Optional[str]=None,
           after: Optional[str]=None,
           before: Optional[str]=None,
           out_dir: str=OUTPUT_DIR) -> List[Link]:
    """Import any new links from subscriptions and retry any previously failed/skipped links"""

    check_data_folder(out_dir=out_dir)
    check_dependencies()

    # Step 1: Load list of links from the existing index
    #         merge in and dedupe new links from import_path
    all_links: List[Link] = []
    new_links: List[Link] = []
    all_links = load_main_index(out_dir=out_dir)

    # Step 2: Write updated index with deduped old and new links back to disk
    write_main_index(links=list(all_links), out_dir=out_dir)

    # Step 3: Filter for selected_links
    matching_links = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )
    matching_folders = list_folders(
        links=list(matching_links),
        status=status,
        out_dir=out_dir,
    )
    all_links = [link for link in matching_folders.values() if link]

    if index_only:
        return all_links
        
    # Step 3: Run the archive methods for each link
    to_archive = new_links if only_new else all_links
    archive_links(to_archive, overwrite=overwrite, out_dir=out_dir)

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links = load_main_index(out_dir=out_dir)
    write_main_index(links=list(all_links), out_dir=out_dir, finished=True)
    return all_links

@enforce_types
def list_all(filter_patterns_str: Optional[str]=None,
             filter_patterns: Optional[List[str]]=None,
             filter_type: str='exact',
             status: Optional[str]=None,
             after: Optional[float]=None,
             before: Optional[float]=None,
             sort: Optional[str]=None,
             csv: Optional[str]=None,
             json: bool=False,
             out_dir: str=OUTPUT_DIR) -> Iterable[Link]:
    """List, filter, and export information about archive entries"""
    
    check_data_folder(out_dir=out_dir)

    if filter_patterns and filter_patterns_str:
        stderr(
            '[X] You should either pass filter patterns as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif filter_patterns_str:
        filter_patterns = filter_patterns_str.split('\n')


    links = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    if sort:
        links = sorted(links, key=lambda link: getattr(link, sort))

    folders = list_folders(
        links=list(links),
        status=status,
        out_dir=out_dir,
    )
    
    print(printable_folders(folders, json=json, csv=csv))
    return folders


@enforce_types
def list_links(filter_patterns: Optional[List[str]]=None,
               filter_type: str='exact',
               after: Optional[float]=None,
               before: Optional[float]=None,
               out_dir: str=OUTPUT_DIR) -> Iterable[Link]:
    
    check_data_folder(out_dir=out_dir)

    all_links = load_main_index(out_dir=out_dir)

    for link in all_links:
        if after is not None and float(link.timestamp) < after:
            continue
        if before is not None and float(link.timestamp) > before:
            continue
        
        if filter_patterns:
            if link_matches_filter(link, filter_patterns, filter_type):
                yield link
        else:
            yield link

@enforce_types
def list_folders(links: List[Link],
                 status: str,
                 out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    
    check_data_folder(out_dir=out_dir)

    if status == 'indexed':
        return get_indexed_folders(links, out_dir=out_dir)
    elif status == 'archived':
        return get_archived_folders(links, out_dir=out_dir)
    elif status == 'unarchived':
        return get_unarchived_folders(links, out_dir=out_dir)

    elif status == 'present':
        return get_present_folders(links, out_dir=out_dir)
    elif status == 'valid':
        return get_valid_folders(links, out_dir=out_dir)
    elif status == 'invalid':
        return get_invalid_folders(links, out_dir=out_dir)

    elif status == 'duplicate':
        return get_duplicate_folders(links, out_dir=out_dir)
    elif status == 'orphaned':
        return get_orphaned_folders(links, out_dir=out_dir)
    elif status == 'corrupted':
        return get_corrupted_folders(links, out_dir=out_dir)
    elif status == 'unrecognized':
        return get_unrecognized_folders(links, out_dir=out_dir)

    raise ValueError('Status not recognized.')


@enforce_types
def config(config_options_str: Optional[str]=None,
           config_options: Optional[List[str]]=None,
           get: bool=False,
           set: bool=False,
           reset: bool=False,
           out_dir: str=OUTPUT_DIR) -> None:
    """Get and set your ArchiveBox project configuration values"""

    check_data_folder(out_dir=out_dir)

    if config_options and config_options_str:
        stderr(
            '[X] You should either pass config values as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif config_options_str:
        config_options = config_options_str.split('\n')

    config_options = config_options or []

    no_args = not (get or set or reset or config_options)

    matching_config: ConfigDict = {}
    if get or no_args:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: CONFIG[key] for key in config_options if key in CONFIG}
            failed_config = [key for key in config_options if key not in CONFIG]
            if failed_config:
                stderr()
                stderr('[X] These options failed to get', color='red')
                stderr('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = CONFIG
        
        print(printable_config(matching_config))
        raise SystemExit(not matching_config)
    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                stderr('[X] Config KEY=VALUE must have an = sign in it', color='red')
                stderr(f'    {line}')
                raise SystemExit(2)

            raw_key, val = line.split('=')
            raw_key = raw_key.upper().strip()
            key = get_real_name(raw_key)
            if key != raw_key:
                stderr(f'[i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.', color='lightyellow')

            if key in CONFIG:
                new_config[key] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            before = CONFIG
            matching_config = write_config_file(new_config, out_dir=OUTPUT_DIR)
            after = load_all_config()
            print(printable_config(matching_config))

            side_effect_changes: ConfigDict = {}
            for key, val in after.items():
                if key in USER_CONFIG and (before[key] != after[key]) and (key not in matching_config):
                    side_effect_changes[key] = after[key]

            if side_effect_changes:
                stderr()
                stderr('[i] Note: This change also affected these other options that depended on it:', color='lightyellow')
                print('    {}'.format(printable_config(side_effect_changes, prefix='    ')))
        if failed_options:
            stderr()
            stderr('[X] These options failed to set (check for typos):', color='red')
            stderr('    {}'.format('\n    '.join(failed_options)))
        raise SystemExit(bool(failed_options))
    elif reset:
        stderr('[X] This command is not implemented yet.', color='red')
        stderr('    Please manually remove the relevant lines from your config file:')
        stderr(f'        {CONFIG_FILE}')
        raise SystemExit(2)
    else:
        stderr('[X] You must pass either --get or --set, or no arguments to get the whole config.', color='red')
        stderr('    archivebox config')
        stderr('    archivebox config --get SOME_KEY')
        stderr('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)


@enforce_types
def schedule(add: bool=False,
             show: bool=False,
             clear: bool=False,
             foreground: bool=False,
             run_all: bool=False,
             quiet: bool=False,
             every: Optional[str]=None,
             import_path: Optional[str]=None,
             out_dir: str=OUTPUT_DIR):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    
    check_data_folder(out_dir=out_dir)

    os.makedirs(os.path.join(out_dir, LOGS_DIR_NAME), exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))
    if foreground or run_all:
        if import_path or (not existing_jobs):
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**ANSI))
            stderr('    archivebox schedule --every=hour https://example.com/some/rss/feed.xml')
            raise SystemExit(1)
        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **ANSI))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r  √ {job.command}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)
        if foreground:
            try:
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)

    elif show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            stderr('{red}[X] There are no ArchiveBox cron jobs scheduled for your user ({}).{reset}'.format(USER, **ANSI))
            stderr('    To schedule a new job, run:')
            stderr('        archivebox schedule --every=[timeperiod] https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    elif clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    elif every:
        quoted = lambda s: f'"{s}"' if s and ' ' in s else s
        cmd = [
            'cd',
            quoted(out_dir),
            '&&',
            quoted(ARCHIVEBOX_BINARY),
            *(['add', f'"{import_path}"'] if import_path else ['update']),
            '2>&1',
            '>',
            quoted(os.path.join(LOGS_DIR, 'archivebox.log')),

        ]
        new_job = cron.new(command=' '.join(cmd), comment=CRON_COMMENT)

        if every in ('minute', 'hour', 'day', 'week', 'month', 'year'):
            set_every = getattr(new_job.every(), every)
            set_every()
        elif CronSlices.is_valid(every):
            new_job.setall(every)
        else:
            stderr('{red}[X] Got invalid timeperiod for cron task.{reset}'.format(**ANSI))
            stderr('    It must be one of minute/hour/day/week/month')
            stderr('    or a quoted cron-format schedule like:')
            stderr('        archivebox init --every=day https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_cron_jobs(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_comment(CRON_COMMENT))

        print()
        print('{green}[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).{reset}'.format(USER, len(existing_jobs), **ANSI))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not quiet:
            stderr()
            stderr('{lightyellow}[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.{reset}'.format(total_runs, **ANSI))
            stderr('    Congrats on being an enthusiastic internet archiver! 👌')
            stderr()
            stderr('    Make sure you have enough storage space available to hold all the data.')
            stderr('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
        raise SystemExit(0)


@enforce_types
def server(runserver_args: Optional[List[str]]=None,
           reload: bool=False,
           debug: bool=False,
           init: bool=False,
           out_dir: str=OUTPUT_DIR) -> None:
    """Run the ArchiveBox HTTP server"""

    runserver_args = runserver_args or []
    
    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)

    # setup config for django runserver
    from . import config
    config.SHOW_PROGRESS = False
    config.DEBUG = config.DEBUG or debug

    check_data_folder(out_dir=out_dir)
    setup_django(out_dir)

    from django.core.management import call_command
    from django.contrib.auth.models import User

    admin_user = User.objects.filter(is_superuser=True).order_by('date_joined').only('username').last()

    print('{green}[+] Starting ArchiveBox webserver...{reset}'.format(**ANSI))
    if admin_user:
        print("{lightred}[i] The admin username is:{lightblue} {}{reset}".format(admin_user.username, **ANSI))
    else:
        print('{lightyellow}[!] No admin users exist yet, you will not be able to edit links in the UI.{reset}'.format(**ANSI))
        print()
        print('    To create an admin user, run:')
        print('        archivebox manage createsuperuser')
        print()

    # fallback to serving staticfiles insecurely with django when DEBUG=False
    if not config.DEBUG:
        runserver_args.append('--insecure')  # TODO: serve statics w/ nginx instead
    
    # toggle autoreloading when archivebox code changes (it's on by default)
    if not reload:
        runserver_args.append('--noreload')

    config.SHOW_PROGRESS = False
    config.DEBUG = config.DEBUG or debug


    call_command("runserver", *runserver_args)


@enforce_types
def manage(args: Optional[List[str]]=None, out_dir: str=OUTPUT_DIR) -> None:
    """Run an ArchiveBox Django management command"""

    check_data_folder(out_dir=out_dir)

    setup_django(out_dir)
    from django.core.management import execute_from_command_line

    execute_from_command_line([f'{ARCHIVEBOX_BINARY} manage', *(args or ['help'])])


@enforce_types
def shell(out_dir: str=OUTPUT_DIR) -> None:
    """Enter an interactive ArchiveBox Django shell"""

    check_data_folder(out_dir=out_dir)

    setup_django(OUTPUT_DIR)
    from django.core.management import call_command
    call_command("shell_plus")

