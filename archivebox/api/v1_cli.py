__package__ = "archivebox.api"

import json
from io import StringIO
from typing import Any
from enum import Enum

from django.http import HttpRequest

from ninja import Router, Schema

from archivebox.misc.util import ansi_to_html


# from .auth import API_AUTH_METHODS

# router for API that exposes archivebox cli subcommands as REST endpoints
router = Router(tags=["ArchiveBox CLI Sub-Commands"])


# Schemas

JSONType = list[Any] | dict[str, Any] | bool | int | str | None


class CLICommandResponseSchema(Schema):
    success: bool
    errors: list[str]
    result: JSONType
    result_format: str = "str"
    stdout: str
    stderr: str


class FilterTypeChoices(str, Enum):
    exact = "exact"
    substring = "substring"
    regex = "regex"
    domain = "domain"
    tag = "tag"
    timestamp = "timestamp"


class StatusChoices(str, Enum):
    indexed = "indexed"
    archived = "archived"
    unarchived = "unarchived"
    present = "present"
    valid = "valid"
    invalid = "invalid"
    duplicate = "duplicate"
    orphaned = "orphaned"
    corrupted = "corrupted"
    unrecognized = "unrecognized"


class AddCommandSchema(Schema):
    urls: list[str]
    snapshot_ids: list[str] | None = None
    tag: str = ""
    depth: int = 0
    max_urls: int = 0
    crawl_max_size: int = 0
    crawl_timeout: int = 0
    snapshot_max_size: int = 0
    parser: str = "auto"
    plugins: str = ""
    only_new: bool | None = None
    update: bool = False
    overwrite: bool = False
    index_only: bool = False


class UpdateCommandSchema(Schema):
    resume: str | None = None
    after: float | None = 0
    before: float | None = 999999999999999
    filter_type: str | None = FilterTypeChoices.substring
    filter_patterns: list[str] | None = ["https://example.com"]
    batch_size: int = 100
    continuous: bool = False


class ScheduleCommandSchema(Schema):
    import_path: str | None = None
    add: bool = False
    show: bool = False
    foreground: bool = False
    run_all: bool = False
    quiet: bool = False
    every: str | None = None
    tag: str = ""
    depth: int = 0
    only_new: bool | None = None
    update: bool = False
    overwrite: bool = False
    clear: bool = False


class ListCommandSchema(Schema):
    filter_patterns: list[str] | None = ["https://example.com"]
    filter_type: str = FilterTypeChoices.substring
    status: StatusChoices = StatusChoices.indexed
    after: float | None = 0
    before: float | None = 999999999999999
    sort: str = "bookmarked_at"
    as_json: bool = True
    as_html: bool = False
    as_csv: str | None = "timestamp,url"
    with_headers: bool = False


class RemoveCommandSchema(Schema):
    after: float | None = 0
    before: float | None = 999999999999999
    filter_type: str = FilterTypeChoices.exact
    filter_patterns: list[str] | None = ["https://example.com"]


@router.post("/add", response=CLICommandResponseSchema, summary="archivebox add [args] [urls]")
def cli_add(request: HttpRequest, args: AddCommandSchema):
    from archivebox.cli.archivebox_add import add

    config_overrides: dict[str, object] = {}
    if args.only_new is not None:
        config_overrides["ONLY_NEW"] = bool(args.only_new)
    if args.update or args.overwrite:
        config_overrides["ONLY_NEW"] = False
    crawl, snapshots = add(
        urls=args.urls,
        snapshot_ids=args.snapshot_ids,
        tag=args.tag,
        depth=args.depth,
        max_urls=args.max_urls,
        crawl_max_size=args.crawl_max_size,
        crawl_timeout=args.crawl_timeout,
        snapshot_max_size=args.snapshot_max_size,
        index_only=args.index_only,
        plugins=args.plugins,
        parser=args.parser,
        bg=True,  # Always run in background for API calls
        created_by_id=request.user.pk,
        config=config_overrides or None,
    )

    snapshot_ids = [str(snapshot_id) for snapshot_id in snapshots.values_list("id", flat=True)]
    result_payload = {
        "crawl_id": str(crawl.id),
        "num_snapshots": len(snapshot_ids),
        "snapshot_ids": snapshot_ids,
        "queued_urls": args.urls,
    }
    stdout = getattr(request, "stdout", None)
    stderr = getattr(request, "stderr", None)

    return {
        "success": True,
        "errors": [],
        "result": result_payload,
        "result_format": "json",
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }


