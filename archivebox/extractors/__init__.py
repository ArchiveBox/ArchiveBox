__package__ = 'archivebox.extractors'

from typing import Callable, Optional, Dict, List, Iterable, Union, Protocol, cast

import os
import sys
from pathlib import Path
from importlib import import_module
from datetime import datetime, timezone

from django.db.models import QuerySet

from archivebox.config.legacy import (
    SAVE_ALLOWLIST_PTN,
    SAVE_DENYLIST_PTN,
)
from ..index.schema import ArchiveResult, Link
from ..index.sql import write_link_to_sql_index
from ..index import (
    load_link_details,
    write_link_details,
)
from archivebox.misc.util import enforce_types
from ..logging_util import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
    log_link_archiving_started,
    log_link_archiving_finished,
    log_archive_method_started,
    log_archive_method_finished,
)

from .title import should_save_title, save_title
from .favicon import should_save_favicon, save_favicon
from .wget import should_save_wget, save_wget
from .singlefile import should_save_singlefile, save_singlefile
from .readability import should_save_readability, save_readability
from .mercury import should_save_mercury, save_mercury
from .htmltotext import should_save_htmltotext, save_htmltotext
from .pdf import should_save_pdf, save_pdf
from .screenshot import should_save_screenshot, save_screenshot
from .dom import should_save_dom, save_dom
from .git import should_save_git, save_git
from .media import should_save_media, save_media
from .archive_org import should_save_archive_dot_org, save_archive_dot_org
from .headers import should_save_headers, save_headers


ShouldSaveFunction = Callable[[Link, Optional[Path], Optional[bool]], bool]
SaveFunction = Callable[[Link, Optional[Path], int], ArchiveResult]
ArchiveMethodEntry = tuple[str, ShouldSaveFunction, SaveFunction]

def get_default_archive_methods() -> List[ArchiveMethodEntry]:
    return [
        ('favicon', should_save_favicon, save_favicon),
        ('headers', should_save_headers, save_headers),
        ('singlefile', should_save_singlefile, save_singlefile),
        ('pdf', should_save_pdf, save_pdf),
        ('screenshot', should_save_screenshot, save_screenshot),
        ('dom', should_save_dom, save_dom),
        ('wget', should_save_wget, save_wget),
        # keep title, readability, and htmltotext below wget and singlefile, as they depend on them
        ('title', should_save_title, save_title),
        ('readability', should_save_readability, save_readability),
        ('mercury', should_save_mercury, save_mercury),
        ('htmltotext', should_save_htmltotext, save_htmltotext),
        ('git', should_save_git, save_git),
        ('media', should_save_media, save_media),
        ('archive_org', should_save_archive_dot_org, save_archive_dot_org),
    ]

ARCHIVE_METHODS_INDEXING_PRECEDENCE = [
    ('readability', 1),
    ('mercury', 2),
    ('htmltotext', 3),
    ('singlefile', 4),
    ('dom', 5),
    ('wget', 6)
]


@enforce_types
def get_archive_methods_for_link(link: Link) -> Iterable[ArchiveMethodEntry]:
    DEFAULT_METHODS = get_default_archive_methods()
    allowed_methods = {
        m for pat, methods in
        SAVE_ALLOWLIST_PTN.items()
        if pat.search(link.url)
        for m in methods
    } or { m[0] for m in DEFAULT_METHODS }
    denied_methods = {
        m for pat, methods in
        SAVE_DENYLIST_PTN.items()
        if pat.search(link.url)
        for m in methods
    }
    allowed_methods -= denied_methods

    return (m for m in DEFAULT_METHODS if m[0] in allowed_methods)

@enforce_types
def ignore_methods(to_ignore: List[str]) -> Iterable[str]:
    ARCHIVE_METHODS = get_default_archive_methods()
    return [x[0] for x in ARCHIVE_METHODS if x[0] not in to_ignore]

