__package__ = "archivebox.api"

from django.contrib import admin

from archivebox.base_models.admin import BaseModelAdmin

from archivebox.api.models import APIToken


class APITokenAdmin(BaseModelAdmin):
    list_display = ("created_at", "id", "created_by", "token_redacted", "expires")
    sort_fields = ("id", "created_at", "created_by", "expires")
    readonly_fields = ("created_at", "modified_at")
    search_fields = ("id", "created_by__username", "token")

    fieldsets = (
        (
            "Token",
            {
                "fields": ("token", "expires"),
                "classes": ("card",),
            },
        ),
        (
            "Owner",
            {
                "fields": ("created_by",),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    list_filter = ("created_by",)
    ordering = ["-created_at"]
    list_per_page = 100


def register_admin(admin_site: admin.AdminSite) -> None:
    admin_site.register(APIToken, APITokenAdmin)
