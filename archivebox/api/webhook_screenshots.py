"""Prepare gallery subscriptions through the editor's real HTTP endpoints."""

import json
import re
from html import unescape

import requests


def authenticated_session(base_url, username, password):
    session = requests.Session()
    response = session.get(f"{base_url}/admin/login/", timeout=30)
    response.raise_for_status()
    token = unescape(re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text).group(1))
    response = session.post(
        response.url,
        data={"csrfmiddlewaretoken": token, "username": username, "password": password, "next": "/admin/webhooks/"},
        headers={"Referer": response.url},
        timeout=30,
    )
    response.raise_for_status()
    if "/login/" in response.url:
        raise RuntimeError("Gallery login failed")
    token = unescape(re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text).group(1))
    session.headers.update({"X-CSRFToken": token, "Referer": response.url})
    return session


def prepare(base_url, username, password):
    """Create the folder and hooks before normal, full-plugin news captures."""
    session = authenticated_session(base_url, username, password)
    response = session.get(f"{base_url}/admin/webhooks/data/", timeout=30)
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
        response = session.post(f"{base_url}/admin/webhooks/save/", json=hook, timeout=30)
        response.raise_for_status()
        ids.append(response.json()["hook"]["id"])
    return ids


def verify_actions(base_url, username, password, webhook_ids):
    """Update captured news through the REST API and check real action delivery."""
    session = authenticated_session(base_url, username, password)
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
    response = session.get(f"{base_url}/admin/webhooks/data/", timeout=30)
    response.raise_for_status()
    hook = next(item for item in response.json()["hooks"] if item["id"] == webhook_ids[2])
    assert hook["last_success"] and (not hook["last_failure"] or hook["last_success"] > hook["last_failure"])
    return snapshot["id"]


def gallery_entries(base_url, webhook_ids):
    editor = f"{base_url}/admin/webhooks/?webhook={webhook_ids[0]}"
    return [
        f"Webhooks|{base_url}/admin/webhooks/|/admin/webhooks/|archivebox/api/webhook_views.py|wait-text:Hacker News capture settings",
        f"Webhook actions|{editor}|/admin/webhooks/?webhook=…|archivebox/templates/api/webhooks.html|wait-text:Save webhook",
        f"Webhook event input|{editor}&preview=1|/admin/webhooks/?webhook=…&preview=1|archivebox/templates/api/webhooks.html|wait-text:Planned actions",
        f"Webhook activity|{base_url}/admin/webhooks/?view=activity|/admin/webhooks/?view=activity|archivebox/templates/api/webhooks.html|wait-text:Succeeded",
        f"Webhook events|{base_url}/admin/webhooks/?view=events|/admin/webhooks/?view=events|archivebox/templates/api/webhooks.html|wait-text:Before capture",
        f"Webhook scripts|{base_url}/admin/webhooks/?webhook={webhook_ids[2]}|/admin/webhooks/?webhook=…|archivebox/templates/api/webhooks.html|wait-text:JSON stdin",
        f"Webhook process logs|{base_url}/admin/machine/process/?worker_type=webhook&q={webhook_ids[2]}|/admin/machine/process/|archivebox/machine/admin.py|wait-text:webhook",
    ]
