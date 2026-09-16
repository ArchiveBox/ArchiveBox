"""Render the monitor's crawl, snapshot, and hook payloads from loaded data."""

from pathlib import Path
from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.core.routes_util import build_snapshot_url, build_web_url
from archivebox.misc.logging_util import printable_filesize


def render_crawl(report, crawl):
    crawl_id = str(crawl["id"])
    crawl_snapshot_counts = report.snapshot_counts_by_crawl.get(crawl_id, {})
    total_snapshots = sum(crawl_snapshot_counts.values())
    completed_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.SEALED, 0)
    started_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.STARTED, 0)
    pending_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.QUEUED, 0)
    cancelled_snapshots = report.cancelled_snapshot_counts_by_crawl.get(crawl_id, 0)

    # Count URLs in the crawl (for when snapshots haven't been created yet)
    urls_count = 0
    if crawl["urls"]:
        urls_count = len([u for u in crawl["urls"].split("\n") if u.strip() and not u.startswith("#")])

    # Calculate crawl progress
    crawl_progress = int((completed_snapshots / total_snapshots) * 100) if total_snapshots > 0 else 0
    crawl_run_started_at = crawl["created_at"]
    crawl_setup_plugins = [
        payload
        for payload, proc_started_at in report.process_records_by_crawl.get(crawl_id, [])
        if is_current_run_timestamp(proc_started_at, crawl_run_started_at)
    ]
    crawl_setup_total = len(crawl_setup_plugins)
    crawl_setup_completed = sum(1 for item in crawl_setup_plugins if item.get("status") == "succeeded")
    crawl_setup_failed = sum(1 for item in crawl_setup_plugins if item.get("status") == "failed")
    crawl_setup_pending = sum(1 for item in crawl_setup_plugins if item.get("status") == "queued")
    crawl_screencast_url = screencast_frame_url(report, crawl_id, report.active_crawl_objects[crawl_id].output_dir)
    crawl_screencast_link = f"/admin/crawls/crawl/{crawl_id.replace('-', '')}/change/" if crawl_screencast_url else ""

    active_snapshots_for_crawl = [
        render_snapshot(report, snapshot, crawl_id) for snapshot in report.displayed_snapshots_by_crawl.get(crawl_id, [])
    ]

    # Check if crawl can start (for debugging stuck crawls)
    can_start = bool(crawl["urls"])
    urls_preview = crawl["urls"][:60] if crawl["urls"] else None
    crawl_tags = [tag.strip() for tag in (crawl["tags_str"] or "").replace("\n", ",").split(",") if tag.strip()]
    persona_details = report.persona_details_by_id.get(str(crawl["persona_id"])) if crawl["persona_id"] else None
    persona_name = persona_details["name"] if persona_details else "Default"
    persona_details = persona_details or report.persona_details_by_name.get(persona_name)
    crawl_output_size = report.crawl_output_sizes_by_crawl.get(crawl_id, 0)
    avg_snapshot_size = int(crawl_output_size / completed_snapshots) if completed_snapshots else 0
    crawl_obj = report.active_crawl_objects[crawl_id]
    effective_crawl_config = get_config(crawl=crawl_obj, resolve_plugins=False)
    max_urls = int(effective_crawl_config.CRAWL_MAX_URLS or 0)
    crawl_max_size = int(effective_crawl_config.CRAWL_MAX_SIZE or 0)
    crawl_timeout = int(effective_crawl_config.CRAWL_TIMEOUT or 0)
    snapshot_max_size = int(effective_crawl_config.SNAPSHOT_MAX_SIZE or 0)

    # Check if retry_at is in the future (would prevent worker from claiming)
    retry_at_future = crawl["retry_at"] > report.now if crawl["retry_at"] else False
    is_paused = crawl_obj.is_paused
    seconds_until_retry = (
        0 if is_paused else int((crawl["retry_at"] - report.now).total_seconds()) if crawl["retry_at"] and retry_at_future else 0
    )
    crawl_worker_state = (
        "running"
        if report.crawl_process_pids.get(crawl_id)
        or any(isinstance(snapshot, dict) and snapshot.get("worker_pid") for snapshot in active_snapshots_for_crawl)
        else "waiting"
    )
    if is_paused:
        crawl_worker_state = "paused"
    elif crawl["status"] == Crawl.StatusChoices.STARTED and crawl_worker_state == "waiting" and (started_snapshots or pending_snapshots):
        crawl_worker_state = "waiting" if report.orchestrator_running else "crashed"

    return {
        "id": crawl_id,
        "label": (next((line.strip() for line in (crawl["urls"] or "").splitlines() if line.strip()), "") or crawl_id)[:60],
        "status": crawl["status"],
        "is_paused": is_paused,
        "started": crawl["created_at"].isoformat() if crawl["created_at"] else None,
        "progress": crawl_progress,
        "created_by": crawl["created_by__username"],
        "persona": persona_name,
        "persona_admin_url": persona_details["admin_url"] if persona_details else None,
        "max_depth": crawl["max_depth"],
        "max_urls": max_urls,
        "max_crawl_size": crawl_max_size,
        "crawl_timeout": crawl_timeout,
        "max_snapshot_size": snapshot_max_size,
        "max_crawl_size_display": printable_filesize(crawl_max_size) if crawl_max_size else "unlimited",
        "crawl_timeout_display": f"{crawl_timeout}s" if crawl_timeout else "unlimited",
        "max_snapshot_size_display": printable_filesize(snapshot_max_size) if snapshot_max_size else "unlimited",
        "crawl_output_size": crawl_output_size,
        "avg_snapshot_size": avg_snapshot_size,
        "crawl_output_size_display": printable_filesize(crawl_output_size) if crawl_output_size else "0 B",
        "avg_snapshot_size_display": printable_filesize(avg_snapshot_size) if avg_snapshot_size else "0 B",
        "tags": crawl_tags,
        "urls_count": urls_count,
        "total_snapshots": total_snapshots,
        "completed_snapshots": completed_snapshots,
        "started_snapshots": started_snapshots,
        "failed_snapshots": 0,
        "pending_snapshots": pending_snapshots,
        "cancelled_snapshots": cancelled_snapshots,
        "setup_plugins": crawl_setup_plugins,
        "setup_total_plugins": crawl_setup_total,
        "setup_completed_plugins": crawl_setup_completed,
        "setup_failed_plugins": crawl_setup_failed,
        "setup_pending_plugins": crawl_setup_pending,
        "screencast_url": crawl_screencast_url,
        "screencast_link": crawl_screencast_link,
        "active_snapshots": active_snapshots_for_crawl,
        "queued_snapshots_hidden": report.queued_snapshot_overflow_by_crawl.get(crawl_id, 0),
        "can_start": can_start,
        "urls_preview": urls_preview,
        "retry_at_future": retry_at_future,
        "seconds_until_retry": seconds_until_retry,
        "worker_pid": report.crawl_process_pids.get(crawl_id),
        "worker_state": crawl_worker_state,
    }


