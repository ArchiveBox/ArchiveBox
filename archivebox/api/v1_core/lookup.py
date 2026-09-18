from django.db.models import Q

from archivebox.core.models import Snapshot
from archivebox.misc.db import uuid_ref_query as _uuid_ref_query


def _get_snapshot_by_ref(snapshot_id: str):
    queryset = Snapshot.objects.select_related("crawl__created_by")
    try:
        return queryset.get(_uuid_ref_query("id", snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        return queryset.get(_uuid_ref_query("id", snapshot_id))
