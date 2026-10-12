"""Collection-wide request handlers must never read data/archive.

Single-object detail views may fall back to disk for rows not yet migrated,
but for a sealed row at the latest fs_version they must render from the DB too.

WHY: data/archive may be slow remote storage (e.g. an rclone FUSE mount of
Backblaze B2) where every stat/listdir/open is a network round trip. Once
``archivebox update --rescan --migrate-only`` has moved old layouts into place,
the DB is the source of truth for everything list/progress/search/index views
render. A single filesystem probe per row turns into thousands of remote calls.

This guard builds a real collection with real hook output, then makes the
archive directory unreadable (chmod 000) AND observes every filesystem syscall
made from Python (sys.monitoring CALL events, the same native observation API
pytest coverage tools use; nothing is replaced or patched). Python 3.14's
``Path.exists()``/``is_dir()`` swallow PermissionError, so chmod alone would
miss existence probes; the observer catches those, chmod catches anything the
observer cannot see (C-level reads).
"""

import io
import os
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import pytest
from django.test import override_settings
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST, WEB_TEST_HOST
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook
from archivebox.tests.test_search import consume_streaming_response

pytestmark = pytest.mark.django_db(transaction=True)

# Python-visible entry points for every filesystem syscall that can reach a
# FUSE mount. Higher-level helpers (pathlib, os.path, os.walk, glob, shutil,
# open/read_text) all funnel through these builtins.
_FS_SYSCALLS = frozenset(
    {
        os.stat,
        os.lstat,
        os.access,
        os.listdir,
        os.scandir,
        os.open,
        io.open,
        os.readlink,
        os.mkdir,
        os.chmod,
        os.rename,
        os.replace,
        os.remove,
        os.unlink,
        os.rmdir,
        os.utime,
        os.symlink,
        os.link,
        os.statvfs,
    },
)

# WHY these routes are exempt: they exist to stream bytes out of the archive,
# so reading data/archive is their job. They are always scoped to one
# snapshot/crawl and one requested path, never to a collection-wide listing.
FILE_SERVING_ROUTES_EXEMPT = (
    "/snapshot/<id>/<path>  and  /<user>/<date>/<domain>/<id>/<path>  (replay of saved files)",
    "/original/<domain>/<path>  (original-domain replay of saved files)",
    "/archive/<timestamp>/<path>  (legacy static archive file serving)",
    "/api/v1/crawls/crawl/<id>/files/...  (crawl output files, screencast/live frame jpgs)",
    "snapshot/crawl zip downloads  (stream the whole output dir by design)",
    "/admin/core/snapshot/<id>/preview/<plugin>/<file>  (serves one saved image)",
    "?discover_outputs=1 on a single snapshot  (reads its sealed hashes manifest)",
    # Full-text search over saved files is the user's explicit request; the
    # ripgrep backend greps archive files in a subprocess by design. Metadata
    # (search_mode=meta) search is DB-only and is covered below.
    "search_mode=contents/deep with the ripgrep backend",
)


def _archive_path(arg: object, roots: tuple[str, ...]) -> str | None:
    if isinstance(arg, int) or not isinstance(arg, (str, bytes, os.PathLike)):
        return None
    try:
        path = os.fsdecode(os.fspath(arg))
    except TypeError:
        return None
    # os.getcwd is not an observed syscall; normpath is pure string work.
    path = os.path.normpath(path if os.path.isabs(path) else os.path.join(os.getcwd(), path))
    for root in roots:
        if path == root or path.startswith(root + os.sep):
            return path
    return None


