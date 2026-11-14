from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.urls import path

from archivebox.core.models import Folder
from archivebox.uuid_compat import compact_uuid


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
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            folder_id = compact_uuid(request.POST.get("folder_id", ""))
        except ValueError:
            return JsonResponse({"error": "Invalid folder."}, status=400)
        folder = get_object_or_404(Folder, pk=folder_id)
        if not self.has_delete_permission(request, folder):
            raise PermissionDenied
        try:
            folder.validate_deletion()
            self.log_deletions(request, [folder])
            self.delete_model(request, folder)
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)
        return JsonResponse({"deleted": True})

    def get_deleted_objects(self, objs, request):
        deleted, counts, perms, protected = super().get_deleted_objects(objs, request)
        for folder in objs:
            try:
                folder.validate_deletion()
            except ValidationError as error:
                protected.extend(error.messages)
        return deleted, counts, perms, protected

    def delete_queryset(self, request, queryset):
        for folder in queryset:
            folder.delete()

    def rule_schema(self, request):
        from archivebox.core.smart_folders import RuleQuery, OPERATORS

        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        folders = Folder.tree()
        current = next((folder for folder in folders if str(folder.pk) == request.GET.get("folder_id")), None)
        return JsonResponse(
            {
                "fields": RuleQuery.schema(),
                "sort_fields": RuleQuery.sort_fields(),
                "operators": OPERATORS,
                "folders": [{"id": str(folder.pk), "name": folder.path_label} for folder in folders],
                "unavailable_parents": [str(pk) for pk in Folder.subtree_ids(current.pk)] if current else [],
                "rules": current.rules if current else None,
                "container": current.is_container if current else False,
                "can_delete": bool(current and self.has_delete_permission(request, current)),
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
        return JsonResponse({"id": str(folder.pk), "name": folder.name})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent" and request.resolver_match.kwargs.get("object_id"):
            folder_id = compact_uuid(request.resolver_match.kwargs["object_id"])
            kwargs["queryset"] = Folder.objects.exclude(pk__in=Folder.subtree_ids(folder_id))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
