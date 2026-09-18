from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.views import View
from django.utils.http import url_has_allowed_host_and_scheme

from archivebox.config import CONSTANTS
from archivebox.config.common import (
    get_request_config,
)
from archivebox.core.models import Snapshot
from archivebox.core.permissions import (
    is_admin_user,
)
from archivebox.core.routes_util import (
    build_admin_url,
    build_snapshot_url,
)

from .lookup import _find_snapshot_by_ref

REPLAY_AUTH_SALT = "archivebox.private-snapshot-replay"
REPLAY_COOKIE_PREFIX = f"archivebox_replay_{CONSTANTS.COLLECTION_ID}_"
REPLAY_GRANT_MAX_AGE = 60


def _admin_login_redirect_or_forbidden(request: HttpRequest):
    if get_request_config(request).CONTROL_PLANE_ENABLED:
        return redirect(f"/admin/login/?next={request.path}")
    return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")


def _replay_cookie_name(snapshot: Snapshot) -> str:
    return f"{REPLAY_COOKIE_PREFIX}{str(snapshot.id).replace('-', '')[-12:]}"


def _clean_replay_next(path: str | None) -> str:
    """Only allow same-snap relative replay paths; grants must never redirect off-host."""
    path = f"/{(path or 'index.html').lstrip('/')}"
    if not url_has_allowed_host_and_scheme(path, allowed_hosts=set()):
        return "/index.html"
    return path


def _replay_payload_is_valid(payload: dict, snapshot: Snapshot) -> bool:
    """A replay cookie is not its own auth source; it must point at a live admin session.

    Replayed pages can execute hostile JS, so admin cookies stay host-only on admin.*.
    The snap host gets only this host-only HttpOnly cookie, and every request checks
    that the original Django session still exists and still belongs to an active staff user.
    Logout, session expiry, user deletion/deactivation, or password auth-hash rotation all
    make the replay cookie inert without needing admin.* to delete a cookie on snap-*.
    """
    if payload.get("snapshot_id") != str(snapshot.id):
        return False
    try:
        session = Session.objects.get(session_key=str(payload.get("session_key") or ""))
        session_data = session.get_decoded()
        user_id = str(session_data.get(SESSION_KEY) or "")
        auth_hash = str(session_data.get(HASH_SESSION_KEY) or "")
        user = get_user_model().objects.get(pk=user_id)
    except (Session.DoesNotExist, get_user_model().DoesNotExist, KeyError, TypeError, ValueError):
        return False
    return (
        str(payload.get("user_id")) == user_id
        and str(payload.get("auth_hash") or "") == auth_hash
        and user.is_active
        and user.is_staff
        and auth_hash == user.get_session_auth_hash()
    )


def _has_replay_cookie(request: HttpRequest, snapshot: Snapshot) -> bool:
    value = request.COOKIES.get(_replay_cookie_name(snapshot))
    if not value:
        return False
    try:
        payload = signing.loads(value, salt=REPLAY_AUTH_SALT, max_age=settings.SESSION_COOKIE_AGE)
    except signing.BadSignature:
        return False
    return isinstance(payload, dict) and _replay_payload_is_valid(payload, snapshot)


def _private_snapshot_auth_redirect(request: HttpRequest, snapshot: Snapshot, path: str = "", *, preserve_query: bool = True):
    next_path = _clean_replay_next(path or "index.html")
    if preserve_query and request.META.get("QUERY_STRING"):
        next_path = f"{next_path}?{request.META['QUERY_STRING']}"
    target = build_admin_url(
        f"/admin/core/snapshot/replay-auth/?snapshot={snapshot.id}&next={quote(next_path, safe='')}",
        request=request,
    )
    return redirect(target)


def _replay_auth_response(request: HttpRequest, snapshot: Snapshot):
    try:
        payload = signing.loads(str(request.GET.get("grant") or ""), salt=REPLAY_AUTH_SALT, max_age=REPLAY_GRANT_MAX_AGE)
    except signing.BadSignature:
        return _private_snapshot_auth_redirect(request, snapshot, "index.html", preserve_query=False)

    if not isinstance(payload, dict) or not _replay_payload_is_valid(payload, snapshot):
        return _private_snapshot_auth_redirect(request, snapshot, "index.html", preserve_query=False)

    cookie_value = signing.dumps(payload, salt=REPLAY_AUTH_SALT)
    response = redirect(_clean_replay_next(request.GET.get("next")))
    response.set_cookie(
        _replay_cookie_name(snapshot),
        cookie_value,
        max_age=settings.SESSION_COOKIE_AGE,
        secure=request.is_secure(),
        httponly=True,
        samesite="Lax",
    )
    return response


class SnapshotReplayAuthView(View):
    """Admin-only handoff that lets a snap host mint its own replay cookie.

    admin.* cannot set a host-only cookie for snap-* (browsers forbid that), and
    widening the real Django session cookie to *.archivebox.localhost would let XSS
    in replayed pages hit the admin UI. Instead admin.* proves the user is logged in
    with a short URL grant, then snap-* validates it and sets a snap-host-only cookie.
    """

    def get(self, request: HttpRequest):
        if not is_admin_user(request):
            return redirect(f"{build_admin_url('/admin/login/', request=request)}?next={quote(request.get_full_path(), safe='')}")

        snapshot = _find_snapshot_by_ref(str(request.GET.get("snapshot") or ""))
        if not snapshot:
            raise Http404

        payload = {
            "snapshot_id": str(snapshot.id),
            "user_id": str(request.user.pk),
            "session_key": request.session.session_key,
            "auth_hash": request.user.get_session_auth_hash(),
        }
        grant = signing.dumps(payload, salt=REPLAY_AUTH_SALT)
        next_path = _clean_replay_next(request.GET.get("next"))
        target = build_snapshot_url(str(snapshot.id), "_auth", request=request, config=get_request_config(request))
        return redirect(f"{target}?grant={quote(grant, safe='')}&next={quote(next_path, safe='')}")
