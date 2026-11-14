"""Ordered OutboundWebhook actions using native model APIs and Process logs."""

from __future__ import annotations

import json
import logging
import re
import sys
from urllib.parse import urlsplit

import httpx
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.utils import timezone
from signal_webhooks.settings import webhook_settings
from signal_webhooks.utils import truncate

from archivebox.config.common import ArchiveBoxConfig, config_field_metadata, get_config
from archivebox.plugins.discovery import get_enabled_plugins, get_plugin_catalog

logger = logging.getLogger(__name__)

# These names are existing ArchiveBox configuration/model fields. No expression
# evaluator lives here: Folder's queryset decides membership before dispatch.
ACTION_FIELDS = {
    "disable_plugins": {"disable_plugins"},
    "enable_plugins": {"enable_plugins"},
    "config_overrides": {"config_overrides"},
    "max_depth": {"max_depth"},
    "add_tags": {"add_tags"},
    "remove_tags": {"remove_tags"},
    "folder": {"folder_id"},
    "permissions": {"permissions"},
    "http_request": {"method", "endpoint", "headers", "body"},
    "python": {"code"},
    "shell": {"command"},
}
CAPTURE_ACTIONS = {"disable_plugins", "enable_plugins", "config_overrides", "max_depth"}
SNAPSHOT_ACTIONS = {"add_tags", "remove_tags", "folder", "permissions"}


def configurable_fields():
    return {
        key: metadata
        for key, metadata in config_field_metadata().items()
        if metadata["scope"] == "crawl_frozen" and not metadata["sensitive"] and key not in ArchiveBoxConfig.computed_config_keys
    }


def validate_actions(hook):
    """Validate saved JSON against the installed plugins and config schemas."""
    from archivebox.core.models import Folder

    if not isinstance(hook.actions, list) or len(hook.actions) > 100:
        raise ValidationError({"actions": "Use an ordered list of at most 100 actions."})
    for index, action in enumerate(hook.actions, 1):
        try:
            if not isinstance(action, dict) or action.get("type") not in ACTION_FIELDS:
                raise ValueError("Choose a supported action.")
            kind = action["type"]
            if action.keys() - (ACTION_FIELDS[kind] | {"type"}):
                raise ValueError("Unexpected action fields.")
            snapshot = hook.ref == "archivebox.core.models.Snapshot"
            crawl = hook.ref == "archivebox.crawls.models.Crawl"
            if kind in CAPTURE_ACTIONS and not (snapshot or crawl):
                raise ValueError("Capture settings apply to Snapshot or Crawl.")
            if kind in SNAPSHOT_ACTIONS and not snapshot:
                raise ValueError("This action requires a Snapshot.")
            if kind in CAPTURE_ACTIONS | SNAPSHOT_ACTIONS and hook.signal == "DELETE":
                raise ValueError("A deleted object cannot be modified.")
            if kind in {"enable_plugins", "disable_plugins"}:
                names = action.get(kind)
                catalog = get_plugin_catalog()
                if not isinstance(names, list) or not names or any(not isinstance(name, str) or name not in catalog for name in names):
                    raise ValueError("Select installed plugins by their exact name.")
            elif kind == "config_overrides":
                overrides = action.get(kind)
                if not isinstance(overrides, dict) or not overrides:
                    raise ValueError("Choose at least one configuration setting.")
                invalid = overrides.keys() - configurable_fields().keys()
                if invalid:
                    raise ValueError(f"Unknown or non-capture settings: {', '.join(sorted(invalid))}.")
                resolved = get_config(overrides=overrides, include_machine=False).model_dump(mode="json")
                action[kind] = {key: resolved[key] for key in overrides}
                if "PLUGINS" in overrides:
                    if any(name.strip() not in get_plugin_catalog() for name in str(overrides["PLUGINS"]).split(",") if name.strip()):
                        raise ValueError("PLUGINS must contain installed plugin names.")
            elif kind == "max_depth":
                depth = action.get(kind)
                if not crawl or not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 4:
                    raise ValueError("Choose a Crawl depth from 0 to 4.")
            elif kind in {"add_tags", "remove_tags"}:
                value = action.get(kind)
                if not isinstance(value, str) or not value.strip() or any(len(name.strip()) > 100 for name in value.split(",")):
                    raise ValueError("Enter comma-separated tags, at most 100 characters each.")
            elif kind == "permissions" and action.get(kind) not in {"private", "unlisted", "public"}:
                raise ValueError("Choose private, unlisted, or public.")
            elif kind == "folder" and action.get("folder_id"):
                if not Folder.objects.filter(pk=action["folder_id"]).exists():
                    raise ValueError("Choose an existing folder.")
            elif kind in {"python", "shell"}:
                value = action.get("code" if kind == "python" else "command")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Enter code to execute.")
                if kind == "python":
                    compile(value, "<webhook>", "exec")
            elif kind == "http_request":
                endpoint = action.get("endpoint", "")
                if not isinstance(endpoint, str) or not endpoint:
                    raise ValueError("Enter a request URL.")
                relative = endpoint.startswith("/api/")
                if not relative and (urlsplit(endpoint).scheme not in {"http", "https"} or not urlsplit(endpoint).netloc):
                    raise ValueError("Use an HTTP(S) URL or an ArchiveBox /api/ path.")
                if action.get("method", "POST") not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    raise ValueError("Choose a valid HTTP method.")
                headers = action.get("headers", {})
                if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
                    raise ValueError("HTTP headers must map names to strings.")
        except (ValueError, TypeError, SyntaxError, ValidationError) as error:
            raise ValidationError({"actions": f"Action {index}: {error}"}) from error


def _render(value, payload):
    """Substitute event fields only; scripts receive JSON instead of interpolation."""
    if isinstance(value, dict):
        return {key: _render(item, payload) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, payload) for item in value]
    if not isinstance(value, str):
        return value

    def resolve(match):
        path = match.group(1).split(".")
        current = payload
        if path[0] in {"object", "event"} and len(path) > 1:
            path = path[1:]
        for key in path:
            if not isinstance(current, dict) or key not in current:
                raise ValueError(f"Unknown event field: {match.group(1)}")
            current = current[key]
        return current

    pattern = r"{{\s*([A-Za-z_][\w.]*)\s*}}"
    if match := re.fullmatch(pattern, value):
        return resolve(match)
    return re.sub(pattern, lambda match: str(resolve(match)), value)


def _apply_capture_action(action, instance):
    from archivebox.core.models import Snapshot

    is_snapshot = isinstance(instance, Snapshot)
    # Membership may change after a capture. Updating that capture's frozen
    # settings would imply the saved bytes were produced with different options.
    if is_snapshot and (instance.status not in Snapshot.RUNNABLE_STATES or instance.archiveresult_set.exists()):
        raise ValueError("Capture settings can only change before this snapshot starts capturing.")
    crawl = instance.crawl if is_snapshot else instance
    config = dict(instance.config or {})
    kind = action["type"]
    if kind == "max_depth":
        instance.max_depth = action[kind]
        instance.save(update_fields=["max_depth", "modified_at"])
        return {"max_depth": instance.max_depth}
    if kind == "config_overrides":
        config.update(action[kind])
    else:
        effective = get_config(crawl=crawl, snapshot=instance if is_snapshot else None, overrides=config)
        selected = str(effective.PLUGINS or "").strip()
        names = {name.strip() for name in selected.split(",") if name.strip()} if selected else set(get_enabled_plugins(config=effective))
        if kind == "enable_plugins":
            names.update(action[kind])
        else:
            names.difference_update(action[kind])
        if not names:
            raise ValueError("Cannot disable every plugin: empty PLUGINS selects ambient defaults.")
        config["PLUGINS"] = ",".join(sorted(names))
    instance.config = config
    instance.save(update_fields=["config", "modified_at"])
    return {"config": {key: config[key] for key in (action.get("config_overrides") or {"PLUGINS": None})}}


def _apply_model_action(action, instance, hook):
    from archivebox.core.models import Folder, Snapshot, Tag

    kind = action["type"]
    if kind in CAPTURE_ACTIONS:
        return _apply_capture_action(action, instance)
    if kind == "add_tags":
        tags = [
            Tag.get_or_create_by_name(name.strip(), defaults={"created_by_id": hook.created_by_id})[0]
            for name in action[kind].split(",")
            if name.strip()
        ]
        instance.add_tag_ids([tag.pk for tag in tags])
        return {kind: [tag.name for tag in tags]}
    if kind == "remove_tags":
        names = [name.strip() for name in action[kind].split(",") if name.strip()]
        tags = [tag for tag in instance.tags.all() if tag.name.casefold() in {name.casefold() for name in names}]
        instance.remove_tag_ids([tag.pk for tag in tags])
        return {kind: [tag.name for tag in tags]}
    if kind == "folder":
        Folder.move_snapshots(Snapshot.objects.filter(pk=instance.pk), action.get("folder_id"))
        instance.refresh_from_db()
        return {"folder_id": str(instance.folder_id) if instance.folder_id else None}
    if kind == "permissions":
        instance.config = {**(instance.config or {}), "PERMISSIONS": action[kind]}
        instance.save(update_fields=["config", "modified_at"])
        return {kind: action[kind]}
    raise ValueError(f"Unknown action: {kind}")


def _request(action, hook, payload):
    from archivebox.core.routes_util import get_api_base_url
    from archivebox.crawls.locks import lifecycle_locks_held

    endpoint = str(_render(action["endpoint"], payload))
    self_request = action["endpoint"].startswith("/api/")
    method = action.get("method", "POST")
    if self_request and method not in {"GET", "HEAD", "OPTIONS"} and lifecycle_locks_held():
        # Blocking preparation cannot wait for an HTTP request which itself
        # needs this crawl's lock. Fail explicitly instead of hanging until the
        # HTTP timeout or releasing capture ownership. Native actions can still
        # change preparation settings; post-event HTTP runs after lock release.
        raise ValueError(
            "A blocking webhook cannot call a mutating ArchiveBox API while a lifecycle lock is held. Use a native action or a post-capture event.",
        )
    if self_request:
        base = get_api_base_url()
        if not base:
            raise ValueError("Configure BASE_URL before calling the ArchiveBox API.")
        endpoint = base.rstrip("/") + endpoint
    headers = {**hook.default_headers(), **_render(action.get("headers", {}), payload)}
    if self_request:
        from django.core import signing

        # Carry only server-signed provenance across the HTTP boundary. The
        # receiving API still requires normal authentication; external requests
        # never receive a marker that could suppress this server's webhooks.
        headers = {key: value for key, value in headers.items() if key.lower() != "x-archivebox-webhook"}
        headers["X-ArchiveBox-Webhook"] = signing.dumps({"webhook_id": str(hook.pk)}, salt="archivebox.webhook-action")
    # Use the existing encrypted token; never silently create a root API key.
    body = action.get("body")
    if body is None and method not in {"GET", "HEAD", "OPTIONS"}:
        body = payload
    body = _render(body, payload)
    with httpx.Client(timeout=webhook_settings.TIMEOUT, follow_redirects=False) as client:
        response = client.request(method, endpoint, headers=headers, **({"json": body} if body is not None else {}))
    if response.is_error:
        raise RuntimeError(f"HTTP {response.status_code}: {truncate(response.text)}")
    response.raise_for_status()
    return {"status_code": response.status_code, "body": truncate(response.text) if hook.keep_last_response else ""}


def execute_actions(hook, instance, signal, payload) -> bool:
    """Run a sequence outside transactions and retain each result in Process."""
    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Machine, Process

    if connection.in_atomic_block:
        raise RuntimeError("Webhook actions must run after commit, outside database transactions.")
    success = True
    last_process = None
    for index, action in enumerate(hook.actions, 1):
        kind = action["type"]
        process = Process(
            machine=Machine.current(),
            parent=Process.current_readonly(),
            process_type=Process.TypeChoices.HOOK,
            worker_type="webhook",
            timeout=int(webhook_settings.TIMEOUT),
            started_at=timezone.now(),
            cmd=["webhook", str(hook.pk), str(index), kind],
            env={
                "ARCHIVEBOX_WEBHOOK_ID": str(hook.pk),
                "ARCHIVEBOX_OBJECT_ID": str(payload["id"]),
                "ARCHIVEBOX_OBJECT_TYPE": payload["object_type"],
                "ARCHIVEBOX_EVENT": signal,
            },
        )
        process.pwd = str(CONSTANTS.LOGS_DIR / "webhooks" / str(process.pk))
        process.save()
        process.ensure_log_files()
        last_process = process
        try:
            if index == 1:
                validate_actions(hook)
            if kind in {"python", "shell"}:
                # Positional args are argv, never interpolated into source. Additional
                # membership metadata has declared order rather than dict iteration.
                arguments = [str(payload["id"]), str(payload["object_type"]), signal]
                if "folder_id" in payload:
                    arguments.append(str(payload["folder_id"]))
                process.cmd = (
                    [sys.executable, "-c", action["code"]] if kind == "python" else ["bash", "-c", action["command"], "webhook"]
                ) + arguments
                process.save(update_fields=["cmd", "modified_at"])
                process.launch(cwd=str(CONSTANTS.DATA_DIR), stdin=json.dumps(payload, cls=DjangoJSONEncoder).encode())
                if process.exit_code:
                    raise RuntimeError(f"{kind} exited with status {process.exit_code}")
            else:
                process.mark_running()
                result = _request(action, hook, payload) if kind == "http_request" else _apply_model_action(action, instance, hook)
                process.stdout = json.dumps(result, cls=DjangoJSONEncoder, indent=2)
                process.stdout_file.write_text(process.stdout + "\n")
                process.save(update_fields=["stdout", "started_at", "modified_at"])
                process.mark_exited()
        except Exception as error:
            success = False
            # Root logging already writes logs/errors.log, which is listed by the
            # admin log view. Full output remains on the linked Process admin row.
            message = f"{type(error).__name__}: {error}"
            if hook.auth_token:
                message = message.replace(hook.auth_token, "[REDACTED]")
            process.stderr = (process.stderr + "\n" + message).strip()
            process.stderr_file.write_text(process.stderr + "\n")
            process.save(update_fields=["stderr", "modified_at"])
            process.mark_exited(exit_code=process.exit_code or 1)
            logger.error(
                "Webhook %s (%s) action %s %s failed: %s; /admin/machine/process/%s/change/",
                hook.pk,
                hook.name,
                index,
                kind,
                message,
                process.pk,
            )
            if hook.stop_on_failure:
                break
    field = "last_success" if success else "last_failure"
    now = timezone.now()
    response = (
        f"{'Completed' if success else 'Failed'} · {index} / {len(hook.actions)} actions · /admin/machine/process/{last_process.pk}/change/"
        if last_process
        else "No actions"
    )
    type(hook).objects.filter(pk=hook.pk).update(**{field: now, "last_response": response})
    setattr(hook, field, now)
    hook.last_response = response
    return success
