"""Stable, derived host grouping shared by navigation and domain summaries."""

from functools import lru_cache
from ipaddress import ip_address
from urllib.parse import urlsplit


@lru_cache(maxsize=1)
def domain_suffixes():
    from tldextract import TLDExtract

    return TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


@lru_cache(maxsize=8192)
def group_host(host):
    try:
        normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        normalized = host.rstrip(".").lower()
    registered = domain_suffixes()(normalized).top_domain_under_public_suffix
    domain = registered or normalized
    try:
        ip_address(domain)
        scope = f"[{domain}]" if ":" in domain else domain
    except ValueError:
        scope = f"*.{domain}" if registered else domain
    return domain, scope


def domain_group(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return group_host(parsed.hostname)[0]
    except ValueError:
        pass
    return ""