@contextmanager
def forbid_archive_access(archive_dir: Path) -> Iterator[list[str]]:
    """Make ``archive_dir`` unreadable and record every Python-level syscall into it."""
    roots = tuple(dict.fromkeys((os.path.normpath(str(archive_dir)), os.path.normpath(str(archive_dir.resolve())))))
    touches: list[str] = []
    monitoring = sys.monitoring
    tool_id = next(tool for tool in range(6) if monitoring.get_tool(tool) is None)

    def on_call(code: types.CodeType, _offset: int, callee: object, arg0: object) -> None:
        if type(callee) is not types.BuiltinFunctionType or callee not in _FS_SYSCALLS:
            return
        path = _archive_path(arg0, roots)
        if path is None:
            return
        frame = sys._getframe(1)
        stack = []
        while frame is not None and len(stack) < 8:
            filename = frame.f_code.co_filename
            if "/archivebox/" in filename and "/tests/" not in filename:
                stack.append(f"{filename.split('/archivebox/', 1)[-1]}:{frame.f_lineno} {frame.f_code.co_name}")
            frame = frame.f_back
        touches.append(f"{callee.__name__}({path}) <- " + " <- ".join(stack))

    monitoring.use_tool_id(tool_id, "archive-storage-isolation-guard")
    monitoring.register_callback(tool_id, monitoring.events.CALL, on_call)
    original_mode = archive_dir.stat().st_mode & 0o7777
    archive_dir.chmod(0)
    monitoring.set_events(tool_id, monitoring.events.CALL)
    try:
        yield touches
    finally:
        monitoring.set_events(tool_id, 0)
        monitoring.register_callback(tool_id, monitoring.events.CALL, None)
        monitoring.free_tool_id(tool_id)
        archive_dir.chmod(original_mode)


