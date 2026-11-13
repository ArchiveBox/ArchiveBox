"""A saved site is a URL-filtered view of snapshots, independent of crawls."""

import re
from urllib.parse import urlsplit

from archivebox.core.models import Snapshot


def normalize_site_scope(value: str) -> str:
    value = str(value or "").strip()
    if "," in value and "/" not in value:
        return ",".join(sorted({normalize_site_scope(part) for part in value.split(",")}))
    wildcard = value.startswith("*.")
    candidate = value[2:] if wildcard else value
    try:
        parts = urlsplit(candidate if "://" in candidate else "//" + candidate)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port
    except (ValueError, UnicodeError) as error:
        raise ValueError("Enter a domain or an HTTP URL prefix.") from error
    if (
        not host
        or parts.scheme not in {"", "http", "https"}
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not re.fullmatch(r"[a-z0-9_.-]+|[0-9a-f:]+", host)
        or ".." in host
        or (wildcard and ":" in host)
    ):
        raise ValueError("Enter a domain or URL prefix without credentials, query or fragment.")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    return ("*." if wildcard else "") + authority + parts.path.rstrip("/")


def crawl_site_scope(crawl) -> str:
    seed = next((line.strip() for line in crawl.urls.splitlines() if line.strip()), "")
    parts = urlsplit(seed)
    scope = parts.netloc
    # DomainCrawlForm stores this host boundary in the native allow/deny filters.
    if any("(?:[a-zA-Z0-9-]+\\.)*" in str(crawl.config.get(key, "")) for key in ("URL_ALLOWLIST", "URL_DENYLIST")):
        scope = "*." + scope
    return normalize_site_scope(scope)


def site_snapshots(scope: str):
    scope = normalize_site_scope(scope)
    if "," in scope and "/" not in scope:
        return Snapshot.objects.filter_by_domain(scope)
    wildcard = scope.startswith("*.")
    parts = urlsplit("//" + (scope[2:] if wildcard else scope))
    prefix = re.escape(parts.path.rstrip("/"))
    snapshots = Snapshot.objects.filter_by_domain(("*." if wildcard else "") + parts.netloc)
    # Keep path matching case-sensitive without scoped inline regex flags,
    # which PostgreSQL's ARE syntax does not support.
    if prefix:
        snapshots = snapshots.filter(url__regex=rf"^[a-zA-Z]+://[^/?#]+{prefix}(?:/|\?|#|$)")
    return snapshots


def site_snapshot_filters(scope: str):
    from django.http import QueryDict

    scope = normalize_site_scope(scope)
    query = QueryDict(mutable=True)
    if "," in scope and "/" not in scope:
        query["domain"] = scope
        return query
    wildcard = scope.startswith("*.")
    parts = urlsplit("//" + (scope[2:] if wildcard else scope))
    query["domain"] = ("*." if wildcard else "") + parts.netloc
    prefix = re.escape(parts.path.rstrip("/"))
    if prefix:
        query["url__regex"] = rf"^[a-zA-Z]+://[^/?#]+{prefix}(?:/|\?|#|$)"
    return query
