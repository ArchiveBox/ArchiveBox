__package__ = 'archivebox.api'

from signal_webhooks.admin import WebhookAdmin
from signal_webhooks.utils import get_webhook_model

from archivebox.base_models.admin import BaseModelAdmin

from api.models import APIToken


class APITokenAdmin(BaseModelAdmin):
    list_display = ('created_at', 'id', 'created_by', 'token_redacted', 'expires')
    sort_fields = ('id', 'created_at', 'created_by', 'expires')
    readonly_fields = ('created_at', 'modified_at')
    search_fields = ('id', 'created_by__username', 'token')
    fields = ('created_by', 'token', 'expires', *readonly_fields)

    list_filter = ('created_by',)
    ordering = ['-created_at']
    list_per_page = 100


class CustomWebhookAdmin(WebhookAdmin, BaseModelAdmin):
    list_display = ('created_at', 'created_by', 'id', *WebhookAdmin.list_display)
    sort_fields = ('created_at', 'created_by', 'id', 'referenced_model', 'endpoint', 'last_success', 'last_error')
    readonly_fields = ('created_at', 'modified_at', *WebhookAdmin.readonly_fields)


def register_admin(admin_site):
    admin_site.register(APIToken, APITokenAdmin)
    admin_site.register(get_webhook_model(), CustomWebhookAdmin)
