__package__ = "archivebox.api"

import json
from io import StringIO
from typing import Any
from enum import Enum

from django.http import HttpRequest

from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from archivebox.misc.util import ansi_to_html
from archivebox.core.models import SnapshotQuerySet


# router for API that exposes archivebox cli subcommands as REST endpoints
router = Router(tags=["ArchiveBox CLI Sub-Commands"])


# Schemas

JSONType = list[Any] | dict[str, Any] | bool | int | str | None
FILTER_PATTERNS_EXAMPLES = [["https://example.com"]]


class CLICommandResponseSchema(Schema):
    success: bool
    errors: list[str]
    result: JSONType
    result_format: str = "str"
    stdout: str
    stderr: str


FilterTypeChoices = Enum(
    "FilterTypeChoices",
    {filter_type: filter_type for filter_type in SnapshotQuerySet.FILTER_TYPE_CHOICES},
    type=str,
)


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
    persona: str = "Default"
    only_new: bool | None = None
    update: bool = False
    overwrite: bool = False
    index_only: bool = False


class SnapshotFilterCommandSchema(Schema):
    after: float | None = 0
    before: float | None = None
    filter_type: str | None = FilterTypeChoices.substring
    filter_patterns: list[str] | None = Field(default=None, examples=FILTER_PATTERNS_EXAMPLES)
    status: str | None = None
    url__icontains: str | None = None
    url__istartswith: str | None = None
    tag: str | None = None
    crawl_id: str | None = None
    limit: int | None = None
    sort: str | None = None
    search: str | None = None


class UpdateCommandSchema(SnapshotFilterCommandSchema):
    resume: str | None = None
    batch_size: int = 100
    continuous: bool = False
    index_only: bool = False
    migrate_only: bool = False


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


class ListCommandSchema(SnapshotFilterCommandSchema):
    as_json: bool = True
    as_html: bool = False
    as_csv: str | None = "timestamp,url"
    with_headers: bool = False


class RemoveCommandSchema(SnapshotFilterCommandSchema):
    filter_type: str = FilterTypeChoices.exact
    timeout: float = 60.0


def snapshot_filter_kwargs(args: SnapshotFilterCommandSchema, *, default_filter_type: str) -> dict[str, Any]:
    kwargs = args.dict()
    kwargs["filter_patterns"] = kwargs.get("filter_patterns") or []
    kwargs["filter_type"] = kwargs.get("filter_type") or default_filter_type
    return kwargs


