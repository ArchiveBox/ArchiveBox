__package__ = 'archivebox.api'

import json
from typing import List, Dict, Any, Optional
from enum import Enum

from ninja import Router, Schema

from archivebox.misc.util import ansi_to_html
from archivebox.config.common import ARCHIVING_CONFIG


# from .auth import API_AUTH_METHODS

# router for API that exposes archivebox cli subcommands as REST endpoints
router = Router(tags=['ArchiveBox CLI Sub-Commands'])


# Schemas

JSONType = List[Any] | Dict[str, Any] | bool | int | str | None

class CLICommandResponseSchema(Schema):
    success: bool
    errors: List[str]
    result: JSONType
    result_format: str = 'str'
    stdout: str
    stderr: str

class FilterTypeChoices(str, Enum):
    exact = 'exact'
    substring = 'substring'
    regex = 'regex'
    domain = 'domain'
    tag = 'tag'
    timestamp = 'timestamp'

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


class AddCommandSchema(Schema):
    urls: List[str]
    tag: str = ""
    depth: int = 0
    parser: str = "auto"
    extract: str = ""
    update: bool = not ARCHIVING_CONFIG.ONLY_NEW  # Default to the opposite of ARCHIVING_CONFIG.ONLY_NEW
    overwrite: bool = False
    index_only: bool = False

class UpdateCommandSchema(Schema):
    resume: Optional[float] = 0
    only_new: bool = ARCHIVING_CONFIG.ONLY_NEW
    index_only: bool = False
    overwrite: bool = False
    after: Optional[float] = 0
    before: Optional[float] = 999999999999999
    status: Optional[StatusChoices] = StatusChoices.unarchived
    filter_type: Optional[str] = FilterTypeChoices.substring
    filter_patterns: Optional[List[str]] = ['https://example.com']
    extractors: Optional[str] = ""

class ScheduleCommandSchema(Schema):
    import_path: Optional[str] = None
    add: bool = False
    every: Optional[str] = None
    tag: str = ''
    depth: int = 0
    overwrite: bool = False
    update: bool = not ARCHIVING_CONFIG.ONLY_NEW
    clear: bool = False

class ListCommandSchema(Schema):
    filter_patterns: Optional[List[str]] = ['https://example.com']
    filter_type: str = FilterTypeChoices.substring
    status: StatusChoices = StatusChoices.indexed
    after: Optional[float] = 0
    before: Optional[float] = 999999999999999
    sort: str = 'bookmarked_at'
    as_json: bool = True
    as_html: bool = False
    as_csv: str | None = 'timestamp,url'
    with_headers: bool = False

class RemoveCommandSchema(Schema):
    delete: bool = True
    after: Optional[float] = 0
    before: Optional[float] = 999999999999999
    filter_type: str = FilterTypeChoices.exact
    filter_patterns: Optional[List[str]] = ['https://example.com']





@router.post("/add", response=CLICommandResponseSchema, summary='archivebox add [args] [urls]')
def cli_add(request, args: AddCommandSchema):
    from archivebox.cli.archivebox_add import add
    
    result = add(
        urls=args.urls,
        tag=args.tag,
        depth=args.depth,
        update=args.update,
        index_only=args.index_only,
        overwrite=args.overwrite,
        extract=args.extract,
        parser=args.parser,
    )

    return {
        "success": True,
        "errors": [],
        "result": result,
        "stdout": ansi_to_html(request.stdout.getvalue().strip()),
        "stderr": ansi_to_html(request.stderr.getvalue().strip()),
    }


@router.post("/update", response=CLICommandResponseSchema, summary='archivebox update [args] [filter_patterns]')
def cli_update(request, args: UpdateCommandSchema):
    from archivebox.cli.archivebox_update import update
    
    result = update(
        resume=args.resume,
        only_new=args.only_new,
        index_only=args.index_only,
        overwrite=args.overwrite,
        before=args.before,
        after=args.after,
        status=args.status,
        filter_type=args.filter_type,
        filter_patterns=args.filter_patterns,
        extractors=args.extractors,
    )
    return {
        "success": True,
        "errors": [],
        "result": result,
        "stdout": ansi_to_html(request.stdout.getvalue().strip()),
        "stderr": ansi_to_html(request.stderr.getvalue().strip()),
    }


@router.post("/schedule", response=CLICommandResponseSchema, summary='archivebox schedule [args] [import_path]')
def cli_schedule(request, args: ScheduleCommandSchema):
    from archivebox.cli.archivebox_schedule import schedule
    
    result = schedule(
        import_path=args.import_path,
        add=args.add,
        show=args.show,
        clear=args.clear,
        every=args.every,
        tag=args.tag,
        depth=args.depth,
        overwrite=args.overwrite,
        update=args.update,
    )

    return {
        "success": True,
        "errors": [],
        "result": result,
        "stdout": ansi_to_html(request.stdout.getvalue().strip()),
        "stderr": ansi_to_html(request.stderr.getvalue().strip()),
    }



@router.post("/search", response=CLICommandResponseSchema, summary='archivebox search [args] [filter_patterns]')
def cli_search(request, args: ListCommandSchema):
    from archivebox.cli.archivebox_search import search
    
    result = search(
        filter_patterns=args.filter_patterns,
        filter_type=args.filter_type,
        status=args.status,
        after=args.after,
        before=args.before,
        sort=args.sort,
        csv=args.as_csv,
        json=args.as_json,
        html=args.as_html,
        with_headers=args.with_headers,
    )

    result_format = 'txt'
    if args.as_json:
        result_format = "json"
        result = json.loads(result)
    elif args.as_html:
        result_format = "html"
    elif args.as_csv:
        result_format = "csv"

    return {
        "success": True,
        "errors": [],
        "result": result,
        "result_format": result_format,
        "stdout": ansi_to_html(request.stdout.getvalue().strip()),
        "stderr": ansi_to_html(request.stderr.getvalue().strip()),
    }
    


@router.post("/remove", response=CLICommandResponseSchema, summary='archivebox remove [args] [filter_patterns]')
def cli_remove(request, args: RemoveCommandSchema):
    from archivebox.cli.archivebox_remove import remove
    
    result = remove(
        yes=True,            # no way to interactively ask for confirmation via API, so we force yes
        delete=args.delete,
        before=args.before,
        after=args.after,
        filter_type=args.filter_type,
        filter_patterns=args.filter_patterns,
    )
    return {
        "success": True,
        "errors": [],
        "result": result,
        "stdout": ansi_to_html(request.stdout.getvalue().strip()),
        "stderr": ansi_to_html(request.stderr.getvalue().strip()),
    }
    
