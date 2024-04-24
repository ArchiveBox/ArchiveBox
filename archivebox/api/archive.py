# archivebox_api.py
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel
from ninja import Router
from main import (
    add,
    remove,
    update,
    list_all,
    ONLY_NEW,
)  # Assuming these functions are defined in main.py


# Schemas

class StatusChoices(str, Enum):
    indexed = 'indexed'
    archived = 'archived'
    unarchived = 'unarchived'
    present = 'present'
    valid = 'valid'
    invalid = 'invalid'
    duplicate = 'duplicate'
    orphaned = 'orphaned'
    corrupted = 'corrupted'
    unrecognized = 'unrecognized'


class AddURLSchema(BaseModel):
    urls: List[str]
    tag: str = ""
    depth: int = 0
    update: bool = not ONLY_NEW  # Default to the opposite of ONLY_NEW
    update_all: bool = False
    index_only: bool = False
    overwrite: bool = False
    init: bool = False
    extractors: str = ""
    parser: str = "auto"


class RemoveURLSchema(BaseModel):
    yes: bool = False
    delete: bool = False
    before: Optional[float] = None
    after: Optional[float] = None
    filter_type: str = "exact"
    filter_patterns: Optional[List[str]] = None


class UpdateSchema(BaseModel):
    resume: Optional[float] = None
    only_new: Optional[bool] = None
    index_only: Optional[bool] = False
    overwrite: Optional[bool] = False
    before: Optional[float] = None
    after: Optional[float] = None
    status: Optional[StatusChoices] = None
    filter_type: Optional[str] = 'exact'
    filter_patterns: Optional[List[str]] = None
    extractors: Optional[str] = ""


class ListAllSchema(BaseModel):
    filter_patterns: Optional[List[str]] = None
    filter_type: str = 'exact'
    status: Optional[StatusChoices] = None
    after: Optional[float] = None
    before: Optional[float] = None
    sort: Optional[str] = None
    csv: Optional[str] = None
    json: bool = False
    html: bool = False
    with_headers: bool = False


# API Router
router = Router()


@router.post("/add", response={200: dict})
def api_add(request, payload: AddURLSchema):
    try:
        result = add(
            urls=payload.urls,
            tag=payload.tag,
            depth=payload.depth,
            update=payload.update,
            update_all=payload.update_all,
            index_only=payload.index_only,
            overwrite=payload.overwrite,
            init=payload.init,
            extractors=payload.extractors,
            parser=payload.parser,
        )
        # Currently the add function returns a list of ALL items in the DB, ideally only return new items
        return {
            "status": "success",
            "message": "URLs added successfully.",
            "result": str(result),
        }
    except Exception as e:
        # Handle exceptions raised by the add function or during processing
        return {"status": "error", "message": str(e)}


@router.post("/remove", response={200: dict})
def api_remove(request, payload: RemoveURLSchema):
    try:
        result = remove(
            yes=payload.yes,
            delete=payload.delete,
            before=payload.before,
            after=payload.after,
            filter_type=payload.filter_type,
            filter_patterns=payload.filter_patterns,
        )
        return {
            "status": "success",
            "message": "URLs removed successfully.",
            "result": result,
        }
    except Exception as e:
        # Handle exceptions raised by the remove function or during processing
        return {"status": "error", "message": str(e)}


@router.post("/update", response={200: dict})
def api_update(request, payload: UpdateSchema):
    try:
        result = update(
            resume=payload.resume,
            only_new=payload.only_new,
            index_only=payload.index_only,
            overwrite=payload.overwrite,
            before=payload.before,
            after=payload.after,
            status=payload.status,
            filter_type=payload.filter_type,
            filter_patterns=payload.filter_patterns,
            extractors=payload.extractors,
        )
        return {
            "status": "success",
            "message": "Archive updated successfully.",
            "result": result,
        }
    except Exception as e:
        # Handle exceptions raised by the update function or during processing
        return {"status": "error", "message": str(e)}


@router.post("/list_all", response={200: dict})
def api_list_all(request, payload: ListAllSchema):
    try:
        result = list_all(
            filter_patterns=payload.filter_patterns,
            filter_type=payload.filter_type,
            status=payload.status,
            after=payload.after,
            before=payload.before,
            sort=payload.sort,
            csv=payload.csv,
            json=payload.json,
            html=payload.html,
            with_headers=payload.with_headers,
        )
        # TODO: This is kind of bad, make the format a choice field
        if payload.json:
            return {"status": "success", "format": "json", "data": result}
        elif payload.html:
            return {"status": "success", "format": "html", "data": result}
        elif payload.csv:
            return {"status": "success", "format": "csv", "data": result}
        else:
            return {
                "status": "success",
                "message": "List generated successfully.",
                "data": result,
            }
    except Exception as e:
        # Handle exceptions raised by the list_all function or during processing
        return {"status": "error", "message": str(e)}
