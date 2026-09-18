"""Core REST routes, composed from entity-specific routers."""

from typing import Union

from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import redirect
from ninja import Router
from ninja.errors import HttpError

from archivebox.api.v1_crawls import CrawlSchema, get_crawl

from . import archiveresults, snapshots, tags
from .archiveresults import get_archiveresult
from .pagination import CustomPagination as CustomPagination
from .schemas import ArchiveResultSchema, SnapshotSchema, TagSchema
from .snapshots import get_snapshot
from .tags import get_tag

router = Router(tags=["Core Models"])
router.add_router("", archiveresults.router)
router.add_router("", snapshots.router)
router.add_router("", tags.router)


@router.get(
    "/any/{id}",
    response=Union[SnapshotSchema, ArchiveResultSchema, TagSchema, CrawlSchema],
    url_name="get_any",
    summary="Get any object by its ID",
)
def get_any(request: HttpRequest, id: str):
    """Get any object by its ID (e.g. snapshot, archiveresult, tag, crawl, etc.)."""
    setattr(request, "with_snapshots", False)
    setattr(request, "with_archiveresults", False)

    for getter in (get_snapshot, get_archiveresult, get_tag, get_crawl):
        try:
            response = getter(request, id)
            if isinstance(response, Model):
                return redirect(
                    f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.pk}?{request.META['QUERY_STRING']}",
                )
        except Exception:
            pass

    raise HttpError(404, "Object with given ID not found")
