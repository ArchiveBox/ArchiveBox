__package__ = 'archivebox.core'

from django.contrib.auth import get_user_model


from core.models import Snapshot, ArchiveResult, Tag
from core.admin_tags import TagAdmin
from core.admin_snapshots import SnapshotAdmin
from core.admin_archiveresults import ArchiveResultAdmin
from core.admin_users import UserAdmin

import abx


@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(get_user_model(), UserAdmin)
    admin_site.register(ArchiveResult, ArchiveResultAdmin)
    admin_site.register(Snapshot, SnapshotAdmin)
    admin_site.register(Tag, TagAdmin)
