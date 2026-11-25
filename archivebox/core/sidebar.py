"""Bounded, keyset-paginated navigation shared by the two snapshot libraries."""

from collections import defaultdict, deque
from urllib.parse import urlencode

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.db.models import Exists, OuterRef, Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from archivebox.config.common import get_request_config
from archivebox.core.exports import normalize_export_query
from archivebox.core.list_results_util import favicon_results, snapshot_favicon_data
from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.core.permissions import public_snapshots_queryset
from archivebox.core.routes_util import build_snapshot_export_urls
from archivebox.core.tag_colors import tag_color_style
from archivebox.core.tag_util import _tag_snapshot_memberships

from archivebox.uuid_compat import compact_uuid

SIDEBAR_PAGE_SIZE = 100
DOMAIN_SIDEBAR_PAGE_SIZE = 50
INITIAL_FOLDER_PAGE_SIZE = 50
SIDEBAR_SCOPES = {"folders": "folder", "tags": "tag", "domains": "domain"}

OBJECT_SIDEBAR_MODES = {
    "personas": ("Personas", "Find a persona", "library-persona", ("persona",)),
    "importers": ("Importers", "Find an importer", "library-tray", ("importer",)),
    "scheduled-crawls": ("Scheduled Crawls", "Find a scheduled crawl", "library-schedule", ("crawl_schedule", "crawl")),
}


def _object_sidebar_adapters(request, public):
    if public:
        return {}
    from archivebox.core.sidebar_importers import importer_add_actions, importer_entries_page, importer_sidebar_allowed
    from archivebox.core.sidebar_personas import persona_add_actions, persona_entries_page, persona_sidebar_allowed
    from archivebox.core.sidebar_schedules import schedule_add_actions, schedule_entries_page, schedule_sidebar_allowed

    return {
        mode: (page, actions)
        for mode, allowed, page, actions in (
            ("personas", persona_sidebar_allowed, persona_entries_page, persona_add_actions),
            ("importers", importer_sidebar_allowed, importer_entries_page, importer_add_actions),
            ("scheduled-crawls", schedule_sidebar_allowed, schedule_entries_page, schedule_add_actions),
        )
        if allowed(request)
    }


def _sidebar_template(mode):
    if mode == "folders":
        return "core/folder_tree.html"
    if mode in OBJECT_SIDEBAR_MODES:
        return "core/sidebar_object_entries.html"
    return "core/sidebar_entries.html"


def _sidebar_view_filters(request):
    filters = normalize_export_query(request.GET)
    for key in ("cursor", "sidebar_q", "parent"):
        filters.pop(key, None)
    return filters


def sidebar_search_placeholder(request, *, entries=(), folder_tree=None, public=False):
    fallback = "Search snapshots..."
    scopes = [(scope, request.GET[scope]) for scope in SIDEBAR_SCOPES.values() if request.GET.get(scope)]
    if len(scopes) != 1:
        return fallback
    scope, value = scopes[0]

    try:
        if scope == "folder":
            if value == "unfiled":
                return fallback
            # Full pages already have the folder tree. Toolbar-only search
            # responses do not render that tree and need just the selected row.
            if folder_tree is None:
                name = Folder.objects.filter(pk=value).values_list("name", flat=True).first()
            else:
                name = next((folder.name for folder in folder_tree if str(folder.pk) == value), None)
            icon = "📂"
        else:
            name = next((entry["name"] for entry in entries if entry["selected"] and entry["filter_value"] == value), None)
            if scope == "tag":
                icon = "🏷️"
                if name is None and value.isdecimal():
                    tags = Tag.objects.filter(pk=value)
                    if public:
                        membership = _tag_snapshot_memberships().filter(snapshot__permissions="public")
                        tags = tags.filter(Exists(membership))
                    name = tags.values_list("name", flat=True).first()
            else:
                icon = "🌐"
                if name is None and "," not in value:
                    Snapshot.domain_q(value)
                    name = value.strip().removeprefix("*.")
    except (ValueError, ValidationError):
        return fallback
    return f"Search in {icon} {name}..." if name else fallback


