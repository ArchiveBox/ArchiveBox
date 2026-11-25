#!/usr/bin/env python3
"""Prepare, capture, assemble, and publish the ArchiveBox screenshot gallery."""

import argparse
import hashlib
import html
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from html import unescape
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit


def authenticated_session(base_url, username, password):
    import requests

    session = requests.Session()
    response = session.get(f"{base_url}/admin/login/", timeout=30)
    response.raise_for_status()
    token = unescape(re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text).group(1))
    response = session.post(
        response.url,
        data={"csrfmiddlewaretoken": token, "username": username, "password": password, "next": "/admin/rules/"},
        headers={"Referer": response.url},
        timeout=30,
    )
    response.raise_for_status()
    if "/login/" in response.url:
        raise RuntimeError("Gallery login failed")
    token = unescape(re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text).group(1))
    session.headers.update({"X-CSRFToken": token, "Referer": response.url})
    return session


def prepare_webhooks(base_url, username, password):
    """Create the folder and hooks before normal, full-plugin news captures."""
    session = authenticated_session(base_url, username, password)
    response = session.get(f"{base_url}/admin/rules/data/", timeout=30)
    response.raise_for_status()
    existing = response.json()
    folder = next((folder for folder in existing["folders"] if folder["name"] == "Hacker News"), None)
    if folder is None:
        response = session.post(
            f"{base_url}/admin/core/folder/save/",
            data={
                "name": "Hacker News",
                "parent": "",
                "rules": json.dumps({"field": "domain", "lookup": "exact", "value": "news.ycombinator.com"}),
            },
            timeout=30,
        )
        response.raise_for_status()
        folder = response.json()
    hooks = [
        {
            "name": "Hacker News capture settings",
            "ref": "archivebox.core.models.Snapshot",
            "signal": "FOLDER_ENTERED",
            "folder_id": folder["id"],
            "enabled": True,
            "actions": [
                {"type": "config_overrides", "config_overrides": {"YTDLP_MAX_SIZE": "1256m"}},
                {"type": "add_tags", "add_tags": "Hacker News"},
            ],
            "stop_processing": False,
            "stop_on_failure": True,
        },
        {
            "name": "Tag completed captures",
            "ref": "archivebox.core.models.Snapshot",
            "signal": "CAPTURE_COMPLETED",
            "folder_id": None,
            "enabled": True,
            "actions": [{"type": "add_tags", "add_tags": "captured"}],
            "stop_processing": False,
            "stop_on_failure": True,
        },
        {
            "name": "Log snapshot changes",
            "ref": "archivebox.core.models.Snapshot",
            "signal": "UPDATE",
            "folder_id": None,
            "enabled": True,
            "actions": [
                {"type": "python", "code": "import sys\nprint(sys.stdin.read())"},
                {"type": "shell", "command": "cat"},
            ],
            "stop_processing": False,
            "stop_on_failure": True,
        },
    ]
    ids = []
    for hook in hooks:
        previous = next((item for item in existing["hooks"] if item["name"] == hook["name"]), None)
        if previous:
            hook["id"] = previous["id"]
        response = session.post(f"{base_url}/admin/rules/save/", json=hook, timeout=30)
        response.raise_for_status()
        ids.append(response.json()["hook"]["id"])
    return ids


def verify_actions(base_url, username, password, webhook_ids):
    """Update captured news through the REST API and check real action delivery."""
    session = authenticated_session(base_url, username, password)
    response = session.get(f"{base_url}/admin/rules/data/", timeout=30)
    response.raise_for_status()
    previous = next(item for item in response.json()["hooks"] if item["id"] == webhook_ids[2])["last_success"]
    response = session.post(f"{base_url}/api/v1/auth/get_api_token", json={"username": username, "password": password}, timeout=30)
    response.raise_for_status()
    credentials = response.json()
    if not credentials.get("success"):
        raise RuntimeError("Gallery API authentication failed")
    # Keep the native API credential in headers, never screenshot URLs or hooks.
    session.headers["X-ArchiveBox-API-Key"] = credentials["token"]
    response = session.get(f"{base_url}/api/v1/core/snapshots", params={"domain": "news.ycombinator.com"}, timeout=30)
    response.raise_for_status()
    snapshots = response.json()["items"]
    snapshot = next(item for item in snapshots if item["url"].rstrip("/") == "https://news.ycombinator.com")
    response = session.patch(
        f"{base_url}/api/v1/core/snapshot/{snapshot['id']}",
        json={"tags": list(dict.fromkeys([*snapshot["tags"], "webhook-reviewed"]))},
        timeout=30,
    )
    response.raise_for_status()
    assert "webhook-reviewed" in response.json()["tags"]
    response = session.get(f"{base_url}/admin/rules/data/", timeout=30)
    response.raise_for_status()
    hook = next(item for item in response.json()["hooks"] if item["id"] == webhook_ids[2])
    assert hook["last_success"] and (not previous or hook["last_success"] > previous)
    assert not hook["last_failure"] or hook["last_success"] > hook["last_failure"]
    return snapshot["id"]


def gallery_entries(base_url, webhook_ids):
    editor = f"/admin/rules/?webhook={webhook_ids[0]}"
    event_input = f"{editor}&preview=1"
    scripts = f"/admin/rules/?webhook={webhook_ids[2]}"
    processes = f"/admin/machine/process/?worker_type=webhook&q={webhook_ids[2]}"
    return [
        f"Rules|{base_url}/admin/rules/|/admin/rules/|archivebox/api/webhook_views.py|wait-text:Hacker News capture settings",
        f"Rule actions|{base_url}{editor}|{editor}|archivebox/templates/api/webhooks.html|wait-text:Save rule",
        f"Rule event input|{base_url}{event_input}|{event_input}|archivebox/templates/api/webhooks.html|wait-text:PLANNED ACTIONS",
        f"Rule activity|{base_url}/admin/rules/?view=activity|/admin/rules/?view=activity|archivebox/templates/api/webhooks.html|wait-text:Succeeded",
        f"Rule events|{base_url}/admin/rules/?view=events|/admin/rules/?view=events|archivebox/templates/api/webhooks.html|wait-text:Before capture",
        f"Rule scripts|{base_url}{scripts}|{scripts}|archivebox/templates/api/webhooks.html|wait-text:JSON stdin",
        f"Webhook process logs|{base_url}{processes}|{processes}|archivebox/machine/admin.py|wait-text:bash -c cat",
    ]


STAMP = "2026-01-01T00:00:00Z"


def jsonb(data):
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_recording(path, url, title, source, *, assets=()):
    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter

    stream = io.BytesIO()
    writer = WARCWriter(stream, gzip=True)
    index = []
    for target, mime, payload in ((url, "text/html; charset=utf-8", source), *assets):
        offset = stream.tell()
        record = writer.create_warc_record(
            target,
            "response",
            payload=io.BytesIO(payload),
            length=len(payload),
            http_headers=StatusAndHeaders("200 OK", [("Content-Type", mime)], protocol="HTTP/1.1"),
            warc_headers_dict={"WARC-Date": STAMP, "WARC-Record-ID": f"<urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, target)}>"},
        )
        writer.write_record(record)
        parsed = urlsplit(target)
        surt = ",".join(reversed((parsed.hostname or "").split(".")))
        if parsed.port:
            surt += f":{parsed.port}"
        surt += ")" + (parsed.path or "/")
        index.append(
            f"{surt} 20260101000000 ".encode()
            + jsonb(
                {
                    "url": target,
                    "digest": record.rec_headers.get_header("WARC-Payload-Digest"),
                    "mime": mime.split(";", 1)[0],
                    "status": 200,
                    "offset": offset,
                    "length": stream.tell() - offset,
                    "filename": "data.warc.gz",
                },
            )
            + b"\n",
        )
    warc = stream.getvalue()
    cdx = b"".join(sorted(index))
    pages = jsonb({"format": "json-pages-1.0", "id": "pages", "title": "All Pages"}) + b"\n"
    pages += (
        jsonb(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, url)),
                "url": url,
                "title": title,
                "ts": STAMP,
            },
        )
        + b"\n"
    )
    members = {
        "archive/data.warc.gz": warc,
        "indexes/index.cdx": cdx,
        "pages/pages.jsonl": pages,
    }
    metadata = jsonb(
        {
            "profile": "data-package",
            "wacz_version": "1.1.1",
            "mainPageUrl": url,
            "mainPageDate": STAMP,
            "resources": [
                {
                    "name": p.rsplit("/", 1)[-1],
                    "path": p,
                    "bytes": len(b),
                    "hash": digest(b),
                }
                for p, b in members.items()
            ],
        },
    )
    members["datapackage.json"] = metadata
    members["datapackage-digest.json"] = jsonb(
        {"path": "datapackage.json", "hash": digest(metadata)},
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in members.items():
            archive.writestr(zipfile.ZipInfo(name), body)


def prepare_replay_fixture():
    """Create a gallery-only crawl, separate from native capture evidence."""
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    homepage = "https://field-notes.example/"
    stories = {
        "https://design-notes.example/field-journal": (
            "A digital field journal",
            "A short guide to keeping field notes, recording context, and revisiting the source material later.",
        ),
        "https://garden-notes.example/pollinators": (
            "A guide to urban pollinators",
            "A field guide to noticing insects, keeping seasonal records, and identifying plants that provide food and cover.",
        ),
        "https://map-notes.example/walking-routes": (
            "Mapping neighborhood walks",
            "How a walking map can capture landmarks, everyday shortcuts, and the details that disappear from larger maps.",
        ),
    }
    pages = {
        homepage: (
            "Field Notes",
            "<ul>" + "".join(f'<li><a href="{url}">{title}</a></li>' for url, (title, _) in stories.items()) + "</ul>",
        ),
        **{url: (title, f"<p>{body}</p>") for url, (title, body) in stories.items()},
    }
    crawl = Crawl.objects.create(
        urls="\n".join(pages),
        tags_str="screenshot-library",
        status=Crawl.StatusChoices.SEALED,
    )
    for url, (title, body) in pages.items():
        html = f"<!doctype html><html lang=en><meta charset=utf-8><title>{title}</title><main><article><h1>{title}</h1>{body}</article></main></html>".encode()
        snapshot = Snapshot.objects.create(
            url=url,
            title=title,
            crawl=crawl,
            config={"PERMISSIONS": "public"},
            status=Snapshot.StatusChoices.SEALED,
        )
        paths = {
            "dom": "dom/output.html",
            "archivewebpage": "archivewebpage/archivewebpage.wacz",
        }
        for plugin, relative in paths.items():
            output = snapshot.output_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            if plugin == "dom":
                output.write_bytes(html)
                mime = "text/html"
            else:
                write_recording(output, url, title, html)
                mime = "application/wacz"
            size = output.stat().st_size
            # Model the app's usual saved-output contract. This row describes a
            # generated fixture, not an extractor that was invoked and passed.
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin=plugin,
                hook_name="gallery_fixture",
                status=ArchiveResult.StatusChoices.SUCCEEDED,
                output_str=relative,
                output_size=size,
                output_files={relative: {"size": size, "mimetype": mime}},
            )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            output_size=sum((snapshot.output_dir / name).stat().st_size for name in paths.values()),
        )
    return {
        "crawl_id": str(crawl.pk),
        "homepage": homepage,
        "stories": list(stories),
        "replay_urls": {url: url for url in pages},
        "homepage_selector": "main article",
        "title": "Field Notes",
    }


