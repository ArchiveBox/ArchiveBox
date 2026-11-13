"""Capture current public news through the real CLI for recurring gallery runs."""

import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import requests
from django.utils import timezone


def configure_provider(model, data_dir):
    """Use the collection's real OpenCode server and its protected credential store."""
    from abx_plugins.plugins.opencode import runtime
    from archivebox.config import CONSTANTS
    from archivebox.config.common import get_config

    collection = Path(data_dir).resolve()
    if collection != CONSTANTS.DATA_DIR.resolve():
        raise ValueError("Run AI gallery preparation from its explicit collection directory.")
    config = get_config().model_dump(mode="json")
    if not config.get("OPENCODE_ENABLED"):
        raise RuntimeError("Enable OpenCode in the screenshot collection before preparing AI screenshots.")
    settings = runtime._settings(config, collection)
    if settings["host"] not in {"127.0.0.1", "localhost", "::1"} or any(
        not settings[key].resolve().is_relative_to(collection) for key in ("opencode_dir", "workdir")
    ):
        raise ValueError("AI gallery authentication requires a local OpenCode server scoped to its screenshot collection.")
    ok, error = runtime._ensure_opencode(settings)
    if not ok:
        raise RuntimeError(error)
    auth = runtime._server_auth(settings)
    if api_key := os.environ.get("OPENAI_API_KEY"):
        response = requests.put(f"{settings['origin']}/auth/openai", json={"type": "api", "key": api_key}, auth=auth, timeout=30)
        response.raise_for_status()
        credential_store = settings["data_home"] / "opencode" / "auth.json"
        if credential_store.exists():
            credential_store.chmod(0o600)
    response = requests.get(f"{settings['origin']}/provider", auth=auth, timeout=30)
    response.raise_for_status()
    providers = response.json()
    provider = next((provider for provider in providers.get("all", []) if provider.get("id") == "openai"), {})
    if "openai" not in providers.get("connected", []) or model.removeprefix("openai/") not in provider.get("models", {}):
        raise RuntimeError("The requested OpenAI model is unavailable. Configure OpenAI in this collection or supply OPENAI_API_KEY.")


class NewsLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "span" and values.get("class") == "titleline":
            self.in_title = True
        elif tag == "a" and self.in_title:
            url = values.get("href", "")
            if url.startswith(("http://", "https://")) and url not in self.urls:
                self.urls.append(url)
            self.in_title = False


def prepare(evidence_dir, *, model=""):
    from archivebox.config import CONSTANTS
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.core.tag_util import normalize_tag_name
    from archivebox.crawls.models import Crawl

    evidence = Path(evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    response = requests.get("https://news.ycombinator.com/front", timeout=30)
    response.raise_for_status()
    parser = NewsLinks()
    parser.feed(response.text)
    urls = ["https://news.ycombinator.com/", *parser.urls[:3]]
    if len(urls) != 4:
        raise RuntimeError("The live Hacker News front page did not provide three story links.")
    (evidence / "hacker-news-front.html").write_text(response.text)
    (evidence / "hacker-news-urls.json").write_text(json.dumps(urls, indent=2))
    plugins = "title,favicon,wget,screenshot,readability,archivewebpage"
    capture_env = os.environ.copy()
    if model:
        if not model.startswith("openai/"):
            raise ValueError("Gallery AI captures require an explicitly configured OpenAI model.")
        configure_provider(model, CONSTANTS.DATA_DIR)
        plugins += ",autotag,autosummary"
        capture_env.update(AUTOTAG_ENABLED="True", AUTOSUMMARY_ENABLED="True", AUTOTAG_MODEL=model, AUTOSUMMARY_MODEL=model)
    started = timezone.now()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
            "add",
            "--no-only-new",
            "--tag=screenshot-library,depth=1",
            "--max-urls=4",
            f"--plugins={plugins}",
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
    for snapshot in snapshots:
        if snapshot.status != Snapshot.StatusChoices.SEALED or snapshot.output_size <= 0:
            raise RuntimeError(f"Gallery capture is incomplete: {snapshot.url}")
        if not snapshot.archiveresult_set.filter(plugin="screenshot", status=ArchiveResult.StatusChoices.SUCCEEDED).exists():
            raise RuntimeError(f"Gallery capture has no real screenshot: {snapshot.url}")
        recording = snapshot.archiveresult_set.filter(plugin="archivewebpage", status=ArchiveResult.StatusChoices.SUCCEEDED).first()
        relative = recording.embed_path_db() if recording else ""
        archive = snapshot.output_dir / relative if relative else None
        if archive is None or archive.suffix.lower() != ".wacz" or not archive.is_file() or archive.stat().st_size == 0:
            raise RuntimeError(f"Gallery capture has no successful WACZ recording: {snapshot.url}")
        if model:
            for plugin in ("autotag", "autosummary"):
                if not snapshot.archiveresult_set.filter(plugin=plugin, status=ArchiveResult.StatusChoices.SUCCEEDED).exists():
                    raise RuntimeError(f"Gallery capture has no successful {plugin} result: {snapshot.url}")
            tag_records = [
                json.loads(line) for line in (snapshot.output_dir / "autotag/tags.jsonl").read_text().splitlines() if line.strip()
            ]
            if any(record.get("type") != "Tag" or not isinstance(record.get("name"), str) for record in tag_records):
                raise RuntimeError(f"Gallery capture has invalid tag records: {snapshot.url}")
            tags = [record["name"] for record in tag_records]
            if not tags or not {normalize_tag_name(tag).casefold() for tag in tags}.issubset(
                {name.casefold() for name in snapshot.tags.values_list("name", flat=True)},
            ):
                raise RuntimeError(f"Gallery capture has no real emitted tags: {snapshot.url}")
            if not (snapshot.output_dir / "autosummary/summary.md").read_text().strip():
                raise RuntimeError(f"Gallery capture has no real summary artifact: {snapshot.url}")
    if model:
        from archivebox.core.routes_util import build_snapshot_detail_path
        from urllib.parse import urlsplit

        snapshot = next(snapshot for snapshot in snapshots if snapshot.url != urls[0])
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
        snapshot_path = build_snapshot_detail_path(snapshot.archive_path_from_db)
        snapshot_url = f"{base}{snapshot_path}"
        views = [
            f"Automatic tags configuration|{base}/add/|/add/|archivebox/templates/plugins/plugin_config_grid.html|plugin-config:autotag",
            f"Automatic summary configuration|{base}/add/|/add/|archivebox/templates/plugins/plugin_config_grid.html|plugin-config:autosummary",
            f"Snapshot View (automatic tags)|{snapshot_url}#autotag/tags.jsonl|{snapshot_path}|archivebox/templates/core/snapshot.html",
            f"Snapshot View (automatic summary)|{snapshot_url}#autosummary/summary.md|{snapshot_path}|archivebox/templates/core/snapshot.html",
        ]
        (evidence / "ai-views.txt").write_text("\n".join(views) + "\n")
    (evidence / "library-crawl-id.txt").write_text(str(crawl.pk))
    return str(crawl.pk)