def sidebar_context(request, *, public=False, folder_tree=None):
    adapters = _object_sidebar_adapters(request, public)
    modes = {
        "folders": ("Folders", "Find a folder", "library-pages", ("folder",)),
        "tags": ("Tags", "Find a tag", "library-tag", ("tag",)),
        "domains": ("Domains", "Find a domain", "library-globe", ("domain",)),
        **{key: OBJECT_SIDEBAR_MODES[key] for key in adapters},
    }
    mode = request.GET.get("sidebar", "folders")
    if mode not in modes:
        mode = "folders"
    label, search_label, icon, active_scopes = modes[mode]
    export_filters = _sidebar_view_filters(request)
    mode_filters = export_filters.copy()
    selected = [scope for _, _, _, scopes in modes.values() for scope in scopes if export_filters.get(scope)]
    if len(selected) == 1 and selected[0] in active_scopes:
        mode_filters.pop(selected[0], None)

    mode_queries = {}
    mode_items = []
    for option, (item_label, _, item_icon, _) in modes.items():
        query = mode_filters.copy()
        if option != "folders":
            query["sidebar"] = option
        mode_queries[option] = query.urlencode()
        mode_items.append({"mode": option, "label": item_label, "icon": item_icon, "query": mode_queries[option]})

    root_filters = export_filters.copy()
    for scope in active_scopes:
        export_filters.pop(scope, None)
        root_filters.pop(scope, None)
    if mode != "folders":
        root_filters["sidebar"] = mode

    return {
        "sidebar_mode_queries": mode_queries,
        "sidebar_mode_items": mode_items,
        "sidebar_mode": mode,
        "sidebar_label": label,
        "sidebar_search_label": search_label,
        "sidebar_object_icon": icon,
        "sidebar_object_mode": mode in adapters,
        "sidebar_tree_navigation": mode == "folders" or mode in adapters,
        "sidebar_active_scope": bool(selected),
        "sidebar_root_query": root_filters.urlencode(),
        "sidebar_url": reverse("public-sidebar" if public else "admin-sidebar"),
        "sidebar_add_actions": adapters[mode][1](request) if mode in adapters else [],
        "sidebar_export_urls": build_snapshot_export_urls(export_filters, api=public, request=request),
        **sidebar_page(request, mode=mode, public=public, folder_tree=folder_tree, adapters=adapters),
    }