def prepare_folder():
    """Use owned linked recordings to exercise actual folder export and replay."""
    from archivebox.core.models import Folder, Snapshot

    source = prepare_replay_fixture()
    folder = Folder.objects.create(name="Folder replay fixture")
    snapshots = Snapshot.objects.filter(crawl_id=source["crawl_id"])
    Folder.move_snapshots(snapshots, folder.pk, notify=False)
    return {**source, "folder_id": str(folder.pk)}


def prepare_site_navigation(crawl_id, site_directory):
    """Fill missing capture roles for the disposable, app-owned local site."""
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.plugins.discovery import get_snapshot_role_paths

    directory = Path(site_directory)
    crawl = Crawl.objects.get(pk=crawl_id)
    homepage = crawl.urls.splitlines()[0]
    origin = urlsplit(homepage)
    if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"} or origin.path != "/site-navigation/index.html":
        raise ValueError("Expected the disposable gallery site-navigation crawl.")
    assets = tuple(
        (name, mime, (directory / name).read_bytes()) for name, mime in (("style.css", "text/css"), ("notebook.svg", "image/svg+xml"))
    )
    for filename, title in (("index.html", "Field Notes"), ("chapter.html", "A Walk by the River")):
        url = urljoin(homepage, filename)
        html = (directory / filename).read_bytes()
        snapshot, _ = Snapshot.objects.get_or_create(
            crawl=crawl,
            url=url,
            defaults={"title": title, "status": Snapshot.StatusChoices.SEALED},
        )
        if snapshot.status != Snapshot.StatusChoices.SEALED:
            raise ValueError("Wait for the gallery crawl to finish before preparing replay fixtures.")
        results = list(snapshot.archiveresult_set.filter(status=ArchiveResult.StatusChoices.SUCCEEDED))
        if not any((snapshot.output_dir / relative).is_file() for relative in get_snapshot_role_paths(snapshot, results, "html_replay")):
            relatives = {"dom/gallery-fixture/output.html": ("text/html", html)}
            relatives.update({f"dom/gallery-fixture/{name}": (mime, data) for name, mime, data in assets})
            for relative, (_, data) in relatives.items():
                output = snapshot.output_dir / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    # Keep the bytes left by the failed native hook available for diagnosis.
                    raise ValueError(f"Refusing to replace existing {relative} in the gallery fixture.")
                output.write_bytes(data)
            _save_gallery_output(snapshot, "dom", "dom/gallery-fixture/output.html", relatives)
        if not any(
            (relative := result.embed_path_db()) and relative.endswith(".wacz") and (snapshot.output_dir / relative).is_file()
            for result in results
        ):
            relative = "archivewebpage/gallery-fixture.wacz"
            output = snapshot.output_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            write_recording(output, url, title, html, assets=tuple((urljoin(url, name), mime, data) for name, mime, data in assets))
            _save_gallery_output(snapshot, "archivewebpage", relative, {relative: ("application/wacz", output.read_bytes())})


def _save_gallery_output(snapshot, plugin, primary, files):
    from archivebox.core.models import ArchiveResult, Snapshot

    from django.db.models import F

    manifest = {path: {"mimetype": mime, "size": len(data)} for path, (mime, data) in files.items()}
    size = sum(meta["size"] for meta in manifest.values())
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name="gallery_fixture",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=primary,
        output_size=size,
        output_files=manifest,
    )
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=F("output_size") + size)


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
    import requests

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
def gallery_persona_config(persona, overrides):
    """Keep live flags on the fixture's existing Persona, not the collection."""
    if not overrides:
        yield
        return

    from archivebox.personas.models import Persona

    persona.refresh_from_db(fields=["config"])
    previous = persona.config
    applied = {**(previous or {}), **overrides}

    def update(expected, value):
        key = "config" if expected is not None else "config__isnull"
        return Persona.objects.filter(pk=persona.pk, **{key: expected if expected is not None else True}).update(config=value)

    if not update(previous, applied):
        raise RuntimeError("Gallery Persona settings changed before capture.")
    try:
        yield
    finally:
        persona.refresh_from_db(fields=["config"])
        current = dict(persona.config or {})
        for key, value in overrides.items():
            if key in current and current[key] == value:
                if key in (previous or {}):
                    current[key] = previous[key]
                else:
                    del current[key]
        if not update(persona.config, current or (None if previous is None else {})):
            raise RuntimeError("Gallery Persona settings changed during restoration.")


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