def render_snapshot(report, snapshot, crawl_id):
    snapshot_run_started_at = snapshot.get("downloaded_at") or snapshot.get("created_at")
    snapshot_process_started_at = snapshot.get("created_at")
    # Get archive results only for displayed active snapshots. Large crawls can
    # contain thousands of sealed snapshots, and prefetching all their results
    # makes the progress endpoint compete with the runner.
    snapshot_results = [
        ar
        for ar in report.archiveresults_by_snapshot.get(str(snapshot["id"]), [])
        if archiveresult_matches_current_run(ar, snapshot_run_started_at)
    ]
    if snapshot["status"] == Snapshot.StatusChoices.QUEUED:
        snapshot_results = []

    plugin_progress_values: list[int] = []
    all_plugins: list[dict[str, object]] = []
    seen_plugin_keys: set[str] = set()
    snapshot_title = (
        str(snapshot["title"] or "")
        if snapshot["status"] == Snapshot.StatusChoices.QUEUED
        else Snapshot._normalize_title_candidate(snapshot["title"], snapshot_url=snapshot["url"])
    )
    snapshot_favicon_url = ""
    snapshot_preview_url = ""
    snapshot_preview_link = ""
    snapshot_screencast_url = ""
    snapshot_screencast_link = ""
    snapshot_fallback_urls: list[str] = []
    result_by_plugin = {result.plugin: result for result in snapshot_results}
    title_result = result_by_plugin.get("title")
    if not snapshot_title and title_result is not None and title_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
        snapshot_title = Snapshot._normalize_title_candidate(title_result.output_str, snapshot_url=snapshot["url"])
    favicon_result = result_by_plugin.get("favicon")
    if favicon_result is not None and favicon_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
        favicon_path = (
            favicon_result.embed_path_db(
                favicon_result.output_files if isinstance(favicon_result.output_files, dict) else {},
                check_filesystem=False,
            )
            or "favicon/favicon.ico"
        )
        snapshot_favicon_url = snapshot_output_url(report, snapshot, favicon_path)
    screenshot_result = result_by_plugin.get("screenshot")
    if screenshot_result is not None and screenshot_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
        snapshot_preview_link = snapshot_view_url(report, snapshot)
        screenshot_path = (
            screenshot_result.embed_path_db(
                screenshot_result.output_files if isinstance(screenshot_result.output_files, dict) else {},
                check_filesystem=False,
            )
            or "screenshot/screenshot.png"
        )
        snapshot_preview_url = snapshot_output_url(report, snapshot, screenshot_path)
        snapshot_preview_link = snapshot_view_url(report, snapshot, screenshot_path)
        if snapshot_favicon_url:
            snapshot_fallback_urls.append(snapshot_favicon_url)
    elif snapshot_favicon_url:
        snapshot_preview_url = snapshot_favicon_url

    if snapshot["status"] == Snapshot.StatusChoices.STARTED:
        snapshot_screencast_url = screencast_frame_url(report, crawl_id, report.active_crawl_objects[crawl_id].output_dir)
        snapshot_screencast_link = snapshot_view_url(report, snapshot) if snapshot_screencast_url else ""

    def plugin_sort_key(ar):
        status_order = {
            ArchiveResult.StatusChoices.STARTED: 0,
            ArchiveResult.StatusChoices.QUEUED: 1,
            ArchiveResult.StatusChoices.SUCCEEDED: 2,
            ArchiveResult.StatusChoices.NORESULTS: 3,
            ArchiveResult.StatusChoices.FAILED: 4,
        }
        return (status_order.get(ar.status, 5), ar.plugin, ar.hook_name or "")

    for ar in sorted(snapshot_results, key=plugin_sort_key):
        status = ar.status
        process = ar.process_record
        progress_value = 0
        if status in (
            ArchiveResult.StatusChoices.SUCCEEDED,
            ArchiveResult.StatusChoices.FAILED,
            ArchiveResult.StatusChoices.SKIPPED,
            ArchiveResult.StatusChoices.NORESULTS,
        ):
            progress_value = 100
        elif status == ArchiveResult.StatusChoices.STARTED:
            started_at = ar.start_ts or (process.started_at if process else None)
            timeout = process.timeout if process else 120
            if started_at and timeout:
                elapsed = max(0.0, (report.now - started_at).total_seconds())
                progress_value = int(min(99, max(1, (elapsed / float(timeout)) * 100)))
            else:
                progress_value = 1
        else:
            progress_value = 0

        plugin_progress_values.append(progress_value)
        plugin, label, phase, hook_name = hook_details(ar.hook_name or ar.plugin, plugin=ar.plugin)

        plugin_payload = {
            "id": str(ar.id),
            "plugin": ar.plugin,
            "label": label,
            "hook_name": hook_name,
            "phase": phase,
            "status": status,
            "process_id": str(process.id) if process else None,
            "admin_url": f"/admin/core/archiveresult/{ar.id}/change/",
        }
        output_path = ar.embed_path_db(ar.output_files if isinstance(ar.output_files, dict) else {}, check_filesystem=False)
        if output_path:
            plugin_payload["output_path"] = output_path
            plugin_payload["output_url"] = snapshot_view_url(report, snapshot, output_path)
        if status == ArchiveResult.StatusChoices.STARTED and process:
            plugin_payload["pid"] = process.pid
        if status == ArchiveResult.StatusChoices.STARTED:
            plugin_payload["progress"] = progress_value
            plugin_payload["timeout"] = process.timeout if process else 120
        plugin_payload["source"] = "archiveresult"
        all_plugins.append(plugin_payload)
        seen_plugin_keys.add(str(process.id) if process else f"{ar.plugin}:{hook_name}")

    for proc_payload, proc_started_at in report.process_records_by_snapshot.get(str(snapshot["id"]), []):
        if not is_current_run_timestamp(proc_started_at, snapshot_process_started_at):
            continue
        proc_key = str(proc_payload.get("process_id") or f"{proc_payload.get('plugin')}:{proc_payload.get('hook_name')}")
        if proc_key in seen_plugin_keys:
            continue
        seen_plugin_keys.add(proc_key)
        all_plugins.append(proc_payload)

        proc_status = proc_payload.get("status")
        if proc_status in ("succeeded", "failed", "skipped"):
            plugin_progress_values.append(100)
        elif proc_status == "started":
            plugin_progress_values.append(1)
        else:
            plugin_progress_values.append(0)

    total_plugins = len(all_plugins)
    completed_plugins = sum(1 for item in all_plugins if item.get("status") == "succeeded")
    failed_plugins = sum(1 for item in all_plugins if item.get("status") == "failed")
    pending_plugins = sum(1 for item in all_plugins if item.get("status") == "queued")

    snapshot_progress = int(sum(plugin_progress_values) / len(plugin_progress_values)) if plugin_progress_values else 0
    worker_state = "running" if report.snapshot_process_pids.get(str(snapshot["id"])) else "waiting"
    if (
        snapshot["status"] == Snapshot.StatusChoices.STARTED
        and worker_state == "waiting"
        and not all_plugins
        and snapshot["modified_at"]
        and (report.now - snapshot["modified_at"]).total_seconds() > 30
    ):
        worker_state = "waiting" if report.orchestrator_running else "crashed"

    if snapshot["status"] == Snapshot.StatusChoices.QUEUED and not report.snapshot_process_pids.get(str(snapshot["id"])):
        compact_snapshot = [
            str(snapshot["id"]),
            snapshot_display_url(snapshot["url"]),
        ]
        if snapshot_title:
            compact_snapshot.append(snapshot_title)
        return compact_snapshot

    snapshot_payload = {
        "id": str(snapshot["id"]),
        "url": snapshot_display_url(snapshot["url"]),
        "title": snapshot_title,
        "status": snapshot["status"],
        "worker_state": worker_state,
    }
    if snapshot["status"] != Snapshot.StatusChoices.QUEUED or all_plugins or report.snapshot_process_pids.get(str(snapshot["id"])):
        snapshot_payload.update(
            {
                "view_url": snapshot_view_url(report, snapshot),
                "started": (snapshot["downloaded_at"] or snapshot["created_at"]).isoformat()
                if (snapshot["downloaded_at"] or snapshot["created_at"])
                else None,
                "progress": snapshot_progress,
                "total_plugins": total_plugins,
                "completed_plugins": completed_plugins,
                "failed_plugins": failed_plugins,
                "pending_plugins": pending_plugins,
                "all_plugins": all_plugins,
            },
        )
        if snapshot_favicon_url:
            snapshot_payload["favicon_url"] = snapshot_favicon_url
        if snapshot_preview_url:
            snapshot_payload["preview_url"] = snapshot_preview_url
            snapshot_payload["preview_link"] = snapshot_preview_link
        if snapshot_screencast_url:
            snapshot_payload["screencast_url"] = snapshot_screencast_url
            snapshot_payload["screencast_link"] = snapshot_screencast_link
        if snapshot_fallback_urls:
            snapshot_payload["preview_fallbacks"] = snapshot_fallback_urls
        if report.snapshot_process_pids.get(str(snapshot["id"])):
            snapshot_payload["worker_pid"] = report.snapshot_process_pids[str(snapshot["id"])]

    return snapshot_payload