def sidebar_page(request, *, mode, public=False, folder_tree=None, adapters=None):
    term = request.GET.get("sidebar_q", "").strip()[:253]
    parent = request.GET.get("parent", "")
    cursor = None
    if token := request.GET.get("cursor"):
        cursor = signing.loads(token, salt="library-sidebar")
        if cursor[:3] != [mode, term, parent]:
            raise ValueError("Cursor does not match this sidebar query")
        cursor = cursor[3:]
    entries, folders, next_key = [], [], None
    snapshots = public_snapshots_queryset(Snapshot.objects.all()) if public else Snapshot.objects.all()
    snapshot_admin_url = reverse("admin:core_snapshot_changelist") if mode in ("tags", "domains") and not public else ""
    if mode in OBJECT_SIDEBAR_MODES:
        if adapters is None:
            adapters = _object_sidebar_adapters(request, public)
        if mode not in adapters:
            raise PermissionDenied
        entries, next_key = adapters[mode][0](request, term=term, parent=parent, cursor=cursor, limit=INITIAL_FOLDER_PAGE_SIZE)
        filters = _sidebar_view_filters(request)
        # A click chooses one sidebar entry. The remaining search, sort and
        # explicit non-sidebar filters keep their current values.
        for scope in (*SIDEBAR_SCOPES.values(), *(scope for _, _, _, scopes in OBJECT_SIDEBAR_MODES.values() for scope in scopes)):
            filters.pop(scope, None)
        filters["sidebar"] = mode
        for entry in entries:
            if scope := entry.get("scope"):
                scope_filters = filters.copy()
                scope_filters[scope] = entry["filter_value"]
                entry["url"] = "?" + scope_filters.urlencode()
                entry["selected"] = request.GET.get(scope) == entry["filter_value"]
                entry["export_urls"] = build_snapshot_export_urls(scope_filters, request=request)
    elif mode == "tags":
        membership = _tag_snapshot_memberships()
        if public:
            membership = membership.filter(snapshot__permissions="public")
        tags = Tag.objects.annotate(has_snapshots=Exists(membership)).order_by("name", "pk")
        if public:
            tags = tags.filter(has_snapshots=True)
        if term:
            tags = tags.filter(name__icontains=term)
        if cursor:
            tags = tags.filter(Q(name__gt=cursor[0]) | Q(name=cursor[0], pk__gt=cursor[1]))
        rows = list(tags.only("id", "name")[: SIDEBAR_PAGE_SIZE + 1])
        for tag in rows[:SIDEBAR_PAGE_SIZE]:
            url = "?" + urlencode({"sidebar": mode, "tag": tag.pk})
            entries.append(
                {
                    "id": tag.pk,
                    "name": tag.name,
                    "filter_value": str(tag.pk),
                    "rename_url": reverse("admin:core_tag_change", args=[tag.pk]) if not public else "",
                    "delete_tag_url": reverse("admin:core_tag_delete", args=[tag.pk]) if not public else "",
                    "delete_snapshots_url": snapshot_admin_url + url + "#delete-snapshots"
                    if snapshot_admin_url and tag.has_snapshots
                    else "",
                    "style": tag_color_style(tag.name),
                    "url": url,
                    "selected": request.GET.get("tag") == str(tag.pk),
                },
            )
        if len(rows) > SIDEBAR_PAGE_SIZE:
            last = rows[SIDEBAR_PAGE_SIZE - 1]
            next_key = [last.name, last.pk]
    elif mode == "domains":
        if public and connections[snapshots.db].vendor == "sqlite":
            # Let SQLite seek by hostname and check visibility by snapshot ID.
            # A direct permissions constraint can scan every public snapshot
            # and sort its domains before yielding even the first page.
            snapshots = Snapshot.objects.using(snapshots.db).filter(Exists(snapshots.filter(pk=OuterRef("pk"))))
        choices, next_key = snapshots.domain_choices_page(term, DOMAIN_SIDEBAR_PAGE_SIZE, cursor)
        ids = snapshots.domain_representative_ids(key for scope, key in choices.values())
        roots = dict(snapshots.filter(pk__in=ids.values()).values_list("pk", "reversed_domain"))
        results = defaultdict(list)
        for result in favicon_results().filter(snapshot_id__in=roots):
            results[result.snapshot_id].append(result)
        for name, (scope, key) in choices.items():
            root_id = ids.get(key)
            if root_id is None or roots.get(root_id) != key:
                continue
            url = "?" + urlencode({"sidebar": mode, "domain": scope})
            favicon = snapshot_favicon_data(root_id, results[root_id], request=request)
            entries.append(
                {
                    "id": root_id,
                    "name": name,
                    "filter_value": scope,
                    "url": url,
                    "delete_snapshots_url": snapshot_admin_url + url + "#delete-snapshots" if snapshot_admin_url else "",
                    "selected": request.GET.get("domain") == scope,
                    "favicon": favicon["url"] if favicon else "",
                    "favicon_fallbacks": favicon["fallbacks"] if favicon else "",
                },
            )
    else:
        # Reuse a page's already-loaded picker/breadcrumb tree. Standalone
        # admin sidebar requests still fetch only the indexed sibling page.
        if public and folder_tree is None:
            folder_tree = Folder.tree(public=True)
        loaded_by_id = {folder.pk: folder for folder in folder_tree} if folder_tree is not None else None
        if folder_tree is not None:
            candidates = [
                folder
                for folder in folder_tree
                if (term.casefold() in folder.name.casefold() if term else str(folder.parent_id or "") == parent)
            ]
            if cursor:
                candidates = [folder for folder in candidates if (folder.position, folder.name, str(folder.pk)) > tuple(cursor)]
            candidates.sort(key=lambda folder: (folder.position, folder.name, str(folder.pk)))
            rows = candidates[: SIDEBAR_PAGE_SIZE + 1]
        else:
            candidates = Folder.objects.annotate(has_children=Exists(Folder.objects.filter(parent_id=OuterRef("pk"))))
            candidates = candidates.matching_name(term) if term else candidates.filter(parent_id=parent or None)
            if cursor:
                position, name, pk = cursor
                candidates = candidates.filter(
                    Q(position__gt=position) | Q(position=position, name__gt=name) | Q(position=position, name=name, pk__gt=pk),
                )
            rows = list(candidates.order_by("position", "name", "pk")[: SIDEBAR_PAGE_SIZE + 1])
        folders = rows[:SIDEBAR_PAGE_SIZE]
        if len(rows) > SIDEBAR_PAGE_SIZE:
            last = folders[-1]
            next_key = [last.position, last.name, str(last.pk)]

        preload = folder_tree is not None and not (term or parent or cursor)
        children = defaultdict(list)
        preloaded_ids = set()
        if preload:
            for folder in folder_tree:
                children[folder.parent_id].append(folder)
            for siblings in children.values():
                siblings.sort(key=lambda folder: (folder.position, folder.name, str(folder.pk)))
            queue = deque(children[None])
            folders = []
            while queue and len(folders) < INITIAL_FOLDER_PAGE_SIZE:
                folder = queue.popleft()
                folders.append(folder)
                queue.extend(children[folder.pk])
            preloaded_ids = {folder.pk for folder in folders}
            roots = [folder for folder in folders if not folder.parent_id]
            next_key = None
            if len(roots) < len(children[None]):
                last = roots[-1]
                next_key = [last.position, last.name, str(last.pk)]

        def folder_by_id(pk):
            if loaded_by_id is not None:
                return loaded_by_id.get(pk)
            return Folder.objects.annotate(has_children=Exists(Folder.objects.filter(parent_id=OuterRef("pk")))).filter(pk=pk).first()

        # Keep the selected branch reachable even when its siblings are beyond
        # this page. Every ancestor is emitted before its selected descendant.
        reveal = []
        if not term and not cursor and (selected := request.GET.get("folder")):
            try:
                item = folder_by_id(compact_uuid(selected))
            except (ValueError, TypeError):
                item = None
            while item:
                reveal.append(item)
                item = folder_by_id(item.parent_id) if item.parent_id else None
            if parent:
                reveal = [item for item in reveal if str(item.parent_id or "") == parent]
        by_id = {folder.pk: folder for folder in [*folders, *reveal]}
        pending = {folder.parent_id for folder in folders if folder.parent_id} - by_id.keys()
        while pending:
            if loaded_by_id is not None:
                ancestors = [loaded_by_id[pk] for pk in pending if pk in loaded_by_id]
            else:
                ancestors = list(
                    Folder.objects.filter(pk__in=pending).annotate(has_children=Exists(Folder.objects.filter(parent_id=OuterRef("pk")))),
                )
            by_id.update((folder.pk, folder) for folder in ancestors)
            pending = {folder.parent_id for folder in ancestors if folder.parent_id} - by_id.keys()
        export_filters = _sidebar_view_filters(request)
        for folder in by_id.values():
            if preload:
                siblings = children[folder.pk]
                included = [child for child in siblings if child.pk in preloaded_ids]
                folder.sidebar_children_loaded = len(included) == len(siblings)
                folder.sidebar_children_next = ""
                if included and not folder.sidebar_children_loaded:
                    last = included[-1]
                    folder.sidebar_children_next = signing.dumps(
                        [mode, term, str(folder.pk), last.position, last.name, str(last.pk)],
                        salt="library-sidebar",
                        compress=True,
                    )
            path = folder.path_parts(by_id)
            folder.level = len(path) - 1
            folder.path_label = " / ".join(path)
            export_filters["folder"] = str(folder.pk)
            folder.export_urls = build_snapshot_export_urls(export_filters, api=public, request=request)
        if preload or term or (reveal and not parent):
            # Search and selected branches include ancestors before their leaves.
            folders = []

            visible_children = defaultdict(list)
            for folder in by_id.values():
                visible_children[folder.parent_id].append(folder)
            for siblings in visible_children.values():
                siblings.sort(key=lambda item: (item.position, item.name, str(item.pk)))

            def append_children(parent_id):
                for folder in visible_children[parent_id]:
                    folders.append(folder)
                    append_children(folder.pk)

            append_children(None)
        elif reveal:
            folders = list({folder.pk: folder for folder in [*folders, *reveal]}.values())
    return {
        "sidebar_query": term,
        "sidebar_entries": entries,
        "sidebar_folder_tree": folders,
        "sidebar_next": signing.dumps([mode, term, parent, *next_key], salt="library-sidebar", compress=True) if next_key else "",
    }


