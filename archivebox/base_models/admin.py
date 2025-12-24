"""Base admin classes for models using UUIDv7."""

__package__ = 'archivebox.base_models'

from django.contrib import admin
from django_object_actions import DjangoObjectActions


class BaseModelAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('id', 'created_at', 'created_by')
    readonly_fields = ('id', 'created_at', 'modified_at')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form