@pytest.fixture
def real_collection(admin_user, cached_abxpkg_lib_dir):
    """Two crawls with sealed, current-layout snapshots produced by shipped hooks."""
    from archivebox.config import CONSTANTS
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    public_crawl = Crawl.objects.create(
        urls="https://public.example.com/article\nhttps://public.example.com/other",
        tags_str="isolation",
        label="Public isolation crawl",
        created_by=admin_user,
        config={"PERMISSIONS": "public"},
    )
    private_crawl = Crawl.objects.create(
        urls="https://private.example.org/page",
        label="Private isolation crawl",
        created_by=admin_user,
        config={"PERMISSIONS": "private"},
    )
    public_snapshot = Snapshot.objects.create(
        url="https://public.example.com/article",
        title="Public Isolation Article",
        crawl=public_crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    private_snapshot = Snapshot.objects.create(
        url="https://private.example.org/page",
        title="Private Isolation Page",
        crawl=private_crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    active_snapshot = Snapshot.objects.create(
        url="https://public.example.com/other",
        title="Active Isolation Capture",
        crawl=public_crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    public_snapshot.save_tags(["isolation"], created_by=admin_user)

    for snapshot in (public_snapshot, private_snapshot, active_snapshot):
        # New rows start at the pre-0.9.4 marker; the runner migrates each one
        # before capture. Do the same so these rows are at the latest layout.
        snapshot.migrate_filesystem_to_current_version()
        snapshot.refresh_from_db()
        staticfile_dir = Path(snapshot.output_dir) / "staticfile"
        staticfile_dir.mkdir(parents=True, exist_ok=True)
        (staticfile_dir / "input.txt").write_text(f"{snapshot.url}/linked-page\n", encoding="utf-8")
        _run_shipped_snapshot_hook(
            snapshot,
            plugin="parse_txt_urls",
            hook_name="on_Snapshot__71_parse_txt_urls.py",
            lib_dir=cached_abxpkg_lib_dir,
        )
        if snapshot is active_snapshot:
            # Left mid-capture so /progress.json renders a live tree for it.
            continue
        _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=cached_abxpkg_lib_dir,
        )
        assert snapshot.seal()
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert (Path(snapshot.output_dir) / "hashes" / "hashes.json").is_file()

    Crawl.objects.filter(pk=public_crawl.pk).update(status=Crawl.StatusChoices.STARTED)
    Crawl.objects.filter(pk=private_crawl.pk).update(status=Crawl.StatusChoices.SEALED, retry_at=None)

    # Rows that list views must render without storage access even though
    # their files are not (yet) in the latest layout: a queued row that has
    # never been captured, and an un-migrated 0.8.x row in archive/<timestamp>.
    queued_snapshot = Snapshot.objects.create(
        url="https://public.example.com/queued",
        title="Queued Isolation Row",
        crawl=public_crawl,
    )
    legacy_snapshot = Snapshot.objects.create(
        url="https://private.example.org/legacy",
        title="Legacy Isolation Row",
        crawl=private_crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )
    Snapshot.objects.filter(pk=legacy_snapshot.pk).update(fs_version="0.8.0")
    legacy_snapshot.refresh_from_db()
    legacy_dir = CONSTANTS.ARCHIVE_DIR / legacy_snapshot.timestamp
    (legacy_dir / "title").mkdir(parents=True)
    (legacy_dir / "title" / "title.txt").write_text("Legacy Isolation Row", encoding="utf-8")
    assert Path(legacy_snapshot.output_dir) == legacy_dir

    persona = Persona.objects.create(name="isolation", created_by=admin_user)
    results = list(
        ArchiveResult.objects.filter(snapshot__in=[public_snapshot, private_snapshot, active_snapshot]).order_by("plugin", "snapshot__url"),
    )
    assert {result.plugin for result in results} == {"parse_txt_urls", "hashes"}
    assert all(result.output_files for result in results if result.plugin == "hashes")
    assert CONSTANTS.ARCHIVE_DIR.is_dir()
    return {
        "public_crawl": public_crawl,
        "private_crawl": private_crawl,
        "public_snapshot": public_snapshot,
        "private_snapshot": private_snapshot,
        "active_snapshot": active_snapshot,
        "queued_snapshot": queued_snapshot,
        "legacy_snapshot": legacy_snapshot,
        "results": results,
        "persona": persona,
    }


def _get(client, path: str, host: str, **extra):
    response = client.get(path, HTTP_HOST=host, **extra)
    if not getattr(response, "streaming", False):
        return response.status_code, response.content.decode(errors="replace")
    return response.status_code, consume_streaming_response(response).decode(errors="replace")


@override_settings(PUBLIC_INDEX=True, PUBLIC_SNAPSHOTS=True)
def test_collection_wide_routes_never_read_archive_storage(client, admin_user, api_headers, real_collection):
    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Process

    public_snapshot = real_collection["public_snapshot"]
    private_snapshot = real_collection["private_snapshot"]
    active_snapshot = real_collection["active_snapshot"]
    queued_snapshot = real_collection["queued_snapshot"]
    legacy_snapshot = real_collection["legacy_snapshot"]
    public_crawl = real_collection["public_crawl"]
    results = real_collection["results"]
    process = Process.objects.filter(archiveresult__in=results).order_by("-created_at").first()
    assert process is not None

    tag = public_snapshot.tags.get()
    search = {"q": "Isolation", "search_mode": "meta"}
    admin_search_url = reverse("admin:core_snapshot_changelist") + "?" + urlencode(search)
    public_search_url = "/public/?" + urlencode(search)

    # (path, host, expected substrings) — every expectation is DB-derived content.
    admin_routes = [
        ("/admin/", ADMIN_TEST_HOST, ["Snapshots"]),
        (
            reverse("admin:core_snapshot_changelist"),
            ADMIN_TEST_HOST,
            [public_snapshot.url, private_snapshot.url, queued_snapshot.url, legacy_snapshot.url, "Public Isolation Article"],
        ),
        # Search streams IDs into the cache that the following list page reads.
        (
            reverse("admin:core_snapshot_search_stream") + "?" + urlencode({**search, "search_url": admin_search_url}),
            ADMIN_TEST_HOST,
            ["\n5 "],
        ),
        (admin_search_url, ADMIN_TEST_HOST, [public_snapshot.url, private_snapshot.url, active_snapshot.url, legacy_snapshot.url]),
        (reverse("admin:core_snapshot_changelist") + f"?tags__id__exact={tag.pk}", ADMIN_TEST_HOST, [public_snapshot.url]),
        (reverse("admin:core_archiveresult_changelist"), ADMIN_TEST_HOST, ["parse_txt_urls", "hashes", public_snapshot.url]),
        (reverse("admin:core_archiveresult_changelist") + "?q=hashes", ADMIN_TEST_HOST, ["hashes"]),
        (reverse("admin:crawls_crawl_changelist"), ADMIN_TEST_HOST, ["Public isolation crawl", "Private isolation crawl"]),
        (reverse("admin:personas_persona_changelist"), ADMIN_TEST_HOST, ["isolation"]),
        (reverse("admin:machine_process_changelist"), ADMIN_TEST_HOST, [str(process.pk)[:8]]),
        ("/progress.json?tree=0", ADMIN_TEST_HOST, ['"crawls_active":1', '"crawls_recent":2']),
        (
            "/progress.json",
            ADMIN_TEST_HOST,
            [str(public_crawl.pk), str(active_snapshot.pk), active_snapshot.title, '"plugin":"parse_txt_urls"'],
        ),
        ("/progress.json?collection=1&metrics=1", ADMIN_TEST_HOST, ['"is_admin":true']),
        # Polled every second on crawl and snapshot pages.
        (f"/progress.json?crawl_id={public_crawl.pk}", ADMIN_TEST_HOST, [str(active_snapshot.pk), '"plugin":"parse_txt_urls"']),
        (f"/progress.json?snapshot_id={active_snapshot.pk}", ADMIN_TEST_HOST, [str(active_snapshot.pk), '"plugin":"parse_txt_urls"']),
        (
            reverse("admin:core_snapshot_changelist") + f"?crawl_id={public_crawl.pk}",
            ADMIN_TEST_HOST,
            [public_snapshot.url, active_snapshot.url, queued_snapshot.url],
        ),
        (reverse("admin:grid"), ADMIN_TEST_HOST, [public_snapshot.url, private_snapshot.url, legacy_snapshot.url]),
        ("/add/", ADMIN_TEST_HOST, []),
        (reverse("admin:core_tag_changelist"), ADMIN_TEST_HOST, ["isolation"]),
        (reverse("admin:crawls_crawlschedule_changelist"), ADMIN_TEST_HOST, []),
        (reverse("admin:machine_binary_changelist"), ADMIN_TEST_HOST, []),
        (reverse("admin:machine_machine_changelist"), ADMIN_TEST_HOST, []),
        ("/", ADMIN_TEST_HOST, []),
    ]
    api_routes = [
        ("/api/v1/core/snapshots", [public_snapshot.url, private_snapshot.url, queued_snapshot.url, legacy_snapshot.url]),
        ("/api/v1/core/snapshots?with_archiveresults=true", [public_snapshot.url, "parse_txt_urls", "hashes"]),
        ("/api/v1/core/snapshots?search=Isolation&search_mode=meta", [public_snapshot.url]),
        ("/api/v1/core/archiveresults", ["parse_txt_urls", "hashes"]),
        ("/api/v1/core/tags", ["isolation"]),
        ("/api/v1/core/snapshots.rss", [public_snapshot.url]),
        (f"/api/v1/core/tag/{tag.pk}/snapshots.jsonl", [public_snapshot.url]),
        (f"/api/v1/core/tag/{tag.pk}/urls.txt", [public_snapshot.url]),
        ("/api/v1/crawls/crawls", [str(public_crawl.pk).replace("-", "")]),
        ("/api/v1/personas/personas", ["isolation"]),
    ]
    anonymous_routes = [
        ("/public/", WEB_TEST_HOST, [public_snapshot.url, queued_snapshot.url, "Public Isolation Article"]),
        ("/public/search-stream/?" + urlencode({**search, "search_url": public_search_url}), WEB_TEST_HOST, ["\n3 "]),
        (public_search_url, WEB_TEST_HOST, [public_snapshot.url, active_snapshot.url]),
        ("/", WEB_TEST_HOST, []),
    ]
    forbidden_for_anonymous = [private_snapshot.url, "Private Isolation Page", legacy_snapshot.url]

    failures: list[str] = []
    with forbid_archive_access(CONSTANTS.ARCHIVE_DIR) as touches:
        client.force_login(admin_user)
        for path, host, expected in admin_routes:
            before = len(touches)
            status, body = _get(client, path, host, follow=True)
            if status != 200 or any(text not in body for text in expected):
                failures.append(f"admin GET {path}: status={status} missing={[t for t in expected if t not in body]} body={body[:3000]!r}")
            failures.extend(f"admin GET {path}: {touch}" for touch in touches[before:])
        for path, expected in api_routes:
            before = len(touches)
            status, body = _get(client, path, API_TEST_HOST, **{k: v for k, v in api_headers.items() if k != "HTTP_HOST"})
            if status != 200 or any(text not in body for text in expected):
                failures.append(f"api GET {path}: status={status} missing={[t for t in expected if t not in body]} body={body[:3000]!r}")
            failures.extend(f"api GET {path}: {touch}" for touch in touches[before:])
        client.logout()
        for path, host, expected in anonymous_routes:
            before = len(touches)
            status, body = _get(client, path, host, follow=True)
            if status != 200 or any(text not in body for text in expected):
                failures.append(f"anon GET {path}: status={status} missing={[t for t in expected if t not in body]} body={body[:3000]!r}")
            leaked = [text for text in forbidden_for_anonymous if text in body]
            if leaked:
                failures.append(f"anon GET {path}: leaked private content {leaked}")
            failures.extend(f"anon GET {path}: {touch}" for touch in touches[before:])

    assert failures == [], "\n".join(failures)


@override_settings(PUBLIC_INDEX=True, PUBLIC_SNAPSHOTS=True)
def test_current_layout_detail_routes_render_from_db_without_archive_reads(client, admin_user, api_headers, real_collection):
    """Single-object views may fall back to disk for stale rows, but a sealed
    snapshot at the latest fs_version has complete DB metadata, so its detail
    pages (not the raw file replay routes) must not need archive storage."""
    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Process

    public_snapshot = real_collection["public_snapshot"]
    private_snapshot = real_collection["private_snapshot"]
    public_crawl = real_collection["public_crawl"]
    persona = real_collection["persona"]
    results = real_collection["results"]
    hashes_result = next(result for result in results if result.plugin == "hashes" and result.snapshot_id == public_snapshot.pk)
    process = Process.objects.filter(archiveresult=hashes_result).get()
    snapshot_dir = str(public_snapshot.output_dir)
    routes = [
        (reverse("admin:core_snapshot_change", args=[public_snapshot.pk]), ADMIN_TEST_HOST, [public_snapshot.url, snapshot_dir, "hashes"]),
        (reverse("admin:core_archiveresult_change", args=[hashes_result.pk]), ADMIN_TEST_HOST, ["hashes", public_snapshot.url]),
        (reverse("admin:crawls_crawl_change", args=[public_crawl.pk]), ADMIN_TEST_HOST, ["Public isolation crawl", public_snapshot.url]),
        (reverse("admin:personas_persona_change", args=[persona.pk]), ADMIN_TEST_HOST, ["isolation"]),
        (reverse("admin:machine_process_change", args=[process.pk]), ADMIN_TEST_HOST, ["on_Snapshot__93_hashes"]),
        (f"/api/v1/core/snapshot/{public_snapshot.pk}", API_TEST_HOST, [public_snapshot.url, "hashes", "parse_txt_urls"]),
        (f"/api/v1/core/archiveresult/{hashes_result.pk}", API_TEST_HOST, ["hashes", "hashes.json"]),
        (f"/api/v1/crawls/crawl/{public_crawl.pk}", API_TEST_HOST, [str(public_crawl.pk)]),
        # Main snapshot detail HTML (not raw file replay): outputs come from DB rows.
        ("/" + public_snapshot.archive_path_from_db, WEB_TEST_HOST, [public_snapshot.url, "urls.jsonl"]),
        ("/" + private_snapshot.archive_path_from_db, WEB_TEST_HOST, [private_snapshot.url, "urls.jsonl"]),
    ]

    failures: list[str] = []
    with forbid_archive_access(CONSTANTS.ARCHIVE_DIR) as touches:
        client.force_login(admin_user)
        for path, host, expected in routes:
            before = len(touches)
            extra = {k: v for k, v in api_headers.items() if k != "HTTP_HOST"} if host == API_TEST_HOST else {}
            status, body = _get(client, path, host, follow=True, **extra)
            if status != 200 or any(text not in body for text in expected):
                failures.append(f"GET {path}: status={status} missing={[t for t in expected if t not in body]}")
            failures.extend(f"GET {path}: {touch}" for touch in touches[before:])
        client.logout()
        before = len(touches)
        status, body = _get(client, "/" + public_snapshot.archive_path_from_db, WEB_TEST_HOST, follow=True)
        if status != 200 or public_snapshot.url not in body or "urls.jsonl" not in body:
            failures.append(f"anon GET public snapshot detail: status={status}")
        status, body = _get(client, "/" + private_snapshot.archive_path_from_db, WEB_TEST_HOST, follow=True)
        if private_snapshot.title in body:
            failures.append(f"anon GET private snapshot detail leaked it: status={status}")
        failures.extend(f"anon GET snapshot detail: {touch}" for touch in touches[before:])

    assert failures == [], "\n".join(failures)
