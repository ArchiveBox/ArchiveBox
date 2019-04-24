import os
import re
import shutil

from typing import List, Optional, Iterable

from .schema import Link
from .util import (
    enforce_types,
    TimedProgress,
    get_dir_size,
    human_readable_size,
)
from .index import (
    links_after_timestamp,
    load_main_index,
    import_new_links,
    write_main_index,
)
from .storage.json import parse_json_main_index, parse_json_links_details
from .storage.sql import parse_sql_main_index
from .archive_methods import archive_link
from .config import (
    stderr,
    ANSI,
    ONLY_NEW,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    LOGS_DIR,
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
    setup_django,
)
from .logs import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
    log_removal_started,
    log_removal_finished,
    log_list_started,
    log_list_finished,
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
def init():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    is_empty = not len(set(os.listdir(OUTPUT_DIR)) - ALLOWED_IN_OUTPUT_DIR)
    existing_index = os.path.exists(os.path.join(OUTPUT_DIR, JSON_INDEX_FILENAME))

    if is_empty and not existing_index:
        print('{green}[+] Initializing a new ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {OUTPUT_DIR}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    elif is_empty and existing_index:
        print('{green}[*] Updating existing ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {OUTPUT_DIR}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    else:
        stderr(
            ("{red}[X] This folder appears to already have files in it, but no index.json is present.{reset}\n\n"
            "    You must run init in a completely empty directory, or an existing data folder.\n\n"
            "    {lightred}Hint:{reset} To import an existing data folder make sure to cd into the folder first, \n"
            "    then run and run 'archivebox init' to pick up where you left off.\n\n"
            "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
            ).format(OUTPUT_DIR, **ANSI)
        )
        raise SystemExit(1)

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
    
    if os.path.exists(os.path.join(OUTPUT_DIR, SQL_INDEX_FILENAME)):
        print('\n{green}[*] Verifying main SQL index and running migrations...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building main SQL index and running migrations...{reset}'.format(**ANSI))
    
    setup_django(OUTPUT_DIR, check_db=False)
    from django.conf import settings
    assert settings.DATABASE_FILE == os.path.join(OUTPUT_DIR, SQL_INDEX_FILENAME)
    print(f'    √ {settings.DATABASE_FILE}')
    print()
    from .storage.sql import apply_migrations
    for migration_line in apply_migrations(OUTPUT_DIR):
        print(f'    {migration_line}')


    assert os.path.exists(settings.DATABASE_FILE)
    
    # from django.contrib.auth.models import User
    # if IS_TTY and not User.objects.filter(is_superuser=True).exists():
    #     print('{green}[+] Creating admin user account...{reset}'.format(**ANSI))
    #     call_command("createsuperuser", interactive=True)

    print()
    print('{green}[*] Collecting links from any existing index or archive folders...{reset}'.format(**ANSI))

    all_links = {}
    if existing_index:
        all_links = {
            link.url: link
            for link in load_main_index(out_dir=OUTPUT_DIR, warn=False)
        }
        print('    √ Loaded {} links from existing main index...'.format(len(all_links)))

    orphaned_json_links = {
        link.url: link
        for link in parse_json_main_index(OUTPUT_DIR)
        if link.url not in all_links
    }
    if orphaned_json_links:
        all_links.update(orphaned_json_links)
        print('    {lightyellow}√ Added {} orphaned links from existing JSON index...{reset}'.format(len(orphaned_json_links), **ANSI))

    orphaned_sql_links = {
        link.url: link
        for link in parse_sql_main_index(OUTPUT_DIR)
        if link.url not in all_links
    }
    if orphaned_sql_links:
        all_links.update(orphaned_sql_links)
        print('    {lightyellow}√ Added {} orphaned links from existing SQL index...{reset}'.format(len(orphaned_sql_links), **ANSI))

    orphaned_data_dir_links = {
        link.url: link
        for link in parse_json_links_details(OUTPUT_DIR)
        if link.url not in all_links
    }
    if orphaned_data_dir_links:
        all_links.update(orphaned_data_dir_links)
        print('    {lightyellow}√ Added {} orphaned links from existing archive directories...{reset}'.format(len(orphaned_data_dir_links), **ANSI))

    write_main_index(list(all_links.values()), out_dir=OUTPUT_DIR)

    print('\n{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    if existing_index:
        print('{green}[√] Done. Verified and updated the existing ArchiveBox collection.{reset}'.format(**ANSI))
    else:
        print('{green}[√] Done. A new ArchiveBox collection was initialized ({} links).{reset}'.format(len(all_links), **ANSI))
    print()
    print('    To view your archive index, open:')
    print('        {}'.format(os.path.join(OUTPUT_DIR, HTML_INDEX_FILENAME)))
    print()
    print('    To add new links, you can run:')
    print("        archivebox add 'https://example.com'")
    print()
    print('    For more usage and examples, run:')
    print('        archivebox help')


@enforce_types
def info():
    all_links = load_main_index(out_dir=OUTPUT_DIR)

    print('{green}[*] Scanning archive collection main index with {} links:{reset}'.format(len(all_links), **ANSI))
    print(f'    {OUTPUT_DIR}')
    num_bytes, num_dirs, num_files = get_dir_size(OUTPUT_DIR, recursive=False)
    size = human_readable_size(num_bytes)
    print(f'    > Index Size: {size} across {num_files} files')
    print()

    setup_django()
    from django.contrib.auth.models import User
    from core.models import Page

    users = User.objects.all()
    num_pages = Page.objects.count()
    
    print(f'    > {len(users)} admin users:', ', '.join(u.username for u in users))
    print(f'    > {num_pages} pages in SQL database {SQL_INDEX_FILENAME}')
    print(f'    > {len(all_links)} pages in JSON database {JSON_INDEX_FILENAME}')
    print()

    print('{green}[*] Scanning archive collection data directory with {} entries:{reset}'.format(len(all_links), **ANSI))
    print(f'    {ARCHIVE_DIR}')

    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = human_readable_size(num_bytes)
    print(f'    > Total Size: {size} across {num_files} files in {num_dirs} directories')
    print()

    link_data_dirs = {link.link_dir for link in all_links}
    valid_archive_dirs = set()
    num_invalid = 0
    for entry in os.scandir(ARCHIVE_DIR):
        if entry.is_dir(follow_symlinks=True):
            if os.path.exists(os.path.join(entry.path, 'index.json')):
                valid_archive_dirs.add(entry.path)
            else:
                num_invalid += 1

    print(f'    > {len(valid_archive_dirs)} valid archive data directories (valid directories matched to links in the index)')

    num_unarchived = sum(1 for link in all_links if link.link_dir not in valid_archive_dirs)
    print(f'    > {num_unarchived} missing data directories (directories missing for links in the index)')

    print(f'    > {num_invalid} invalid data directories (directories present that don\'t contain an index file)')

    num_orphaned = sum(1 for data_dir in valid_archive_dirs if data_dir not in link_data_dirs)
    print(f'    > {num_orphaned} orphaned data directories (directories present for links that don\'t exist in the index)')
    

@enforce_types
def update_archive_data(import_path: Optional[str]=None, resume: Optional[float]=None, only_new: bool=False) -> List[Link]:
    """The main ArchiveBox entrancepoint. Everything starts here."""

    check_dependencies()
    check_data_folder()

    # Step 1: Load list of links from the existing index
    #         merge in and dedupe new links from import_path
    all_links: List[Link] = []
    new_links: List[Link] = []
    all_links = load_main_index(out_dir=OUTPUT_DIR)
    if import_path:
        all_links, new_links = import_new_links(all_links, import_path)

    # Step 2: Write updated index with deduped old and new links back to disk
    write_main_index(links=list(all_links), out_dir=OUTPUT_DIR)

    # Step 3: Run the archive methods for each link
    links = new_links if ONLY_NEW else all_links
    log_archiving_started(len(links), resume)
    idx: int = 0
    link: Link = None                                             # type: ignore
    try:
        for idx, link in enumerate(links_after_timestamp(links, resume)):
            archive_link(link, out_dir=link.link_dir)

    except KeyboardInterrupt:
        log_archiving_paused(len(links), idx, link.timestamp if link else '0')
        raise SystemExit(0)

    except:
        print()
        raise    

    log_archiving_finished(len(links))

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links = load_main_index(out_dir=OUTPUT_DIR)
    write_main_index(links=list(all_links), out_dir=OUTPUT_DIR, finished=True)
    return all_links


LINK_FILTERS = {
    'exact': lambda link, pattern: (link.url == pattern) or (link.base_url == pattern),
    'substring': lambda link, pattern: pattern in link.url,
    'regex': lambda link, pattern: bool(re.match(pattern, link.url)),
    'domain': lambda link, pattern: link.domain == pattern,
}

@enforce_types
def link_matches_filter(link: Link, filter_patterns: List[str], filter_type: str='exact') -> bool:
    for pattern in filter_patterns:
        if LINK_FILTERS[filter_type](link, pattern):
            return True

    return False


@enforce_types
def list_archive_data(filter_patterns: Optional[List[str]]=None, filter_type: str='exact',
                      after: Optional[float]=None, before: Optional[float]=None) -> Iterable[Link]:
    
    all_links = load_main_index(out_dir=OUTPUT_DIR)

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
def remove_archive_links(filter_patterns: List[str], filter_type: str='exact',
                         after: Optional[float]=None, before: Optional[float]=None,
                         yes: bool=False, delete: bool=False) -> List[Link]:
    
    check_dependencies()
    check_data_folder()

    log_list_started(filter_patterns, filter_type)
    timer = TimedProgress(360, prefix='      ')
    try:
        links = list(list_archive_data(
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
        all_links = load_main_index(out_dir=OUTPUT_DIR)
        for link in all_links:
            should_remove = (
                (after is not None and float(link.timestamp) < after)
                or (before is not None and float(link.timestamp) > before)
                or link_matches_filter(link, filter_patterns, filter_type)
            )
            if not should_remove:
                to_keep.append(link)
            elif should_remove and delete:
                shutil.rmtree(link.link_dir)
    finally:
        timer.end()

    write_main_index(links=to_keep, out_dir=OUTPUT_DIR, finished=True)
    log_removal_finished(len(all_links), len(to_keep))
    
    return to_keep
