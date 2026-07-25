from typing import Any

from archivebox.core.routes_util import canonical_base_host_for_request, get_base_url, split_host_port


def get_setup_wizard_context(request, config) -> dict[str, Any]:
    """Build the first-run setup context when ``BASE_URL`` is unset."""
    context = {
        "mode": "unconfigured",
        "canonical_host": "",
        "display_host": "",
        "suggested_base_url": "",
        "machine_admin_url": "",
        "can_configure": False,
        "public_index": config.PUBLIC_INDEX,
        "public_add_view": config.PUBLIC_ADD_VIEW,
        "permissions": config.PERMISSIONS,
    }
    if request is None:
        return context

    scheme = request.scheme or "http"
    canonical_host = canonical_base_host_for_request(request.get_host() or "")
    display_hostname, display_port = split_host_port(canonical_host)
    display_host = canonical_host
    if (scheme, display_port) in (("http", "80"), ("https", "443")):
        display_host = display_hostname

    user = request.user
    is_superuser = bool(user and user.is_authenticated and user.is_superuser)
    machine_admin_url = ""
    if is_superuser:
        try:
            from archivebox.machine.models import Machine

            machine_admin_url = f"/admin/machine/machine/{Machine.current().id}/change/"
        except (ImportError, RuntimeError, TypeError, ValueError):
            machine_admin_url = ""

    context.update(
        canonical_host=canonical_host,
        display_host=display_host,
        suggested_base_url=f"{scheme}://{canonical_host}" if canonical_host else "",
        machine_admin_url=machine_admin_url,
        can_configure=is_superuser,
    )
    return context


def get_base_url_mismatch_context(request, config) -> dict[str, str] | None:
    """Describe a request origin that does not resolve to the configured base."""
    if request is None or not config.BASE_URL:
        return None

    scheme = request.scheme or "http"
    browser_url = f"{scheme}://{request.get_host()}".rstrip("/")
    browser_base_url = browser_url
    if config.USES_SUBDOMAIN_ROUTING:
        browser_base_url = f"{scheme}://{canonical_base_host_for_request(request.get_host())}".rstrip("/")
    configured_base_url = get_base_url(config=config).rstrip("/")
    if browser_base_url.lower() == configured_base_url.lower():
        return None

    return {
        "mode": "base_url_mismatch",
        "browser_url": browser_url,
        "configured_base_url": configured_base_url,
    }
