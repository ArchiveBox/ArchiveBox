"""The webhook editor uses OutboundWebhook and existing folder selections."""

import json
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from signal_webhooks.utils import model_from_reference

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Folder, Snapshot
from archivebox.plugins.discovery import get_plugin_catalog

from .models import OutboundWebhook
from .webhook_actions import configurable_fields
from .webhook_events import event_catalog, event_payload


def webhook_admin(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def webhook_data(hook):
    # The existing encrypted auth_token stays server-side, including when editing
    # a legacy HTTP-only webhook. It must never become a browser-side API preset.
    actions = hook.actions or (
        [{"type": "http_request", "method": "POST", "endpoint": hook.endpoint, "headers": hook.headers}] if hook.endpoint else []
    )
    return {
        "id": str(hook.pk),
        "name": hook.name,
        "ref": hook.ref,
        "signal": hook.signal,
        "enabled": hook.enabled,
        "folder_id": str(hook.folder_id) if hook.folder_id else None,
        "actions": actions,
        "stop_processing": hook.stop_processing,
        "stop_on_failure": hook.stop_on_failure,
        "has_auth_token": bool(hook.auth_token),
        "last_success": hook.last_success,
        "last_failure": hook.last_failure,
        "last_response": hook.last_response if hook.keep_last_response else "",
    }


def editor_data():
    return {
        "hooks": [webhook_data(hook) for hook in OutboundWebhook.objects.all().order_by("created_at", "pk")],
        "models": event_catalog(),
        "signal_labels": dict(OutboundWebhook._meta.get_field("signal").choices),
        "folders": [{"id": str(folder.pk), "name": folder.path_label} for folder in Folder.tree()],
        "plugins": sorted(get_plugin_catalog()),
        "config_fields": sorted(configurable_fields()),
    }


@webhook_admin
@require_GET
@ensure_csrf_cookie
def index(request):
    return render(
        request,
        "api/webhooks.html",
        {**archivebox_admin.each_context(request), "title": "Webhooks", "webhook_editor": editor_data()},
    )


@webhook_admin
@require_GET
def data(request):
    return JsonResponse(editor_data())


def submitted_webhook(request):
    payload = json.loads(request.body)
    if not isinstance(payload, dict):
        raise ValidationError("Expected a webhook object.")
    allowed = {
        "id",
        "name",
        "ref",
        "signal",
        "enabled",
        "folder_id",
        "actions",
        "stop_processing",
        "stop_on_failure",
        "auth_token",
        "clear_auth_token",
    }
    if payload.keys() - allowed:
        raise ValidationError("Unknown webhook fields.")
    for field in ("enabled", "stop_processing", "stop_on_failure", "clear_auth_token"):
        if field in payload and not isinstance(payload[field], bool):
            raise ValidationError(f"{field} must be a boolean.")
    if "auth_token" in payload and not isinstance(payload["auth_token"], str):
        raise ValidationError("auth_token must be a string.")
    hook = get_object_or_404(OutboundWebhook, pk=payload["id"]) if payload.get("id") else OutboundWebhook(created_by=request.user)
    for field in allowed - {"id", "auth_token", "clear_auth_token"}:
        if field in payload:
            setattr(hook, field, payload[field])
    if payload.get("clear_auth_token"):
        hook.auth_token = ""
    elif payload.get("auth_token"):
        hook.auth_token = payload["auth_token"]
    hook.full_clean()
    return hook


def validation_error(error):
    return JsonResponse({"error": "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid webhook data."}, status=400)


@webhook_admin
@require_POST
def save(request):
    try:
        hook = submitted_webhook(request)
        hook.save()
    except (ValidationError, ValueError, TypeError, IntegrityError) as error:
        return validation_error(error)
    return JsonResponse({"hook": webhook_data(hook)})


@webhook_admin
@require_POST
def delete(request, webhook_id):
    get_object_or_404(OutboundWebhook, pk=webhook_id).delete()
    return JsonResponse({"deleted": True})


@webhook_admin
@require_POST
def preview(request):
    try:
        hook = submitted_webhook(request)
        model = model_from_reference(hook.ref)
        candidates = model._default_manager.all()
        if hook.folder_id:
            # Parent folders and predicate folders share precisely the sidebar's
            # selector. No second matcher or include-subfolders flag belongs here.
            candidates = Folder.select_snapshots(Snapshot.objects.all(), hook.folder_id)
        objects = [
            {
                "id": str(obj.pk),
                "label": getattr(obj, "title", None) or getattr(obj, "name", None) or str(obj.pk),
                "payload": event_payload(obj, hook.signal, **({"folder_id": str(hook.folder_id)} if hook.folder_id else {})),
            }
            for obj in candidates[:5]
        ]
    except (ValidationError, ValueError, TypeError) as error:
        return validation_error(error)
    # Read-only inspection of existing objects, never a dispatch or saved event.
    return JsonResponse({"objects": objects})
