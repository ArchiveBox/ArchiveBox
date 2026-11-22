"""A saved site is a URL-filtered view of snapshots, independent of crawls."""

import re
from urllib.parse import urlsplit

from django.db.models import Q

from archivebox.core.models import Snapshot


def normalize_site_scope(value: str) -> str:
    value = str(value or "").strip()
    if "," in value and "/" in value:
        raise ValueError("Select domains without path prefixes for a multi-domain export.")
    if "," in value:
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


def site_snapshot_q(scopes):
    query = Q(pk__in=[])
    hosts = []
    for value in scopes:
        scope = normalize_site_scope(value)
        if "," in scope:
            hosts.extend(scope.split(","))
            continue
        wildcard = scope.startswith("*.")
        parts = urlsplit("//" + (scope[2:] if wildcard else scope))
        host = ("*." if wildcard else "") + parts.netloc
        prefix = re.escape(parts.path.rstrip("/"))
        if prefix:
            # The host match is case-insensitive and the path match is case-sensitive.
            query |= Snapshot.objects.domain_q(host) & Q(url__regex=rf"^[a-zA-Z]+://[^/?#]+{prefix}(?:/|[?#]|$)")
        else:
            hosts.append(host)
    if hosts:
        query |= Snapshot.objects.domain_q(",".join(hosts))
    return query


def filter_domain_search(queryset, term):
    """Resolve a domain-name search against the current snapshot URLs."""
    from django.db import connections
    from django.db.models import CharField, Func
    from archivebox.core.domain_index import group_host

    term = term.strip().casefold()
    if connections[queryset.db].vendor == "sqlite":
        matches = queryset.alias(live_domain=Func("url", function="archivebox_domain_group", output_field=CharField()))
        return matches.filter(live_domain__contains=term) if term else matches.exclude(live_domain="")
    candidates = queryset.with_hostname()
    if not term:
        return candidates
    hosts = candidates.order_by("_domain_host").values_list("_domain_host", flat=True).distinct().iterator(chunk_size=1000)
    scopes = {scope for domain, scope in (group_host(host) for host in hosts) if term in domain}
    return candidates.filter(site_snapshot_q(sorted(scopes)))


def site_snapshots(scope: str):
    return Snapshot.objects.filter(site_snapshot_q([scope]))


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
