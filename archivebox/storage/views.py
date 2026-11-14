import json
import secrets
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

import requests
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot
from archivebox.config.constants import CONSTANTS
from archivebox.progressmonitor.metrics import progress_metrics
from .diagnostics import inspect_storage
from .forms import DestinationForm
from .service import (
    StorageUnavailable,
    active_operation,
    assert_archive_available,
    configuration_access,
    launch_operation,
    processes,
    read_config,
    settings,
    write_config,
)


def storage_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Storage settings require a superuser account.")
        response = view(request, *args, **kwargs)
        if view.__name__ == "oauth_callback":
            response["Referrer-Policy"] = "no-referrer"
        return response

    return wrapped


def page(request, template, context):
    return render(request, template, {**archivebox_admin.each_context(request), **context})


@storage_admin
@require_GET
def index(request):
    config = settings()
    metadata, options = read_config()
    operation = active_operation()
    unavailable = ""
    try:
        assert_archive_available()
    except StorageUnavailable as error:
        unavailable = str(error)
    archive_stats = Snapshot.objects.aggregate(
        total=Count("pk"),
        sealed=Count("pk", filter=Q(status=Snapshot.StatusChoices.SEALED)),
        recorded_bytes=Sum("output_size", default=0),
    )
    cached_metrics = progress_metrics(request.user) or {}
    system = cached_metrics.get("system") or {}
    host_io = system.get("io") or {}
    sampled_at = system.get("sampled_at")
    sample_age = max(0, int(time.time() - sampled_at)) if sampled_at else None
    provider_label = {"drive": "Google Drive", "local": "Local directory"}.get(metadata.get("provider"), "S3 storage")
    if metadata.get("provider") == "s3":
        provider_label = {"AWS": "Amazon S3", "Cloudflare": "Cloudflare R2", "Minio": "MinIO"}.get(
            options.get("provider"),
            "S3-compatible storage",
        )
    active_revision = config.get("ARCHIVE_STORAGE_ACTIVE", "")
    diagnostics = inspect_storage(metadata, config, unavailable)
    collection_free = diagnostics["rows"][0]["free"]
    history = list(processes().filter(worker_type="storage")[:12])
    for process in history:
        process.operation = process.cmd[5] if len(process.cmd) > 5 else "storage"
    return page(
        request,
        "storage/index.html",
        {
            "title": "Storage",
            "connection": metadata,
            "provider_label": provider_label,
            "storage_type": provider_label if active_revision else "Local filesystem",
            "archive_stats": archive_stats,
            "diagnostics": diagnostics,
            "archive_path": str(CONSTANTS.ARCHIVE_DIR),
            "mount_path": str(CONSTANTS.DATA_DIR / "storage" / "mounts" / active_revision) if active_revision else "",
            "host_io": host_io,
            "io_known": host_io.get("bytes_per_second") is not None,
            "disk_free": collection_free,
            "disk_free_known": collection_free is not None,
            "sample_age": sample_age,
            "sample_stale": sample_age is not None and sample_age > 120,
            "operation": operation,
            "history": history,
            "active": bool(config.get("ARCHIVE_STORAGE_ACTIVE")),
            "unavailable": unavailable,
            "checked": config.get("ARCHIVE_STORAGE_CHECKED") == config.get("ARCHIVE_STORAGE_REVISION") and bool(metadata),
            "previous": config.get("ARCHIVE_STORAGE_PREVIOUS", ""),
            "needs_oauth": options.get("type") == "drive" and not options.get("service_account_credentials") and not options.get("token"),
        },
    )


