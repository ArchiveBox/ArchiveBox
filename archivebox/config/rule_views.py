"""Stateless helpers for composing and previewing the existing crawl URL rules."""

import json
import re
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from archivebox.crawls.models import Crawl


def compose_url_rules(entries: str, mode: str) -> str:
    if mode not in {"domain", "subdomains", "path", "descendants"}:
        raise ValueError("Choose a domain or path match.")
    patterns = []
    for entry in Crawl.split_filter_patterns(entries):
        parsed = urlsplit(entry if "://" in entry else f"https://{entry}")
        hostname = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not hostname or re.search(r"[\s/?#@]", hostname) or parsed.username is not None:
            raise ValueError(f"Enter a domain or HTTP URL: {entry}")
        # Accessing .port validates its range and rejects nonnumeric port values.
        port = parsed.port
        hostname = hostname.encode("idna").decode("ascii")
        if ":" in hostname:
            if mode == "subdomains":
                raise ValueError("IP addresses do not have subdomains.")
            hostname = f"[{hostname}]"
        host_pattern = re.escape(hostname)
        if mode == "subdomains":
            host_pattern = r"(?:[a-z0-9-]+\.)*" + host_pattern
        # HTTP schemes and hosts are case insensitive; URL paths are not.
        authority = f"(?i:^https?://{host_pattern})" + (f":{port}" if port is not None else r"(?::[0-9]+)?")
        if mode in {"domain", "subdomains"}:
            pattern = authority + r"(?:[/?#]|$)"
        elif mode == "path":
            path_pattern = r"/?" if parsed.path in {"", "/"} else re.escape(parsed.path)
            pattern = authority + path_pattern + r"(?:[?#]|$)"
        else:
            path = (parsed.path or "/").rstrip("/")
            pattern = authority + re.escape(path) + r"(?:[/?#]|$)"
        if pattern not in patterns:
            patterns.append(pattern)
    if not patterns:
        raise ValueError("Enter at least one domain or URL.")
    return "\n".join(patterns)


def url_rule_errors(allowlist, denylist) -> list[dict[str, str]]:
    """Validate only the regex branch of Crawl's existing domain-or-regex matcher."""
    errors = []
    for field, value in (("allowlist", allowlist), ("denylist", denylist)):
        for pattern in Crawl.split_filter_patterns(value):
            # Bare domains and *.domain have their own branch in Crawl's matcher.
            if re.fullmatch(r"[\w.*:-]+", pattern):
                continue
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append({"field": field, "pattern": pattern, "message": str(error)})
    return errors


@never_cache
@csrf_protect
@require_POST
def url_rules_preview(request):
    # Match AddView's permission to override capture configuration.
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_superuser):
        return JsonResponse({"error": "Configuration editing requires an administrator account."}, status=403)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("Expected an object.")
        for key in ("entries", "mode", "allowlist", "denylist", "urls"):
            if key in payload and not isinstance(payload[key], str):
                raise ValueError(f"{key} must be text.")
        if "entries" in payload:
            return JsonResponse({"generated": compose_url_rules(payload["entries"], payload.get("mode", "domain"))})
    except (ValueError, UnicodeError) as error:
        return JsonResponse({"error": str(error)}, status=400)

    allowlist = Crawl.split_filter_patterns(payload.get("allowlist", ""))
    denylist = Crawl.split_filter_patterns(payload.get("denylist", ""))
    errors = url_rule_errors(allowlist, denylist)
    crawl = Crawl()
    results = []
    for url in Crawl.split_filter_patterns(payload.get("urls", "")):
        allow_matches = [pattern for pattern in allowlist if crawl._pattern_matches_url(url, pattern)]
        deny_matches = [pattern for pattern in denylist if crawl._pattern_matches_url(url, pattern)]
        allowed = crawl.url_passes_compiled_filters(url, allowlist=allowlist, denylist=denylist)
        results.append(
            {
                "url": url,
                "allowed": allowed,
                "reason": "denylist"
                if deny_matches
                else "allowlist"
                if allow_matches
                else "not_allowlisted"
                if allowlist
                else "unrestricted",
                "allow_matches": allow_matches,
                "deny_matches": deny_matches,
            },
        )
    return JsonResponse({"results": results, "errors": errors})
