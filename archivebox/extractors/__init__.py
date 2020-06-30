__package__ = 'archivebox.extractors'

import os

from typing import Optional
from datetime import datetime

from ..index.schema import Link
from ..index import (
    load_link_details,
    write_link_details,
    patch_main_index,
)
from ..util import enforce_types
from ..cli.logging import (
    log_link_archiving_started,
    log_link_archiving_finished,
    log_archive_method_started,
    log_archive_method_finished,
)

from .title import should_save_title, save_title
from .favicon import should_save_favicon, save_favicon
from .wget import should_save_wget, save_wget
from .pdf import should_save_pdf, save_pdf
from .screenshot import should_save_screenshot, save_screenshot
from .dom import should_save_dom, save_dom
from .git import should_save_git, save_git
from .media import should_save_media, save_media
from .archive_org import should_save_archive_dot_org, save_archive_dot_org


@enforce_types
def archive_link(link: Link, overwrite: bool=False, out_dir: Optional[str]=None) -> Link:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""

    ARCHIVE_METHODS = (
        ('title', should_save_title, save_title),
        ('favicon', should_save_favicon, save_favicon),
        ('wget', should_save_wget, save_wget),
        ('pdf', should_save_pdf, save_pdf),
        ('screenshot', should_save_screenshot, save_screenshot),
        ('dom', should_save_dom, save_dom),
        ('git', should_save_git, save_git),
        ('media', should_save_media, save_media),
        ('archive_org', should_save_archive_dot_org, save_archive_dot_org),
    )

    out_dir = out_dir or link.link_dir
    try:
        is_new = not os.path.exists(out_dir)
        if is_new:
            os.makedirs(out_dir)

        link = load_link_details(link, out_dir=out_dir)
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

        write_link_details(link, out_dir=link.link_dir)
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