@router.post("/add", response=CLICommandResponseSchema, summary="archivebox add [args] [urls]")
def cli_add(request: HttpRequest, args: AddCommandSchema):
    from archivebox.cli.archivebox_add import add
    from archivebox.misc.util import validate_url

    config_overrides: dict[str, object] = {}
    if args.only_new is not None:
        config_overrides["ONLY_NEW"] = bool(args.only_new)
    if args.update or args.overwrite:
        config_overrides["ONLY_NEW"] = False
    submitted_urls: str | list[str] = args.urls
    if len(args.urls) == 1:
        try:
            validate_url(args.urls[0])
        except ValueError:
            submitted_urls = args.urls[0]
    else:
        submitted_urls = []
        for url in args.urls:
            try:
                submitted_urls.append(validate_url(url))
            except ValueError:
                continue
        if not submitted_urls:
            raise HttpError(400, "No valid URLs were submitted")
    crawl, snapshots = add(
        urls=submitted_urls,
        snapshot_ids=args.snapshot_ids,
        tag=args.tag,
        depth=args.depth,
        max_urls=args.max_urls,
        crawl_max_size=args.crawl_max_size,
        crawl_timeout=args.crawl_timeout,
        snapshot_max_size=args.snapshot_max_size,
        index_only=args.index_only,
        plugins=args.plugins,
        persona=args.persona,
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
        "queued_urls": args.urls if isinstance(submitted_urls, str) else submitted_urls,
    }
    stdout = request.__dict__.get("stdout")
    stderr = request.__dict__.get("stderr")

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
    from archivebox.cli.archivebox_update import _build_filtered_snapshots_queryset, update
    from archivebox.core.snapshot_status import normalize_snapshot_status

    try:
        status = normalize_snapshot_status(args.status)
    except ValueError as err:
        raise HttpError(400, str(err)) from err

    update_kwargs = snapshot_filter_kwargs(args, default_filter_type=FilterTypeChoices.substring)
    update_kwargs["status"] = status
    update_kwargs["stop_daemon_stack"] = False

    is_filtered_update = any(
        (update_kwargs.get(key) for key in (*SnapshotQuerySet.FILTER_ARG_KEYS, "resume") if key != "filter_type"),
    )
    matched_snapshot_ids = []
    if is_filtered_update:
        matched_snapshot_ids = [
            str(snapshot_id) for snapshot_id in _build_filtered_snapshots_queryset(**update_kwargs).values_list("id", flat=True)
        ]

    update(**update_kwargs)
    stdout = request.__dict__.get("stdout")
    stderr = request.__dict__.get("stderr")
    return {
        "success": True,
        "errors": [],
        "result": {
            "matched_count": len(matched_snapshot_ids),
            "snapshot_ids": matched_snapshot_ids,
        }
        if is_filtered_update
        else None,
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

    stdout = request.__dict__.get("stdout")
    stderr = request.__dict__.get("stderr")
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
    from archivebox.cli.archivebox_snapshot import build_snapshot_queryset

    search_kwargs = snapshot_filter_kwargs(args, default_filter_type=FilterTypeChoices.substring)
    as_json = search_kwargs.pop("as_json")
    as_html = search_kwargs.pop("as_html")
    as_csv = search_kwargs.pop("as_csv")
    with_headers = search_kwargs.pop("with_headers")
    try:
        snapshots = build_snapshot_queryset(**search_kwargs).select_related("crawl", "crawl__created_by")
    except ValueError as err:
        raise HttpError(400, str(err)) from err

    result_format = "txt"
    if as_json:
        result_format = "json"
        result = [
            json.loads(json.dumps(snapshot.to_dict(extended=True), default=str))
            for snapshot in snapshots.prefetch_related("tags").iterator(chunk_size=500)
        ]
    elif as_html:
        result_format = "html"
        result = "\n".join(snapshot.url for snapshot in snapshots.iterator(chunk_size=500))
    elif as_csv:
        result_format = "csv"
        cols = [col.strip() for col in as_csv.split(",") if col.strip()]
        rows = [snapshot.to_csv(cols=cols, separator=",") for snapshot in snapshots.prefetch_related("tags").iterator(chunk_size=500)]
        result = "\n".join((",".join(cols), *rows) if with_headers else rows)
    else:
        result = "\n".join(snapshot.url for snapshot in snapshots.iterator(chunk_size=500))

    stdout = request.__dict__.get("stdout")
    stderr = request.__dict__.get("stderr")
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
    from archivebox.core.models import Snapshot

    remove_kwargs = snapshot_filter_kwargs(args, default_filter_type=FilterTypeChoices.exact)
    timeout_arg = remove_kwargs.pop("timeout")
    timeout = min(float(timeout_arg if timeout_arg is not None else 60.0), 60.0)
    try:
        snapshots_to_remove = Snapshot.objects.order_by("-created_at").search(**remove_kwargs)
    except ValueError as err:
        raise HttpError(400, str(err)) from err

    result = remove(
        yes=True,  # no way to interactively ask for confirmation via API, so we force yes
        snapshots=snapshots_to_remove,
        timeout=timeout,
    )
    stdout = request.__dict__.get("stdout")
    stderr = request.__dict__.get("stderr")
    return {
        "success": bool(result["success"]),
        "errors": [str(result["error"])] if result["error"] else [],
        "result": result,
        "result_format": "json",
        "stdout": ansi_to_html(stdout.getvalue().strip()) if isinstance(stdout, StringIO) else "",
        "stderr": ansi_to_html(stderr.getvalue().strip()) if isinstance(stderr, StringIO) else "",
    }
