import re
import json

from typing import List, Optional, Iterable

from .schema import Link
from .util import enforce_types, ExtendedEncoder
from .index import (
    links_after_timestamp,
    load_links_index,
    write_links_index,
)
from .archive_methods import archive_link
from .config import (
    ONLY_NEW,
    OUTPUT_DIR,
    check_dependencies,
)
from .logs import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
)


@enforce_types
def update_archive_data(import_path: Optional[str]=None, resume: Optional[float]=None, only_new: bool=False) -> List[Link]:
    """The main ArchiveBox entrancepoint. Everything starts here."""

    check_dependencies()

    # Step 1: Load list of links from the existing index
    #         merge in and dedupe new links from import_path
    all_links, new_links = load_links_index(out_dir=OUTPUT_DIR, import_path=import_path)

    # Step 2: Write updated index with deduped old and new links back to disk
    write_links_index(links=list(all_links), out_dir=OUTPUT_DIR)

    # Step 3: Run the archive methods for each link
    links = new_links if ONLY_NEW else all_links
    log_archiving_started(len(links), resume)
    idx: int = 0
    link: Optional[Link] = None
    try:
        for idx, link in enumerate(links_after_timestamp(links, resume)):
            archive_link(link, link_dir=link.link_dir)

    except KeyboardInterrupt:
        log_archiving_paused(len(links), idx, link.timestamp if link else '0')
        raise SystemExit(0)

    except:
        print()
        raise    

    log_archiving_finished(len(links))

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links, _ = load_links_index(out_dir=OUTPUT_DIR)
    write_links_index(links=list(all_links), out_dir=OUTPUT_DIR, finished=True)
    return all_links


@enforce_types
def list_archive_data(filter_regex: Optional[str]=None, after: Optional[float]=None, before: Optional[float]=None) -> Iterable[Link]:
    
    all_links, _ = load_links_index(out_dir=OUTPUT_DIR)

    pattern = re.compile(filter_regex, re.IGNORECASE) if filter_regex else None

    for link in all_links:
        if pattern and not pattern.match(link.url):
            continue
        if after is not None and float(link.timestamp) < after:
            continue
        if before is not None and float(link.timestamp) > before:
            continue

        yield link


def csv_format(link: Link, csv_cols: str) -> str:
    return ','.join(json.dumps(getattr(link, col), cls=ExtendedEncoder) for col in csv_cols.split(','))
