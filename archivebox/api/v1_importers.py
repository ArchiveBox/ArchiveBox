"""Native importer catalog, source configuration, actions, and durable run history."""

from dataclasses import asdict
from uuid import UUID
from typing import Literal

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from archivebox.importers.catalog import get_importers
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.importers.service import delete_source, save_source, source_action

router = Router(tags=["Importers"])


class SourceSchema(Schema):
    type: str = "ImporterSource"
    id: str
    name: str
    plugin: str
    feed: str
    created_by_id: int
    created_by_username: str
    created_at: str
    persona_id: str | None
    persona_name: str | None
    folder_id: str | None
    folder_name: str | None
    settings: dict
    checkpoint: dict
    account: dict
    limit: int
    tags: str
    schedule: str
    enabled: bool
    next_run_at: str | None


class RunSchema(Schema):
    type: str = "ImporterRun"
    id: str
    source_id: str
    source_name: str
    action: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    owner_id: str | None
    crawl_id: str | None
    cancel_requested: bool
    items: list
    result: dict
    message: str


class SourceCreate(Schema):
    plugin: str
    feed: str
    name: str = ""
    persona_id: UUID | None = None
    folder_id: UUID | None = None
    settings: dict = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=500)
    tags: str = ""
    schedule: str = ""
    enabled: bool = True


class SourceUpdate(Schema):
    name: str | None = None
    persona_id: UUID | None = None
    folder_id: UUID | None = None
    settings: dict | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    tags: str | None = None
    schedule: str | None = None
    enabled: bool | None = None


@router.get("/catalog")
def importer_catalog(request):
    return [asdict(item) for item in get_importers().values()]


@router.get("/sources", response=list[SourceSchema])
def list_sources(request, format: str | None = None):
    records = (source.to_json() for source in ImporterSource.objects.select_related("created_by", "persona", "folder"))
    if format:
        from archivebox.core.exports import model_export_response

        return model_export_response(records, format, name="importers")
    return list(records)


@router.post("/sources", response=SourceSchema)
def create_source(request, data: SourceCreate):
    try:
        return save_source(ImporterSource(created_by=request.user), data.model_dump()).to_json()
    except (ValidationError, ValueError) as error:
        raise HttpError(400, str(error)) from error


@router.get("/source/{source_id}", response=SourceSchema)
def get_source(request, source_id: UUID):
    return get_object_or_404(ImporterSource, pk=source_id).to_json()


@router.patch("/source/{source_id}", response=SourceSchema)
def update_source(request, source_id: UUID, data: SourceUpdate):
    source = get_object_or_404(ImporterSource, pk=source_id)
    values = data.model_dump(exclude_unset=True)
    if any(value is None and key not in {"persona_id", "folder_id"} for key, value in values.items()):
        raise HttpError(400, "Only persona_id and folder_id can be cleared with null.")
    try:
        return save_source(source, values).to_json()
    except (ValidationError, ValueError) as error:
        raise HttpError(400, str(error)) from error


@router.delete("/source/{source_id}")
def remove_source(request, source_id: UUID):
    source = get_object_or_404(ImporterSource, pk=source_id)
    try:
        delete_source(source)
    except ValueError as error:
        raise HttpError(409, str(error)) from error
    return {"deleted": True}


@router.post("/source/{source_id}/{action}", response=RunSchema | SourceSchema)
def run_source_action(request, source_id: UUID, action: Literal["check", "preview", "import", "pause", "resume", "reset", "reset_code"]):
    source = get_object_or_404(ImporterSource, pk=source_id)
    try:
        return source_action(source, action).to_json()
    except ValueError as error:
        raise HttpError(400, str(error)) from error


@router.get("/runs", response=list[RunSchema])
def list_runs(request, source_id: UUID | None = None, limit: int = 100, offset: int = 0, format: str | None = None):
    if not 1 <= limit <= 1000 or offset < 0:
        raise HttpError(400, "Use a limit from 1 to 1000 and a nonnegative offset.")
    runs = ImporterRun.objects.select_related("source")
    if source_id:
        runs = runs.filter(source_id=source_id)
    records = (run.to_json() for run in runs[offset : offset + limit])
    if format:
        from archivebox.core.exports import model_export_response

        return model_export_response(records, format, name="importer-runs")
    return list(records)


@router.get("/run/{run_id}", response=RunSchema)
def get_run(request, run_id: UUID):
    return get_object_or_404(ImporterRun, pk=run_id).to_json()