@storage_admin
@require_http_methods(["GET", "POST"])
def configure(request):
    metadata, options = read_config()
    form = DestinationForm(request.POST or None, existing=options, initial=metadata or {"provider": request.GET.get("provider", "drive")})
    if request.method == "POST" and form.is_valid():
        with configuration_access():
            if active_operation():
                form.add_error(None, "Wait for the storage operation to finish before changing the connection.")
            elif settings().get("ARCHIVE_STORAGE_ACTIVE"):
                form.add_error(None, "The active archive connection cannot be edited while mounted.")
            else:
                existing = options if options.get("type") == form.cleaned_data["provider"] else {}
                write_config({key: form.cleaned_data[key] for key in ("provider", "path")}, form.remote_options(existing))
                messages.success(request, "Connection saved. Check access, then activate primary archive storage.")
                return redirect("storage:index")
    return page(
        request,
        "storage/configure.html",
        {
            "title": "Configure archive storage",
            "form": form,
            "callback_url": request.build_absolute_uri(reverse("storage:oauth-callback")),
        },
    )


@storage_admin
@require_POST
def action(request, action):
    try:
        launch_operation(action)
    except (ValueError, RuntimeError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Storage operation started. Progress is recorded in Processes.")
    return redirect("storage:index")


@storage_admin
@require_POST
def oauth_start(request):
    metadata, options = read_config()
    if options.get("type") != "drive":
        raise PermissionDenied("Save a Google Drive connection first.")
    if active_operation():
        messages.error(request, "Wait for the active storage operation before reconnecting.")
        return redirect("storage:index")
    if not options.get("client_id") or not options.get("client_secret"):
        messages.error(request, "Save a Google OAuth client ID and secret first.")
        return redirect("storage:configure")
    state = secrets.token_urlsafe(32)
    callback = request.build_absolute_uri(reverse("storage:oauth-callback"))
    request.session["storage_oauth"] = {
        "state": state,
        "revision": settings().get("ARCHIVE_STORAGE_REVISION"),
        "redirect_uri": callback,
        "created": time.time(),
    }
    return redirect(
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode(
            {
                "client_id": options["client_id"],
                "redirect_uri": callback,
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/drive",
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            },
        ),
    )


@storage_admin
@require_GET
def oauth_callback(request):
    pending = request.session.pop("storage_oauth", {})
    if (
        not pending
        or not constant_time_compare(pending.get("state", ""), request.GET.get("state", ""))
        or time.time() - pending.get("created", 0) > 600
    ):
        raise PermissionDenied("The Google sign-in expired or its state did not match. Start again from Storage.")
    if pending["revision"] != settings().get("ARCHIVE_STORAGE_REVISION"):
        raise PermissionDenied("The storage connection changed. Start Google sign-in again.")
    metadata, options = read_config()
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(request, "Google sign-in was cancelled or did not return authorization. No credentials were changed.")
        return redirect("storage:index")
    if active_operation():
        messages.error(request, "Storage is busy. Finish the operation, then reconnect Google Drive.")
        return redirect("storage:index")
    try:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": request.GET["code"],
                "client_id": options["client_id"],
                "client_secret": options["client_secret"],
                "redirect_uri": pending["redirect_uri"],
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        if not token.get("access_token") or not token.get("refresh_token"):
            raise ValueError("Google did not return offline access.")
        options["token"] = json.dumps(
            {
                "access_token": token["access_token"],
                "refresh_token": token["refresh_token"],
                "token_type": token.get("token_type", "Bearer"),
                "expiry": (timezone.now() + timedelta(seconds=int(token.get("expires_in", 3600)))).isoformat(),
            },
        )
        with configuration_access():
            if pending["revision"] != settings().get("ARCHIVE_STORAGE_REVISION") or active_operation():
                raise PermissionDenied("The storage connection changed during Google sign-in.")
            write_config(metadata, options)
    except (requests.RequestException, ValueError, KeyError):
        messages.error(
            request,
            "Google authorization could not be completed. Verify the OAuth client, redirect URL and consent settings, then try again.",
        )
    else:
        messages.success(request, "Google Drive connected. Run Check connection to verify access to your destination folder.")
    return redirect("storage:index")
