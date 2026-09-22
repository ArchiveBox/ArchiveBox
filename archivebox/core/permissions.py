from __future__ import annotations

from django.db.models import QuerySet
from django.http import HttpRequest

PERMISSIONS_PUBLIC = "public"
PERMISSIONS_UNLISTED = "unlisted"
PERMISSIONS_PRIVATE = "private"
PERMISSIONS_CHOICES = (
    (PERMISSIONS_PUBLIC, "Public"),
    (PERMISSIONS_UNLISTED, "Unlisted"),
    (PERMISSIONS_PRIVATE, "Private"),
)
PERMISSIONS_VALUES = {value for value, _label in PERMISSIONS_CHOICES}
PERMISSIONS_META = {
    PERMISSIONS_PUBLIC: ("👥", "Public", "#047857", "#d1fae5"),
    PERMISSIONS_UNLISTED: ("🔗", "Unlisted", "#1d4ed8", "#dbeafe"),
    PERMISSIONS_PRIVATE: ("🔒", "Private", "#991b1b", "#fee2e2"),
}


def normalize_permissions(permissions: object, *, default: str = PERMISSIONS_PRIVATE) -> str:
    permissions = str(permissions or "").strip().lower()
    if permissions not in PERMISSIONS_VALUES:
        return default
    return permissions


def is_admin_user(request: HttpRequest) -> bool:
    user = request.user
    return bool(user.is_authenticated and user.is_active and user.is_staff)


def get_snapshot_permissions(snapshot) -> str:
    return normalize_permissions(snapshot.permissions)


def can_view_snapshot(request: HttpRequest, snapshot) -> bool:
    permissions = get_snapshot_permissions(snapshot)
    return permissions in {PERMISSIONS_PUBLIC, PERMISSIONS_UNLISTED} or is_admin_user(request)


def _persona_ids_for_permissions(allowed_permissions: set[str]) -> list[str]:
    from archivebox.personas.models import Persona

    return [str(persona_id) for persona_id in Persona.objects.filter(permissions__in=allowed_permissions).values_list("id", flat=True)]


def filter_personas_by_permissions(queryset: QuerySet, allowed_permissions: set[str]) -> QuerySet:
    return queryset.filter(id__in=_persona_ids_for_permissions(allowed_permissions))


def filter_snapshots_by_permissions(queryset: QuerySet, *, direct: bool = False, allowed_permissions: set[str] | None = None) -> QuerySet:
    allowed_permissions = allowed_permissions or ({PERMISSIONS_PUBLIC, PERMISSIONS_UNLISTED} if direct else {PERMISSIONS_PUBLIC})
    allowed = sorted(allowed_permissions)
    return queryset.filter(permissions__in=allowed)


def public_snapshots_queryset(queryset: QuerySet) -> QuerySet:
    return filter_snapshots_by_permissions(queryset, direct=False)


def direct_snapshots_queryset(request: HttpRequest, queryset: QuerySet) -> QuerySet:
    return queryset if is_admin_user(request) else filter_snapshots_by_permissions(queryset, direct=True)
