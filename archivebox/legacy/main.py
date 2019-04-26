import os
import re
import shutil

from typing import Dict, List, Optional, Iterable
from itertools import chain

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
from .storage.json import (
    parse_json_main_index,
    parse_json_link_details,
    parse_json_links_details,
)
from .storage.sql import parse_sql_main_index, get_admins
from .storage.html import parse_html_main_index
from .archive_methods import archive_link
from .config import (
    stderr,
    ANSI,
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
    setup_django,
    write_config_file,
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
    elif existing_index:
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

    write_config_file({}, out_dir=OUTPUT_DIR)
    print(f'    √ {CONFIG_FILE}')
    
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
    }
    orphan_new_links = {
        url: link
        for url, link in orphaned_data_dir_links.items()
        if url not in all_links
    }
    orphan_duplicates = {
        url: link
        for url, link in orphaned_data_dir_links.items()
        if url in all_links
    }
    if orphan_new_links:
        all_links.update(orphan_new_links)
        print('    {lightyellow}√ Added {} orphaned links from existing archive directories...{reset}'.format(len(orphan_new_links), **ANSI))
    if orphan_duplicates:
        print('    {lightyellow}! Skipped adding {} invalid link data directories that would have overwritten or corrupted existing data.{reset}'.format(len(orphan_duplicates), **ANSI))

    orphaned_data_dirs = {folder for folder in orphan_duplicates.keys()}
    invalid_folders = {
        folder: link
        for folder, link in get_invalid_folders(all_links.values(), out_dir=OUTPUT_DIR).items()
        if folder not in orphaned_data_dirs
    }
    if invalid_folders:
        print('    {lightyellow}! Skipped adding {} corrupted/unrecognized link data directories that could not be read.{reset}'.format(len(orphan_duplicates), **ANSI))
        
    if orphan_duplicates or invalid_folders:
        print('        For more information about the link data directories that were skipped, run:')
        print('            archivebox info')
        print('            archivebox list --status=invalid')
        print('            archivebox list --status=orphaned')
        print('            archivebox list --status=duplicate')


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

    print('{green}[*] Scanning archive collection main index...{reset}'.format(**ANSI))
    print(f'    {OUTPUT_DIR}/*')
    num_bytes, num_dirs, num_files = get_dir_size(OUTPUT_DIR, recursive=False, pattern='index.')
    size = human_readable_size(num_bytes)
    print(f'    Size: {size} across {num_files} files')
    print()

    links = list(load_main_index(out_dir=OUTPUT_DIR))
    num_json_links = len(links)
    num_sql_links = sum(1 for link in parse_sql_main_index(out_dir=OUTPUT_DIR))
    num_html_links = sum(1 for url in parse_html_main_index(out_dir=OUTPUT_DIR))
    num_link_details = sum(1 for link in parse_json_links_details(out_dir=OUTPUT_DIR))
    users = get_admins().values_list('username', flat=True)
    print(f'    > JSON Main Index: {num_json_links} links'.ljust(36),  f'(found in {JSON_INDEX_FILENAME})')
    print(f'    > SQL Main Index: {num_sql_links} links'.ljust(36), f'(found in {SQL_INDEX_FILENAME})')
    print(f'    > HTML Main Index: {num_html_links} links'.ljust(36), f'(found in {HTML_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_link_details} links'.ljust(36), f'(found in {ARCHIVE_DIR_NAME}/*/index.json)')

    print(f'    > Admin: {len(users)} users {", ".join(users)}'.ljust(36), f'(found in {SQL_INDEX_FILENAME})')
    
    if num_html_links != len(links) or num_sql_links != len(links):
        print()
        print('    {lightred}Hint:{reset} You can fix index count differences automatically by running:'.format(**ANSI))
        print('        archivebox init')
    
    if not users:
        print()
        print('    {lightred}Hint:{reset} You can create an admin user by running:'.format(**ANSI))
        print('        archivebox manage createsuperuser')

    print()
    print('{green}[*] Scanning archive collection link data directories...{reset}'.format(**ANSI))
    print(f'    {ARCHIVE_DIR}/*')

    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = human_readable_size(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')
    print()

    num_indexed = len(get_indexed_folders(links, out_dir=OUTPUT_DIR))
    num_archived = len(get_archived_folders(links, out_dir=OUTPUT_DIR))
    num_unarchived = len(get_unarchived_folders(links, out_dir=OUTPUT_DIR))
    print(f'    > indexed: {num_indexed}'.ljust(36), f'({get_indexed_folders.__doc__})')
    print(f'      > archived: {num_archived}'.ljust(36), f'({get_archived_folders.__doc__})')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), f'({get_unarchived_folders.__doc__})')
    
    num_present = len(get_present_folders(links, out_dir=OUTPUT_DIR))
    num_valid = len(get_valid_folders(links, out_dir=OUTPUT_DIR))
    print()
    print(f'    > present: {num_present}'.ljust(36), f'({get_present_folders.__doc__})')
    print(f'      > valid: {num_valid}'.ljust(36), f'({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(links, out_dir=OUTPUT_DIR)
    orphaned = get_orphaned_folders(links, out_dir=OUTPUT_DIR)
    corrupted = get_corrupted_folders(links, out_dir=OUTPUT_DIR)
    unrecognized = get_unrecognized_folders(links, out_dir=OUTPUT_DIR)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > invalid: {num_invalid}'.ljust(36), f'({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')
    
    if num_indexed:
        print()
        print('    {lightred}Hint:{reset} You can list link data directories by status like so:'.format(**ANSI))
        print('        archivebox list --status=<status>  (e.g. indexed, corrupted, archived, etc.)')

    if orphaned:
        print()
        print('    {lightred}Hint:{reset} To automatically import orphaned data directories into the main index, run:'.format(**ANSI))
        print('        archivebox init')

    if num_invalid:
        print()
        print('    {lightred}Hint:{reset} You may need to manually remove or fix some invalid data directories, afterwards make sure to run:'.format(**ANSI))
        print('        archivebox init')
    
    print()



@enforce_types
def update_archive_data(import_path: Optional[str]=None, 
                        resume: Optional[float]=None,
                        only_new: bool=False,
                        index_only: bool=False) -> List[Link]:
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

    if index_only:
        return all_links
        
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



def get_indexed_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links without checking archive status or data directory validity"""
    return {
        link.link_dir: link
        for link in links
    }

def get_archived_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are archived with a valid data directory"""
    return {
        link.link_dir: link
        for link in filter(is_archived, links)
    }

def get_unarchived_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are unarchived with no data directory or an empty data directory"""
    return {
        link.link_dir: link
        for link in filter(is_unarchived, links)
    }

def get_present_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that are expected to exist based on the main index"""
    all_folders = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            all_folders[entry.path] = link

    return all_folders

def get_valid_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs with a valid index matched to the main index and archived content"""
    return {
        link.link_dir: link
        for link in filter(is_valid, links)
    }

def get_invalid_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that are invalid for any reason: corrupted/duplicate/orphaned/unrecognized"""
    duplicate = get_duplicate_folders(links, out_dir=OUTPUT_DIR)
    orphaned = get_orphaned_folders(links, out_dir=OUTPUT_DIR)
    corrupted = get_corrupted_folders(links, out_dir=OUTPUT_DIR)
    unrecognized = get_unrecognized_folders(links, out_dir=OUTPUT_DIR)
    return {**duplicate, **orphaned, **corrupted, **unrecognized}


def get_duplicate_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that conflict with other directories that have the same link URL or timestamp"""
    links = list(links)
    by_url = {link.url: 0 for link in links}
    by_timestamp = {link.timestamp: 0 for link in links}

    duplicate_folders = {}

    indexed_folders = {link.link_dir for link in links}
    data_folders = (
        entry.path
        for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME))
        if entry.is_dir(follow_symlinks=True) and entry.path not in indexed_folders
    )

    for path in chain(sorted(indexed_folders), sorted(data_folders)):
        link = None
        try:
            link = parse_json_link_details(path)
        except Exception:
            pass

        if link:
            # link folder has same timestamp as different link folder
            by_timestamp[link.timestamp] = by_timestamp.get(link.timestamp, 0) + 1
            if by_timestamp[link.timestamp] > 1:
                duplicate_folders[path] = link

            # link folder has same url as different link folder
            by_url[link.url] = by_url.get(link.url, 0) + 1
            if by_url[link.url] > 1:
                duplicate_folders[path] = link

    return duplicate_folders

def get_orphaned_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that contain a valid index but aren't listed in the main index"""
    links = list(links)
    indexed_folders = {link.link_dir: link for link in links}
    orphaned_folders = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            index_exists = os.path.exists(os.path.join(entry.path, 'index.json'))
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            if index_exists and entry.path not in indexed_folders:
                # folder is a valid link data dir with index details, but it's not in the main index
                orphaned_folders[entry.path] = link

    return orphaned_folders

def get_corrupted_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain a valid index and aren't listed in the main index"""
    return {
        link.link_dir: link
        for link in filter(is_corrupt, links)
    }

def get_unrecognized_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain recognizable archive data and aren't listed in the main index"""
    by_timestamp = {link.timestamp: 0 for link in links}
    unrecognized_folders: Dict[str, Optional[Link]] = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            index_exists = os.path.exists(os.path.join(entry.path, 'index.json'))
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            if index_exists and link is None:
                # index exists but it's corrupted or unparseable
                unrecognized_folders[entry.path] = link
            
            elif not index_exists:
                # link details index doesn't exist and the folder isn't in the main index
                timestamp = entry.path.rsplit('/', 1)[-1]
                if timestamp not in by_timestamp:
                    unrecognized_folders[entry.path] = link

    return unrecognized_folders


def is_valid(link: Link) -> bool:
    dir_exists = os.path.exists(link.link_dir)
    index_exists = os.path.exists(os.path.join(link.link_dir, 'index.json'))
    if not dir_exists:
        # unarchived links are not included in the valid list
        return False
    if dir_exists and not index_exists:
        return False
    if dir_exists and index_exists:
        try:
            parsed_link = parse_json_link_details(link.link_dir)
            return link.url == parsed_link.url
        except Exception:
            pass
    return False

def is_corrupt(link: Link) -> bool:
    if not os.path.exists(link.link_dir):
        # unarchived links are not considered corrupt
        return False

    if is_valid(link):
        return False

    return True

def is_archived(link: Link) -> bool:
    return is_valid(link) and link.is_archived
    
def is_unarchived(link: Link) -> bool:
    if not os.path.exists(link.link_dir):
        return True
    return not link.is_archived
