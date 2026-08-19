#!/usr/bin/env python3
from __future__ import annotations

__package__ = "archivebox.cli"
__command__ = "archivebox add"

import sys
import os
import json
from pathlib import Path

from typing import Any, TYPE_CHECKING

import rich_click as click

from archivebox.config import CONSTANTS
from archivebox.misc.util import enforce_types, docstring
from archivebox.misc.util import parse_filesize_to_bytes


if TYPE_CHECKING:
    from django.db.models import QuerySet
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot


def _collect_input_urls(args: tuple[str, ...], *, parser: str = "auto") -> list[str]:
    from archivebox.misc.jsonl import read_args_or_stdin
    from archivebox.misc.util import validate_url

    urls: list[str] = []
    for record in read_args_or_stdin(args):
        url = record.get("url")
        if isinstance(url, str) and url:
            try:
                urls.append(validate_url(url))
            except ValueError as err:
                raise click.BadParameter(str(err), param_hint="URL") from err

        urls_field = record.get("urls")
        if isinstance(urls_field, str):
            for line in urls_field.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        urls.append(validate_url(line))
                    except ValueError as err:
                        raise click.BadParameter(str(err), param_hint="URL") from err

    return urls


@enforce_types
def add(
    urls: str | list[str],
    snapshot_ids: list[str] | None = None,
    depth: int | str = 0,
    max_urls: int = 0,
    crawl_max_size: int | str = 0,
    crawl_timeout: int = 0,
    snapshot_max_size: int | str = 0,
    crawl_max_concurrent_snapshots: int | None = None,
    tag: str = "",
    url_allowlist: str = "",
    url_denylist: str = "",
    parser: str = "auto",
    plugins: str = "",
    persona: str = "Default",
    index_only: bool = False,
    bg: bool = False,
    created_by_id: int | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[Crawl, QuerySet[Snapshot]]:
    """Add a new URL or list of URLs to your archive.

    The flow is:
    1. Save URLs to sources file
    2. Create Crawl with URLs and max_depth
    3. Crawl runner creates Snapshots from Crawl URLs (depth=0)
    4. Crawl runner runs parser extractors on root snapshots
    5. Parser extractors output to urls.jsonl
    6. URLs are added to Crawl.urls and child Snapshots are created
    7. Repeat until max_depth is reached
    """

    from rich import print

    depth = int(depth)
    max_urls = int(max_urls or 0)
    crawl_max_size = parse_filesize_to_bytes(crawl_max_size)
    crawl_timeout = int(crawl_timeout or 0)
    snapshot_max_size = parse_filesize_to_bytes(snapshot_max_size)
    from archivebox.config.permissions import USER, HOSTNAME
    from archivebox.config.common import get_config

    config_overrides = dict(config or {})
    runtime_config = get_config()
    crawl_max_concurrent_snapshots_override = crawl_max_concurrent_snapshots is not None
    if crawl_max_concurrent_snapshots is None:
        crawl_max_concurrent_snapshots = runtime_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS
    crawl_max_concurrent_snapshots = int(crawl_max_concurrent_snapshots)

    if depth not in (0, 1, 2, 3, 4):
        raise ValueError("Depth must be 0-4")
    if max_urls < 0:
        raise ValueError("max_urls must be >= 0")
    if crawl_max_size < 0:
        raise ValueError("crawl_max_size must be >= 0")
    if crawl_timeout < 0:
        raise ValueError("crawl_timeout must be >= 0")
    if snapshot_max_size < 0:
        raise ValueError("snapshot_max_size must be >= 0")
    if crawl_max_concurrent_snapshots < 1:
        raise ValueError("crawl_max_concurrent_snapshots must be >= 1")

    # import models once django is set up
    from archivebox.crawls.models import Crawl
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.personas.models import Persona
    from archivebox.misc.logging_util import printable_filesize
    from archivebox.misc.system import get_dir_size
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals
    from django.utils import timezone

    created_by_id = created_by_id or get_or_create_system_user_pk()
    started_at = timezone.now()

    use_internal_input_root = isinstance(urls, str)
    source_text = (
        urls
        if use_internal_input_root
        else "\n".join(json.dumps({"type": "CrawlSeed", "url": str(url), "depth": 0}, separators=(",", ":")) for url in urls)
    )

    # 2. Create a new Crawl with inline URLs
    # Foreground add must claim runner ownership before publishing runnable
    # work. Otherwise an existing server runner can lease the new Crawl in the
    # gap between Crawl.objects.create() and current_command(), then be killed
    # by the newer add process halfway through its first Snapshot hook.
    command = None
    if not bg and not index_only:
        from archivebox.machine.models import Process
        from archivebox.core.takeover_util import current_command

        command = current_command(Process.TypeChoices.ADD, data_dir=CONSTANTS.DATA_DIR)

    cli_args = [*sys.argv]
    if cli_args[0].lower().endswith("archivebox"):
        cli_args[0] = "archivebox"
    cmd_str = " ".join(cli_args)

    timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")

    persona_name = (persona or "Default").strip() or "Default"
    plugins = plugins or ""
    persona_obj = Persona.get_or_create_named(persona_name)
    persona_obj.ensure_dirs()
    effective_persona_config = get_config(persona=persona_obj)

    crawl_config = {
        "PERMISSIONS": str(effective_persona_config.PERMISSIONS),
        **({"INDEX_ONLY": True} if index_only else {}),
        **({"PLUGINS": plugins} if plugins else {}),
        **(
            {"CRAWL_MAX_CONCURRENT_SNAPSHOTS": crawl_max_concurrent_snapshots}
            if crawl_max_concurrent_snapshots_override
            and crawl_max_concurrent_snapshots != int(effective_persona_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS)
            else {}
        ),
        **({"CRAWL_MAX_URLS": max_urls} if max_urls else {}),
        **({"CRAWL_MAX_SIZE": crawl_max_size} if crawl_max_size else {}),
        **({"CRAWL_TIMEOUT": crawl_timeout} if crawl_timeout else {}),
        **({"SNAPSHOT_MAX_SIZE": snapshot_max_size} if snapshot_max_size else {}),
        **({"PARSER": parser} if parser != "auto" else {}),
        **({"URL_ALLOWLIST": url_allowlist} if url_allowlist else {}),
        **({"URL_DENYLIST": url_denylist} if url_denylist else {}),
    }
    # Caller-supplied overrides (e.g. {"ONLY_NEW": False}) are the highest
    # priority for crawl-frozen keys. Runtime-derived execution keys are
    # stripped by Crawl.save() and rederived when hooks run.
    crawl_config.update(config_overrides)

    # Crawl.urls is the user's submitted source, not a derived work queue for
    # this add path. Keeping it byte-for-byte readable is what lets API/UI/CLI
    # callers audit or resume imports without losing RSS/Netscape/JSON metadata
    # that is not representable as one plain URL per line.
    try:
        crawl = Crawl.objects.create(
            urls=source_text,
            # Stdin/import text gets an extra hop because the synthetic
            # archivebox://internal root lives at depth 0 and parser-discovered
            # URLs land at depth 1; direct URL args become the depth=0 input
            # snapshots themselves so --depth=N matches the deepest hop the user
            # asked for.
            max_depth=depth + 1 if use_internal_input_root else depth,
            tags_str=tag,
            persona_id=persona_obj.id,
            label=f"{USER}@{HOSTNAME} $ {cmd_str} [{timestamp}]",
            created_by_id=created_by_id,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=None if index_only else timezone.now(),
            config=crawl_config,
        )
        first_url = crawl.get_urls_list()[0] if crawl.get_urls_list() else ""
    except BaseException:
        if command is not None:
            command.mark_exited(exit_code=1)
        raise
    if command is not None:
        command.url = first_url
        command.save(update_fields=["url", "modified_at"])

    print(f"[green]\\[+] Created Crawl {crawl.id} with max_depth={depth}[/green]")
    print(f"    [dim]First URL: {first_url}[/dim]")

    # 3. The CrawlMachine will create Snapshots from all URLs when started
    #    Parser extractors run on snapshots and discover more URLs
    #    Discovered URLs become child Snapshots (depth+1)

    if index_only:
        print("[yellow]\\[*] Index-only mode - URLs queued, runner not started[/yellow]")
        return crawl, crawl.snapshot_set.none()

    # 5. Start the crawl runner to process the queue
    #    The runner will:
    #    - Process Crawl -> create Snapshots from all URLs
    #    - Process Snapshots -> run extractors
    #    - Parser extractors discover new URLs -> create child Snapshots
    #    - Repeat until max_depth reached

    if bg:
        # Background mode: just queue work and return (background runner via server will pick it up).
        print(
            "[yellow]\\[*] URLs queued. The background runner will process them (run `archivebox server` or `archivebox run --daemon` if not already running).[/yellow]",
        )
        from archivebox.services.runner import ensure_background_runner

        ensure_background_runner()
    else:
        # Foreground mode: run full crawl runner until all work is done
        print("[green]\\[*] Starting crawl runner to process crawl...[/green]")
        from archivebox.core.takeover_util import command_owns_foreground_runner, standby_until_foreground_runner_needed
        from archivebox.workers.supervisord_util import get_existing_supervisord_process, run_runner_worker, stop_own_supervisord_process

        assert command is not None
        exit_code = 0

        def crawl_is_complete() -> bool:
            crawl.refresh_from_db(fields=["status"])
            return crawl.status not in crawl.RUNNABLE_STATES

        try:
            try:
                with foreground_shutdown_signals(first_signal_message=None), foreground_parent_watchdog():
                    while True:
                        standby = standby_until_foreground_runner_needed(
                            command,
                            data_dir=CONSTANTS.DATA_DIR,
                            work_is_complete=crawl_is_complete,
                        )
                        if standby["work_completed"]:
                            break
                        exit_code = run_runner_worker(
                            ["--crawl-id", str(crawl.id)],
                            name=f"worker_runner_add_{os.getpid()}",
                            interactive_interrupts=True,
                            config=get_config(crawl=crawl),
                        )
                        crawl.refresh_from_db(fields=["status", "retry_at"])
                        if exit_code == 0 and crawl.status == crawl.StatusChoices.SEALED:
                            break
                        # A shared supervisord can be stopped by another
                        # foreground owner (for example `archivebox server`
                        # shutting down) and stop the one-shot add runner while
                        # this add's crawl is still runnable. Keep the add
                        # process alive so it can re-enter the normal
                        # foreground-runner ownership loop and finish its crawl.
                        supervisor_gone = exit_code == 1 and get_existing_supervisord_process(quiet=True) is None
                        if crawl.status in crawl.RUNNABLE_STATES and (exit_code in (0, 130, 143) or supervisor_gone):
                            continue
                        if exit_code == 0:
                            break
                        if not command_owns_foreground_runner(command, data_dir=CONSTANTS.DATA_DIR):
                            continue
                        raise SystemExit(exit_code)
            except KeyboardInterrupt:
                exit_code = 130
                print("\n[red][X] archivebox add interrupted.[/red]")
                print("[yellow]Hint: resume this crawl with:[/yellow]")
                print(f"    [green]archivebox run --crawl-id={crawl.id}[/green]")
                raise SystemExit(exit_code)
        finally:
            command.mark_exited(exit_code=exit_code)
            stop_own_supervisord_process()

        # Print summary for foreground runs
        try:
            crawl.refresh_from_db()
            try:
                from django.db.models import Count, Sum

                totals = crawl.snapshot_set.aggregate(snapshot_count=Count("id"), total_bytes=Sum("output_size"))
                snapshots_count = int(totals["snapshot_count"] or 0)
                total_bytes = int(totals["total_bytes"] or 0)
            except Exception:
                snapshots_count = crawl.snapshot_set.count()
                total_bytes, _, _ = get_dir_size(crawl.output_dir)
            total_size = printable_filesize(total_bytes)
            total_time = timezone.now() - started_at
            total_seconds = int(total_time.total_seconds())
            mins, secs = divmod(total_seconds, 60)
            hours, mins = divmod(mins, 60)
            if hours:
                duration_str = f"{hours}h {mins}m {secs}s"
            elif mins:
                duration_str = f"{mins}m {secs}s"
            else:
                duration_str = f"{secs}s"

            # Output dir relative to DATA_DIR
            try:
                rel_output = Path(crawl.output_dir).relative_to(CONSTANTS.DATA_DIR)
                rel_output_str = f"./{rel_output}"
            except Exception:
                rel_output_str = str(crawl.output_dir)

            from archivebox.core.routes_util import build_admin_url

            admin_url = build_admin_url(f"/admin/crawls/crawl/{crawl.id}/change/", config=config)

            print("\n[bold]crawl output saved to:[/bold]")
            print(f"  {rel_output_str}")
            print(f"  {admin_url}")
            print(f"\n[bold]total urls snapshotted:[/bold] {snapshots_count}")
            print(f"[bold]total size:[/bold] {total_size}")
            print(f"[bold]total time:[/bold] {duration_str}")
        except Exception:
            # Summary is best-effort; avoid failing the command if something goes wrong
            pass

    # 6. Return the list of Snapshots in this crawl
    snapshots = crawl.snapshot_set.all()
    return crawl, snapshots


@click.command()
@click.option(
    "--depth",
    "-d",
    type=click.Choice([str(i) for i in range(5)]),
    default="0",
    help="Recursively archive linked pages up to N hops away",
)
@click.option("--max-urls", type=int, default=0, help="Maximum number of URLs to snapshot for this crawl (0 = unlimited)")
@click.option("--crawl-max-size", default="0", help="Maximum total crawl size in bytes or units like 45mb / 1gb (0 = unlimited)")
@click.option("--crawl-timeout", type=int, default=0, help="Maximum total crawl runtime in seconds (0 = unlimited)")
@click.option("--snapshot-max-size", default="0", help="Maximum per-snapshot size in bytes or units like 45mb / 1gb (0 = unlimited)")
@click.option("--crawl-max-concurrent-snapshots", type=int, default=None, help="Maximum snapshots to archive concurrently within one crawl")
@click.option("--tag", "-t", default="", help="Comma-separated list of tags to add to each snapshot e.g. tag1,tag2,tag3")
@click.option("--url-allowlist", "--domain-allowlist", default="", help="Comma-separated URL/domain allowlist for this crawl")
@click.option("--url-denylist", "--domain-denylist", default="", help="Comma-separated URL/domain denylist for this crawl")
@click.option("--parser", default="auto", help="Parser for reading input URLs (auto, txt, html, rss, json, jsonl, netscape, ...)")
@click.option("--plugins", "-p", default="", help="Comma-separated list of plugins to run e.g. title,favicon,screenshot,singlefile,...")
@click.option("--extract", default="", help="Comma-separated plugins or output types to extract e.g. title,pdf,text/html,image,...")
@click.option("--persona", default="Default", help="Authentication profile to use when archiving")
@click.option(
    "--only-new/--no-only-new",
    "only_new",
    default=None,
    help="Skip URLs that already have a snapshot (default: inherit from ONLY_NEW config). "
    "Pass --no-only-new to force re-archive of URLs that already exist.",
)
@click.option("--index-only", is_flag=True, help="Just add the URLs to the index without archiving them now")
@click.option("--overwrite", is_flag=True, help="Re-archive URLs even if they already exist (alias for --no-only-new)")
@click.option("--update", is_flag=True, help="Re-archive URLs even if they already exist (alias for --no-only-new)")
@click.option("--bg", is_flag=True, help="Run archiving in background (queue work and return immediately)")
@click.argument("urls", nargs=-1, type=click.Path())
@docstring(add.__doc__)
def main(**kwargs):
    """Add a new URL or list of URLs to your archive"""

    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals

    with foreground_shutdown_signals(), foreground_parent_watchdog():
        raw_urls = kwargs.pop("urls")
        if raw_urls:
            urls = _collect_input_urls(raw_urls, parser=kwargs.get("parser", "auto"))
        elif not sys.stdin.isatty():
            urls = sys.stdin.read()
        else:
            urls = []
        if not urls:
            raise click.UsageError("No URLs provided. Pass URLs as arguments or via stdin.")
        if int(kwargs.get("max_urls") or 0) < 0:
            raise click.BadParameter("max_urls must be 0 or a positive integer.", param_hint="--max-urls")
        if int(kwargs.get("crawl_timeout") or 0) < 0:
            raise click.BadParameter("crawl_timeout must be 0 or a positive integer.", param_hint="--crawl-timeout")
        try:
            kwargs["crawl_max_size"] = parse_filesize_to_bytes(kwargs.get("crawl_max_size"))
        except ValueError as err:
            raise click.BadParameter(str(err), param_hint="--crawl-max-size") from err
        try:
            kwargs["snapshot_max_size"] = parse_filesize_to_bytes(kwargs.get("snapshot_max_size"))
        except ValueError as err:
            raise click.BadParameter(str(err), param_hint="--snapshot-max-size") from err
        if kwargs.get("crawl_max_concurrent_snapshots") is not None and int(kwargs["crawl_max_concurrent_snapshots"]) < 1:
            raise click.BadParameter("crawl_max_concurrent_snapshots must be at least 1.", param_hint="--crawl-max-concurrent-snapshots")
        if not kwargs.get("index_only"):
            from archivebox.workers.supervisord_util import require_crawl_memory

            require_crawl_memory()

        # Translate --only-new/--no-only-new into a crawl config override.
        # add() takes config overrides as a dict; no per-flag kwargs.
        overwrite = kwargs.pop("overwrite", False)
        update = kwargs.pop("update", False)
        only_new = kwargs.pop("only_new", None)
        extract = kwargs.pop("extract", "")
        if overwrite or update:
            only_new = False
        if only_new is not None:
            kwargs["config"] = {"ONLY_NEW": bool(only_new)}
        if extract:
            from abx_dl.models import discover_plugins, plugins_matching_output

            all_plugins = discover_plugins()
            tokens = [token.strip() for token in extract.split(",") if token.strip()]
            plugin_names = {name.lower(): name for name in all_plugins}
            selected = [plugin_names[token.lower()] for token in tokens if token.lower() in plugin_names]
            selected += plugins_matching_output(all_plugins, tokens)
            if not selected:
                raise click.UsageError(f"No plugins found matching extract types: {extract}")
            existing = [token.strip() for token in (kwargs.get("plugins") or "").split(",") if token.strip()]
            kwargs["plugins"] = ",".join(dict.fromkeys([*existing, *selected]))

        add(urls=urls, **kwargs)


if __name__ == "__main__":
    main()
