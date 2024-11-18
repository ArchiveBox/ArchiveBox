__package__ = 'archivebox.queues'

import abx

@abx.hookimpl
def register_admin(admin_site):
    from queues.admin import register_admin
    register_admin(admin_site)
