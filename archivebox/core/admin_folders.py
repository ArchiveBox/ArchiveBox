import json
from contextlib import contextmanager
from time import monotonic

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, OperationalError, router, transaction
from django.db.models import Max
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import path

from archivebox.core.models import Folder, Snapshot
from archivebox.uuid_compat import compact_uuid


@contextmanager
def _preview_query_budget(using):
    """Do not let a typed predicate or an unindexed sort monopolize the DB."""
    connection = connections[using]
    if connection.vendor == "sqlite":
        connection.ensure_connection()
        raw = connection.connection
        deadline = monotonic() + 0.2
        raw.set_progress_handler(lambda: int(monotonic() >= deadline), 1_000)
        try:
            yield
        finally:
            raw.set_progress_handler(None, 0)
    else:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '200ms'")
            yield


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
        return model_export_response((folder.to_json() for folder in folders), format, name="folders")

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

    def rule_schema(self, request):
        from archivebox.core.smart_folders import RuleQuery, OPERATORS

        if request.method == "POST":
            return self.preview_rules(request)
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        folders = Folder.tree()
        current = next((folder for folder in folders if str(folder.pk) == request.GET.get("folder_id")), None)
        return JsonResponse(
            {
                "fields": RuleQuery.schema(),
                "sort_fields": RuleQuery.sort_fields(),
                "operators": OPERATORS,
                "folders": [{"id": str(pk), "name": label} for pk, label in Folder.path_choices(folders)],
                "unavailable_parents": [str(pk) for pk in Folder.subtree_ids(current.pk)] if current else [],
                "rules": current.rules if current else None,
                "container": current.is_container if current else False,
                "can_delete": bool(current and self.has_delete_permission(request, current)),
            },
        )

    def preview_rules(self, request):
        from archivebox.core.smart_folders import RuleQuery
        from archivebox.misc.paginators import snapshot_page

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

        folder = get_object_or_404(self.get_queryset(request), pk=folder_id) if folder_id else Folder(parent_id=parent_id)
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
                size = min(rules.get("limit", 6), 6)
                folder.rules = {key: value for key, value in rules.items() if key != "limit"}
                compiler = RuleQuery(folders.values())
                base = Snapshot.objects.using(using)
                matches = base.filter(compiler.folder(folder.pk)).order_by(*ordering)
                ids = snapshot_page(
                    matches.values_list("pk", flat=True),
                    base_queryset=base.values_list("pk", flat=True),
                    start=0,
                    size=size,
                )
                rows = base.only("id", "title", "url", "created_at").in_bulk(ids)
        except (TypeError, ValidationError) as error:
            return JsonResponse({"error": " ".join(error.messages) if isinstance(error, ValidationError) else "Invalid rules."}, status=400)
        except OperationalError as error:
            cause = error.__cause__
            if getattr(cause, "sqlite_errorcode", None) != 9 and getattr(cause, "sqlstate", None) != "57014":
                raise
            return JsonResponse({"error": "Preview timed out."}, status=503)
        return JsonResponse(
            {
                "snapshots": [
                    {"title": rows[pk].title_stripped, "domain": rows[pk].domain, "date": rows[pk].created_at.date().isoformat()}
                    for pk in ids
                    if pk in rows
                ]
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
        form = FolderForm(request.POST, instance=folder)
        if not form.is_valid():
            return JsonResponse({"error": " ".join(error for errors in form.errors.values() for error in errors)}, status=400)
        folder = form.save(commit=False)
        if not folder_id:
            last_position = Folder.objects.filter(parent=folder.parent).aggregate(last=Max("position"))["last"]
            folder.position = last_position + 1 if last_position is not None else 0
        self.save_model(request, folder, form, change=bool(folder_id))
        folders = Folder.tree()
        choices = Folder.path_choices(folders)
        result = {"id": str(folder.pk), "name": folder.name, "path_label": dict(choices)[folder.pk]}
        if request.POST.get("refresh_tree") == "1":
            from archivebox.core.routes_util import build_snapshot_export_urls

            for item in folders:
                filters = request.GET.copy()
                filters["folder"] = str(item.pk)
                item.export_urls = build_snapshot_export_urls(filters)
            result["folder_html"] = render_to_string(
                "core/folder_tree.html",
                {"folder_tree": folders, "selected_folder": request.GET.get("folder", "")},
                request=request,
            )
            result["folder_choices"] = choices
            result["move_folder_choices"] = Folder.path_choices(folder for folder in folders if not folder.is_smart or folder.is_container)
        return JsonResponse(result)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        excluded = set()
        if db_field.name == "parent" and request.resolver_match.kwargs.get("object_id"):
            folder_id = compact_uuid(request.resolver_match.kwargs["object_id"])
            excluded = set(Folder.subtree_ids(folder_id))
            kwargs["queryset"] = Folder.objects.exclude(pk__in=excluded)
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "parent":
            field.choices = [("", field.empty_label), *Folder.path_choices(folder for folder in Folder.tree() if folder.pk not in excluded)]
        return field
