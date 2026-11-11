"""Real provider-backed gallery preparation; never manufactures model output."""

import re
import os
import subprocess
import time
from pathlib import Path
from html import unescape
from urllib.parse import urlsplit

import requests

from .screenshots import authenticated_session, hidden_value


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


def prepare(admin_base_url, username, password, *, model, data_dir, project_dir, source_urls=None):
    if not model or not model.startswith("openai/"):
        raise ValueError("Set UI_SCREENSHOT_AI_MODEL to an explicitly configured openai/model for real gallery enrichment.")
    collection = Path(data_dir).resolve()
    project = Path(project_dir).resolve()
    if collection == project or not (collection / "index.sqlite3").is_file():
        raise ValueError("AI gallery worker requires an explicit initialized collection outside the source checkout.")
    configure_provider(model, collection)
    session = authenticated_session(admin_base_url, username, password)
    url = f"{admin_base_url}/admin/automation/ai/"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = {
        "csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"),
        "model": model,
        "apply_tags": "on",
        "language": "English",
        "tag_style": "as_generated",
        "allowed_tags": "",
        "instructions": "Use concise English summaries and topic tags.",
    }
    response = session.post(url, data=payload, headers={"Referer": url}, timeout=30)
    response.raise_for_status()
    options = re.findall(r'<option value="([0-9a-f-]+)">([^<]+)</option>', response.text)
    if source_urls is not None:
        if "https://news.ycombinator.com/" not in source_urls or len(source_urls) < 3:
            raise ValueError("AI gallery source URLs must include the real HN homepage and at least two captured stories.")
        # The UI orders captures newest first. Select exactly one current capture
        # per requested URL; unrelated saved pages must never reach the provider.
        by_url = {}
        for value, text in options:
            option_url = unescape(text).rsplit(" — ", 1)[-1]
            if option_url in source_urls:
                by_url.setdefault(option_url, value)
        if set(source_urls) != set(by_url):
            raise RuntimeError("The latest completed-capture picker is missing one or more requested gallery URLs.")
        options = [(by_url[url], url) for url in source_urls]
    homepage = [value for value, text in options if unescape(text).endswith("https://news.ycombinator.com/")]
    stories = [value for value, text in options if "news.ycombinator.com" not in text]
    if not homepage or len(stories) < 2:
        raise RuntimeError("AI gallery requires a real captured HN homepage and at least two real story captures.")
    selected = [homepage[0], *stories[:3]]
    response = session.post(
        f"{url}queue/",
        data={"csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"), "snapshots": selected},
        headers={"Referer": url},
        timeout=30,
    )
    response.raise_for_status()
    if f"Queued {len(selected)} captures" not in response.text:
        raise RuntimeError("The real enrichment form did not queue all gallery captures.")
    subprocess.run(
        ["uv", "run", "--no-sync", "--project", str(project), "archivebox", "manage", "automation", "--ai"],
        cwd=collection,
        check=True,
        timeout=700,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = session.get(url, params=[("snapshot", snapshot_id) for snapshot_id in selected], timeout=30)
        response.raise_for_status()
        states = dict(re.findall(r'data-snapshot-id="([0-9a-f-]+)" data-enrichment-status="([a-z]+)"', response.text))
        outcomes = [states.get(snapshot_id) for snapshot_id in selected]
        if "failed" in outcomes:
            raise RuntimeError("An actual selected AI job failed; inspect /admin/automation/ai/ before publishing gallery screenshots.")
        if outcomes and all(status == "succeeded" for status in outcomes):
            from archivebox.core.models import Snapshot
            from archivebox.core.routes_util import build_snapshot_detail_url

            snapshot = Snapshot.objects.get(pk=selected[1])
            return build_snapshot_detail_url(snapshot.archive_path_from_db)
        time.sleep(2)
    raise RuntimeError("AI gallery jobs did not finish within their ten-minute deadline.")


def gallery_entries(admin_base_url, snapshot_url=""):
    entries = [
        f"AI summaries and tags|{admin_base_url}/admin/automation/ai/|/admin/automation/ai/|archivebox/automation/ai_views.py|wait-text:Summarized",
        f"AI preferences|{admin_base_url}/admin/automation/ai/|/admin/automation/ai/|archivebox/automation/templates/automation/ai.html|automation-preferences",
    ]
    if snapshot_url:
        entries.append(
            f"AI snapshot summary|{snapshot_url}|{urlsplit(snapshot_url).path}|archivebox/automation/templates/automation/snapshot_summary.html|snapshot-summary",
        )
    return entries
