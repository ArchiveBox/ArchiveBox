"""Portable browser-state editing and value-free Persona summaries."""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django import forms

from archivebox.misc.system import atomic_write
from archivebox.personas.importers import _merge_auth_storage, _merge_netscape_cookies, _parse_netscape_cookies


def validate_cookies(text):
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) != 7 or not parts[0] or not parts[2].startswith("/") or not parts[5]:
            raise forms.ValidationError(f"Line {number}: use Netscape cookies.txt format with seven tab-separated columns.")
        if parts[1] not in {"TRUE", "FALSE"} or parts[3] not in {"TRUE", "FALSE"} or not parts[4].isdigit():
            raise forms.ValidationError(f"Line {number}: check the cookie flags and expiry timestamp.")


def validate_auth(text):
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise forms.ValidationError("Enter valid auth.json or Playwright storage-state JSON.")
    if not isinstance(payload, dict):
        raise forms.ValidationError("Auth JSON must be an object.")
    for key in ("cookies", "origins", "tabs"):
        if key in payload and not isinstance(payload[key], list):
            raise forms.ValidationError(f"{key} must be a list.")
    for cookie in payload.get("cookies", []):
        if not isinstance(cookie, dict) or any(not isinstance(cookie.get(key), str) for key in ("domain", "name", "value")):
            raise forms.ValidationError("Each cookie needs a domain, name, and value.")
    for key in ("localStorage", "sessionStorage"):
        if key in payload and not isinstance(payload[key], dict):
            raise forms.ValidationError(f"{key} must map origins to stored entries.")
    for origin in payload.get("origins", []):
        if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str):
            raise forms.ValidationError("Each storage origin needs an origin URL.")
        for key in ("localStorage", "sessionStorage"):
            if key in origin and (not isinstance(origin[key], list) or any(not isinstance(entry, dict) for entry in origin[key])):
                raise forms.ValidationError(f"Origin {key} must be a list of entries.")
    if any(not isinstance(tab, dict) or not isinstance(tab.get("url"), str) for tab in payload.get("tabs", [])):
        raise forms.ValidationError("Each tab needs a URL.")
    return payload


class PersonaStateForm(forms.Form):
    artifact = forms.ChoiceField(choices=(("cookies", "Cookies"), ("auth", "Auth storage")))
    action = forms.ChoiceField(choices=(("merge", "Merge"), ("clear", "Clear")))
    payload = forms.CharField(required=False, strip=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "merge":
            payload = cleaned.get("payload", "")
            if not payload.strip():
                self.add_error("payload", "Paste or upload browser state to add.")
            elif cleaned.get("artifact") == "cookies":
                validate_cookies(payload)
            elif cleaned.get("artifact") == "auth":
                validate_auth(payload)
        return cleaned

    def apply(self, persona):
        artifact = self.cleaned_data["artifact"]
        path = persona.path / ("cookies.txt" if artifact == "cookies" else "auth.json")
        if self.cleaned_data["action"] == "clear":
            contents = "" if artifact == "cookies" else "{}\n"
        else:
            existing = path.read_text() if path.exists() else ("" if artifact == "cookies" else "{}")
            (validate_cookies if artifact == "cookies" else validate_auth)(existing)
            # Existing import helpers do the same merge for browser imports. Work
            # on temporary files, then atomically publish the completed artifact.
            with tempfile.TemporaryDirectory(prefix="archivebox-persona-state-") as directory:
                merged = Path(directory) / "existing"
                incoming = Path(directory) / "incoming"
                merged.write_text(existing)
                incoming.write_text(self.cleaned_data["payload"])
                (_merge_netscape_cookies if artifact == "cookies" else _merge_auth_storage)(merged, incoming)
                contents = merged.read_text()
        persona.ensure_dirs()
        atomic_write(path, contents)


def browser_state_summary(persona):
    """Only counts, domain names, file sizes, and timestamps cross into HTML."""
    cards = []
    profile_root = persona.path / "chrome_profile"
    profile = {"key": "profile", "title": "Browser profile", "icon": "◉", "count": 0, "unit": "profiles", "domains": []}
    try:
        profiles = [
            path
            for path in [profile_root, *profile_root.glob("*")]
            if path.is_dir() and any((path / marker).exists() for marker in ("Preferences", "Cookies", "Network/Cookies"))
        ]
        profile["count"] = len(profiles)
        domains, cookies, updated = set(), 0, 0
        for directory in profiles:
            for database in (directory / "Cookies", directory / "Network" / "Cookies"):
                if not database.exists():
                    continue
                with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.1) as connection:
                    cookies += connection.execute("SELECT count(*) FROM cookies").fetchone()[0]
                    domains.update(row[0].lstrip(".") for row in connection.execute("SELECT DISTINCT host_key FROM cookies"))
                updated = max(updated, database.stat().st_mtime)
        profile.update(
            detail=f"{cookies} cookies · {len(domains)} sites",
            domains=sorted(domains)[:5],
            updated=datetime.fromtimestamp(updated, timezone.utc) if updated else None,
        )
    except (OSError, sqlite3.Error):
        profile["detail"] = "Cookie summary unavailable"
    cards.append(profile)
    for key, filename, title, icon in (("cookies", "cookies.txt", "Cookies", "◌"), ("auth", "auth.json", "Browser storage", "▤")):
        path = persona.path / filename
        card = {
            "key": key,
            "title": title,
            "icon": icon,
            "count": 0,
            "unit": "cookies" if key == "cookies" else "origins",
            "domains": [],
            "detail": "Netscape cookie file" if key == "cookies" else "Local storage · Session storage · Cookies",
        }
        try:
            if path.exists():
                stat = path.stat()
                card.update(size=stat.st_size, updated=datetime.fromtimestamp(stat.st_mtime, timezone.utc))
                if key == "cookies":
                    validate_cookies(path.read_text())
                    cookies = _parse_netscape_cookies(path)
                    domains = {domain.lstrip(".") for domain, _, _ in cookies}
                    card.update(count=len(cookies), domains=sorted(domains)[:5], detail=f"{len(domains)} sites · Netscape format")
                else:
                    payload = validate_auth(path.read_text() or "{}")
                    origins = (
                        set(payload.get("localStorage", {}))
                        | set(payload.get("sessionStorage", {}))
                        | {item["origin"] for item in payload.get("origins", [])}
                    )
                    cookies = payload.get("cookies", [])
                    from urllib.parse import urlsplit

                    domains = {urlsplit(origin).hostname for origin in origins} | {cookie["domain"].lstrip(".") for cookie in cookies}
                    card.update(
                        count=len(origins),
                        domains=sorted(domain for domain in domains if domain)[:5],
                        detail=f"{len(cookies)} cookies · {len(origins)} storage origins",
                    )
        except (OSError, ValueError, forms.ValidationError):
            card["detail"] = "Summary unavailable"
        cards.append(card)
    return cards