def prepare_library(evidence_dir, *, model=""):
    from django.utils import timezone

    from archivebox.config import CONSTANTS
    from archivebox.core.models import Snapshot
    from archivebox.core.tag_util import normalize_tag_name
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    evidence = Path(evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    capture_env = os.environ.copy()
    if model:
        if not model.startswith("openai/"):
            raise ValueError("Gallery AI captures require an explicitly configured OpenAI model.")
        configure_provider(model, CONSTANTS.DATA_DIR)
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
    (evidence / "gallery-library-source.json").write_text(json.dumps(source))
    ai_snapshots = {}
    for snapshot in snapshots:
        if model:
            # Native hooks can stop at the snapshot size limit after replay is ready.
            # Validate actual AI attempts without requiring every replay to have one.
            available = {
                plugin: validate_ai_result(snapshot, plugin)
                for plugin, _, _ in AI_GALLERY_OUTPUTS
                if snapshot.archiveresult_set.filter(plugin=plugin).exists()
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
            # Tag.save() decodes sanitized text (e.g. "&amp;" becomes "&") before storing it.
            stored_tags = list(snapshot.tags.values_list("name", flat=True))
            if not tags or not {unescape(normalize_tag_name(tag)).strip().casefold() for tag in tags}.issubset(
                {name.casefold() for name in stored_tags},
            ):
                raise RuntimeError(
                    f"Gallery tag projection mismatch for {snapshot.url}: emitted={tags!r}, stored={stored_tags!r}",
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
            else:
                raise RuntimeError(f"No captured output for {name}")
        (evidence / "ai-views.txt").write_text("\n".join(views) + "\n")
    (evidence / "library-crawl-id.txt").write_text(source["crawl_id"])
    return source["crawl_id"]


def importer_view_names(name):
    return (name, name + " history", name + " snapshots", name + " export")


def prepare_importers(admin_base_url, recipes, *, capture_opt_ins=None):
    def command(*args, settings=None):
        extra = {"env": {**os.environ, **settings}} if settings else {}
        result = subprocess.run([sys.executable, "-m", "archivebox", *args], capture_output=True, text=True, **extra)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    def runs_for(source_id):
        return json.loads(command("importer", "runs", "--source-id", source_id, "--format", "json"))

    def run_action(source_id, action, recipe):
        key = (capture_opt_ins or {}).get(recipe["plugin"])
        settings = {key: "True"} if key else None
        command("manage", "importers", "--source", source_id, "--action", action, settings=settings)

    views = []
    for recipe in recipes:
        sources = json.loads(command("importer", "list", "--format", "json"))
        source = next(
            (
                source
                for source in sources
                if source["plugin"] == recipe["plugin"]
                and source["feed"] == recipe["feed"]
                and source["settings"] == recipe["settings"]
                and source["name"] == recipe["name"]
            ),
            None,
        )
        if source is None:
            source = json.loads(
                command(
                    "importer",
                    "create",
                    "--plugin",
                    recipe["plugin"],
                    "--feed",
                    recipe["feed"],
                    "--name",
                    recipe["name"],
                    "--tags",
                    "screenshot-gallery",
                    "--settings",
                    json.dumps(recipe["settings"]),
                ),
            )
        source_id = source["id"]
        run_action(source_id, "preview", recipe)
        runs = runs_for(source_id)
        imports = [run for run in runs if run["action"] == "import"]
        if not imports:
            run_action(source_id, "import", recipe)
            runs = runs_for(source_id)
            imports = [run for run in runs if run["action"] == "import"]
        if not imports or any(run["status"] != "succeeded" for run in runs):
            raise RuntimeError("Importer gallery requires successful preview and import records.")
        if not any(run["items"] for run in imports):
            raise RuntimeError("Importer gallery requires nonempty imported records.")
        for crawl_id in dict.fromkeys(run["crawl_id"] for run in imports if run["crawl_id"]):
            # No plugin selector: every imported URL receives the normal full capture.
            print(f"[*] Verifying full importer capture: {crawl_id}", file=sys.stderr)
            command("run", "--crawl-id", crawl_id)
        run = next(run for run in imports if run["items"])
        for name, path, mode in (
            (recipe["name"], f"/admin/importers/runs/{run['id']}/", ""),
            (recipe["name"] + " export", f"/admin/importers/runs/{run['id']}/", "view-export-menu"),
            (recipe["name"] + " history", f"/admin/importers/{source_id}/", ""),
            (recipe["name"] + " snapshots", f"/admin/core/snapshot/?crawl_id={run['crawl_id']}", ""),
        ):
            views.append("|".join((name, admin_base_url + path, urlsplit(path).path, "archivebox/importers/views.py", mode)))
    return views


REPO_DIR = Path(__file__).resolve().parents[1]
PUBLIC_SCREENSHOT_BASE = "https://archivebox.io/screenshots/"
CAPTURE_PROFILES = {
    "desktop": (1600, 1000),
    "tablet": (1024, 1366),
    "mobile": (390, 844),
}

REQUIRED_VIEW_NAMES = {
    "First-time setup wizard",
    "Login",
    "Public snapshot list",
    "Add URLs",
    "Admin dashboard",
    "AI agent",
    "Snapshots table",
    "Snapshots grid",
    "Snapshot admin detail",
    "Snapshot View (capture in progress)",
    "Snapshot View (header collapsed)",
    "Folder WACZ homepage",
    "Folder WACZ story navigation",
    "WACZ archived story",
    "Snapshot files",
    "Archive results",
    "Archive result detail",
    "Crawl detail",
    "Crawl schedules",
    "Crawl schedule detail",
    "Persona detail",
    "Persona browser state",
    "Machine settings",
    "Network interface detail",
    "Binary detail",
    "Process detail",
    "API tokens",
    "API token detail",
    "Environment",
    "Configuration",
    "Configuration detail",
    "Dependencies",
    "Dependency detail",
    "Plugins",
    "Workers",
    "Worker detail",
    "Logs",
    "Log detail",
}


def write_chrome_lifecycle_diagnostics(output_path: Path) -> None:
    """Classify persisted hook stderr without exporting any log-derived values.

    Successful hook sidecars are deleted, but their Process.stderr remains in
    the database. Older Chrome hooks can report success after a renderer crash.
    Keep page crashes separate from unexplained closes (including tab discard).
    """
    from django.db.models.functions import Length, Right

    from archivebox.machine.models import Process

    process_limit = 128
    stderr_limit = 65536
    patterns = {
        "renderer_crashed": re.compile(r"Page crashed!|Snapshot target [0-9a-f]+ crashed:", re.I),
        "unexpected_target_close": re.compile(r"tab closed unexpectedly!|Snapshot target [0-9a-f]+ closed unexpectedly", re.I),
        "heap_allocation_failure": re.compile(
            r"JavaScript heap out of memory|Reached heap limit|FatalProcessOutOfMemory|OOM_CRASH|"
            r"(?:PartitionAlloc|partition_alloc).*out of memory",
            re.I,
        ),
        "browser_close_failed": re.compile(r"Browser\.close failed:|cleanup did not fully stop the browser process tree", re.I),
    }
    processes = list(
        Process.objects.filter(process_type=Process.TypeChoices.HOOK, pwd__endswith="/chrome")
        .order_by("-created_at")
        .annotate(stderr_tail=Right("stderr", stderr_limit), stderr_length=Length("stderr"))
        .values_list("exit_code", "stderr_tail", "stderr_length")[: process_limit + 1],
    )
    report = {
        "version": 1,
        "process_limit": process_limit,
        "stderr_tail_limit": stderr_limit,
        "processes_scanned": min(len(processes), process_limit),
        "processes_omitted": len(processes) > process_limit,
        "stderr_truncated_processes": 0,
        "reported_success_with_lifecycle_evidence": 0,
        "classifications": dict.fromkeys(patterns, 0),
    }
    for exit_code, stderr, stderr_length in processes[:process_limit]:
        matches = {name: bool(pattern.search(stderr)) for name, pattern in patterns.items()}
        for name, matched in matches.items():
            report["classifications"][name] += int(matched)
        report["stderr_truncated_processes"] += int(stderr_length > stderr_limit)
        report["reported_success_with_lifecycle_evidence"] += int(exit_code == 0 and any(matches.values()))
    with output_path.open("w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")


def write_navigation_diagnostics(data_dir: Path, output_path: Path) -> None:
    """Retain numeric navigation evidence and cooldown headers, never URLs or credentials."""
    archive_dir = (data_dir / "archive").resolve()
    records = []
    for navigation_path in archive_dir.glob("**/chrome/navigation.json"):
        if len(records) >= 128:
            break
        snapshot_dir = navigation_path.parent.parent
        if not re.fullmatch(r"[0-9a-f-]{32,36}", snapshot_dir.name):
            continue
        record = {"snapshot_id": snapshot_dir.name, "navigation": {}, "headers_capture": {}}
        for kind, source in (("navigation", navigation_path), ("headers_capture", snapshot_dir / "headers/headers.json")):
            try:
                if source.is_symlink() or not source.resolve().is_relative_to(archive_dir):
                    continue
                with source.open("rb") as saved:
                    contents = saved.read(65537)
                if len(contents) > 65536:
                    continue
                document = json.loads(contents)
                if not isinstance(document, dict):
                    continue
            except (OSError, ValueError):
                continue
            keys = ("status", "elapsed", "attempts", "retry_after_ms") if kind == "navigation" else ("status",)
            record[kind].update({key: document[key] for key in keys if type(document.get(key)) is int and document[key] >= 0})
            if kind == "headers_capture":
                headers = document.get("response_headers", document.get("headers", {}))
                if not isinstance(headers, dict):
                    continue
                for name, value in headers.items():
                    name = name.lower()
                    if name not in ("retry-after", "date"):
                        continue
                    record[kind][name] = "invalid"
                    if not isinstance(value, str):
                        continue
                    if name == "retry-after" and re.fullmatch(r"[0-9]{1,12}", value.strip()):
                        record[kind][name] = value.strip()
                    else:
                        try:
                            parsed = parsedate_to_datetime(value)
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            record[kind][name] = format_datetime(parsed.astimezone(timezone.utc), usegmt=True)
                        except (ValueError, TypeError, OverflowError):
                            pass
        records.append(record)
    with output_path.open("w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(records, output, indent=2, sort_keys=True)
        output.write("\n")


def plugin_screenshot_plan() -> dict:
    """Discover default coverage and plugin-owned examples from the installed package."""
    from abx_plugins import get_plugins_dir

    required = []
    examples = {}
    overrides = {}
    config_views = []
    importer_views = []
    enabled_plugins = []
    capture_opt_ins = {}
    owned_views = {}
    app_pages = []
    selected = set(filter(None, os.environ.get("UI_SCREENSHOT_PLUGINS", "").split(",")))
    for plugin_dir in sorted(get_plugins_dir().iterdir()):
        if selected and plugin_dir.name not in selected:
            continue
        config_path = plugin_dir / "config.json"
        if not config_path.is_file():
            continue
        config = json.loads(config_path.read_text())
        recipe = json.loads((plugin_dir / config["screenshot"]).read_text()) if config.get("screenshot") else {}
        plugin = plugin_dir.name
        first_view = len(required)
        enabled_key = f"{plugin.upper()}_ENABLED"
        enable_schema = config.get("properties", {}).get(enabled_key, {})
        enabled = enable_schema.get("default", False)
        if recipe.get("enabled") or recipe.get("url"):
            enabled_plugins.append(plugin)
            enabled = True
        if page := recipe.get("app_page"):
            app_pages.append({**page, "name": recipe["view"], "plugin": plugin})
            mode = ""
            if selector := page.get("wait_for_selector"):
                mode = f"wait-selector:{selector}"
            elif page.get("wait_for_text"):
                mode = f"wait-text:{page['wait_for_text']}"
            config_views.append(
                {
                    "name": recipe["view"],
                    "plugin": plugin,
                    "path": page["path"],
                    "source": f"https://github.com/ArchiveBox/abx-plugins/blob/main/abx_plugins/plugins/{plugin}/{page['source']}",
                    "mode": mode,
                }
            )
        if recipe.get("view"):
            required.append(recipe["view"])
            if recipe.get("importer"):
                required.extend(importer_view_names(recipe["view"])[1:])
                importer_views.append(
                    {"name": recipe["view"], "plugin": plugin, "feed": recipe["importer"], "settings": recipe.get("config_overrides", {})},
                )
            if recipe.get("config"):
                config_name = recipe["view"] + " configuration" if recipe.get("importer") else recipe["view"]
                if recipe.get("importer"):
                    required.append(config_name)
                feed = next(iter(config.get("importers", {})), None)
                config_views.append(
                    {
                        "name": config_name,
                        "plugin": plugin,
                        "path": f"/admin/importers/new/{plugin}/{feed}/" if feed else "/add/",
                        "source": "archivebox/importers/templates/importers/configure.html"
                        if feed
                        else "archivebox/templates/plugins/plugin_config_grid.html",
                        "mode": "" if feed else f"plugin-config:{plugin}",
                    },
                )
        elif enabled and (
            recipe.get("url")
            or (plugin_dir / "templates/full.html").is_file()
            or ((plugin_dir / "templates/card.html").is_file() and not config.get("card_hidden"))
        ):
            required.append(f"Snapshot View ({plugin})")
        if recipe.get("url"):
            overrides[plugin] = recipe
            key = recipe["url"]
            example = examples.setdefault(key, {"url": key, "plugins": []})
            example["plugins"].append(plugin)
            for output in recipe.get("outputs", []):
                required.append(output["name"])
                key = output.get("url", recipe["url"])
                example = examples.setdefault(key, {"url": key, "plugins": []})
                if plugin not in example["plugins"]:
                    example["plugins"].append(plugin)
        # Options shown in the configuration UI do not require actually
        # enabling their extractors. An app-only recipe (e.g. a server
        # route), however, must retain its collection-level enable.
        if (
            enable_schema.get("default") is False
            and plugin in enabled_plugins
            and (recipe.get("url") or recipe.get("importer") or f"Snapshot View ({plugin})" in required[first_view:])
        ):
            enabled_plugins.remove(plugin)
            capture_opt_ins[plugin] = enabled_key
        for name in required[first_view:]:
            if name in REQUIRED_VIEW_NAMES or (recipe.get("app_page") and name == recipe["view"]):
                continue  # Ownership remains with the required application UI.
            if name in owned_views:
                raise ValueError(f"Duplicate plugin screenshot view: {name}")
            owned_views[name] = plugin
    if not selected:
        for plugin, title, _ in AI_GALLERY_OUTPUTS:
            name = f"Snapshot View ({title})"
            owned_views[name] = plugin
    return {
        "required": required,
        "app_pages": app_pages,
        "owned_views": owned_views,
        "examples": list(examples.values()),
        "overrides": overrides,
        "enabled": enabled_plugins,
        "capture_opt_ins": capture_opt_ins,
        "config_views": config_views,
        "importer_views": importer_views,
    }


def supplementary_recipe_views(recipe, owner, source_url=None):
    names = [f"Snapshot View ({owner})"] if source_url is None or source_url == recipe["url"] else []
    names.extend(
        output["name"] for output in recipe.get("outputs", ()) if source_url is None or source_url == output.get("url", recipe["url"])
    )
    return names


def record_unavailable_recipe(plan, snapshot_id, owner, source_url, report):
    """Only record a terminal native owner failure on a successfully opened capture."""
    from archivebox.core.models import ArchiveResult, Snapshot

    if not Snapshot.objects.filter(pk=snapshot_id, url=source_url, status=Snapshot.StatusChoices.SEALED).exists():
        return False
    results = ArchiveResult.objects.filter(snapshot_id=snapshot_id)
    states = set(results.filter(plugin=owner).values_list("status", flat=True))
    failure = {"failed", "noresults"}
    if not (states & failure) or states - (failure | {"skipped"}):
        return False
    if not results.filter(plugin="chrome", hook_name="on_Snapshot__30_chrome_navigate", status="succeeded").exists():
        return False
    recipe = plan["overrides"][owner]
    names = supplementary_recipe_views(recipe, owner, source_url)
    if not names or any(name in REQUIRED_VIEW_NAMES or plan["owned_views"].get(name) != owner for name in names):
        raise ValueError("Unavailable capture did not resolve to a plugin-owned view")
    with report.open("a", encoding="utf-8") as out:
        for name in names:
            print(name, file=out)
            print(f"::warning title=Native plugin screenshot unavailable::{name} (owner: {', '.join(sorted(states))})", file=sys.stderr)
    return True


def capture_settings(plan, plugin_names):
    owners = plugin_names or [
        plugin for name, plugin in plan["owned_views"].items() if plugin not in plan["overrides"] and name == f"Snapshot View ({plugin})"
    ]
    config = {}
    for plugin in plugin_names:
        for key, value in plan["overrides"][plugin].get("config_overrides", {}).items():
            if key in config and config[key] != value:
                raise ValueError(f"Conflicting screenshot config for {key}")
            config[key] = value
    overrides = {key: config.get(key, True) for plugin in owners if (key := plan["capture_opt_ins"].get(plugin))}
    return config, overrides


def capture_add(plan, plugin_names, source_url, *, scoped):
    config, overrides = capture_settings(plan, plugin_names)
    os.environ.update({key: json.dumps(value) if isinstance(value, (dict, list)) else str(value) for key, value in config.items()})

    sys.argv = ["archivebox", "add", "--depth=0", "--overwrite", "--tag=screenshot-gallery", source_url]
    if not scoped or not overrides:
        os.execvp(sys.argv[0], sys.argv)

    from archivebox.cli import main

    from archivebox.config.django import setup_django
    from archivebox.core.shutdown_util import foreground_shutdown_signals

    # A shared supervisor does not inherit a later CLI's execution flags.
    # Temporarily scope them to the same Persona and preserve its browser state.
    with foreground_shutdown_signals(first_signal_message=None):
        setup_django()
        from archivebox.personas.models import Persona

        with gallery_persona_config(Persona.get_or_create_named("Default"), overrides):
            main(args=sys.argv[1:])


def build_provenance() -> dict[str, str]:
    version = tomllib.loads((REPO_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    revision = os.environ.get("GITHUB_SHA", "").strip()
    if not revision:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    return {
        "version": version,
        "revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def validate_navigation(metadata_path: Path, expected_path: str) -> None:
    navigation = json.loads(metadata_path.read_text(encoding="utf-8"))
    navigation = navigation.get("checks", navigation)
    status = navigation.get("status")
    final_url = navigation.get("finalUrl") or ""
    actual = urlparse(final_url)
    expected = urlparse(expected_path)
    if status != 200:
        raise SystemExit(f"expected HTTP 200, got {status}: {final_url or metadata_path}")
    if actual.path != expected.path:
        raise SystemExit(f"expected final path {expected.path}, got {actual.path}: {final_url}")
    if expected.query and parse_qs(actual.query, keep_blank_values=True) != parse_qs(expected.query, keep_blank_values=True):
        raise SystemExit(f"expected final query {expected.query}, got {actual.query}: {final_url}")


def append_manifest(manifest_path: Path, screenshot_path: Path) -> None:
    data = screenshot_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise SystemExit(f"not a valid PNG: {screenshot_path}")
    dimensions = struct.unpack(">II", data[16:24])
    profile = os.environ["UI_SCREENSHOT_PROFILE"]
    if profile not in CAPTURE_PROFILES:
        raise SystemExit(f"unknown screenshot profile: {profile}")
    expected_dimensions = CAPTURE_PROFILES[profile]
    if dimensions != expected_dimensions:
        raise SystemExit(
            f"expected {expected_dimensions[0]}x{expected_dimensions[1]} for {profile}, "
            f"got {dimensions[0]}x{dimensions[1]}: {screenshot_path}",
        )

    item = {
        "name": os.environ["UI_SCREENSHOT_NAME"],
        "url": os.environ["UI_SCREENSHOT_URL"],
        "source": os.environ["UI_SCREENSHOT_SOURCE"],
        "filename": os.environ["UI_SCREENSHOT_FILENAME"],
        "profile": profile,
        "width": dimensions[0],
        "height": dimensions[1],
    }
    timing_report_path = os.environ.get("UI_SCREENSHOT_TIMING_REPORT", "").strip()
    if timing_report_path:
        timing_report = json.loads(Path(timing_report_path).read_text(encoding="utf-8"))
        ttfb_ms = timing_report.get("checks", {}).get("ttfbMs")
        if isinstance(ttfb_ms, int | float):
            item["ttfb_ms"] = round(ttfb_ms)
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(item) + "\n")


def render_gallery(gallery_header: str, gallery_sections: str) -> str:
    # Older capture bundles contain the Django admin form for the same Rules.
    gallery_sections = re.sub(r'<article id="(?:webhooks|webhook-detail)">.*?</article>', "", gallery_sections, flags=re.DOTALL)
    # Some plugins are captured during library setup. Keep their snapshot
    # outputs together regardless of when the underlying captures ran.
    snapshot_outputs = []

    def move_snapshot_output(match):
        if match[1] in {"snapshot-view-capture-in-progress", "snapshot-view-header-collapsed"}:
            return match[0]
        snapshot_outputs.append(match[0])
        return ""

    gallery_sections = re.sub(r'<article id="(snapshot-view-[^"]+)">.*?</article>', move_snapshot_output, gallery_sections, flags=re.DOTALL)
    gallery_sections += "".join(snapshot_outputs)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        + (REPO_DIR / "bin/templates/screenshots-head.html").read_text(encoding="utf-8")
        + "<style>"
        ":root{--ink:#28252a;--muted:#716c74;--accent:#9b2854;--paper:#fcfaf7;--line:#e9e2e3}"
        "*{box-sizing:border-box}body{margin:0;font:16px/1.75 system-ui,sans-serif;"
        "background:var(--paper);color:var(--ink)}.screenshot-content{max-width:1100px;margin:0 auto;padding:28px}"
        "a{color:var(--accent)}h1,h2{line-height:1.15;letter-spacing:-.045em}"
        "article{margin:40px 0 65px}article h2{font-size:29px;margin:0 0 10px}article p{font-size:13px;color:var(--muted);margin:0 0 20px}"
        ".profile-switch{display:flex;flex-wrap:wrap;gap:4px;background:#f0e8eb;border:1px solid var(--line);padding:5px;"
        "border-radius:28px;width:max-content;max-width:100%;margin:30px 0}.profile-switch button{font:600 13px system-ui;"
        "cursor:pointer;border:0;border-radius:22px;background:transparent;color:var(--muted);padding:10px 20px}"
        ".profile-switch button[aria-pressed=true]{background:var(--accent);color:white;box-shadow:0 3px 10px #9b285425}"
        "a:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:4px}"
        "figure{min-width:0;margin:0 0 20px;padding:18px;border:1px solid var(--line);border-radius:20px;"
        "background:linear-gradient(140deg,#fff,#f8edf2)}figure[hidden]{display:none}"
        ".shot-mobile{max-width:440px;margin-inline:auto}.shot-tablet{max-width:800px;margin-inline:auto}"
        "figcaption{font-size:12px;color:var(--muted);text-align:center;margin:0 0 12px}"
        "img{display:block;width:100%;height:auto;border-radius:8px}code{overflow-wrap:anywhere}"
        "@media(max-width:550px){.screenshot-content{padding:20px}figure{padding:8px;border-radius:12px}.profile-switch button{padding:9px 16px}}"
        "</style></head><body>"
        + (REPO_DIR / "bin/templates/screenshots-header.html").read_text(encoding="utf-8")
        + '<div class="screenshot-content">'
        + gallery_header
        + '<div class="profile-switch" role="group" aria-label="Screenshot viewport">'
        + "".join(
            f'<button type="button" data-viewport="{profile}" aria-pressed="{str(profile == "desktop").lower()}">{profile.title()}</button>'
            for profile in CAPTURE_PROFILES
        )
        + "</div><main>"
        + gallery_sections
        + """</main><script>
const figures = document.querySelectorAll('.shot');
const buttons = document.querySelectorAll('[data-viewport]');
function selectProfile(profile) {
  for (const figure of figures) figure.hidden = figure.dataset.profile !== profile;
  for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.viewport === profile));
}
for (const button of buttons) button.addEventListener('click', () => selectProfile(button.dataset.viewport));
selectProfile('desktop');
</script></div>"""
        + (REPO_DIR / "bin/templates/screenshots-footer.html").read_text(encoding="utf-8")
        + "</body></html>\n"
    )


def build_galleries(manifest_path: Path, markdown_path: Path, html_path: Path, unavailable=()) -> None:
    provenance = build_provenance()
    source_base_url = f"https://github.com/ArchiveBox/ArchiveBox/blob/{provenance['revision']}/"
    captures = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    allow_partial = os.environ.get("UI_SCREENSHOT_ALLOW_PARTIAL") == "1"
    grouped_captures: list[dict[str, object]] = []
    captures_by_name: dict[str, dict[str, object]] = {}
    for capture in captures:
        group = captures_by_name.get(capture["name"])
        if group is None:
            group = {
                "name": capture["name"],
                "url": capture["url"],
                "source": capture["source"],
                "variants": {},
            }
            captures_by_name[capture["name"]] = group
            grouped_captures.append(group)
        elif group["url"] != capture["url"] or group["source"] != capture["source"]:
            raise SystemExit(f"inconsistent manifest metadata for {capture['name']}")
        variants = group["variants"]
        assert isinstance(variants, dict)
        if capture["profile"] in variants:
            raise SystemExit(f"duplicate {capture['profile']} capture for {capture['name']}")
        variants[capture["profile"]] = capture

    outcomes = unavailable_recipe_outcomes(unavailable, captures_by_name)
    if not grouped_captures and not (allow_partial and outcomes):
        raise SystemExit("No gallery views were captured")
    for group in grouped_captures:
        variants = group["variants"]
        assert isinstance(variants, dict)
        missing_profiles = [profile for profile in CAPTURE_PROFILES if profile not in variants]
        if missing_profiles:
            raise SystemExit(f"missing {', '.join(missing_profiles)} capture for {group['name']}")

    if not allow_partial:
        captured_names = set(captures_by_name)
        missing = sorted((REQUIRED_VIEW_NAMES | set(plugin_screenshot_plan()["required"])) - captured_names - set(unavailable))
        if missing:
            raise SystemExit(f"required UI screenshot coverage is missing: {', '.join(missing)}")
    markdown_sections = []
    html_sections = []
    for capture in grouped_captures:
        variants = capture["variants"]
        assert isinstance(variants, dict)
        parsed_url = urlparse(str(capture["url"]))
        route = parsed_url.path or "/"
        if parsed_url.fragment:
            route = f"{route}#{parsed_url.fragment}"
        source = capture["source"]
        source_url = source if source.startswith("https://") else f"{source_base_url}{source}"
        ttfb_values = [variant["ttfb_ms"] for variant in variants.values() if isinstance(variant.get("ttfb_ms"), int | float)]
        ttfb_text = f" · ~{round(sum(ttfb_values) / len(ttfb_values))}ms TTFB" if ttfb_values else ""
        markdown_cells = []
        html_figures = []
        for profile, (width, height) in CAPTURE_PROFILES.items():
            variant = variants[profile]
            label = f"{profile.title()} ({width}x{height})"
            filename = str(variant["filename"])
            screenshot_path = markdown_path.parent / "screenshots" / filename
            if not screenshot_path.is_file():
                raise SystemExit(f"missing screenshot for gallery: {screenshot_path}")
            cache_version = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()[:12]
            versioned_filename = f"{html.escape(filename)}?v={cache_version}"
            markdown_cells.append(
                f'<td align="center"><strong>{label}</strong><br>'
                f'<img src="{PUBLIC_SCREENSHOT_BASE}{versioned_filename}" '
                f'alt="{html.escape(str(capture["name"]))} — {profile}" width="{width}"></td>',
            )
            html_figures.append(
                f'<figure class="shot shot-{profile}" data-profile="{profile}"><figcaption>{label}</figcaption>'
                f'<a href="./{versioned_filename}">'
                f'<img src="./{versioned_filename}" width="{width}" height="{height}" loading="lazy" '
                f'alt="{html.escape(str(capture["name"]))} — {profile}"></a></figure>',
            )
        markdown_sections.append(
            "\n".join(
                (
                    f"## {capture['name']}",
                    "",
                    f"View: [`{route}`]({capture['url']}) · [View code]({source_url}){ttfb_text}",
                    "",
                    "<table><thead><tr>",
                    "".join(f"<th>{profile.title()}</th>" for profile in CAPTURE_PROFILES),
                    "</tr></thead><tbody><tr>",
                    "".join(markdown_cells),
                    "</tr></tbody></table>",
                ),
            ),
        )
        html_sections.append(
            f'<article id="{re.sub(r"[^a-z0-9]+", "-", capture["name"].lower()).strip("-")}"><h2>{html.escape(capture["name"])}</h2>'
            f'<p><a href="{html.escape(capture["url"])}"><code>{html.escape(route)}</code></a> · '
            f'<a href="{html.escape(source_url)}">View code</a>{html.escape(ttfb_text)}</p>'
            f'<div class="shots">{"".join(html_figures)}</div></article>',
        )

    markdown_path.write_text(
        "\n".join(
            (
                "# UI Screenshots",
                "",
                "<!-- Generated by bin/collect_ui_screenshots.sh. Do not edit by hand. -->",
                "",
                (
                    "These desktop, tablet, and mobile screenshots cover ArchiveBox's major public and authenticated UI views. "
                    "Raw API endpoints, API documentation, health-check, and error routes are intentionally excluded."
                ),
                f"Generated from ArchiveBox `{provenance['version']}` at revision `{provenance['revision']}`.",
                "",
                "\n\n".join(markdown_sections),
                "",
            ),
        ),
        encoding="utf-8",
    )

    gallery_header = (
        '<header><p><a href="../">← ArchiveBox</a></p><h1>ArchiveBox UI Screenshots</h1>'
        + f"<p>Generated from ArchiveBox <code>{html.escape(provenance['version'])}</code> at "
        f'<a href="https://github.com/ArchiveBox/ArchiveBox/commit/{html.escape(provenance["revision"])}">'
        f"<code>{html.escape(provenance['revision'][:12])}</code></a> on "
        f'<time datetime="{html.escape(provenance["generated_at"])}">{html.escape(provenance["generated_at"])}</time>. '
        "Desktop, tablet, and mobile viewports are captured from the same build.</p>"
        "</header>"
    )
    html_path.write_text(render_gallery(gallery_header, "".join(html_sections)), encoding="utf-8")

    file_hashes = {
        capture["filename"]: hashlib.sha256((html_path.parent / capture["filename"]).read_bytes()).hexdigest() for capture in captures
    }
    (html_path.parent / "build.json").write_text(
        json.dumps(
            {
                **provenance,
                "capture_count": len(captures),
                "files": file_hashes,
                **({"optional_recipe_captures": outcomes} if outcomes else {}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if not allow_partial:
        expected_filenames = {capture["filename"] for capture in captures}
        for screenshot_dir in (markdown_path.parent / "screenshots", html_path.parent):
            for screenshot_path in screenshot_dir.glob("*.png"):
                if screenshot_path.name not in expected_filenames:
                    screenshot_path.unlink()


def refresh_gallery(html_path: Path) -> None:
    """Apply current presentation to published capture content without changing provenance."""
    document = html_path.read_text(encoding="utf-8")
    header = re.search(r"<header>.*?</header>", document, re.DOTALL)
    sections = re.search(r"<main>(.*?)</main>", document, re.DOTALL)
    if not header or not sections:
        raise SystemExit("Published screenshot gallery is missing its capture header or content")
    content = sections[1]
    content = re.sub(
        r"<article><h2>(.*?)</h2>",
        lambda match: f'<article id="{re.sub(r"[^a-z0-9]+", "-", html.unescape(match[1]).lower()).strip("-")}"><h2>{match[1]}</h2>',
        content,
        flags=re.DOTALL,
    )
    for profile in CAPTURE_PROFILES:
        # Galleries published before the switcher used classes alone.
        content = content.replace(
            f'<figure class="shot shot-{profile}">',
            f'<figure class="shot shot-{profile}" data-profile="{profile}">',
        )
    # Targeted captures can introduce a view before the next full gallery run.
    # Keep their own source revision instead of relabeling older screenshots.
    manifest = json.loads(html_path.with_name("build.json").read_text())
    manual = manifest.get("manual_captures", {})
    refreshed = []
    for filename, capture in manual.items():
        if not filename.endswith("-desktop.png") or not capture.get("source_path"):
            continue
        view = filename.removesuffix("-desktop.png")
        title = html.escape(capture["name"])
        figures = []
        for profile, (width, height) in CAPTURE_PROFILES.items():
            image = f"{view}-{profile}.png"
            if image not in manual or not html_path.with_name(image).is_file():
                raise SystemExit(f"missing manual capture: {image}")
            url = f"./{image}?v={manifest['files'][image][:12]}"
            figures.append(
                f'<figure class="shot shot-{profile}" data-profile="{profile}">'
                f'<figcaption>{profile.title()} ({width}x{height})</figcaption><a href="{url}">'
                f'<img src="{url}" width="{width}" height="{height}" loading="lazy" alt="{title} — {profile}"></a></figure>',
            )
        source = html.escape(f"https://github.com/ArchiveBox/ArchiveBox/blob/{capture['source_revision']}/{capture['source_path']}")
        section = (
            f'<article id="{view}"><h2>{title}</h2><p>'
            f'<a href="{html.escape(capture["url"])}"><code>{html.escape(capture["path"])}</code></a> · '
            f'<a href="{source}">View code</a> · Captured {html.escape(capture["captured_at"])} · '
            f'~{capture["ttfb_ms"]}ms TTFB</p><div class="shots">{"".join(figures)}</div></article>'
        )
        pattern = r'<article id="' + re.escape(view) + r'">.*?</article>'
        content = (
            re.sub(pattern, lambda _: section, content, flags=re.DOTALL) if re.search(pattern, content, re.DOTALL) else content + section
        )
        refreshed.append(f'<a href="#{view}">{title}</a>')
    heading = re.sub(r'<p id="latest-captures">.*?</p>', "", header[0], flags=re.DOTALL)
    if refreshed:
        heading = heading.replace("Generated from ArchiveBox", "Base gallery captured from ArchiveBox")
        heading = heading.replace("Desktop, tablet, and mobile viewports are captured from the same build.", "")
        heading = heading.replace("</header>", f'<p id="latest-captures">Updated views: {" · ".join(refreshed)}</p></header>')
    html_path.write_text(render_gallery(heading, content), encoding="utf-8")


PUBLIC_LANES = {
    **{plugin: (plugin,) for plugin in ("git", "packageregistry", "papersdl", "staticfile", "ytdlp", "iwork")},
    "cad": ("caddl",),
    "boards": ("drawio", "excalidraw", "tldraw"),
    "documents": ("calendar", "liteparse", "opendataloader", "podcast_archiver"),
    "parsers": ("parse_jsonl_urls", "parse_netscape_urls", "parse_rss_urls", "sourcemaps"),
    "web": ("forumdl", "gallerydl"),
    "browser-automation": ("playwright", "puppeteer"),
}
PUBLIC_OWNERS = {plugin: lane for lane, plugins in PUBLIC_LANES.items() for plugin in plugins}


def view_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def public_views(plan):
    views = {lane: set() for lane in PUBLIC_LANES}
    for name, plugin in plan["owned_views"].items():
        if lane := PUBLIC_OWNERS.get(plugin):
            views[lane].add(name)
    return views


def recipes(plan, split):
    moved = {lane: set() for lane in PUBLIC_LANES}
    for example in plan["examples"]:
        names = set(example["plugins"])
        known = names & PUBLIC_OWNERS.keys()
        if split and known:
            owners = {PUBLIC_OWNERS[name] for name in known}
            if len(owners) != 1 or names != known:
                raise ValueError("An anonymous recipe would split a native source across lanes")
            lane = owners.pop()
            url = example["url"]
            for name in known:
                recipe = plan["overrides"][name]
                views = [f"Snapshot View ({name})"] if url == recipe["url"] else []
                views.extend(output["name"] for output in recipe.get("outputs", ()) if output.get("url", recipe["url"]) == url)
                if moved[lane].intersection(views):
                    raise ValueError(f"Anonymous lane captures a view more than once: {lane}")
                moved[lane].update(views)
            continue
        yield ",".join(example["plugins"]) + "|" + example["url"]
    if split and moved != public_views(plan):
        raise ValueError("Anonymous recipe partition no longer covers the exact public gallery views")


def identity():
    return {
        **{key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "pins": {package: version(package) for package in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")},
    }


def read_rows(manifest):
    return [json.loads(line) for line in manifest.read_text().splitlines()]


def unavailable_recipe_outcomes(unavailable, captured_names):
    if not unavailable:
        return {}
    plan = plugin_screenshot_plan()
    owners = plan["owned_views"]
    recipes = {
        name
        for owner, recipe in plan["overrides"].items()
        for name in supplementary_recipe_views(recipe, owner)
        if owners.get(name) == owner
    }
    names = set(unavailable)
    if (
        len(names) != len(unavailable)
        or names - recipes
        or names & REQUIRED_VIEW_NAMES
        or {view_slug(name) for name in names} & {view_slug(name) for name in captured_names}
    ):
        raise ValueError("Invalid or overlapping unavailable plugin views")
    result = {}
    for name in unavailable:
        key = "recipe-" + hashlib.sha256(f"{owners[name]}:{name}".encode()).hexdigest()[:16]
        result[key] = {"status": "unavailable", "views": [view_slug(name)]}
    if len(result) != len(names) or len({view_slug(name) for name in names}) != len(names):
        raise ValueError("Colliding unavailable views")
    return result


def unavailable_names(path):
    return path.read_text(encoding="utf-8").splitlines() if path is not None else []


def validate(lane, rows, root, digests, unavailable=()):
    filenames = set()
    views = {}
    for row in rows:
        name, profile, filename = (row[key] for key in ("name", "profile", "filename"))
        if (
            profile not in CAPTURE_PROFILES
            or not re.fullmatch(r"[a-z0-9-]+\.png", filename)
            or filename != f"{view_slug(name)}-{profile}.png"
        ):
            raise ValueError(f"Invalid capture filename or profile: {filename}")
        if filename in filenames or profile in views.setdefault(name, set()):
            raise ValueError(f"Duplicate capture: {filename}")
        views[name].add(profile)
        filenames.add(filename)
        image = root / filename
        if not image.is_file() or image.is_symlink():
            raise ValueError(f"Missing or invalid PNG file: {filename}")
        data = image.read_bytes()
        expected = CAPTURE_PROFILES[profile]
        if (
            len(data) < 24
            or data[:8] != PNG_HEADER
            or struct.unpack(">II", data[16:24]) != expected
            or (row["width"], row["height"]) != expected
            or hashlib.sha256(data).hexdigest() != digests[filename]
        ):
            raise ValueError(f"Invalid capture dimensions or checksum: {filename}")
    unavailable_recipe_outcomes(unavailable, views)
    if (
        (not views and (lane == "base" or not unavailable))
        or filenames != digests.keys()
        or any(profiles != CAPTURE_PROFILES.keys() for profiles in views.values())
    ):
        raise ValueError(f"Incomplete viewport manifest: {lane}")
    expected_views = public_views(plugin_screenshot_plan())
    if lane == "base":
        if (views.keys() | set(unavailable)) & set().union(*expected_views.values()):
            raise ValueError("Public recipe view was captured twice")
    else:
        expected = expected_views[lane]
        if views.keys() | set(unavailable) != expected:
            raise ValueError(f"Public lane did not capture its exact view: {lane}")


def pack(lane, manifest, screenshot_root, bundle, unavailable=()):
    build = json.loads((screenshot_root / "build.json").read_text())
    current = identity()
    if build["revision"] != current["GITHUB_SHA"] or build["capture_count"] != len(build["files"]):
        raise ValueError("Native build differs from checked-out source or is incomplete")
    rows = read_rows(manifest)
    validate(lane, rows, screenshot_root, build["files"], unavailable)
    if build.get("optional_recipe_captures", {}) != unavailable_recipe_outcomes(unavailable, {row["name"] for row in rows}):
        raise ValueError("Native render and capture availability differ")
    validate_optional_recipe_captures(screenshot_root, build)
    bundle.mkdir()
    for name in build["files"]:
        shutil.copyfile(screenshot_root / name, bundle / name)
    shutil.copyfile(manifest, bundle / "capture.jsonl")
    receipt = {"identity": current, "lane": lane, "files": build["files"], "unavailable": list(unavailable)}
    (bundle / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def merge(artifact_root, output, manifest, unavailable_out=None):
    current = identity()
    attempt = current["GITHUB_RUN_ATTEMPT"]
    lanes = ("base", *PUBLIC_LANES)
    bundles = {lane: artifact_root / f"gallery-capture-{attempt}-{lane}" for lane in lanes}
    expected_names = {bundle.name for bundle in bundles.values()}
    if {path.name for path in artifact_root.iterdir()} != expected_names:
        raise ValueError("Unexpected or missing capture artifacts")
    all_files = {}
    all_rows = []
    unavailable = []
    for lane, bundle in bundles.items():
        receipt = json.loads((bundle / "receipt.json").read_text())
        if set(receipt) != {"identity", "lane", "files", "unavailable"} or receipt["identity"] != current or receipt["lane"] != lane:
            raise ValueError(f"Mixed capture provenance: {lane}")
        files = receipt["files"]
        rows = read_rows(bundle / "capture.jsonl")
        missing = receipt["unavailable"]
        if not isinstance(missing, list) or any(not isinstance(name, str) for name in missing) or (missing and unavailable_out is None):
            raise ValueError("Unexpected unavailable plugin views")
        validate(lane, rows, bundle, files, missing)
        unavailable.extend(missing)
        if {path.name for path in bundle.iterdir()} != files.keys() | {"capture.jsonl", "receipt.json"}:
            raise ValueError(f"Unexpected native capture files: {lane}")
        if all_files.keys() & files.keys():
            raise ValueError(f"Duplicate gallery file: {lane}")
        all_files.update({name: bundle / name for name in files})
        all_rows.extend(rows)
    unavailable_recipe_outcomes(unavailable, {row["name"] for row in all_rows})
    if unavailable_out is not None:
        unavailable_out.write_text("".join(f"{name}\n" for name in unavailable), encoding="utf-8")
    output.mkdir()
    for name, source in all_files.items():
        shutil.copyfile(source, output / name)
    manifest.write_text("".join(json.dumps(row) + "\n" for row in all_rows))


def pages_artifacts():
    # The Pages client is shared with the website deployment scripts.
    pages = str(REPO_DIR / ".github/pages")
    sys.path.insert(0, pages)
    try:
        import artifacts
    finally:
        sys.path.remove(pages)
    return artifacts


# Repository-specific capture contract.
REPO = "ArchiveBox/ArchiveBox"
BRANCH = "dev"
BASE = "https://archivebox.io/screenshots/"
MANIFEST = "build.json"
GALLERY_VIEW_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def capture_revision_order(repo_dir):
    # Use immutable source ancestry, not upload time: an older manual capture
    # can finish after a newer automatic capture. Fail closed on shallow clones.
    shallow = subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], cwd=repo_dir, text=True).strip()
    if shallow != "false":
        raise ValueError("Screenshot source ordering requires complete Git history")
    revisions = subprocess.check_output(["git", "rev-list", "--topo-order", "HEAD"], cwd=repo_dir, text=True).splitlines()
    return {revision: rank for rank, revision in enumerate(revisions)}


def validate_optional_provider_captures(destination, manifest):
    # Older published artifacts did not record provider availability.
    if "optional_provider_captures" not in manifest:
        return
    outcomes = manifest["optional_provider_captures"]
    if (
        not isinstance(outcomes, dict)
        or not outcomes
        or any(not GALLERY_VIEW_SLUG.fullmatch(provider) for provider in outcomes)
        or any(status not in ("captured", "unavailable") for status in outcomes.values())
    ):
        raise ValueError("Invalid optional provider capture outcomes")
    for provider, status in outcomes.items():
        names = {f"snapshot-view-{provider}-{profile}.png" for profile in CAPTURE_PROFILES}
        present = names.intersection(manifest["files"])
        if status == "captured" and present != names:
            raise ValueError(f"Incomplete optional provider capture: {provider}")
        if status == "unavailable" and (
            present or any((destination / name).exists() or (destination / name).is_symlink() for name in names)
        ):
            raise ValueError(f"Unavailable provider includes screenshot files: {provider}")


def validate_optional_recipe_captures(destination, manifest):
    if "optional_recipe_captures" not in manifest:
        return
    outcomes = manifest["optional_recipe_captures"]
    if not isinstance(outcomes, dict) or "optional_provider_captures" in manifest:
        raise ValueError("Invalid optional gallery recipe outcomes")
    seen_views = set()
    for recipe, outcome in outcomes.items():
        if (
            not re.fullmatch(r"recipe-[a-f0-9]{16}", recipe)
            or not isinstance(outcome, dict)
            or set(outcome) != {"status", "views"}
            or outcome["status"] not in ("captured", "unavailable")
            or not isinstance(outcome["views"], list)
            or not outcome["views"]
            or any(not isinstance(view, str) or not GALLERY_VIEW_SLUG.fullmatch(view) for view in outcome["views"])
            or outcome["views"] != sorted(set(outcome["views"]))
            or seen_views.intersection(outcome["views"])
        ):
            raise ValueError("Invalid optional gallery recipe outcome")
        seen_views.update(outcome["views"])
        for view in outcome["views"]:
            names = {f"{view}-{profile}.png" for profile in CAPTURE_PROFILES}
            present = names.intersection(manifest["files"])
            if outcome["status"] == "captured" and present != names:
                raise ValueError(f"Incomplete optional gallery recipe capture: {recipe}")
            if outcome["status"] == "unavailable" and (
                present or any((destination / name).exists() or (destination / name).is_symlink() for name in names)
            ):
                raise ValueError(f"Unavailable gallery recipe includes screenshot files: {recipe}")


def validate_published_gallery(destination, run=None):
    artifacts = pages_artifacts()
    manifest = json.loads((destination / MANIFEST).read_text())
    if run and manifest["revision"] != run["head_sha"]:
        raise ValueError("Screenshot revision differs from the original capture run")
    if not manifest.get("files") or len(manifest["files"]) != manifest["capture_count"]:
        raise ValueError("Incomplete screenshot manifest")
    validate_optional_provider_captures(destination, manifest)
    validate_optional_recipe_captures(destination, manifest)
    for name, expected in manifest["files"].items():
        image = destination / artifacts.relative_path(name)
        if hashlib.sha256(image.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Screenshot checksum mismatch: {name}")
    if not (destination / "index.html").is_file():
        raise ValueError("Missing gallery content for the current renderer")
    return manifest


def capture_meets_published_floor(revision, published, revision_order, *, repo_dir):
    published_revision = published["revision"]
    if published_revision not in revision_order:
        raise ValueError("Published screenshot source is outside the checked-out Core lineage")
    if revision not in revision_order:
        return False
    # Both sides of a merge belong to Core history, but a topological rank
    # alone cannot prove that one side includes the other's published changes.
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", published_revision, revision], cwd=repo_dir, check=False)
    if ancestry.returncode not in (0, 1):
        ancestry.check_returncode()
    return ancestry.returncode == 0


def normalize_filenames(destination):
    """Migrate older capture artifacts to order-independent public filenames."""
    manifest_path = destination / MANIFEST
    manifest = validate_published_gallery(destination)
    names = {name: re.sub(r"^\d+-", "", name) for name in manifest["files"]}
    if len(set(names.values())) != len(names):
        raise ValueError("Screenshot names collide after removing capture-order prefixes")
    gallery_path = destination / "index.html"
    gallery = gallery_path.read_text()
    for old, new in names.items():
        if old != new:
            (destination / old).replace(destination / new)
            gallery = gallery.replace(f"./{old}", f"./{new}")
    manifest["files"] = {names[name]: digest for name, digest in manifest["files"].items()}
    gallery_path.write_text(gallery)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    validate_published_gallery(destination)


def restore_gallery(destination):
    artifacts = pages_artifacts()
    destination.mkdir(parents=True, exist_ok=True)
    # An expired artifact must not let an older manual re-capture replace the
    # already-published gallery. Unknown/unavailable provenance fails closed.
    raw = artifacts.fetch(BASE, MANIFEST)
    manifest = json.loads(raw)
    if os.environ.get("GH_TOKEN"):
        repo_dir = Path(__file__).resolve().parents[1]
        revision_order = capture_revision_order(repo_dir)
        for run in artifacts.runs(REPO, "screenshots.yml", BRANCH, revision_order=revision_order):
            if not capture_meets_published_floor(run["head_sha"], manifest, revision_order, repo_dir=repo_dir):
                continue
            if "site-screenshots" not in artifacts.names(REPO, run):
                continue
            artifacts.download(REPO, run, "site-screenshots", destination)
            validate_published_gallery(destination, run)
            normalize_filenames(destination)
            print(f"Restored validated screenshots from {run['id']} ({run['head_sha']})")
            return
    names = [*manifest["files"], "index.html"]

    def restore(name):
        target = destination / artifacts.relative_path(name)
        data = artifacts.fetch(BASE, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, names))
    (destination / MANIFEST).write_bytes(raw)
    validate_published_gallery(destination)
    normalize_filenames(destination)
    print(f"Restored {len(names)} published files from {manifest['revision']}")


def serve_exports(port, directory):
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    import django
    from django.conf import settings
    from django.core.handlers.wsgi import WSGIHandler
    from django.http import HttpResponseNotAllowed
    from django.urls import re_path

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
    django.setup()
    from archivebox.misc.serve_static import serve_static_with_byterange_support

    export_directory = directory.resolve(strict=True)

    def serve_export(request, path=""):
        if request.method not in {"GET", "HEAD"}:
            return HttpResponseNotAllowed(["GET", "HEAD"])
        request.GET = request.GET.copy()
        request.GET["raw"] = "1"
        if not path or path.endswith("/"):
            path += "index.html"
        return serve_static_with_byterange_support(request, path, document_root=export_directory)

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    settings.ROOT_URLCONF = (re_path(r"^(?P<path>.*)$", serve_export),)
    settings.MIDDLEWARE = []
    settings.ALLOWED_HOSTS = ["127.0.0.1"]
    with make_server("127.0.0.1", port, WSGIHandler(), server_class=ThreadingWSGIServer) as server:
        print(f"Serving gallery exports on http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


PHASES = {
    "navigate": "on_Snapshot__30_chrome_navigate",
    "singlefile": "on_Snapshot__50_singlefile",
    "screenshot": "on_Snapshot__51_screenshot",
    "canva": "on_Snapshot__53_canva",
    "responses": "on_Snapshot__24_responses.daemon.bg",
    "tab": "on_Snapshot__01_chrome_tab.daemon.bg",
}


def safe_text(path):
    if path.is_file() and not path.is_symlink():
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 2 * 1024**2))
            return stream.read().decode(errors="replace")
    return ""


def phase_metrics(text):
    phases = {}
    for name, hook in PHASES.items():
        matches = re.findall(
            rf"(?m)^\s*{re.escape(hook)}\s+(succeeded|failed|noresults|skipped)\s+[^\n]*?\b(\d+(?:\.\d+)?)s/\d+s\b",
            text,
        )
        if matches:
            status, seconds = matches[-1]
            phases[name] = {"status": status, "elapsed_seconds": float(seconds)}
    return phases


def signals(text):
    return {
        "navigation_200": bool(re.search(r"page loaded http=200\b", text)),
        "singlefile_download_timeout": bool(re.search(r"SingleFile download for tab \d+ did not complete", text)),
        "renderer_crashed": "renderer crashed" in text.lower(),
        "unexpected_target_close": "closed unexpectedly" in text.lower(),
        "missing_target_marker": "target_id.txt" in text
        and bool(re.search(r"(?:No target_id\.txt found|target_id\.txt is missing)", text)),
        "tab_sigterm": "Received SIGTERM, closing chrome tab" in text,
    }


def read_counter(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def memory():
    matches = re.findall(r"(?m)^0::(.*)$", read_counter(Path("/proc/self/cgroup")))
    root = (Path("/sys/fs/cgroup") / matches[0].lstrip("/")) if matches else Path("/sys/fs/cgroup")
    result = {}
    for name in ("memory.peak", "memory.swap.peak"):
        text = read_counter(root / name).strip()
        if text.isdecimal():
            result[name] = int(text)
    for key, value in re.findall(r"(?m)^(oom|oom_kill|oom_group_kill) (\d+)$", read_counter(root / "memory.events")):
        result[key] = int(value)
    return result


def verified_canva_images(directory):
    manifest = directory / "build.json"
    if not manifest.is_file():
        return {}
    build = json.loads(manifest.read_text())
    files = build["files"]
    expected = {f"snapshot-view-canva-{profile}.png": dimensions for profile, dimensions in CAPTURE_PROFILES.items()}
    if files.keys() != expected.keys() or build["revision"] != os.environ["GITHUB_SHA"]:
        return {}
    for name, dimensions in expected.items():
        image = (directory / name).read_bytes()
        if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", image[16:24]) != dimensions:
            return {}
        if hashlib.sha256(image).hexdigest() != files[name]:
            return {}
    return files


def summarize_canva(root):
    if not root.is_dir():
        return 1
    logs = [safe_text(root / "collector.log"), safe_text(root / "capture.log")]
    for pattern in (
        "**/canva-supplementary-capture.log",
        "**/on_Snapshot__01_chrome_tab*.stderr.log",
        "**/on_Snapshot__50_singlefile*.stderr.log",
    ):
        logs.extend(safe_text(path) for path in sorted((root / "failure").glob(pattern))[:4])
    text = "\n".join(logs)
    status = safe_text(root / "exit-code").strip()
    timestamps = {}
    for name in ("start", "end"):
        value = safe_text(root / name).strip()
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
            timestamps[name] = value
    signs = {
        (match, int(code))
        for match, code in re.findall(
            r"target_crash status=(normal|abnormal|killed|crashed|oom|launch-failed|integrity-failure|still-running|unknown) error_code=(-?\d+)",
            text,
        )
    }
    digests = verified_canva_images(root / "png")
    report = {
        "revision": os.environ["GITHUB_SHA"],
        "start_end": timestamps,
        "exit_status": int(status) if status.isdecimal() else None,
        "phases": phase_metrics(text),
        "signals": signals(text),
        "target_crash_diagnostics": [{"status": name, "error_code": code} for name, code in sorted(signs)],
        "memory": memory(),
        "validated_canva_png_sha256": digests,
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if status == "0" and len(digests) == len(CAPTURE_PROFILES) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plugin-plan")
    capture = commands.add_parser("capture-add")
    capture.add_argument("plan", type=Path)
    capture.add_argument("scoped", choices=("0", "1"))
    capture.add_argument("plugins")
    capture.add_argument("url")
    commands.add_parser("refresh").add_argument("html", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("metadata", type=Path)
    validate.add_argument("expected_path")
    append = commands.add_parser("append")
    append.add_argument("manifest", type=Path)
    append.add_argument("screenshot", type=Path)
    build = commands.add_parser("build")
    build.add_argument("manifest", type=Path)
    build.add_argument("markdown", type=Path)
    build.add_argument("html", type=Path)
    build.add_argument("--unavailable", type=Path)
    commands.add_parser("restore").add_argument("destination", type=Path)
    commands.add_parser("summarize-canva").add_argument("directory", type=Path)
    serve = commands.add_parser("serve-exports")
    serve.add_argument("port", type=int)
    serve.add_argument("--directory", type=Path, required=True)
    recipe_parser = commands.add_parser("recipes")
    recipe_parser.add_argument("plan", type=Path)
    recipe_parser.add_argument("split", choices=("0", "1"))
    pack_parser = commands.add_parser("pack")
    pack_parser.add_argument("lane", choices=("base", *PUBLIC_LANES))
    pack_parser.add_argument("manifest", type=Path)
    pack_parser.add_argument("screenshot_root", type=Path)
    pack_parser.add_argument("bundle", type=Path)
    pack_parser.add_argument("--unavailable", type=Path)
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("artifacts", type=Path)
    merge_parser.add_argument("output", type=Path)
    merge_parser.add_argument("manifest", type=Path)
    merge_parser.add_argument("--unavailable-out", type=Path)
    args = parser.parse_args()
    if args.command == "plugin-plan":
        print(json.dumps(plugin_screenshot_plan()))
    elif args.command == "capture-add":
        capture_add(json.loads(args.plan.read_text()), list(filter(None, args.plugins.split(","))), args.url, scoped=args.scoped == "1")
    elif args.command == "refresh":
        refresh_gallery(args.html)
    elif args.command == "validate":
        validate_navigation(args.metadata, args.expected_path)
    elif args.command == "append":
        append_manifest(args.manifest, args.screenshot)
    elif args.command == "build":
        build_galleries(args.manifest, args.markdown, args.html, unavailable_names(args.unavailable))
    elif args.command == "restore":
        restore_gallery(args.destination)
    elif args.command == "serve-exports":
        serve_exports(args.port, args.directory)
    elif args.command == "summarize-canva":
        return summarize_canva(args.directory)
    elif args.command == "recipes":
        print(*recipes(json.loads(args.plan.read_text()), args.split == "1"), sep="\n")
    elif args.command == "pack":
        pack(args.lane, args.manifest, args.screenshot_root, args.bundle, unavailable_names(args.unavailable))
    elif args.command == "merge":
        merge(args.artifacts, args.output, args.manifest, args.unavailable_out)


if __name__ == "__main__":
    sys.exit(main())
