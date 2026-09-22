__package__ = "archivebox.api"

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.utils.text import capfirst
from signal_webhooks.admin import WebhookAdmin, WebhookModelForm
from signal_webhooks.settings import webhook_settings
from signal_webhooks.utils import get_webhook_model, model_from_reference

from archivebox.base_models.admin import BaseModelAdmin

from archivebox.api.models import APIToken


def _webhook_fields(*names: str) -> tuple[str, ...]:
    model_fields = {field.name for field in get_webhook_model()._meta.fields}
    return tuple(name for name in names if name in model_fields)


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


class OutboundWebhookAdminForm(WebhookModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ref"] = forms.ChoiceField(
            label=self.fields["ref"].label,
            help_text=self.fields["ref"].help_text,
            choices=[
                (ref, f"{capfirst(model_from_reference(ref, check_hooks=False)._meta.verbose_name_plural)} ({ref})")
                for ref in sorted(webhook_settings.HOOKS)
            ],
        )


class CustomWebhookAdmin(WebhookAdmin, BaseModelAdmin):
    form = OutboundWebhookAdminForm
    list_display = ("created_at", "created_by", "id", *WebhookAdmin.list_display)
    sort_fields = _webhook_fields("created_at", "created_by", "id", "ref", "endpoint", "last_success", "last_failure")
    readonly_fields = _webhook_fields("created_at", "modified_at", *WebhookAdmin.readonly_fields)

    fieldsets = (
        (
            "Webhook",
            {
                "fields": _webhook_fields("name", "signal", "ref", "endpoint", "headers", "keep_last_response"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Authentication",
            {
                "fields": _webhook_fields("auth_token"),
                "classes": ("card",),
            },
        ),
        (
            "Status",
            {
                "fields": _webhook_fields("enabled", "last_success", "last_failure", "last_response"),
                "classes": ("card",),
            },
        ),
        (
            "Owner",
            {
                "fields": _webhook_fields("created_by"),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": _webhook_fields("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    def lookup_allowed(self, lookup: str, value: str, request: HttpRequest | None = None) -> bool:
        """Preserve WebhookAdmin's auth token filter with Django's current admin signature."""
        return not lookup.startswith("auth_token") and admin.ModelAdmin.lookup_allowed(self, lookup, value, request)


def register_admin(admin_site: admin.AdminSite) -> None:
    admin_site.register(APIToken, APITokenAdmin)
    admin_site.register(get_webhook_model(), CustomWebhookAdmin)
