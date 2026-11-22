"""Bounded, keyset-paginated navigation shared by the two snapshot libraries."""

from urllib.parse import urlencode

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from archivebox.config.common import get_request_config
from archivebox.core.list_results_util import load_snapshot_list_results
from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.core.permissions import public_snapshots_queryset
from archivebox.core.routes_util import build_snapshot_url, build_snapshot_export_urls
from archivebox.core.tag_colors import tag_color_style
from archivebox.core.tag_util import _tag_snapshot_memberships
from archivebox.plugins.discovery import get_snapshot_role_names
from archivebox.search.config import get_search_mode

from archivebox.uuid_compat import compact_uuid

SIDEBAR_PAGE_SIZE = 100


def sidebar_context(request, *, public=False, folder_tree=None):
    mode = request.GET.get("sidebar", "folders")
    if mode not in {"folders", "tags", "domains"}:
        mode = "folders"
    export_filters = request.GET.copy()
    for key in ("tag", "domain", "folder", "cursor", "sidebar_q", "parent"):
        export_filters.pop(key, None)
    return {
        "sidebar_mode": mode,
        "sidebar_label": {"folders": "All folders", "tags": "Tags", "domains": "Domains"}[mode],
        "sidebar_search_label": {"folders": "Find a folder", "tags": "Find a tag", "domains": "Find a domain"}[mode],
        "sidebar_url": reverse("public-sidebar" if public else "admin-sidebar"),
        "sidebar_export_urls": build_snapshot_export_urls(export_filters, api=public, request=request),
        **sidebar_page(request, mode=mode, public=public, folder_tree=folder_tree),
    }


def sidebar_page(request, *, mode, public=False, folder_tree=None):
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
    if mode == "tags":
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
                    "rename_url": reverse("admin:core_tag_change", args=[tag.pk]),
                    "delete_tag_url": reverse("admin:core_tag_delete", args=[tag.pk]),
                    "delete_snapshots_url": reverse("admin:core_snapshot_changelist") + url + "#delete-snapshots"
                    if tag.has_snapshots
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
        choices, next_key = snapshots.domain_choices_page(term, SIDEBAR_PAGE_SIZE, cursor)
        ids = snapshots.domain_representative_ids(key for scope, key in choices.values())
        roots = {snapshot.pk: snapshot for snapshot in snapshots.filter(pk__in=ids.values()).only("id", "url", "reversed_domain")}
        results = load_snapshot_list_results(roots.values())
        icon_plugins = set(get_snapshot_role_names("list_icon"))
        for name, (scope, key) in choices.items():
            root = roots.get(ids.get(key))
            if root is None or root.reversed_domain != key:
                continue
            root_id = root.pk
            url = "?" + urlencode({"sidebar": mode, "domain": scope})
            favicons = [build_snapshot_url(str(root_id), path, request=request) for path in results[root_id].succeeded_paths(icon_plugins)]
            entries.append(
                {
                    "id": root_id,
                    "name": name,
                    "filter_value": scope,
                    "url": url,
                    "delete_snapshots_url": reverse("admin:core_snapshot_changelist") + url + "#delete-snapshots",
                    "selected": request.GET.get("domain") == scope,
                    "favicon": favicons[0] if favicons else "",
                    "favicon_fallbacks": ",".join(favicons[1:]),
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
            candidates = candidates.filter(name__icontains=term) if term else candidates.filter(parent_id=parent or None)
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
        if public:
            export_filters = {
                "q": request.GET.get("q", ""),
                "search_mode": get_search_mode(request.GET.get("search_mode"), config=get_request_config(request)),
            }
        else:
            export_filters = request.GET.copy()
            for key in ("sidebar_q", "cursor", "parent"):
                export_filters.pop(key, None)
        for folder in by_id.values():
            path, ancestor = [], folder
            while ancestor:
                path.insert(0, ancestor.name)
                ancestor = by_id.get(ancestor.parent_id)
            folder.level = len(path) - 1
            folder.path_label = " / ".join(path)
            export_filters["folder"] = str(folder.pk)
            folder.export_urls = build_snapshot_export_urls(export_filters, api=public, request=request)
        if term or (reveal and not parent):
            # Search and selected branches include ancestors before their leaves.
            folders = []

            def append_children(parent_id):
                for folder in sorted(
                    (item for item in by_id.values() if item.parent_id == parent_id),
                    key=lambda item: (item.position, item.name, str(item.pk)),
                ):
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
    if mode not in {"folders", "tags", "domains"}:
        return JsonResponse({"error": "Invalid sidebar mode"}, status=400)
    try:
        context = sidebar_page(request, mode=mode, public=public)
    except (ValueError, signing.BadSignature):
        return JsonResponse({"error": "Invalid sidebar cursor"}, status=400)
    template = "core/folder_tree.html" if mode == "folders" else "core/sidebar_entries.html"
    html = render_to_string(
        template,
        {
            **context,
            "folder_tree": context["sidebar_folder_tree"],
            "folder_readonly": public,
            "sidebar_mode": mode,
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
