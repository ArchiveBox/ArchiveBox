
__package__ = 'archivebox.seeds'
__order__ = 100

import abx


@abx.hookimpl
def register_admin(admin_site):
    from .admin import register_admin as register_seeds_admin
    register_seeds_admin(admin_site)

