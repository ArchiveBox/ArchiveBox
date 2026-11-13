"""Gallery setup through real HTTP forms against the running screenshot server."""

import re
import json
from html import unescape

import requests


def hidden_value(html, name):
    match = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    if not match:
        raise RuntimeError(f"Missing form field {name}; gallery setup did not reach the real UI.")
    return unescape(match.group(1))


def authenticated_session(admin_base_url, username, password):
    session = requests.Session()
    response = session.get(f"{admin_base_url}/admin/login/", timeout=30)
    response.raise_for_status()
    response = session.post(
        response.url,
        data={
            "csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"),
            "username": username,
            "password": password,
            "next": "/admin/automation/",
        },
        headers={"Referer": response.url},
        timeout=30,
    )
    response.raise_for_status()
    if "/login/" in response.url:
        raise RuntimeError("Gallery login failed.")
    return session


def prepare(admin_base_url, username, password):
    """Save a real HN rule, preview real captures and apply only the shown matches."""
    session = authenticated_session(admin_base_url, username, password)
    response = session.get(f"{admin_base_url}/admin/automation/new/", timeout=30)
    response.raise_for_status()
    payload = {
        "csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"),
        "name": "Hacker News reading list",
        "enabled": "on",
        "position": "0",
        "trigger": "capture",
        "match": "all",
        "add_tags": "Hacker News, Read later",
        "condition-groups": json.dumps({"g1": {"parent": "", "match": "any"}}),
        "conditions-TOTAL_FORMS": "3",
        "conditions-INITIAL_FORMS": "0",
        "conditions-MIN_NUM_FORMS": "0",
        "conditions-MAX_NUM_FORMS": "20",
        "conditions-0-field": "domain",
        "conditions-0-operator": "equals",
        "conditions-0-value": "news.ycombinator.com",
        "conditions-1-group": "g1",
        "conditions-1-field": "title",
        "conditions-1-operator": "contains",
        "conditions-1-value": "Hacker News",
        "conditions-2-group": "g1",
        "conditions-2-field": "url",
        "conditions-2-operator": "contains",
        "conditions-2-value": "item?id=",
    }
    response = session.post(response.url, data=payload, headers={"Referer": response.url}, timeout=30)
    response.raise_for_status()
    token = hidden_value(response.text, "preview")
    rule_id = re.search(r"/automation/([0-9a-f]{32})/preview/", response.url).group(1)
    response = session.post(
        response.url,
        data={"csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"), "preview": token},
        headers={"Referer": response.url},
        timeout=30,
    )
    response.raise_for_status()
    if "Applied rule to" not in response.text:
        raise RuntimeError("Gallery rule did not apply to the real captured data.")
    return rule_id


def gallery_entries(admin_base_url, rule_id=None, capture_rule_ids=None):
    entries = [
        f"Rules|{admin_base_url}/admin/automation/|/admin/automation/|archivebox/automation/views.py|wait-text:Hacker News reading list",
        f"Rule history|{admin_base_url}/admin/automation/history/|/admin/automation/history/|archivebox/automation/views.py|wait-text:Hacker News reading list",
    ]
    if rule_id is not None:
        entries.append(
            f"Rule builder|{admin_base_url}/admin/automation/{rule_id}/|/admin/automation/{rule_id}/|archivebox/automation/templates/automation/edit.html|wait-text:3 · Then",
        )
    if capture_rule_ids:
        capture_id = capture_rule_ids["snapshot"]
        entries.extend(
            [
                f"Capture rules|{admin_base_url}/admin/automation/{capture_id}/|/admin/automation/{capture_id}/|archivebox/automation/templates/automation/edit.html|wait-text:Capture settings",
                f"Capture rule preview|{admin_base_url}/admin/automation/{capture_id}/preview/?url=https%3A%2F%2Fnews.ycombinator.com%2F&tags=depth%3D1&plugins=title%2Cwget%2Creadability%2Cpdf&max_depth=3|/admin/automation/{capture_id}/preview/|archivebox/automation/templates/automation/capture_preview.html|wait-text:Effective capture settings",
            ],
        )
    return entries


def prepare_capture_rules(admin_base_url, username, password):
    """Save schema-backed rules through the same forms used by administrators."""
    session = authenticated_session(admin_base_url, username, password)
    definitions = {
        "crawl": {
            "name": "Crawl depth from tags",
            "trigger": "before_crawl",
            "max_depth": "1",
            "conditions-0-field": "crawl_tag",
            "conditions-0-operator": "equals",
            "conditions-0-value": "depth=1",
        },
        "snapshot": {
            "name": "Hacker News capture settings",
            "trigger": "before_snapshot",
            "config_overrides": json.dumps({"YTDLP_MAX_SIZE": "1256m"}),
            "disable_plugins": "pdf",
            "conditions-0-field": "domain",
            "conditions-0-operator": "in",
            "conditions-0-value": "news.ycombinator.com, example.com",
            "conditions-TOTAL_FORMS": "2",
            "conditions-1-field": "url",
            "conditions-1-operator": "contains",
            "conditions-1-value": "news.ycombinator.com/",
        },
    }
    result = {}
    for name, settings in definitions.items():
        response = session.get(f"{admin_base_url}/admin/automation/new/", timeout=30)
        response.raise_for_status()
        payload = {
            "csrfmiddlewaretoken": hidden_value(response.text, "csrfmiddlewaretoken"),
            "enabled": "on",
            "position": "0",
            "match": "all",
            "condition-groups": "{}",
            "conditions-TOTAL_FORMS": "1",
            "conditions-INITIAL_FORMS": "0",
            "conditions-MIN_NUM_FORMS": "0",
            "conditions-MAX_NUM_FORMS": "20",
            **settings,
        }
        response = session.post(response.url, data=payload, headers={"Referer": response.url}, timeout=30)
        response.raise_for_status()
        match = re.search(r"/automation/([0-9a-f]{32})/preview/", response.url)
        if not match:
            raise RuntimeError(f"Could not save {name} capture rule through the editor: {response.status_code}")
        result[name] = match.group(1)
    return result
