__package__ = 'archivebox.extractors'

import os

from typing import Optional, List, Iterable
from datetime import datetime

from ..index.schema import Link
from ..index import (
    load_link_details,
    write_link_details,
    patch_main_index,
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

from .title import should_save_title, save_title
from .favicon import should_save_favicon, save_favicon
from .wget import should_save_wget, save_wget
from .singlefile import should_save_singlefile, save_singlefile
from .pdf import should_save_pdf, save_pdf
from .screenshot import should_save_screenshot, save_screenshot
from .dom import should_save_dom, save_dom
from .git import should_save_git, save_git
from .media import should_save_media, save_media
from .archive_org import should_save_archive_dot_org, save_archive_dot_org

def get_default_archive_methods():
    return [
            ('title', should_save_title, save_title),
            ('favicon', should_save_favicon, save_favicon),
            ('wget', should_save_wget, save_wget),
            ('singlefile', should_save_singlefile, save_singlefile),
            ('pdf', should_save_pdf, save_pdf),
            ('screenshot', should_save_screenshot, save_screenshot),
            ('dom', should_save_dom, save_dom),
            ('git', should_save_git, save_git),
            ('media', should_save_media, save_media),
            ('archive_org', should_save_archive_dot_org, save_archive_dot_org),
        ]

@enforce_types
def ignore_methods(to_ignore: List[str]):
    ARCHIVE_METHODS = get_default_archive_methods()
    methods = filter(lambda x: x[0] not in to_ignore, ARCHIVE_METHODS)
    methods = map(lambda x: x[1], methods)
    return list(methods)

@enforce_types
def archive_link(link: Link, overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[str]=None, skip_index: bool=False) -> Link:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    ARCHIVE_METHODS = get_default_archive_methods()
    
    if methods is not None:
        ARCHIVE_METHODS = [
            method for method in ARCHIVE_METHODS
            if method[1] in methods
        ]

    out_dir = out_dir or link.link_dir
    try:
        is_new = not os.path.exists(out_dir)
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
                    log_archive_method_finished(result)
                else:
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
        if not skip_index:
            patch_main_index(link)

        # # If any changes were made, update the main links index json and html
        # was_changed = stats['succeeded'] or stats['failed']
        # if was_changed:
        #     patch_main_index(link)

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
def archive_links(links: List[Link], overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[str]=None) -> List[Link]:
    if not links:
        return []

    log_archiving_started(len(links))
    idx: int = 0
    link: Link = links[0]
    try:
        for idx, link in enumerate(links):
            archive_link(link, overwrite=overwrite, methods=methods, out_dir=link.link_dir)
    except KeyboardInterrupt:
        log_archiving_paused(len(links), idx, link.timestamp)
        raise SystemExit(0)
    except BaseException:
        print()
        raise

    log_archiving_finished(len(links))
    return links
