__package__ = 'archivebox.workers'
__order__ = 100


def register_admin(admin_site):
    from workers.admin import register_admin
    register_admin(admin_site)
