"""The webhook editor uses OutboundWebhook and existing folder selections."""

import json
from functools import wraps
from uuid import UUID

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_safe
from signal_webhooks.utils import model_from_reference

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.core.widgets import TagEditorWidget
from archivebox.plugins.discovery import get_plugin_catalog

from .models import OutboundWebhook
from .webhook_actions import configurable_fields
from .webhook_events import RELATIONSHIP_EVENTS, TAG_EVENTS, event_catalog, event_payload


def webhook_admin(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def tag_scope(hook):
    if hook.signal not in TAG_EVENTS:
        return None
    scope = hook.relationship
    return int(scope) if scope.isascii() and scope.isdecimal() else scope or None


def webhook_data(hook, tag_names=None):
    tag_id = tag_scope(hook)
    if type(tag_id) is int:
        tag_name = tag_names.get(tag_id) if tag_names is not None else Tag.objects.filter(pk=tag_id).values_list("name", flat=True).first()
    else:
        tag_name = None
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
        "folder_id": "*" if hook.any_folder else str(hook.folder_id) if hook.folder_id else None,
        "tag_id": tag_id,
        "tag_name": tag_name,
        "relationship": (hook.relationship or "*") if hook.signal in RELATIONSHIP_EVENTS else None,
        "actions": actions,
        "stop_processing": hook.stop_processing,
        "stop_on_failure": hook.stop_on_failure,
        "has_auth_token": bool(hook.auth_token),
        "keep_last_response": hook.keep_last_response,
        "last_success": hook.last_success,
        "last_failure": hook.last_failure,
        "num_uses_succeeded": hook.num_uses_succeeded,
        "num_uses_failed": hook.num_uses_failed,
        "last_response": hook.last_response if hook.keep_last_response else "",
    }


def editor_data():
    rules = list(OutboundWebhook.objects.order_by("created_at", "pk"))
    tag_ids = {scope for hook in rules if type(scope := tag_scope(hook)) is int}
    tag_names = dict(Tag.objects.filter(pk__in=tag_ids).values_list("pk", "name"))
    hooks = [webhook_data(hook, tag_names) for hook in rules]
    folder_ids = {hook["folder_id"] for hook in hooks if hook["folder_id"] not in (None, "*")}
    folder_ids.update(
        action["folder_id"] for hook in hooks for action in hook["actions"] if action.get("type") == "folder" and action.get("folder_id")
    )
    return {
        "hooks": hooks,
        "models": event_catalog(),
        "signal_labels": dict(OutboundWebhook._meta.get_field("signal").choices),
        "folders": Folder.picker_choices(Folder.objects.filter(pk__in=folder_ids).only("name", "parent")),
        "plugins": sorted(get_plugin_catalog()),
        "config_fields": sorted(configurable_fields()),
        "tag_editor": str(TagEditorWidget().render("webhook_action_tags_TOKEN", None)),
    }


@webhook_admin
@require_GET
@ensure_csrf_cookie
def index(request):
    return render(
        request,
        "api/webhooks.html",
        {**archivebox_admin.each_context(request), "title": "Rules", "webhook_editor": editor_data()},
    )


@webhook_admin
@require_safe
def legacy_model_redirect(request, suffix=""):
    """Keep old admin bookmarks without offering another way to edit rules."""
    target = (suffix or "").partition("/")[0]
    if target == "add":
        return redirect(reverse("webhooks:index", query={"webhook": "new"}))
    if target:
        try:
            webhook_id = UUID(target).hex
        except ValueError:
            pass
        else:
            return redirect(reverse("webhooks:index", query={"webhook": webhook_id}))
    return redirect("webhooks:index")


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
        "tag_id",
        "relationship",
        "actions",
        "stop_processing",
        "stop_on_failure",
        "auth_token",
        "clear_auth_token",
        "keep_last_response",
    }
    if payload.keys() - allowed:
        raise ValidationError("Unknown webhook fields.")
    for field in ("enabled", "stop_processing", "stop_on_failure", "clear_auth_token", "keep_last_response"):
        if field in payload and not isinstance(payload[field], bool):
            raise ValidationError(f"{field} must be a boolean.")
    if "auth_token" in payload and not isinstance(payload["auth_token"], str):
        raise ValidationError("auth_token must be a string.")
    hook = get_object_or_404(OutboundWebhook, pk=payload["id"]) if payload.get("id") else OutboundWebhook(created_by=request.user)
    previous_signal = hook.signal
    for field in allowed - {"id", "auth_token", "clear_auth_token", "tag_id", "relationship"}:
        if field in payload:
            value = payload[field]
            if field == "folder_id":
                hook.any_folder = value == "*"
                value = None if hook.any_folder else value
            setattr(hook, field, value)
    if "relationship" in payload:
        value = payload["relationship"]
        if value is not None and not isinstance(value, str):
            raise ValidationError("Relationship must be a string.")
        if hook.signal not in TAG_EVENTS:
            hook.relationship = "" if value in (None, "*") else value
        elif value not in (None, ""):
            raise ValidationError("Choose a tag for a tag event.")
    if hook.signal != previous_signal and (hook.signal in TAG_EVENTS) != (previous_signal in TAG_EVENTS):
        if hook.signal in TAG_EVENTS or "relationship" not in payload:
            hook.relationship = ""
    if "tag_id" in payload:
        value = payload["tag_id"]
        if value is not None and (hook.signal not in TAG_EVENTS or (value != "*" and (type(value) is not int or value <= 0))):
            raise ValidationError("Choose an existing tag or Any tag for a tag event.")
        if hook.signal in TAG_EVENTS:
            hook.relationship = "" if value is None else str(value)
    if payload.get("relationship") == "*" and hook.signal not in RELATIONSHIP_EVENTS:
        raise ValidationError("Choose a relationship for a relationship event only.")
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
        metadata = {}
        if hook.folder_id:
            metadata["folder_id"] = str(hook.folder_id)
        tag_id = tag_scope(hook)
        if type(tag_id) is int:
            if hook.signal == "TAGGED":
                candidates = candidates.filter(tags=tag_id)
            else:
                candidates = candidates.exclude(tags=tag_id)
            metadata.update(tag_id=tag_id, tag_name=Tag.objects.filter(pk=tag_id).values_list("name", flat=True).first())
        if hook.signal in RELATIONSHIP_EVENTS and hook.relationship:
            metadata["relationship"] = hook.relationship
        objects = [
            {
                "id": str(obj.pk),
                "label": getattr(obj, "title", None) or getattr(obj, "name", None) or str(obj.pk),
                "payload": event_payload(obj, hook.signal, **metadata),
            }
            for obj in candidates[:5]
        ]
    except (ValidationError, ValueError, TypeError) as error:
        return validation_error(error)
    # Read-only inspection of existing objects, never a dispatch or saved event.
    return JsonResponse({"objects": objects})
