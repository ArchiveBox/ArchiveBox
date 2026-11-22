"""Capture current public news through the real CLI for recurring gallery runs."""

import json
import os
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import requests
from django.utils import timezone


def configure_provider(model, data_dir):
    from archivebox.plugins.discovery import get_plugin_catalog
    from abx_dl.execution import iter_plugin_command
    from archivebox.plugins.host import host

    config = host.request_config()
    if Path(data_dir).resolve() != Path(config["DATA_DIR"]).resolve():
        raise ValueError("Run gallery preparation from its explicit collection directory.")
    configured = False
    catalog = get_plugin_catalog()
    for plugin in catalog:
        command = catalog.command(plugin, "configure-gallery")
        if command is None:
            continue
        try:
            result = json.loads(
                "\n".join(
                    iter_plugin_command(
                        command,
                        stdin=[json.dumps({"model": model, "config": config, "data_dir": str(data_dir)})],
                        cwd=Path(data_dir),
                        timeout=config.get("TIMEOUT", 120),
                    ),
                ),
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(error.stderr or str(error)) from error
        if not isinstance(result, dict) or type(result.get("configured")) is not bool:
            raise ValueError(f"Invalid configure-gallery result from {plugin}")
        configured = result["configured"] or configured
    if not configured:
        raise RuntimeError("Enable an agent plugin in the screenshot collection before preparing AI screenshots.")


class LibrarySourceUnavailable(RuntimeError):
    pass


def news_urls():
    # Use HN's machine-readable discovery API; the CLI still captures real pages.
    api = "https://hacker-news.firebaseio.com/v0"
    urls = ["https://news.ycombinator.com/"]
    with requests.Session() as session:
        response = session.get(f"{api}/topstories.json", timeout=30)
        response.raise_for_status()
        for item_id in response.json()[:30]:
            response = session.get(f"{api}/item/{item_id}.json", timeout=30)
            response.raise_for_status()
            story = response.json() or {}
            url = story.get("url", "")
            if story.get("type") == "story" and not story.get("dead") and not story.get("deleted"):
                if url.startswith(("http://", "https://")) and url not in urls:
                    urls.append(url)
            if len(urls) == 7:
                return urls
    raise LibrarySourceUnavailable("The live Hacker News API did not provide six story candidates.")


def select_gallery_snapshots(snapshots, urls, evidence):
    from archivebox.core.models import Snapshot
    from archivebox.plugins.discovery import get_snapshot_role_paths

    candidates = {snapshot.url: snapshot for snapshot in snapshots}
    eligible = []
    records = []
    for url in urls:
        snapshot = candidates[url]
        results = list(snapshot.archiveresult_set.all())
        try:
            navigation = json.loads((snapshot.output_dir / "chrome/navigation.json").read_text())
        except (OSError, ValueError):
            navigation = {}
        status = navigation.get("status") if isinstance(navigation, dict) else None
        browser_ok = isinstance(status, int) and 200 <= status < 400 and navigation.get("url") == url and not navigation.get("error")
        paths = {
            "html": next(get_snapshot_role_paths(snapshot, results, "html_replay"), None),
            "screenshot": snapshot.plugin_output_path("screenshot", archive_results=results),
            "wacz": snapshot.plugin_output_path("archivewebpage", archive_results=results),
        }
        files_ok = all(
            path and (snapshot.output_dir / path).is_file() and (snapshot.output_dir / path).stat().st_size for path in paths.values()
        )
        usable = bool(
            browser_ok
            and files_ok
            and paths["wacz"].endswith(".wacz")
            and snapshot.status == Snapshot.StatusChoices.SEALED
            and snapshot.output_size > 0,
        )
        replay_url = url
        final_url = navigation.get("finalUrl") if browser_ok else None
        if usable and isinstance(final_url, str) and final_url != url:
            # A recorded HTTP redirect changes the replay frame and its deep
            # link. Accept only the settled URL retained in this same WACZ.
            with zipfile.ZipFile(snapshot.output_dir / paths["wacz"]) as recording:
                for name in ("pages/pages.jsonl", "pages/extraPages.jsonl"):
                    if name not in recording.namelist():
                        continue
                    with recording.open(name) as pages:
                        for line in pages:
                            if json.loads(line).get("url") == final_url:
                                replay_url = final_url
        records.append(
            {
                "url": url,
                "snapshot_id": str(snapshot.pk),
                "browser_status": status,
                "replay_url": replay_url,
                "eligible": usable,
                "results": {result.plugin: result.status for result in results},
            },
        )
        if usable:
            eligible.append(snapshot)
    (evidence / "hacker-news-captures.json").write_text(json.dumps(records, indent=2))
    if diagnostics := os.environ.get("SCREENSHOT_FAILURE_DIR"):
        Path(diagnostics).mkdir(parents=True, exist_ok=True)
        (Path(diagnostics) / "hacker-news-captures.json").write_text(json.dumps(records, indent=2))
    if len(eligible) < 4 or eligible[0].url != urls[0]:
        raise LibrarySourceUnavailable("Gallery needs a successful homepage and three captured stories; inspect hacker-news-captures.json.")
    featured = eligible[:4]
    (evidence / "hacker-news-urls.json").write_text(json.dumps([snapshot.url for snapshot in featured], indent=2))
    return featured


def native_plugin_output_unavailable(snapshot_id, plugin, *, default_view=False):
    """Only a sealed, successfully opened native snapshot proves scoped absence."""
    from django.db.models import Q
    from archivebox.core.models import ArchiveResult, Snapshot

    if not Snapshot.objects.filter(id=snapshot_id, status=Snapshot.StatusChoices.SEALED).exists():
        return False
    results = ArchiveResult.objects.filter(snapshot_id=snapshot_id)
    states = set(results.filter(plugin=plugin).values_list("status", flat=True))
    if not states <= {"noresults", "failed", "skipped"}:
        return False
    navigated = results.filter(plugin="chrome", hook_name="on_Snapshot__30_chrome_navigate", status="succeeded").exists()
    if navigated and (states or default_view):
        return True
    return (
        results.filter(
            plugin="chrome",
            hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
            status="failed",
        )
        .filter(
            Q(process__stderr__contains="[chrome] target_crash status=crashed ")
            | Q(process__stderr__contains="[chrome] target_crash status=oom ")
            | Q(process__stderr__contains="tab closed unexpectedly!"),
        )
        .exists()
    )


AI_GALLERY_OUTPUTS = (
    ("autotag", "automatic tags", "tags.jsonl"),
    ("autosummary", "automatic summary", "summary.md"),
)


def validate_ai_result(snapshot, plugin):
    from archivebox.core.models import ArchiveResult

    results = list(snapshot.archiveresult_set.filter(plugin=plugin))
    if any(result.status == ArchiveResult.StatusChoices.SUCCEEDED for result in results):
        return True
    unsuccessful = {ArchiveResult.StatusChoices.FAILED, ArchiveResult.StatusChoices.NORESULTS, ArchiveResult.StatusChoices.SKIPPED}
    if not results or any(result.status not in unsuccessful for result in results):
        raise RuntimeError(f"Gallery capture has no terminal {plugin} result: {snapshot.url}")
    warning = f"Native plugin {plugin} did not succeed; no output screenshot from this snapshot."
    print(f"::warning::{warning}")
    return False


@contextmanager
def homepage_capture_budget(homepage_url):
    """Allow the real homepage's 60-second server cooldown, only in this fixture."""
    from archivebox.api.models import OutboundWebhook
    from archivebox.core.models import Folder

    folder = Folder.objects.create(
        name="Gallery homepage cooldown",
        rules={"field": "url", "lookup": "exact", "value": homepage_url},
    )
    rule = None
    try:
        candidate = OutboundWebhook(
            name="Gallery homepage cooldown",
            ref="archivebox.core.models.Snapshot",
            signal="FOLDER_ENTERED",
            folder=folder,
            enabled=True,
            actions=[{"type": "config_overrides", "config_overrides": {"CHROME_TIMEOUT": 90}}],
        )
        candidate.full_clean()
        candidate.save()
        rule = candidate
        yield
    finally:
        # Do not leave a fixture-only rule/folder in the user-facing Rules shots.
        if rule is not None:
            rule.delete()
        folder.delete()


@contextmanager
def library_capture_plugins(persona, *, model=""):
    """Scope gallery fixture flags to the real library crawl."""
    previous = dict(persona.config or {})
    # The HN library only needs replay, screenshot, WACZ and AI artifacts.
    # TLSNotary keeps its own genuine required provider example; notarizing
    # these seven unrelated captures is redundant and dominates runner time.
    persona.config = {**previous, "TLSNOTARY_ENABLED": False}
    if model:
        persona.config.update(
            AUTOTAG_ENABLED=True,
            AUTOSUMMARY_ENABLED=True,
            AUTOTAG_MODEL=model,
            AUTOSUMMARY_MODEL=model,
        )
    persona.save(update_fields=["config"])
    try:
        yield
    finally:
        persona.config = previous
        persona.save(update_fields=["config"])


def native_library_source(crawl, snapshots, urls, evidence):
    featured = select_gallery_snapshots(snapshots, urls, evidence)
    records = json.loads((evidence / "hacker-news-captures.json").read_text())
    replay_urls = {record["url"]: record["replay_url"] for record in records if record["eligible"]}
    return featured, {
        "crawl_id": str(crawl.pk),
        "homepage": featured[0].url,
        "stories": [snapshot.url for snapshot in featured[1:]],
        "replay_urls": replay_urls,
        "homepage_selector": "#hnmain",
        "title": "Hacker News",
    }


def prepare(evidence_dir, *, model=""):
    from archivebox.config import CONSTANTS
    from archivebox.core.models import Snapshot
    from archivebox.core.tag_util import normalize_tag_name
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    evidence = Path(evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    outcomes = os.environ.get("UI_SCREENSHOT_UNAVAILABLE_OUT")
    capture_env = os.environ.copy()
    if model:
        if not model.startswith("openai/"):
            raise ValueError("Gallery AI captures require an explicitly configured OpenAI model.")
        configure_provider(model, CONSTANTS.DATA_DIR)
    snapshots = []
    try:
        urls = news_urls()
        (evidence / "hacker-news-candidates.json").write_text(json.dumps(urls, indent=2))
        # The existing supervisor does not adopt the shell's temporary env.
        # Persist the fixture preset until the foreground crawl has completed.
        persona = Persona.get_or_create_named("Default")
        started = timezone.now()
        with library_capture_plugins(persona, model=model), homepage_capture_budget(urls[0]):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archivebox",
                    "add",
                    "--no-only-new",
                    "--tag=screenshot-library",
                    "--max-urls=7",
                    *urls,
                ],
                cwd=CONSTANTS.DATA_DIR,
                env=capture_env,
                check=True,
            )
        crawl = Crawl.objects.filter(created_at__gte=started, urls__contains=urls[0]).latest("created_at")
        snapshots = list(Snapshot.objects.filter(crawl=crawl))
        if {snapshot.url for snapshot in snapshots} != set(urls):
            raise RuntimeError("Gallery crawl did not create every requested real capture.")
        snapshots, source = native_library_source(crawl, snapshots, urls, evidence)
    except (LibrarySourceUnavailable, requests.RequestException) as error:
        # Native capture stays an observed outcome, never relabeled as passing.
        # Only unavailable source evidence can choose this owned, playable input;
        # scaffold, database, CLI, and archive-format errors remain fatal.
        if not outcomes:
            raise
        from archivebox.core.gallery_replay_fixture import prepare as prepare_fixture

        print(f"::warning title=Native library source unavailable::{type(error).__name__}; using the owned app replay fixture")
        source = prepare_fixture()
        snapshots = [snapshot for snapshot in snapshots if snapshot.status == Snapshot.StatusChoices.SEALED]
    (evidence / "gallery-library-source.json").write_text(json.dumps(source))
    ai_snapshots = {}
    for snapshot in snapshots:
        if model:
            available = {
                plugin: validate_ai_result(snapshot, plugin)
                for plugin, _, _ in AI_GALLERY_OUTPUTS
                if source["title"] == "Hacker News" or snapshot.archiveresult_set.filter(plugin=plugin).exists()
            }
            for plugin, succeeded in available.items():
                if succeeded:
                    ai_snapshots.setdefault(plugin, snapshot)
            if available.get("autosummary") and not (snapshot.output_dir / "autosummary/summary.md").read_text().strip():
                raise RuntimeError(f"Gallery capture has no real summary artifact: {snapshot.url}")
            if not available.get("autotag"):
                continue
            tag_records = [
                json.loads(line) for line in (snapshot.output_dir / "autotag/tags.jsonl").read_text().splitlines() if line.strip()
            ]
            if any(record.get("type") != "Tag" or not isinstance(record.get("name"), str) for record in tag_records):
                raise RuntimeError(f"Gallery capture has invalid tag records: {snapshot.url}")
            tags = [record["name"] for record in tag_records]
            if not tags or not {normalize_tag_name(tag).casefold() for tag in tags}.issubset(
                {name.casefold() for name in snapshot.tags.values_list("name", flat=True)},
            ):
                raise RuntimeError(
                    f"Gallery tag projection mismatch for {snapshot.url}: "
                    f"emitted={tags!r}, stored={list(snapshot.tags.values_list('name', flat=True))!r}",
                )
    if model:
        from archivebox.core.routes_util import build_snapshot_detail_path
        from urllib.parse import urlsplit

        base = os.environ["UI_LIBRARY_ADMIN_URL"].rstrip("/")
        origin = urlsplit(base)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("The gallery origin must be an HTTP(S) origin without credentials, a path, query, or fragment.")
        views = [
            f"Automatic tags configuration|{base}/add/|/add/|archivebox/templates/plugins/plugin_config_grid.html|plugin-config:autotag",
            f"Automatic summary configuration|{base}/add/|/add/|archivebox/templates/plugins/plugin_config_grid.html|plugin-config:autosummary",
        ]
        for plugin, title, artifact in AI_GALLERY_OUTPUTS:
            name = f"Snapshot View ({title})"
            if snapshot := ai_snapshots.get(plugin):
                snapshot_path = build_snapshot_detail_path(snapshot.archive_path_from_db)
                views.append(
                    f"{name}|{base}{snapshot_path}#{plugin}/{artifact}|{snapshot_path}|archivebox/templates/core/snapshot.html",
                )
            elif outcomes:
                with Path(outcomes).open("a") as stream:
                    print(name, file=stream)
        (evidence / "ai-views.txt").write_text("\n".join(views) + "\n")
    (evidence / "library-crawl-id.txt").write_text(source["crawl_id"])
    return source["crawl_id"]
