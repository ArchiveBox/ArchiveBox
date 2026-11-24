"""ArchiveBox data and request operations supplied to plugin web integrations."""

from io import BytesIO
from uuid import UUID

PROCESS_RECORD_FIELDS = (
    "id",
    "pid",
    "parent_id",
    "status",
    "process_type",
    "worker_type",
    "cmd__0",
    "started_at",
    "ended_at",
    "exit_code",
    "archiveresult__plugin",
    "archiveresult__snapshot__url",
    "archiveresult__snapshot_id",
    "archiveresult__hook_name",
    "archiveresult__output_size",
    "archiveresult__snapshot__title",
    "archiveresult__snapshot__crawl_id",
    "archiveresult__snapshot__crawl__label",
    "iface__iface",
    "iface__ip_local",
    "iface__ip_public",
    "iface__modified_at",
)


class ArchiveBoxHost:
    def plugin_catalog(self):
        from archivebox.plugins.discovery import get_plugin_catalog

        return get_plugin_catalog()

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

    def _require_collection_admin(self, request):
        from django.core.exceptions import PermissionDenied

        user = self.authenticate(request)
        if not user or not user.is_active or not user.is_superuser:
            raise PermissionDenied

    def outlink_records(self, request, *, after=None, limit=32):
        """Keyset-page captures and their saved URL output paths."""
        from concurrent.futures import ThreadPoolExecutor

        from archivebox.core.domain_grouping import domain_key_from_url, group_domain_key
        from archivebox.core.models import Snapshot

        self._require_collection_admin(request)
        limit = min(max(limit, 1), 32)
        queryset = Snapshot.objects.all()
        if after:
            queryset = queryset.filter(pk__lt=UUID(after))
        rows = list(
            queryset.select_related("crawl__created_by")
            .only(
                "id",
                "url",
                "fs_version",
                "timestamp",
                "bookmarked_at",
                "created_at",
                "crawl_id",
                "crawl__created_by__username",
            )
            .order_by("-pk")[: limit + 1],
        )
        records = []
        paths = set()
        snapshots = rows[:limit]
        with ThreadPoolExecutor(max_workers=4) as executor:
            files = list(executor.map(self._saved_url_outputs, (snapshot.storage_path_candidates() for snapshot in snapshots)))
        for snapshot, (directory, saved_paths) in zip(snapshots, files, strict=True):
            paths.update(saved_paths)
            key = domain_key_from_url(snapshot.url)
            records.append(
                {
                    "id": str(snapshot.pk),
                    "domain": group_domain_key(key)[0] if key else "",
                    "url": snapshot.url,
                    "output_dir": str(directory),
                    "paths": saved_paths,
                },
            )
        return {"records": records, "paths": sorted(paths), "cursor": str(rows[limit - 1].pk) if len(rows) > limit else None}

    @staticmethod
    def _saved_url_outputs(directories):
        from archivebox.plugins.url_outputs import url_output_candidates

        for directory in directories:
            try:
                paths = sorted(str(path) for path in url_output_candidates(directory) if (directory / path).is_file(follow_symlinks=False))
            except (FileNotFoundError, NotADirectoryError):
                continue
            return directory, paths
        return directories[0], []

    def collection_records(self, request, *, after=None, limit=512):
        """Stream narrow snapshot metadata using the existing primary-key index."""
        from archivebox.core.domain_grouping import domain_key_from_url, group_domain_key
        from archivebox.core.models import Snapshot
        from archivebox.core.list_results_util import favicon_results, snapshot_favicon_data

        self._require_collection_admin(request)
        limit = min(max(limit, 1), 1024)
        queryset = Snapshot.objects.all()
        if after:
            queryset = queryset.filter(pk__gt=UUID(after))
        rows = list(
            queryset.order_by("pk").values(
                "id",
                "url",
                "output_size",
                "parent_snapshot__url",
            )[: limit + 1],
        )
        icons = {}
        for result in favicon_results().filter(snapshot_id__in=[row["id"] for row in rows[:limit]]):
            icons.setdefault(result.snapshot_id, []).append(result)

        def domain_and_scope(url):
            key = domain_key_from_url(url or "")
            return group_domain_key(key) if key else ("", "")

        records = []
        for row in rows[:limit]:
            icon = snapshot_favicon_data(row["id"], icons.get(row["id"], []), request=request)
            domain, scope = domain_and_scope(row["url"])
            records.append(
                {
                    "id": str(row["id"]),
                    "domain": domain,
                    "scope": scope,
                    "url": row["url"],
                    "parent": domain_and_scope(row["parent_snapshot__url"])[0],
                    "parent_url": row["parent_snapshot__url"],
                    "size": row["output_size"] or 0,
                    "favicon": icon["url"] if icon else "",
                },
            )
        return {"records": records, "cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None}

    def domain_records(self, request, *, cursor=None, limit=16):
        """Page registered domains using the existing domain index and grouping."""
        from archivebox.core.models import Snapshot

        self._require_collection_admin(request)
        choices, cursor = Snapshot.objects.all().domain_choices_page("", min(max(limit, 1), 32), cursor)
        return {
            "nodes": [
                {"id": name, "scope": scope, "count": Snapshot.objects.filter_by_domain(scope).count()}
                for name, (scope, _key) in choices.items()
            ],
            "cursor": cursor,
        }

    def domain_favicons(self, request, domains, *, preferred=None):
        """Archived favicons from a bounded set of recent captures per domain."""
        from django.core.cache import cache
        from archivebox.core.list_results_util import favicon_results, snapshot_favicon_data
        from archivebox.core.models import Snapshot

        self._require_collection_admin(request)
        icons = {}
        preferred = {str(snapshot): domain for domain, snapshot in (preferred or {}).items() if domain in domains[:30]}
        if preferred:
            for result in favicon_results().filter(snapshot_id__in=list(preferred)).order_by("-pk"):
                domain = preferred[str(result.snapshot_id)]
                if domain not in icons and (icon := snapshot_favicon_data(result.snapshot_id, [result], request=request)):
                    icons[domain] = icon["url"]
        for domain in domains[:30]:
            if domain in icons:
                continue
            if not domain or len(domain) > 253:
                continue
            key = f"domain-icon:{request.get_host()}:{domain}"
            favicon = cache.get(key)
            if favicon is None:
                try:
                    scope = domain if ":" in domain or "[" in domain else f"*.{domain}"
                    candidates = Snapshot.objects.filter_by_domain(scope).order_by("-pk").values("pk")[:16]
                    result = favicon_results().filter(snapshot_id__in=candidates).order_by("-pk").first()
                except ValueError:
                    continue
                icon = snapshot_favicon_data(result.snapshot_id, [result], request=request) if result else None
                favicon = icon["url"] if icon else ""
                cache.set(key, favicon, 300)
            if favicon:
                icons[domain] = favicon
        return icons

    def snapshot_records(self, request, *, domain, after=None, limit=16):
        """A short keyset page of capture metadata and discovery relationships."""
        from concurrent.futures import ThreadPoolExecutor

        from archivebox.core.domain_grouping import domain_key_from_url, group_domain_key
        from archivebox.core.models import Snapshot

        self._require_collection_admin(request)
        limit = min(max(limit, 1), 32)
        queryset = Snapshot.objects.filter_by_domain(domain)
        if after:
            queryset = queryset.filter(pk__lt=UUID(after))
        captures = list(
            queryset.select_related("crawl__created_by", "parent_snapshot")
            .only(
                "id",
                "url",
                "fs_version",
                "timestamp",
                "bookmarked_at",
                "created_at",
                "crawl_id",
                "crawl__created_by__username",
                "parent_snapshot__url",
                "title",
                "status",
                "output_size",
                "downloaded_at",
            )
            .order_by("-pk")[: limit + 1],
        )

        def group(url):
            key = domain_key_from_url(url)
            return group_domain_key(key)[0] if key else ""

        records = []
        snapshots = captures[:limit]
        with ThreadPoolExecutor(max_workers=4) as executor:
            files = list(executor.map(self._saved_url_outputs, (snapshot.storage_path_candidates() for snapshot in snapshots)))
        for snapshot, (directory, saved_paths) in zip(snapshots, files, strict=True):
            # LIMIT is applied per source, including high-fanout crawl roots.
            children = list(Snapshot.objects.filter(parent_snapshot_id=snapshot.pk).order_by().values_list("url", flat=True)[:32])
            child_links = [(group(url), url) for url in children]
            parent_url = snapshot.parent_snapshot.url if snapshot.parent_snapshot else None
            records.append(
                {
                    "id": str(snapshot.pk),
                    "url": snapshot.url,
                    "domain": group(snapshot.url),
                    "title": snapshot.title or "",
                    "status": snapshot.status,
                    "size": snapshot.output_size or 0,
                    "created": snapshot.created_at.isoformat(),
                    "downloaded": snapshot.downloaded_at.isoformat() if snapshot.downloaded_at else None,
                    "output_dir": str(directory),
                    "paths": saved_paths,
                    "parent": group(parent_url) if parent_url else None,
                    "parent_url": parent_url,
                    "children": [domain for domain, _ in child_links],
                    "child_links": child_links,
                },
            )
        return {"records": records, "cursor": str(captures[limit - 1].pk) if len(captures) > limit else None}

    def resolve_snapshot_urls(self, request, urls):
        """Resolve a bounded set of saved link targets without scanning captures."""
        from archivebox.core.domain_grouping import domain_key_from_url, group_domain_key
        from archivebox.core.models import Snapshot
        from archivebox.misc.util import equivalent_urls

        self._require_collection_admin(request)
        candidates = {}
        for url in urls[:256]:
            for equivalent in equivalent_urls(url):
                candidates[equivalent] = url
        result = {}
        for url in Snapshot.objects.filter(url__in=candidates).order_by().values_list("url", flat=True).distinct():
            key = domain_key_from_url(url)
            if key:
                result[candidates[url]] = group_domain_key(key)[0]
        return result

    def group_snapshot_urls(self, request, urls):
        """Map URLs to collection domain groups without reading snapshot rows."""
        from archivebox.core.domain_grouping import domain_label_from_key, domain_key_from_url

        self._require_collection_admin(request)
        return {url: domain_label_from_key(key) for url in urls[:256] if (key := domain_key_from_url(url))}

    def process_records(self, request, *, after=None, ids=(), limit=128):
        """Bounded current-machine processes plus newly created lifecycle rows."""
        from archivebox.machine.models import Machine, Process
        from archivebox.core.models import Snapshot

        self._require_collection_admin(request)
        limit = min(max(limit, 1), 128)
        processes = Process.objects.filter(machine=Machine.current_readonly())
        fields = PROCESS_RECORD_FIELDS
        if after:
            # Advance a bounded primary-key window before filtering by machine.
            # Sorting all historical rows for one machine would grow with the collection.
            keys = list(Process.objects.filter(pk__gt=UUID(after)).order_by("pk").values_list("pk", flat=True)[:limit])
            rows = list(processes.filter(pk__in=keys).values(*fields))
            cursor = str(keys[-1]) if keys else after
        else:
            # Uses the existing (machine, process_type, -modified_at) index.
            rows = list(processes.filter(process_type=Process.TypeChoices.HOOK).order_by("-modified_at").values(*fields)[:limit])
            cursor = str(max(row["id"] for row in rows)) if rows else None
        active = list(processes.filter(status="running").order_by().values(*fields)[:limit])
        tracked = list(processes.filter(pk__in=[UUID(value) for value in ids[:128]]).values(*fields))
        records = list({str(row["id"]): row for row in [*rows, *tracked, *active]}.values())
        snapshot_ids = list(
            dict.fromkeys(row["archiveresult__snapshot_id"] for row in [*active, *rows, *tracked] if row["archiveresult__snapshot_id"]),
        )[:16]
        directories = {
            str(snapshot.pk): str(snapshot.get_storage_path_for_version(snapshot.fs_version))
            for snapshot in Snapshot.objects.filter(pk__in=snapshot_ids)
            .select_related("crawl__created_by")
            .only(
                "id",
                "url",
                "fs_version",
                "timestamp",
                "bookmarked_at",
                "created_at",
                "crawl_id",
                "crawl__created_by__username",
            )
        }
        return {"records": records, "cursor": cursor, "output_dirs": directories}

    def process_history_records(self, request, *, before=None, since=None, limit=128):
        """Page recorded downloads for the collection across machine identities."""
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        self._require_collection_admin(request)
        limit = min(max(limit, 1), 128)
        reporters = self.download_reporters(request, self.plugin_catalog())
        before_id = UUID(before) if before else None
        complete = Process.objects.filter(status=Process.StatusChoices.EXITED, ended_at__isnull=False)
        if since:
            complete = complete.filter(ended_at__gt=since)
        if since and timezone.now() - since <= timedelta(days=1, seconds=1):
            # Hook completion updates modified_at. Use the existing recent
            # machine/process index before joining archive results or logs.
            recent = Process.objects.filter(
                machine_id__in=Machine.objects.values("pk"),
                process_type=Process.TypeChoices.HOOK,
                modified_at__gt=since,
            ).order_by()
            if before_id:
                recent = recent.filter(pk__lt=before_id)
            query = complete.filter(pk__in=recent.values("pk"), archiveresult__plugin__in=reporters)
            ids = list(query.order_by("-pk").values_list("pk", flat=True)[: limit + 1])
        else:
            # Select a bounded page of actual reporter results before reading
            # Process rows. Old or incomplete captures can yield an empty page.
            reports = ArchiveResult.objects.filter(plugin__in=reporters, process_id__isnull=False)
            if before_id:
                reports = reports.filter(process_id__lt=before_id)
            ids = list(reports.order_by("-process_id").values_list("process_id", flat=True)[: limit + 1])
        rows = list(complete.filter(pk__in=ids[:limit]).order_by("-pk").values(*PROCESS_RECORD_FIELDS))
        return {
            "records": rows,
            "output_dirs": {},
            "cursor": str(ids[limit - 1]) if len(ids) > limit else None,
        }

    def download_reporters(self, request, plugins):
        """Identify plugins that can report completed download measurements."""
        from archivebox.plugins.discovery import get_plugin_presentation_module

        self._require_collection_admin(request)
        return {
            name: report
            for name in dict.fromkeys(plugins)
            if (report := getattr(get_plugin_presentation_module(name), "completed_downloads", None)) is not None
        }

    def process_log_tails(self, request, ids):
        """Read bounded stderr tails for a page of completed processes."""
        from django.db.models.functions import Right

        from archivebox.machine.models import Process

        self._require_collection_admin(request)
        # Use the primary-key index for the supplied page. Filtering on status
        # in SQL can make SQLite scan every exited process and load its log.
        rows = Process.objects.filter(pk__in=ids[:128]).order_by().annotate(tail=Right("stderr", 65536))
        return {str(pk): tail for pk, status, tail in rows.values_list("pk", "status", "tail") if status == Process.StatusChoices.EXITED}

    def group_domains(self, request, hosts):
        """Group a bounded set of hostnames using the collection's offline PSL."""
        from archivebox.core.domain_grouping import domain_suffixes

        self._require_collection_admin(request)
        return {
            host: domain_suffixes()(host, include_psl_private_domains=False).top_domain_under_public_suffix or host
            for host in hosts[:512]
            if isinstance(host, str) and len(host) <= 253
        }

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
