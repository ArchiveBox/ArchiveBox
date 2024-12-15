__package__ = 'archivebox.crawls'
__order__ = 100

import abx


@abx.hookimpl
def register_admin(admin_site):
    from .admin import register_admin as register_crawls_admin
    register_crawls_admin(admin_site)
