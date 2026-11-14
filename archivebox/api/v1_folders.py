"""Folder CRUD and smart rule discovery use native model validation and membership."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from archivebox.core.models import Folder, Snapshot
from archivebox.core.smart_folders import OPERATORS, RuleQuery

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
    records = (folder.to_json() for folder in Folder.objects.select_related("parent", "created_by"))
    if format:
        from archivebox.core.exports import model_export_response

        return model_export_response(records, format, name="folders")
    return list(records)


@router.get("/folders/rules")
def folder_rules(request):
    return {"fields": RuleQuery.schema(), "sort_fields": RuleQuery.sort_fields(), "operators": OPERATORS}


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
