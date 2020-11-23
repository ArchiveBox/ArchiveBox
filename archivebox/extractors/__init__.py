__package__ = 'archivebox.extractors'

import os
from pathlib import Path

from typing import Optional, List, Iterable, Union
from datetime import datetime
from django.db.models import QuerySet

from ..index.schema import Link
from ..index.sql import write_link_to_sql_index
from ..index import (
    load_link_details,
    write_link_details,
)
from ..util import enforce_types
from ..logging_util import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
    log_link_archiving_started,
    log_link_archiving_finished,
    log_archive_method_started,
    log_archive_method_finished,
)
from ..search import write_search_index

from .title import should_save_title, save_title
from .favicon import should_save_favicon, save_favicon
from .wget import should_save_wget, save_wget
from .singlefile import should_save_singlefile, save_singlefile
from .readability import should_save_readability, save_readability
from .mercury import should_save_mercury, save_mercury
from .pdf import should_save_pdf, save_pdf
from .screenshot import should_save_screenshot, save_screenshot
from .dom import should_save_dom, save_dom
from .git import should_save_git, save_git
from .media import should_save_media, save_media
from .archive_org import should_save_archive_dot_org, save_archive_dot_org
from .headers import should_save_headers, save_headers


def get_default_archive_methods():
    return [
        ('title', should_save_title, save_title),
        ('favicon', should_save_favicon, save_favicon),
        ('wget', should_save_wget, save_wget),
        ('singlefile', should_save_singlefile, save_singlefile),
        ('pdf', should_save_pdf, save_pdf),
        ('screenshot', should_save_screenshot, save_screenshot),
        ('dom', should_save_dom, save_dom),
        ('readability', should_save_readability, save_readability), #keep readability below wget and singlefile, as it depends on them
        ('mercury', should_save_mercury, save_mercury),
        ('git', should_save_git, save_git),
        ('media', should_save_media, save_media),
        ('headers', should_save_headers, save_headers),
        ('archive_org', should_save_archive_dot_org, save_archive_dot_org),
    ]

ARCHIVE_METHODS_INDEXING_PRECEDENCE = [('readability', 1), ('singlefile', 2), ('dom', 3), ('wget', 4)]

@enforce_types
def ignore_methods(to_ignore: List[str]):
    ARCHIVE_METHODS = get_default_archive_methods()
    methods = filter(lambda x: x[0] not in to_ignore, ARCHIVE_METHODS)
    methods = map(lambda x: x[0], methods)
    return list(methods)

@enforce_types
def archive_link(link: Link, overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None, skip_index: bool=False) -> Link:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    # TODO: Remove when the input is changed to be a snapshot. Suboptimal approach.
    if not skip_index:
        from core.models import Snapshot, ArchiveResult
        try:
            snapshot = Snapshot.objects.get(url=link.url) # TODO: This will be unnecessary once everything is a snapshot
        except Snapshot.DoesNotExist:
            snapshot = write_link_to_sql_index(link)

    ARCHIVE_METHODS = get_default_archive_methods()
    
    if methods:
        ARCHIVE_METHODS = [
            method for method in ARCHIVE_METHODS
            if method[0] in methods
        ]

    out_dir = out_dir or Path(link.link_dir)
    try:
        is_new = not Path(out_dir).exists()
        if is_new:
            os.makedirs(out_dir)

        link = load_link_details(link, out_dir=out_dir)
        write_link_details(link, out_dir=out_dir, skip_sql_index=skip_index)
        log_link_archiving_started(link, out_dir, is_new)
        link = link.overwrite(updated=datetime.now())
        stats = {'skipped': 0, 'succeeded': 0, 'failed': 0}

        for method_name, should_run, method_function in ARCHIVE_METHODS:
            try:
                if method_name not in link.history:
                    link.history[method_name] = []

                if should_run(link, out_dir) or overwrite:
                    log_archive_method_started(method_name)

                    result = method_function(link=link, out_dir=out_dir)

                    link.history[method_name].append(result)

                    stats[result.status] += 1
                    write_search_index(link=link, texts=result.index_texts)
                    log_archive_method_finished(result)
                    if not skip_index:
                        ArchiveResult.objects.create(snapshot=snapshot, extractor=method_name, cmd=result.cmd, cmd_version=result.cmd_version,
                                                 output=result.output, pwd=result.pwd, start_ts=result.start_ts, end_ts=result.end_ts, status=result.status)

                else:
                    # print('{black}      X {}{reset}'.format(method_name, **ANSI))
                    stats['skipped'] += 1
            except Exception as e:
                raise Exception('Exception in archive_methods.save_{}(Link(url={}))'.format(
                    method_name,
                    link.url,
                )) from e

        # print('    ', stats)

        try:
            latest_title = link.history['title'][-1].output.strip()
            if latest_title and len(latest_title) >= len(link.title or ''):
                link = link.overwrite(title=latest_title)
        except Exception:
            pass

        write_link_details(link, out_dir=out_dir, skip_sql_index=skip_index)

        log_link_archiving_finished(link, link.link_dir, is_new, stats)

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
def archive_links(all_links: Union[Iterable[Link], QuerySet], overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None) -> List[Link]:

    if type(all_links) is QuerySet:
        num_links: int = all_links.count()
        get_link = lambda x: x.as_link()
        all_links = all_links.iterator()
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
            archive_link(to_archive, overwrite=overwrite, methods=methods, out_dir=Path(link.link_dir))
    except KeyboardInterrupt:
        log_archiving_paused(num_links, idx, link.timestamp)
        raise SystemExit(0)
    except BaseException:
        print()
        raise

    log_archiving_finished(num_links)
    return all_links
