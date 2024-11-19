__package__ = 'archivebox.api'

from signal_webhooks.admin import WebhookAdmin
from signal_webhooks.utils import get_webhook_model

from archivebox.base_models.admin import ABIDModelAdmin

from api.models import APIToken


class APITokenAdmin(ABIDModelAdmin):
    list_display = ('created_at', 'abid', 'created_by', 'token_redacted', 'expires')
    sort_fields = ('abid', 'created_at', 'created_by', 'expires')
    readonly_fields = ('created_at', 'modified_at', 'abid_info')
    search_fields = ('id', 'abid', 'created_by__username', 'token')
    fields = ('created_by', 'token', 'expires', *readonly_fields)

    list_filter = ('created_by',)
    ordering = ['-created_at']
    list_per_page = 100


class CustomWebhookAdmin(WebhookAdmin, ABIDModelAdmin):
    list_display = ('created_at', 'created_by', 'abid', *WebhookAdmin.list_display)
    sort_fields = ('created_at', 'created_by', 'abid', 'referenced_model', 'endpoint', 'last_success', 'last_error')
    readonly_fields = ('created_at', 'modified_at', 'abid_info', *WebhookAdmin.readonly_fields)


def register_admin(admin_site):
    admin_site.register(APIToken, APITokenAdmin)
    admin_site.register(get_webhook_model(), CustomWebhookAdmin)
