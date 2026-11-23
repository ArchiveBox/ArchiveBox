"""Folder CRUD and smart rule discovery use native model validation and membership."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.core import signing
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from archivebox.core.models import Folder, Snapshot
from archivebox.core.smart_folders import OPERATORS, RuleQuery
from archivebox.uuid_compat import compact_uuid
from .auth import authenticated_user_from_request

router = Router(tags=["Folders"])


class FolderSchema(Schema):
    type: str = "Folder"
    id: str
    name: str
    parent_id: str | None
    parent_name: str | None
    created_by_id: int | None
    created_by_username: str | None
    position: int
    rules: dict | None
    is_smart: bool
    is_container: bool


class FolderCreate(Schema):
    name: str
    parent_id: UUID | None = None
    position: int = Field(default=0, ge=0)
    rules: dict | None = None


class FolderUpdate(Schema):
    name: str | None = None
    parent_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)
    rules: dict | None = None


class FolderSelection(Schema):
    snapshot_ids: list[UUID]
    destination_id: UUID | None = None


@router.get("/folders", response=list[FolderSchema])
def list_folders(request, format: str | None = None):
    folders = Folder.objects.select_related("parent", "created_by")
    if format:
        from archivebox.core.exports import model_export_response

        return model_export_response(request, (folder.to_json() for folder in folders.iterator(chunk_size=32)), format, name="folders")
    return [folder.to_json() for folder in folders]


@router.get("/folders/rules")
def folder_rules(request):
    return {"fields": RuleQuery.schema(), "sort_fields": RuleQuery.sort_fields(), "operators": OPERATORS}


@router.get("/folders/autocomplete/", url_name="folders_autocomplete", auth=None)
def folders_autocomplete(request, q: str = "", destination: bool = False, exclude: UUID | None = None, after: str = ""):
    """Return one page of folder IDs and their full paths."""
    user = authenticated_user_from_request(request)
    if user is None:
        raise HttpError(401, "Authentication required.")
    if not user.is_superuser and (
        not user.is_staff
        or not any(
            user.has_perm(f"{app}.{action}_{model}")
            for app, model in (("core", "folder"), ("core", "snapshot"), ("crawls", "crawl"), ("importers", "importersource"))
            for action in ("view", "add", "change")
        )
    ):
        raise HttpError(403, "Folder lookup is unavailable for this account.")
    term = q.strip()[:100]
    scope = [term, destination, str(exclude or "")]
    salt = "folder-autocomplete"
    folders = Folder.objects.matching_name(term)
    if destination:
        folders = folders.destinations()
    if exclude:
        folders = folders.exclude(pk__in=Folder.subtree_ids(exclude))
    if after:
        try:
            cursor = signing.loads(after, salt=salt)
            if cursor[:3] != scope:
                raise ValueError
            position, name, pk = cursor[3:]
            folders = folders.filter(
                Q(position__gt=position) | Q(position=position, name__gt=name) | Q(position=position, name=name, pk__gt=compact_uuid(pk)),
            )
        except (signing.BadSignature, ValueError, TypeError) as error:
            raise HttpError(400, "Invalid folder cursor.") from error
    page = list(folders.only("name", "parent", "position").order_by("position", "name", "pk")[:21])
    last = page[19] if len(page) > 20 else None
    return {
        "choices": Folder.picker_choices(page[:20]),
        "next": signing.dumps([*scope, last.position, last.name, str(last.pk)], salt=salt) if last else "",
    }


@router.post("/folders", response=FolderSchema)
def create_folder(request, data: FolderCreate):
    folder = Folder(created_by=request.user, **data.model_dump())
    try:
        folder.save()
    except ValidationError as error:
        raise HttpError(400, " ".join(error.messages)) from error
    folder.refresh_from_db()
    return folder.to_json()


@router.get("/folder/{folder_id}", response=FolderSchema)
def get_folder(request, folder_id: UUID):
    return get_object_or_404(Folder, pk=folder_id).to_json()


@router.patch("/folder/{folder_id}", response=FolderSchema)
def update_folder(request, folder_id: UUID, data: FolderUpdate):
    folder = get_object_or_404(Folder, pk=folder_id)
    values = data.model_dump(exclude_unset=True)
    if any(value is None and key not in {"parent_id", "rules"} for key, value in values.items()):
        raise HttpError(400, "Only parent_id and rules accept null.")
    for key, value in values.items():
        setattr(folder, key, value)
    try:
        folder.save()
    except ValidationError as error:
        raise HttpError(400, " ".join(error.messages)) from error
    folder.refresh_from_db()
    return folder.to_json()


@router.delete("/folder/{folder_id}")
def delete_folder(request, folder_id: UUID):
    folder = get_object_or_404(Folder, pk=folder_id)
    try:
        folder.delete()
    except ValidationError as error:
        raise HttpError(400, " ".join(error.messages)) from error
    return {"deleted": True, "id": str(folder_id).replace("-", "")}


@router.post("/folders/move-snapshots")
def move_snapshots(request, data: FolderSelection):
    if data.destination_id:
        get_object_or_404(Folder, pk=data.destination_id)
    try:
        count = Folder.move_snapshots(Snapshot.objects.filter(pk__in=data.snapshot_ids), data.destination_id)
    except ValidationError as error:
        raise HttpError(400, " ".join(error.messages)) from error
    return {"moved": count}
