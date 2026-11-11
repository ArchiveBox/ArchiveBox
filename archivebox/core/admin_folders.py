from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.urls import path

from archivebox.core.models import Folder


class FolderForm(forms.ModelForm):
    class Meta:
        model = Folder
        fields = ("name", "parent")


class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "position")
    list_editable = ("position",)
    search_fields = ("name",)
    fields = ("name", "parent", "position")

    def get_urls(self):
        return [
            path("save/", self.admin_site.admin_view(self.save_folder), name="core_folder_save"),
            path("move/", self.admin_site.admin_view(self.move_folder), name="core_folder_move"),
            *super().get_urls(),
        ]

    def move_folder(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        folder_id, target_id = request.POST.get("folder_id", ""), request.POST.get("target_id", "")
        placement = request.POST.get("placement", "inside")
        if not folder_id.isdecimal() or (target_id and not target_id.isdecimal()) or placement not in {"inside", "before", "after"}:
            return JsonResponse({"error": "Invalid folder move."}, status=400)
        with transaction.atomic():
            folder = get_object_or_404(Folder.objects.select_for_update(), pk=folder_id)
            target = get_object_or_404(Folder, pk=target_id) if target_id else None
            if target == folder or (not target and placement != "inside"):
                return JsonResponse({"error": "Choose another folder."}, status=400)
            folder.parent = target if placement == "inside" else target.parent
            try:
                folder.full_clean()
            except ValidationError as error:
                return JsonResponse({"error": " ".join(error.messages)}, status=400)
            siblings = list(Folder.objects.select_for_update().filter(parent=folder.parent).exclude(pk=folder.pk))
            index = len(siblings) if placement == "inside" else next(i for i, sibling in enumerate(siblings) if sibling.pk == target.pk)
            if placement == "after":
                index += 1
            siblings.insert(index, folder)
            folder.save()
            for index, sibling in enumerate(siblings):
                sibling.position = index
            Folder.objects.bulk_update(siblings, ["position"])
        return JsonResponse({"id": folder.pk})

    def save_folder(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        folder_id = request.POST.get("folder_id", "")
        if folder_id and not folder_id.isdecimal():
            return JsonResponse({"error": "Invalid folder."}, status=400)
        folder = get_object_or_404(Folder, pk=folder_id) if folder_id else None
        allowed = self.has_change_permission(request, folder) if folder else self.has_add_permission(request)
        if not allowed:
            raise PermissionDenied
        form = FolderForm(request.POST, instance=folder)
        if not form.is_valid():
            return JsonResponse({"error": " ".join(error for errors in form.errors.values() for error in errors)}, status=400)
        folder = form.save()
        return JsonResponse({"id": folder.pk, "name": folder.name})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent" and request.resolver_match.kwargs.get("object_id"):
            folder_id = int(request.resolver_match.kwargs["object_id"])
            kwargs["queryset"] = Folder.objects.exclude(pk__in=Folder.subtree_ids(folder_id))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
