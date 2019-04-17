import os
import re
import shutil

from typing import List, Optional, Iterable

from .schema import Link
from .util import enforce_types, TimedProgress
from .index import (
    links_after_timestamp,
    load_main_index,
    write_main_index,
)
from .archive_methods import archive_link
from .config import (
    stderr,
    ANSI,
    ONLY_NEW,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    DATABASE_DIR,
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


@enforce_types
def init():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    harmless_files = {'.DS_Store', '.venv', 'venv', 'virtualenv', '.virtualenv'}
    is_empty = not len(set(os.listdir(OUTPUT_DIR)) - harmless_files)
    existing_index = os.path.exists(os.path.join(OUTPUT_DIR, 'index.json'))

    if not is_empty:
        if existing_index:
            stderr('{green}[√] You already have an archive index in: {}{reset}'.format(OUTPUT_DIR, **ANSI))
            stderr('    To add new links, you can run:')
            stderr("        archivebox add 'https://example.com'")
            stderr()
            stderr('    For more usage and examples, run:')
            stderr('        archivebox help')
            # TODO: import old archivebox version's archive data folder

            raise SystemExit(1)
        else:
            stderr(
                ("{red}[X] This folder already has files in it. You must run init inside a completely empty directory.{reset}"
                "\n\n"
                "    {lightred}Hint:{reset} To import a data folder created by an older version of ArchiveBox, \n"
                "    just cd into the folder and run the archivebox command to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                ).format(OUTPUT_DIR, **ANSI)
            )
            raise SystemExit(1)


    stderr('{green}[+] Initializing new archive directory: {}{reset}'.format(OUTPUT_DIR, **ANSI))
    os.makedirs(SOURCES_DIR)
    stderr(f'    > {SOURCES_DIR}')
    os.makedirs(ARCHIVE_DIR)
    stderr(f'    > {ARCHIVE_DIR}')
    os.makedirs(DATABASE_DIR)
    stderr(f'    > {DATABASE_DIR}')

    write_main_index([], out_dir=OUTPUT_DIR, finished=True)

    setup_django()
    from django.core.management import call_command
    call_command("makemigrations", interactive=False)
    call_command("migrate", interactive=False)

    stderr('{green}[√] Done.{reset}'.format(**ANSI))



@enforce_types
def update_archive_data(import_path: Optional[str]=None, resume: Optional[float]=None, only_new: bool=False) -> List[Link]:
    """The main ArchiveBox entrancepoint. Everything starts here."""

    check_dependencies()
    check_data_folder()

    # Step 1: Load list of links from the existing index
    #         merge in and dedupe new links from import_path
    all_links, new_links = load_main_index(out_dir=OUTPUT_DIR, import_path=import_path)

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
    all_links, _ = load_main_index(out_dir=OUTPUT_DIR)
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
    
    all_links, _ = load_main_index(out_dir=OUTPUT_DIR)

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
        all_links, _ = load_main_index(out_dir=OUTPUT_DIR)
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
