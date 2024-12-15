"""
Hookspec for ArchiveBox system events that plugins can hook into.

Loosely modeled after Django's signals architecture.
https://docs.djangoproject.com/en/5.1/ref/signals/
"""

__package__ = 'abx.archivebox'

import abx



@abx.hookspec
def on_crawl_schedule_tick(crawl_schedule):
    pass




@abx.hookspec
def on_seed_post_save(seed, created=False):
    ...

@abx.hookspec
def on_crawl_post_save(crawl, created=False):
    ...


@abx.hookspec
def on_snapshot_post_save(snapshot, created=False):
    ...
    
# @abx.hookspec
# def on_snapshot_post_delete(snapshot):
#     ...


@abx.hookspec
def on_archiveresult_post_save(archiveresult, created=False):
    ...

# @abx.hookspec
# def on_archiveresult_post_delete(archiveresult):
#     ...