def is_current_run_timestamp(event_ts, run_started_at) -> bool:
    if run_started_at is None:
        return True
    if event_ts is None:
        return False
    return event_ts >= run_started_at


def archiveresult_matches_current_run(ar, run_started_at) -> bool:
    if run_started_at is None:
        return True
    if ar.status in (
        ArchiveResult.StatusChoices.QUEUED,
        ArchiveResult.StatusChoices.STARTED,
        ArchiveResult.StatusChoices.BACKOFF,
    ):
        return True
    event_ts = ar.end_ts or ar.start_ts or ar.modified_at or ar.created_at
    return is_current_run_timestamp(event_ts, run_started_at)


def hook_details(hook_name: str, plugin: str = "setup") -> tuple[str, str, str, str]:
    normalized_hook_name = Path(hook_name).name if hook_name else ""
    if not normalized_hook_name:
        return (plugin, plugin, "unknown", "")

    phase = "unknown"
    if normalized_hook_name == "InstallEvent":
        phase = "install"
    elif normalized_hook_name.startswith("on_CrawlSetup__"):
        phase = "crawl"
    elif normalized_hook_name.startswith("on_Snapshot__"):
        phase = "snapshot"

    label = normalized_hook_name
    if "__" in normalized_hook_name:
        label = normalized_hook_name.split("__", 1)[1]
    label = label.rsplit(".", 1)[0]
    if len(label) > 3 and label[:2].isdigit() and label[2] == "_":
        label = label[3:]
    label = label.replace("_", " ").strip() or plugin

    return (plugin, label, phase, normalized_hook_name)


