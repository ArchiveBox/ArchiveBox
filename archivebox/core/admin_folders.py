import json
from contextlib import contextmanager
from copy import copy
from html import unescape
from time import monotonic

from django import forms
from django.apps import apps
from django.contrib import admin
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, IntegrityError, OperationalError, router, transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import path

from archivebox.core.models import Folder, Snapshot
from archivebox.core.widgets import FolderPicker
from archivebox.uuid_compat import compact_uuid


@contextmanager
def _preview_query_budget(using, milliseconds=200):
    """Do not let a typed predicate or an unindexed sort monopolize the DB."""
    connection = connections[using]
    if connection.vendor == "sqlite":
        connection.ensure_connection()
        raw = connection.connection
        deadline = monotonic() + milliseconds / 1000
        raw.set_progress_handler(lambda: int(monotonic() >= deadline), 1_000)
        try:
            yield
        finally:
            raw.set_progress_handler(None, 0)
    else:
        nested = connection.in_atomic_block
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                # SET LOCAL lasts until the outer transaction commits. Restore
                # its deadline on success; PostgreSQL restores it on rollback.
                if nested:
                    cursor.execute("SHOW statement_timeout")
                    previous = cursor.fetchone()[0]
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [f"{milliseconds}ms"])
                yield
                if nested:
                    cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous])


def _preview_timed_out(error):
    cause = error.__cause__
    return getattr(cause, "sqlite_errorcode", None) == 9 or getattr(cause, "sqlstate", None) == "57014"


def _preview_page(base, matches, ordering, size, after=None, shown=()):
    using = base.db
    if after is None:
        # Selective indexes can prove a sparse or empty result much faster than
        # walking the library in display order. Bound the initial sort so a slow
        # plan cannot consume the entire interactive preview budget.
        try:
            with _preview_query_budget(using, 90):
                return list(matches.order_by(*ordering).values_list("pk", flat=True)[:size]), None
        except OperationalError as error:
            if not _preview_timed_out(error):
                raise

    # Evaluate the exact predicate only for the next ordered candidate window.
    # Counting candidates (including non-matches) lets the next request resume
    # after this window without counting or sorting the entire matching scope.
    ordered = base.order_by(*ordering)
    candidate = matches.filter(pk=OuterRef("pk"))
    candidate.query._archivebox_candidate_row = True
    deadline = monotonic() + 0.15
    offset, window = after or (0, 1024)
    start_offset = offset
    while True:
        candidates = ordered.values("pk")[offset : offset + window]
        probe = ordered.filter(pk__in=candidates).annotate(_matches=Exists(candidate))
        try:
            milliseconds = max(1, round((deadline - monotonic()) * 1000))
            with _preview_query_budget(using, milliseconds):
                rows = list(probe.values_list("pk", "_matches"))
        except OperationalError as error:
            if not _preview_timed_out(error):
                raise
            # A later window may have had only a few milliseconds left. Give
            # it a fresh request, reducing it only if a full budget was spent.
            if offset == start_offset:
                if window <= 64:
                    raise
                window //= 2
            return [], (offset, window)
        # New snapshots can shift offsets between requests. Repeated rows do
        # not use up the draft's remaining preview slots.
        ids = [pk for pk, matched in rows if matched and pk.hex not in shown][:size]
        offset += len(rows)
        if len(ids) == size or len(rows) < window:
            return ids, None
        if ids or monotonic() >= deadline:
            return ids, (offset, window)


# Only human-facing models with deliberately safe labels/search fields can be
# browsed here. Keep historical predicates on other relations readable/editable
# structurally without publishing join rows, processes, import jobs or Rules.
RELATED_CHOICES = {
    "auth.user": ("username",),
    "core.folder": ("name",),
    "core.tag": ("name",),
    "crawls.crawl": ("label", "created_at"),
    "crawls.crawlschedule": ("label", "schedule"),
    "personas.persona": ("name",),
}
RELATED_LOOKUPS = {"exact", "not_exact", "in", "not_in"}


class FolderForm(forms.ModelForm):
    class Meta:
        model = Folder
        fields = ("name", "parent", "rules")


class FolderAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/folder/change_list.html"
    list_display = ("name", "parent", "position", "created_by")
    list_select_related = ("parent", "created_by")
    list_editable = ("position",)
    search_fields = ("name",)
    fields = ("name", "parent", "rules", "position", "created_by")
    readonly_fields = ("created_by",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_urls(self):
        return [
            path("export.<str:format>", self.admin_site.admin_view(self.export_folders), name="core_folder_export"),
            path("save/", self.admin_site.admin_view(self.save_folder), name="core_folder_save"),
            path("move/", self.admin_site.admin_view(self.move_folder), name="core_folder_move"),
            path("remove/", self.admin_site.admin_view(self.delete_folder), name="core_folder_remove"),
            path("rules/", self.admin_site.admin_view(self.rule_schema), name="core_folder_rules"),
            *super().get_urls(),
        ]

    def export_folders(self, request, format):
        from archivebox.core.exports import model_export_response

        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        folders = self.get_changelist_instance(request).get_queryset(request).select_related("parent", "created_by")
        return model_export_response(request, (folder.to_json() for folder in folders.iterator(chunk_size=32)), format, name="folders")

    def delete_folder(self, request):
        empty_only = request.GET.get("intent") == "empty_only" or request.POST.get("intent") == "empty_only"
        if request.method != "POST" and not (request.method == "GET" and empty_only):
            return HttpResponseNotAllowed(["POST"])
        try:
            folder_id = compact_uuid((request.GET if request.method == "GET" else request.POST).get("folder_id", ""))
        except ValueError:
            return JsonResponse({"error": "Invalid folder."}, status=400)
        if request.method == "GET":
            folder = get_object_or_404(Folder, pk=folder_id)
            snapshot_admin = self.admin_site.get_model_admin(Snapshot)
            can_delete_snapshots = snapshot_admin.has_view_or_change_permission(request) and snapshot_admin.has_delete_permission(request)
            if not (
                self.has_view_or_change_permission(request, folder) or self.has_delete_permission(request, folder) or can_delete_snapshots
            ):
                raise PermissionDenied
            has_snapshots, has_children = self.removal_state(folder)
            return JsonResponse(
                {
                    "has_snapshots": has_snapshots,
                    "has_children": has_children,
                    "can_delete": self.has_delete_permission(request, folder),
                },
            )
        with transaction.atomic():
            folder = get_object_or_404(Folder.objects.select_for_update(), pk=folder_id)
            if not self.has_delete_permission(request, folder):
                raise PermissionDenied
            try:
                folder.validate_deletion()
            except ValidationError as error:
                return JsonResponse({"error": " ".join(error.messages)}, status=400)
            has_snapshots, has_children = self.removal_state(folder)
            if has_snapshots:
                return JsonResponse(
                    {"error": "Delete snapshots first and wait for their removal before deleting this folder."},
                    status=409,
                )
            if has_children:
                return JsonResponse({"error": "Move or delete child folders first."}, status=409)
            try:
                self.log_deletions(request, [folder])
                self.delete_model(request, folder)
            except ValidationError as error:
                return JsonResponse({"error": " ".join(error.messages)}, status=400)
        return JsonResponse({"deleted": True})

    @staticmethod
    def removal_state(folder):
        has_children = folder.children.exists()
        # No changelist filters, cached counts or deletion-state exclusions.
        has_snapshots = Snapshot.objects.filter(folder=folder).exists()
        if not has_snapshots and (folder.is_smart or has_children):
            from archivebox.core.smart_folders import RuleQuery

            compiler = RuleQuery()
            current = compiler.folders[str(folder.pk)]
            if current.rules:
                current.rules = {key: value for key, value in current.rules.items() if key != "limit"}
            has_snapshots = Snapshot.objects.filter(compiler.folder(folder.pk)).exists()
        return has_snapshots, has_children

    def validate_empty_removal(self, folder):
        folder.validate_deletion()
        has_snapshots, has_children = self.removal_state(folder)
        if has_snapshots:
            raise ValidationError("Delete snapshots first and wait for their removal before deleting this folder.")
        if has_children:
            raise ValidationError("Move or delete child folders first.")

    def delete_model(self, request, obj):
        with transaction.atomic():
            locked = get_object_or_404(Folder.objects.select_for_update(), pk=obj.pk)
            self.validate_empty_removal(locked)
            super().delete_model(request, locked)

    def get_deleted_objects(self, objs, request):
        deleted, counts, perms, protected = super().get_deleted_objects(objs, request)
        for folder in objs:
            try:
                self.validate_empty_removal(folder)
            except ValidationError as error:
                protected.extend(error.messages)
        return deleted, counts, perms, protected

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            folders = list(queryset.select_for_update())
            for folder in folders:
                self.validate_empty_removal(folder)
            for folder in folders:
                folder.delete()

    def _rule_related_admin(self, request, model_label):
        if model_label not in RELATED_CHOICES:
            return None
        model = apps.get_model(model_label)
        if not self.admin_site.is_registered(model):
            return None
        related_admin = self.admin_site.get_model_admin(model)
        return related_admin if related_admin.has_view_or_change_permission(request) else None

    def _rule_related_values(self, request, model_label, related_admin, *, query=None, selected=()):
        fields = RELATED_CHOICES[model_label]
        queryset = related_admin.get_queryset(request).order_by()
        if query is None:
            pk = queryset.model._meta.pk
            cleaned = []
            for value in selected[:100]:
                try:
                    cleaned.append(pk.to_python(value))
                except (ValidationError, ValueError, TypeError):
                    continue
            queryset = queryset.filter(pk__in=cleaned)
        elif model_label == "core.tag":
            from archivebox.core.tag_util import get_matching_tags

            matches = get_matching_tags(query).order_by().values("pk")
            queryset = queryset.filter(pk__in=matches).order_by("name", "pk")
        else:
            search = Q(**{f"{fields[0]}__icontains": query})
            if model_label == "crawls.crawlschedule":
                search |= Q(schedule__icontains=query)
            queryset = queryset.filter(search).order_by(fields[0], "pk")

        visible = [obj for obj in queryset[: 100 if query is None else 20] if related_admin.has_view_or_change_permission(request, obj)]
        if model_label == "core.folder":
            return Folder.picker_choices(visible)
        choices = []
        for obj in visible:
            label = str(getattr(obj, fields[0]) or "")
            if model_label == "crawls.crawl":
                date = obj.created_at.strftime("%Y-%m-%d %H:%M") if obj.created_at else ""
                label = " · ".join(part for part in (label or "Crawl", date) if part)
            elif model_label == "crawls.crawlschedule":
                label = " · ".join(part for part in (label, obj.schedule) if part)
            choices.append({"id": obj.pk, "name": unescape(label)})
        return choices

    def rule_schema(self, request):
        from archivebox.core.smart_folders import RuleQuery, OPERATORS

        if request.method == "POST":
            return self.preview_rules(request)
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        fields = RuleQuery.schema()
        # Derive targets from existing RuleQuery paths, never from a model name
        # supplied by the browser. Related ModelAdmin scoping still applies.
        model_admins = {}
        for label in {field.get("related_model") for field in fields}:
            if related_admin := self._rule_related_admin(request, label):
                model_admins[label] = related_admin
        if path := request.GET.get("related_field"):
            field = next((field for field in fields if field["name"] == path), None)
            label = field.get("related_model") if field else None
            if label not in model_admins:
                raise PermissionDenied
            query = request.GET.get("q", "").strip()[:100]
            return JsonResponse({"choices": self._rule_related_values(request, label, model_admins[label], query=query)})

        current = None
        if folder_id := request.GET.get("folder_id"):
            try:
                current = Folder.objects.select_related("parent").filter(pk=compact_uuid(folder_id)).first()
            except ValueError:
                return JsonResponse({"error": "Invalid folder."}, status=400)
        if current and not self.has_view_or_change_permission(request, current):
            raise PermissionDenied
        # One query per relation type for saved selections, not one per chip.
        relations = {field["name"]: field["related_model"] for field in fields if field.get("related_model") in model_admins}
        saved = {}
        pending = [current.rules] if current and current.rules else []
        for _ in range(100):
            if not pending:
                break
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("rules"), list):
                pending.extend(node["rules"][:2])
            elif node.get("lookup") in RELATED_LOOKUPS and (label := relations.get(node.get("field"))):
                value = node.get("value")
                saved.setdefault(label, []).extend(value[:100] if isinstance(value, list) else [value])
            elif node.get("field") == "folder" and node.get("value") not in (None, "*", "self") and "core.folder" in model_admins:
                saved.setdefault("core.folder", []).append(node["value"])
        selected = {
            label: self._rule_related_values(
                request,
                label,
                model_admins[label],
                selected=list(dict.fromkeys(str(value) for value in values)),
            )
            for label, values in saved.items()
        }
        return JsonResponse(
            {
                "fields": fields,
                "related_selected": selected,
                "related_fields": relations,
                "sort_fields": RuleQuery.sort_fields(),
                "operators": OPERATORS,
                "parent_choice": Folder.picker_choices([current.parent])[0] if current and current.parent_id else None,
                "rules": current.rules if current else None,
                "container": current.is_container if current else False,
                "can_delete": bool(current and self.has_delete_permission(request, current)),
            },
        )

    def preview_rules(self, request):
        from archivebox.core.smart_folders import RuleQuery

        snapshot_admin = self.admin_site.get_model_admin(Snapshot)
        if not snapshot_admin.has_view_or_change_permission(request):
            raise PermissionDenied
        try:
            raw_id = request.POST.get("folder_id")
            folder_id = compact_uuid(raw_id) if raw_id else None
            raw_parent = request.POST.get("parent")
            parent_id = compact_uuid(raw_parent) if raw_parent else None
            serialized = request.POST.get("rules", "")
            if not 0 < len(serialized) <= 16_384:
                raise ValueError
            rules = json.loads(serialized)
            if not isinstance(rules, dict) or not rules:
                raise ValueError
        except (ValueError, RecursionError):
            return JsonResponse({"error": "Invalid rules."}, status=400)

        # An unsaved folder's stable shuffle is seeded by its UUID. Carry that
        # UUID and the remaining row allowance across this exact draft's pages.
        salt = f"folder-preview:{request.user.pk}:{folder_id}:{parent_id}:{serialized}"
        window, shown, draft_id = None, [], None
        if after := request.POST.get("after"):
            try:
                window, shown, draft_id = signing.loads(after, salt=salt)
            except signing.BadSignature:
                return JsonResponse({"error": "Invalid preview cursor."}, status=400)
        folder = get_object_or_404(self.get_queryset(request), pk=folder_id) if folder_id else Folder(parent_id=parent_id)
        if draft_id and not folder_id:
            folder.pk = compact_uuid(draft_id)
        allowed = self.has_change_permission(request, folder) if folder_id else self.has_add_permission(request)
        if not allowed:
            raise PermissionDenied
        folder.rules = rules
        using = router.db_for_read(Snapshot)
        try:
            with _preview_query_budget(using):
                folders = {str(item.pk): item for item in self.get_queryset(request)}
                folders[str(folder.pk)] = folder
                validator = RuleQuery(folders.values(), validate=True)
                validator.folder(folder.pk)
                ordering = RuleQuery.ordering(folder)
                # A top-six preview never needs to evaluate the proposed larger
                # limit. Keep referenced folders' limits and ordering intact.
                size = min(rules.get("limit", 6), 6) - len(shown)
                folder.rules = {key: value for key, value in rules.items() if key != "limit"}
                compiler = RuleQuery(folders.values())
                base = Snapshot.objects.using(using)
                matches = base.filter(compiler.folder(folder.pk))
            ids, window = _preview_page(base, matches, ordering, size, window, shown)
            rows = base.only("id", "title", "url", "created_at").in_bulk(ids)
        except (TypeError, ValidationError) as error:
            return JsonResponse({"error": " ".join(error.messages) if isinstance(error, ValidationError) else "Invalid rules."}, status=400)
        except OperationalError as error:
            if not _preview_timed_out(error):
                raise
            return JsonResponse({"error": "Preview timed out."}, status=503)
        shown.extend(pk.hex for pk in ids if pk in rows)
        return JsonResponse(
            {
                "next": signing.dumps([window, shown, str(folder.pk)], salt=salt) if window else "",
                "snapshots": [
                    {"title": rows[pk].title_stripped, "domain": rows[pk].domain, "date": rows[pk].created_at.date().isoformat()}
                    for pk in ids
                    if pk in rows
                ],
            },
        )

    def move_folder(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        folder_id, target_id = request.POST.get("folder_id", ""), request.POST.get("target_id", "")
        placement = request.POST.get("placement", "inside")
        try:
            folder_id = compact_uuid(folder_id)
            target_id = compact_uuid(target_id) if target_id else None
        except ValueError:
            return JsonResponse({"error": "Invalid folder move."}, status=400)
        if placement not in {"inside", "before", "after"}:
            return JsonResponse({"error": "Invalid folder move."}, status=400)
        with transaction.atomic():
            folder = get_object_or_404(Folder.objects, pk=folder_id)
            target = get_object_or_404(Folder, pk=target_id) if target_id else None
            if target == folder or (not target and placement != "inside"):
                return JsonResponse({"error": "Choose another folder."}, status=400)
            folder.parent = target if placement == "inside" else target.parent
            try:
                folder.full_clean()
            except ValidationError as error:
                return JsonResponse({"error": " ".join(error.messages)}, status=400)
            siblings = list(Folder.objects.filter(parent=folder.parent).exclude(pk=folder.pk))
            index = len(siblings) if placement == "inside" else next(i for i, sibling in enumerate(siblings) if sibling.pk == target.pk)
            if placement == "after":
                index += 1
            siblings.insert(index, folder)
            folder.save()
            for index, sibling in enumerate(siblings):
                sibling.position = index
            Folder.objects.bulk_update(siblings, ["position"])
        return JsonResponse({"id": str(folder.pk)})

    def rename_folder(self, request, folder):
        from archivebox.core.templatetags.core_tags import folder_display_name

        # Name-based smart-folder rules can change when a folder is renamed,
        # so keep the normal validation and membership hooks but write only the name.
        folder.name = request.POST.get("name", "")
        try:
            with transaction.atomic(using=folder._state.db):
                folder.save(update_fields=["name"])
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "A folder with this name already exists here."}, status=400)

        return JsonResponse(
            {"name": folder.name, "display": folder_display_name(folder.name), "path_label": Folder.picker_choices([folder])[0]["name"]},
        )

    def save_folder(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        folder_id = request.POST.get("folder_id", "")
        try:
            folder_id = compact_uuid(folder_id) if folder_id else None
        except ValueError:
            return JsonResponse({"error": "Invalid folder."}, status=400)
        folder = get_object_or_404(Folder, pk=folder_id) if folder_id else None
        allowed = self.has_change_permission(request, folder) if folder else self.has_add_permission(request)
        if not allowed:
            raise PermissionDenied
        if request.POST.get("rename") == "1":
            if not folder:
                return JsonResponse({"error": "Choose a folder to rename."}, status=400)
            return self.rename_folder(request, folder)
        form = FolderForm(request.POST, instance=folder)
        if not form.is_valid():
            return JsonResponse({"error": " ".join(error for errors in form.errors.values() for error in errors)}, status=400)
        folder = form.save(commit=False)
        if not folder_id:
            last_position = Folder.objects.filter(parent=folder.parent).aggregate(last=Max("position"))["last"]
            folder.position = last_position + 1 if last_position is not None else 0
        self.save_model(request, folder, form, change=bool(folder_id))
        result = {"id": str(folder.pk), "name": folder.name, "path_label": Folder.picker_choices([folder])[0]["name"]}
        if request.POST.get("refresh_tree") == "1":
            from archivebox.core.sidebar import sidebar_page

            page_request = copy(request)
            page_request.GET = request.GET.copy()
            page_request.GET["folder"] = str(folder.pk)
            page_request.GET.pop("cursor", None)
            page = sidebar_page(page_request, mode="folders", folder_tree=Folder.tree())
            result["folder_html"] = render_to_string(
                "core/folder_tree.html",
                {"folder_tree": page["sidebar_folder_tree"], "selected_folder": request.GET.get("folder", "")},
                request=request,
            )
            result["folder_next"] = page["sidebar_next"]
        return JsonResponse(result)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            folder_id = request.resolver_match.kwargs.get("object_id")
            kwargs["widget"] = FolderPicker(exclude=folder_id)
            if folder_id:
                kwargs["queryset"] = Folder.objects.exclude(pk__in=Folder.subtree_ids(folder_id))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