@never_cache
@require_GET
def sidebar_view(request, *, public=False):
    if public:
        if not get_request_config(request).PUBLIC_INDEX:
            raise PermissionDenied
    elif not request.user.has_perm("core.view_snapshot"):
        raise PermissionDenied
    mode = request.GET.get("sidebar", "folders")
    adapters = _object_sidebar_adapters(request, public)
    if mode not in SIDEBAR_SCOPES and mode not in adapters:
        return JsonResponse({"error": "Invalid sidebar mode"}, status=400)
    try:
        context = sidebar_page(request, mode=mode, public=public, adapters=adapters)
    except (ValueError, signing.BadSignature):
        return JsonResponse({"error": "Invalid sidebar cursor"}, status=400)
    html = render_to_string(
        _sidebar_template(mode),
        {
            **context,
            "folder_tree": context["sidebar_folder_tree"],
            "folder_readonly": public,
            "sidebar_mode": mode,
            "sidebar_object_icon": OBJECT_SIDEBAR_MODES[mode][2] if mode in adapters else "",
            "sidebar_rows_only": True,
            "selected_folder": request.GET.get("folder", ""),
        },
        request=request,
    )
    return JsonResponse(
        {
            "html": html,
            "next": context["sidebar_next"],
            "choices": [{"id": str(row["id"]), "name": row["name"]} for row in context["sidebar_entries"]],
        },
    )