@enforce_types
def archive_link(link: Link, overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None, created_by_id: int | None=None) -> Link:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    from django.conf import settings

    from ..search import write_search_index

    # TODO: Remove when the input is changed to be a snapshot. Suboptimal approach.
    from core.models import Snapshot, ArchiveResult
    try:
        snapshot = Snapshot.objects.get(url=link.url) # TODO: This will be unnecessary once everything is a snapshot
    except Snapshot.DoesNotExist:
        snapshot = write_link_to_sql_index(link, created_by_id=created_by_id)

    active_methods = get_archive_methods_for_link(link)
    
    if methods:
        active_methods = [
            method for method in active_methods
            if method[0] in methods
        ]

    out_dir = out_dir or Path(link.link_dir)
    try:
        is_new = not Path(out_dir).exists()
        if is_new:
            os.makedirs(out_dir)

        link = load_link_details(link, out_dir=out_dir)
        write_link_details(link, out_dir=out_dir, skip_sql_index=False)
        log_link_archiving_started(link, str(out_dir), is_new)
        link = link.overwrite(downloaded_at=datetime.now(timezone.utc))
        stats = {'skipped': 0, 'succeeded': 0, 'failed': 0}
        start_ts = datetime.now(timezone.utc)

        for method_name, should_run, method_function in active_methods:
            try:
                if method_name not in link.history:
                    link.history[method_name] = []

                if should_run(link, out_dir, overwrite):
                    log_archive_method_started(method_name)

                    result = method_function(link=link, out_dir=out_dir)

                    link.history[method_name].append(result)

                    stats[result.status] += 1
                    log_archive_method_finished(result)
                    write_search_index(link=link, texts=result.index_texts)
                    ArchiveResult.objects.create(snapshot=snapshot, extractor=method_name, cmd=result.cmd, cmd_version=result.cmd_version,
                                                 output=result.output, pwd=result.pwd, start_ts=result.start_ts, end_ts=result.end_ts, status=result.status, created_by_id=snapshot.created_by_id)


                    # bump the downloaded_at time on the main Snapshot here, this is critical
                    # to be able to cache summaries of the ArchiveResults for a given
                    # snapshot without having to load all the results from the DB each time.
                    # (we use {Snapshot.pk}-{Snapshot.downloaded_at} as the cache key and assume
                    # ArchiveResults are unchanged as long as the downloaded_at timestamp is unchanged)
                    snapshot.save()
                else:
                    # print('{black}      X {}{reset}'.format(method_name, **ANSI))
                    stats['skipped'] += 1
            except Exception as e:
                # https://github.com/ArchiveBox/ArchiveBox/issues/984#issuecomment-1150541627
                with open(settings.ERROR_LOG, "a", encoding='utf-8') as f:
                    command = ' '.join(sys.argv)
                    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d__%H:%M:%S')
                    f.write(("\n" + 'Exception in archive_methods.save_{}(Link(url={})) command={}; ts={}'.format(
                        method_name,
                        link.url,
                        command,
                        ts
                    ) + "\n" + str(e) + "\n"))
                    #f.write(f"\n> {command}; ts={ts} version={config['VERSION']} docker={config['IN_DOCKER']} is_tty={config['IS_TTY']}\n")

                # print(f'        ERROR: {method_name} {e.__class__.__name__}: {e} {getattr(e, "hints", "")}', ts, link.url, command)
                raise e from Exception('Exception in archive_methods.save_{}(Link(url={}))'.format(
                    method_name,
                    link.url,
                ))


        # print('    ', stats)

        try:
            latest_title = link.history['title'][-1].output.strip()
            if latest_title and len(latest_title) >= len(link.title or ''):
                link = link.overwrite(title=latest_title)
        except Exception:
            pass

        write_link_details(link, out_dir=out_dir, skip_sql_index=False)

        log_link_archiving_finished(link, out_dir, is_new, stats, start_ts)

    except KeyboardInterrupt:
        try:
            write_link_details(link, out_dir=link.link_dir)
        except:
            pass
        raise

    except Exception as err:
        print('    ! Failed to archive link: {}: {}'.format(err.__class__.__name__, err))
        raise

    return link

@enforce_types
def archive_links(all_links: Union[Iterable[Link], QuerySet], overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None, created_by_id: int | None=None) -> List[Link]:

    if type(all_links) is QuerySet:
        num_links: int = all_links.count()
        get_link = lambda x: x.as_link_with_details()
        all_links = all_links.iterator(chunk_size=500)
    else:
        num_links: int = len(all_links)
        get_link = lambda x: x

    if num_links == 0:
        return []

    log_archiving_started(num_links)
    idx: int = 0
    try:
        for link in all_links:
            idx += 1
            to_archive = get_link(link)
            archive_link(to_archive, overwrite=overwrite, methods=methods, out_dir=Path(link.link_dir), created_by_id=created_by_id)
    except KeyboardInterrupt:
        log_archiving_paused(num_links, idx, link.timestamp)
        raise SystemExit(0)
    except BaseException:
        print()
        raise

    log_archiving_finished(num_links)
    return all_links



EXTRACTORS_DIR = Path(__file__).parent

class ExtractorModuleProtocol(Protocol):
    """Type interface for an Extractor Module (WIP)"""
    
    get_output_path: Callable
    
    # TODO:
    # get_embed_path: Callable | None
    # should_extract(Snapshot)
    # extract(Snapshot)


def get_extractors(dir: Path=EXTRACTORS_DIR) -> Dict[str, ExtractorModuleProtocol]:
    """iterate through archivebox/extractors/*.py and load extractor modules"""
    EXTRACTORS = {}

    for filename in EXTRACTORS_DIR.glob('*.py'):
        if filename.name.startswith('__'):
            continue

        extractor_name = filename.name.replace('.py', '')

        extractor_module = cast(ExtractorModuleProtocol, import_module(f'.{extractor_name}', package=__package__))

        assert getattr(extractor_module, 'get_output_path')
        EXTRACTORS[extractor_name] = extractor_module

    return EXTRACTORS

EXTRACTORS = get_extractors(EXTRACTORS_DIR)