def process_label(cmd: list[str] | None) -> tuple[str, str, str, str]:
    hook_path = ""
    if isinstance(cmd, list) and cmd:
        hook_path = next(
            (arg for arg in cmd if isinstance(arg, str) and Path(arg).name.startswith("on_") and "__" in Path(arg).name),
            "",
        )
        if not hook_path and isinstance(cmd[0], str):
            hook_path = cmd[0]

    if not hook_path:
        return ("", "setup", "unknown", "")

    return hook_details(Path(hook_path).name, plugin=Path(hook_path).parent.name or "setup")


def snapshot_output_url(report, snapshot, output_path: str) -> str:
    return build_snapshot_url(str(snapshot["id"]), output_path, request=report.request, config=report.request_config)


def snapshot_archive_path(report, snapshot) -> str:
    if snapshot["fs_version"] in ("0.7.0", "0.8.0"):
        return f"{CONSTANTS.ARCHIVE_DIR_NAME}/{snapshot['timestamp']}"
    crawl = report.crawls_by_id.get(str(snapshot["crawl_id"]))
    username = "web"
    if crawl is not None and crawl["created_by_id"]:
        username = crawl["created_by__username"]
    if username == "system":
        username = "web"
    date_base = snapshot["bookmarked_at"] or snapshot["created_at"]
    date_str = date_base.strftime("%Y%m%d") if date_base else "unknown"
    domain = Snapshot.extract_domain_from_url(snapshot["url"])
    return f"{username}/{date_str}/{domain}/{snapshot['id']}"


def snapshot_view_url(report, snapshot, output_path: str = "") -> str:
    anchor = f"#{output_path}" if output_path else ""
    return build_web_url(
        f"/{snapshot_archive_path(report, snapshot)}/index.html{anchor}",
        request=report.request,
        config=report.request_config,
    )


def snapshot_display_url(url: str) -> str:
    url = str(url or "")
    return url if len(url) <= 96 else f"{url[:93]}..."


def screencast_frame_url(report, crawl_id: str, crawl_dir: Path) -> str:
    frame_path = crawl_dir / "chrome_screencast" / "latest.jpg"
    try:
        frame_stat = frame_path.stat()
    except OSError:
        return ""
    if frame_stat.st_size <= 0:
        return ""
    if report.now.timestamp() - frame_stat.st_mtime > 15:
        return ""
    rel = f"/api/v1/crawls/crawl/{crawl_id}/files/chrome_screencast/latest.jpg?v={frame_stat.st_mtime_ns}"
    return f"{report.api_base}{rel}" if report.api_base else rel