@router.post("/update", response=CLICommandResponseSchema, summary="archivebox update [args] [filter_patterns]")
def cli_update(request: HttpRequest, args: UpdateCommandSchema):
    from archivebox.cli.archivebox_update import update

    result = update(
        filter_patterns=args.filter_patterns or [],
        filter_type=args.filter_type or FilterTypeChoices.substring,
        after=args.after,
        before=args.before,
        resume=args.resume,
        batch_size=args.batch_size,
        continuous=args.continuous,
        stop_daemon_stack=False,
    )
    stdout = getattr(request, "stdout", None)
    stderr = getattr(request, "stderr", None)
    return {
        "success": True,
        "errors": [],
        "result": result,
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }


@router.post("/schedule", response=CLICommandResponseSchema, summary="archivebox schedule [args] [import_path]")
def cli_schedule(request: HttpRequest, args: ScheduleCommandSchema):
    from archivebox.cli.archivebox_schedule import schedule

    config_overrides: dict[str, object] = {}
    if args.only_new is not None:
        config_overrides["ONLY_NEW"] = bool(args.only_new)
    if args.update or args.overwrite:
        config_overrides["ONLY_NEW"] = False
    result = schedule(
        import_path=args.import_path,
        add=args.add,
        show=args.show,
        foreground=args.foreground,
        run_all=args.run_all,
        quiet=args.quiet,
        clear=args.clear,
        every=args.every,
        tag=args.tag,
        depth=args.depth,
        config=config_overrides or None,
    )

    stdout = getattr(request, "stdout", None)
    stderr = getattr(request, "stderr", None)
    return {
        "success": True,
        "errors": [],
        "result": result,
        "result_format": "json",
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }


@router.post("/search", response=CLICommandResponseSchema, summary="archivebox search [args] [filter_patterns]")
def cli_search(request: HttpRequest, args: ListCommandSchema):
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

    result_format = "txt"
    if args.as_json:
        result_format = "json"
        result = json.loads(result)
    elif args.as_html:
        result_format = "html"
    elif args.as_csv:
        result_format = "csv"

    stdout = getattr(request, "stdout", None)
    stderr = getattr(request, "stderr", None)
    return {
        "success": True,
        "errors": [],
        "result": result,
        "result_format": result_format,
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }


@router.post("/remove", response=CLICommandResponseSchema, summary="archivebox remove [args] [filter_patterns]")
def cli_remove(request: HttpRequest, args: RemoveCommandSchema):
    from archivebox.cli.archivebox_remove import remove
    from archivebox.cli.archivebox_search import get_snapshots
    from archivebox.core.models import Snapshot

    filter_patterns = args.filter_patterns or []
    snapshots_to_remove = get_snapshots(
        filter_patterns=filter_patterns,
        filter_type=args.filter_type,
        after=args.after,
        before=args.before,
    )
    removed_snapshot_ids = [str(snapshot_id) for snapshot_id in snapshots_to_remove.values_list("id", flat=True)]

    remove(
        yes=True,  # no way to interactively ask for confirmation via API, so we force yes
        snapshots=snapshots_to_remove,
        before=args.before,
        after=args.after,
        filter_type=args.filter_type,
        filter_patterns=filter_patterns,
    )

    result = {
        "removed_count": len(removed_snapshot_ids),
        "removed_snapshot_ids": removed_snapshot_ids,
        "remaining_snapshots": Snapshot.objects.count(),
    }
    stdout = getattr(request, "stdout", None)
    stderr = getattr(request, "stderr", None)
    return {
        "success": True,
        "errors": [],
        "result": result,
        "result_format": "json",
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }
