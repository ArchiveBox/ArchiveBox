"""ArchiveBox data and request operations supplied to plugin web integrations."""

from io import BytesIO
from uuid import UUID


class ArchiveBoxHost:
    def request_config(self, request=None):
        from archivebox.config.common import get_config, get_request_config
        from archivebox.config.constants import CONSTANTS

        config = get_request_config(request) if request is not None else get_config()
        return {**config.model_dump(mode="json"), "DATA_DIR": str(CONSTANTS.DATA_DIR)}

    def admin_context(self, request):
        from archivebox.core.admin_site import archivebox_admin

        return archivebox_admin.each_context(request)

    def route_urls(self, request):
        from archivebox.core.routes_util import build_admin_url, get_api_base_url, get_base_url

        config = request.__dict__.get("archivebox_config")
        return {
            "base": get_base_url(request=request, config=config).rstrip("/"),
            "admin": build_admin_url("/admin/", request=request, config=config).rstrip("/"),
            "api": f"{get_api_base_url(request=request, config=config).rstrip('/')}/api/",
        }

    def authenticate(self, request, *, api=False):
        if api:
            from archivebox.api.auth import auth_using_token

            token = request.headers.get("X-ArchiveBox-API-Key", "")
            authorization = request.headers.get("Authorization", "")
            if not token and authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            user = auth_using_token(token, request=request)
            if user is not None:
                request.user = user
            return user
        return request.user

    def capture_context(self, request, *, snapshot_id=None, crawl_id=None):
        from django.http import Http404
        from ninja.errors import HttpError
        from archivebox.api.auth import authenticated_user_from_request
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot
        from archivebox.core.permissions import (
            PERMISSIONS_PUBLIC,
            PERMISSIONS_UNLISTED,
            can_view_snapshot,
            is_admin_user,
            normalize_permissions,
        )
        from archivebox.crawls.models import Crawl
        from archivebox.misc.util import filter_queryset_by_uuid_substring

        if (snapshot_id is None) == (crawl_id is None):
            raise ValueError("Select exactly one snapshot or crawl")
        if snapshot_id is not None:
            try:
                snapshot = Snapshot.objects.select_related("crawl__created_by").get(pk=UUID(str(snapshot_id)))
            except (ValueError, Snapshot.DoesNotExist) as error:
                raise Http404("Snapshot not found") from error
            authenticated_user_from_request(request)
            if not can_view_snapshot(request, snapshot):
                raise Http404("Snapshot not found")
            directory = snapshot.get_storage_path_for_version(snapshot.fs_version)
            directories = [directory]
            if directory.name == snapshot.pk.hex:
                directories.append(directory.with_name(str(UUID(snapshot.pk.hex))))
            config = get_config(snapshot=snapshot, resolve_plugins=False)
            context = {
                "id": str(snapshot.id),
                "url": snapshot.url,
                "title": snapshot.title,
                "crawl_id": str(snapshot.crawl_id) if snapshot.crawl_id else None,
                "tags": snapshot.tags_str(),
            }
        else:
            try:
                crawl = filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).get()
            except Crawl.DoesNotExist:
                raise HttpError(404, "Crawl not found")
            user = authenticated_user_from_request(request)
            if not is_admin_user(request):
                permissions = normalize_permissions(crawl.permissions)
                is_owner = bool(user and crawl.created_by_id == user.id)
                # UUIDv7 prefixes are guessable timestamps, not unlisted links.
                ref, full_id = crawl_id.replace("-", "").lower(), str(crawl.id).replace("-", "")
                by_prefix = ref != full_id and full_id.startswith(ref)
                if not is_owner and not (permissions == PERMISSIONS_PUBLIC or (permissions == PERMISSIONS_UNLISTED and not by_prefix)):
                    raise HttpError(404, "Crawl not found")
            directories = crawl.output_dir_candidates
            config = get_config(crawl=crawl, resolve_plugins=False)
            context = {"id": str(crawl.id)}
        return {
            **context,
            "output_dirs": [str(path) for path in directories],
            "tmp_dir": str(config.TMP_DIR),
        }

    def websocket_request(self, scope):
        from django.contrib.auth.middleware import AuthenticationMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.core.exceptions import PermissionDenied
        from django.core.handlers.asgi import ASGIRequest
        from django.db import close_old_connections
        from archivebox.config.common import get_request_config
        from archivebox.core.middleware import ReverseProxyAuthMiddleware
        from archivebox.core.routes_util import get_admin_host, host_matches

        close_old_connections()
        try:
            request = ASGIRequest(
                {**scope, "type": "http", "method": "GET", "scheme": "https" if scope.get("scheme") == "wss" else "http"},
                BytesIO(),
            )
            config = get_request_config(request, resolve_plugins=False)
            request.archivebox_config = config
            if not config.CONTROL_PLANE_ENABLED or (
                config.USES_SUBDOMAIN_ROUTING
                and config.BASE_URL
                and not host_matches(request.get_host(), get_admin_host(config=config, request=request))
            ):
                raise PermissionDenied
            SessionMiddleware(lambda request: None).process_request(request)
            AuthenticationMiddleware(lambda request: None).process_request(request)
            ReverseProxyAuthMiddleware(lambda request: None).process_request(request)
            return request
        finally:
            close_old_connections()

    def browser_sources(self):
        from archivebox.machine.models import Machine, Process
        from archivebox.personas.models import Persona

        return {
            "processes": list(
                Process.objects.filter(
                    machine=Machine.current_readonly(),
                    status=Process.StatusChoices.RUNNING,
                ).values("pwd", "cmd", "env__CRAWL_DIR", "env__ACTIVE_PERSONA", "env__TMP_DIR"),
            ),
            "personas": list(Persona.objects.values_list("name", flat=True)),
        }

    def browser_binding(self, *, persona_name=None, snapshot_id=None, crawl_id=None, browser_id=None, current=False, create=False):
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        if sum(bool(value) for value in (persona_name, snapshot_id, crawl_id, browser_id, current)) != 1:
            raise ValueError("Select exactly one persona, snapshot, crawl, browser or current UI selection")
        snapshot = Snapshot.objects.select_related("crawl").get(pk=snapshot_id) if snapshot_id else None
        crawl = snapshot.crawl if snapshot else Crawl.objects.get(pk=crawl_id) if crawl_id else None
        persona = (
            (Persona.get_or_create_named(persona_name) if create else Persona.find_named(persona_name))
            if persona_name
            else crawl.resolve_persona()
            if crawl
            else None
        )
        if persona_name and persona is None:
            raise ValueError(f"Persona not found: {persona_name}")
        if create and persona is not None:
            persona.ensure_dirs()
        config = get_config(snapshot=snapshot, crawl=crawl, persona=persona).model_dump(mode="json")
        config["ABX_RUNTIME"] = "archivebox"
        if persona_name:
            config.update(persona.get_derived_config())
            config.update(
                CHROME_USER_DATA_DIR=persona.CHROME_USER_DATA_DIR,
                AUTH_STORAGE_FILE=persona.AUTH_STORAGE_FILE,
                COOKIES_FILE=persona.COOKIES_FILE,
            )
        return {
            "config": config,
            "persona_name": persona.name if persona else persona_name,
            "persona_dir": str(persona.path) if persona else None,
            "output_dir": str((snapshot or crawl).output_dir) if (snapshot or crawl) else None,
            "scope": "snapshot" if snapshot else "crawl" if crawl else "persona",
            "browser_id": browser_id,
            "current": current,
            "explicit_persona": bool(persona_name),
        }

    def cli_command(self, plugin, command):
        import sys

        return [sys.executable, "-m", "archivebox", "plugin", plugin, command]

    def collection_context(self, *, crawl_id=None, limit=20):
        import json
        from datetime import datetime, timezone
        from django.db.models import Count

        from archivebox.config import CONSTANTS
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, Process
        from archivebox.personas.models import Persona
        from archivebox.progressmonitor.metrics import system_metrics_path

        config = get_config(resolve_plugins=False)
        crawls = Crawl.objects.select_related("created_by", "persona").defer(
            "config",
            "notes",
        )
        if crawl_id:
            selected_crawls = [crawls.get(pk=crawl_id)]
        else:
            # Separate limits ensure a large queue cannot hide running or paused work.
            selected_crawls = [
                crawl
                for status in ("started", "queued", "paused", "backoff")
                for crawl in crawls.filter(status=status).order_by("-modified_at")[:limit]
            ]
        queue = {}
        for row in (
            Snapshot.objects.filter(crawl_id__in=[c.pk for c in selected_crawls]).values("crawl_id", "status").annotate(count=Count("id"))
        ):
            queue.setdefault(str(row["crawl_id"]), {})[row["status"]] = row["count"]
        try:
            performance = json.loads(system_metrics_path().read_text())
        except (OSError, ValueError):
            performance = None
        return {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "limit_per_status": limit,
            "paths": {
                "collection": str(CONSTANTS.DATA_DIR),
                "archive": str(CONSTANTS.ARCHIVE_DIR),
                "config": str(CONSTANTS.CONFIG_FILE),
                "logs": str(CONSTANTS.LOGS_DIR),
                "personas": str(CONSTANTS.PERSONAS_DIR),
                "system_metrics": str(system_metrics_path()),
            },
            "crawls": [
                {
                    "id": str(c.pk),
                    "status": c.status,
                    "label": c.label,
                    "persona": c.persona.name if c.persona else None,
                    "output_dir": str(c.output_dir),
                    "snapshots": queue.get(str(c.pk), {}),
                }
                for c in selected_crawls
            ],
            "running_processes": list(
                Process.objects.filter(
                    machine=Machine.current_readonly(),
                    status=Process.StatusChoices.RUNNING,
                )
                .order_by("-started_at")
                .values("id", "pid", "process_type", "worker_type", "pwd", "started_at")[:limit],
            ),
            "personas": [
                {
                    "name": p.name,
                    "path": str(p.path),
                    "profile": str(p.CHROME_USER_DATA_DIR),
                }
                for p in Persona.objects.only("name").order_by("name")[:limit]
            ],
            "performance": performance,
            "only_new": config.ONLY_NEW,
        }


host = ArchiveBoxHost()
