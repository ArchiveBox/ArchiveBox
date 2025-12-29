__package__ = 'archivebox.core'

from django.contrib.auth import get_user_model


from archivebox.core.models import Snapshot, ArchiveResult, Tag
from archivebox.core.admin_tags import TagAdmin
from archivebox.core.admin_snapshots import SnapshotAdmin
from archivebox.core.admin_archiveresults import ArchiveResultAdmin
from archivebox.core.admin_users import UserAdmin


def register_admin(admin_site):
    admin_site.register(get_user_model(), UserAdmin)
    admin_site.register(ArchiveResult, ArchiveResultAdmin)
    admin_site.register(Snapshot, SnapshotAdmin)
    admin_site.register(Tag, TagAdmin)
