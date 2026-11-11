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
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin

from .forms import DestinationForm
from .models import StorageDestination, StorageRun
from .service import ACTIVE, enqueue, read_options, write_options


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
    return page(
        request,
        "storage/index.html",
        {
            "title": "Storage",
            "destinations": StorageDestination.objects.all(),
        },
    )


@storage_admin
@require_http_methods(["GET", "POST"])
def configure(request, destination_id=None):
    destination = (
        get_object_or_404(StorageDestination, pk=destination_id) if destination_id else StorageDestination(created_by=request.user)
    )
    initial = {"provider": request.GET.get("provider", "drive")}
    form = DestinationForm(request.POST or None, instance=destination, initial=initial if not destination_id else None)
    if request.method == "POST" and form.is_valid():
        if destination_id and destination.runs.filter(status__in=ACTIVE).exists():
            form.add_error(None, "Wait for the active storage operation to finish before editing this destination.")
        else:
            existing = read_options(destination) if destination_id else {}
            destination = form.save(commit=False)
            write_options(destination, form.remote_options(existing))
            destination.checked_at = None
            destination.save()
            messages.success(request, "Destination saved. Check the connection before copying captures.")
            return redirect("storage:detail", destination_id=destination.pk)
    callback_url = request.build_absolute_uri(reverse("storage:oauth-callback"))
    return page(
        request,
        "storage/configure.html",
        {
            "title": "Edit storage" if destination_id else "Connect storage",
            "form": form,
            "destination": destination if destination_id else None,
            "callback_url": callback_url,
        },
    )


@storage_admin
@require_GET
def detail(request, destination_id):
    destination = get_object_or_404(StorageDestination, pk=destination_id)
    options = read_options(destination)
    return page(
        request,
        "storage/detail.html",
        {
            "title": destination.name,
            "destination": destination,
            "runs": Paginator(destination.runs.all(), 20).get_page(request.GET.get("page")),
            "active": destination.runs.filter(status__in=ACTIVE).exists(),
            "needs_oauth": destination.provider == "drive" and not options.get("service_account_credentials") and not options.get("token"),
        },
    )


@storage_admin
@require_POST
def action(request, destination_id, action):
    destination = get_object_or_404(StorageDestination, pk=destination_id)
    if action == "cancel":
        destination.runs.filter(status="queued").update(
            status="cancelled",
            finished_at=timezone.now(),
            message="Cancelled before starting.",
        )
        destination.runs.filter(status="running").update(cancel_requested=True)
        messages.info(request, "Cancellation requested. Files already copied will remain at the destination.")
    elif action in StorageRun.Action.values:
        enqueue(destination, action)
        messages.success(request, "Storage operation queued. The ArchiveBox worker will process it.")
    else:
        raise PermissionDenied("Unknown storage action.")
    return redirect("storage:detail", destination_id=destination.pk)


@storage_admin
@require_POST
def oauth_start(request, destination_id):
    destination = get_object_or_404(StorageDestination, pk=destination_id, provider="drive")
    if destination.runs.filter(status__in=ACTIVE).exists():
        messages.error(request, "Wait for the active storage operation before reconnecting.")
        return redirect("storage:detail", destination_id=destination.pk)
    options = read_options(destination)
    if not options.get("client_id") or not options.get("client_secret"):
        messages.error(request, "Save a Google OAuth client ID and secret first.")
        return redirect("storage:edit", destination_id=destination.pk)
    state = secrets.token_urlsafe(32)
    callback = request.build_absolute_uri(reverse("storage:oauth-callback"))
    request.session["storage_oauth"] = {
        "state": state,
        "destination": str(destination.pk),
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
    destination = get_object_or_404(StorageDestination, pk=pending["destination"], provider="drive")
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(request, "Google sign-in was cancelled or did not return authorization. No credentials were changed.")
        return redirect("storage:detail", destination_id=destination.pk)
    if destination.runs.filter(status__in=ACTIVE).exists():
        messages.error(request, "Storage is busy. Finish the operation, then reconnect Google Drive.")
        return redirect("storage:detail", destination_id=destination.pk)
    options = read_options(destination)
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
        write_options(destination, options)
        destination.checked_at = None
        destination.save(update_fields=["config_revision", "checked_at"])
    except (requests.RequestException, ValueError, KeyError):
        messages.error(
            request,
            "Google authorization could not be completed. Verify the OAuth client, redirect URL and consent settings, then try again.",
        )
    else:
        messages.success(request, "Google Drive connected. Run Check connection to verify access to your destination folder.")
    return redirect("storage:detail", destination_id=destination.pk)
