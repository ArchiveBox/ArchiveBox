"""Stable, derived host grouping shared by navigation and domain summaries."""

from functools import lru_cache
from ipaddress import ip_address
from urllib.parse import urlsplit

from django.db import models


def domain_key(host: str, port: int | None = None) -> str:
    """Reverse the hostname labels, with the non-default port first."""
    host = host.rstrip(".").lower()
    if not host:
        return ""
    key = f"[{host}]" if ":" in host else ".".join(reversed(host.split(".")))
    return key if port in (None, 80, 443) else f"{port}:{key}"


def domain_key_from_url(url: str) -> str:
    # Changes to this expression require regenerating existing stored keys.
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and (host := parsed.hostname):
            if not host.isascii():
                try:
                    host = host.rstrip(".").encode("idna").decode("ascii")
                except UnicodeError:
                    # Preserve legacy hostnames that the URL parser accepted.
                    pass
            return domain_key(host, parsed.port)
    except ValueError:
        pass
    return ""


def domain_key_parts(key: str) -> tuple[str, int | None]:
    """Read the hostname and non-default port back from a stored key."""
    port = None
    if not key.startswith("[") and ":" in key:
        port_text, key = key.split(":", 1)
        port = int(port_text)
    host = key[1:-1] if key.startswith("[") else ".".join(reversed(key.split(".")))
    return host, port


class ReversedDomain(models.Func):
    function = "archivebox_reversed_domain"


class ReversedDomainField(models.TextField):
    def db_parameters(self, connection):
        params = super().db_parameters(connection)
        if connection.vendor == "postgresql":
            # Use the same bytewise ordering as SQLite's default BINARY
            # collation so dotted prefix ranges use the ordinary index.
            params["collation"] = "C"
        return params


@lru_cache(maxsize=1)
def domain_suffixes():
    from tldextract import TLDExtract

    return TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


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


def domain_authority_from_key(key: str) -> str:
    host, port = domain_key_parts(key)
    authority = f"[{host}]" if ":" in host else host
    return authority if port is None else f"{authority}:{port}"


def group_domain_key(key: str) -> tuple[str, str]:
    host, port = domain_key_parts(key)
    domain, scope = group_host(host)
    if port is None:
        return domain, scope
    authority = f"[{domain}]" if ":" in domain else domain
    return f"{authority}:{port}", f"{scope}:{port}"


def domain_label_from_key(key: str) -> str:
    return group_domain_key(key)[0] if key else ""


def domain_search_term(value: str) -> str:
    term = value.strip().casefold().removeprefix("*.")
    host, _, port = term.rpartition(":")
    if host and port in {"80", "443"} and (":" not in host or host.endswith("]")):
        return host
    return term
