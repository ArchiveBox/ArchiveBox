__package__ = 'archivebox.core'

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html, mark_safe
from django.contrib.auth import get_user_model

import abx


class CustomUserAdmin(UserAdmin):
    sort_fields = ['id', 'email', 'username', 'is_superuser', 'last_login', 'date_joined']
    list_display = ['username', 'id', 'email', 'is_superuser', 'last_login', 'date_joined']
    readonly_fields = ('snapshot_set', 'archiveresult_set', 'tag_set', 'apitoken_set', 'outboundwebhook_set')
    fieldsets = [*UserAdmin.fieldsets, ('Data', {'fields': readonly_fields})]

    @admin.display(description='Snapshots')
    def snapshot_set(self, obj):
        total_count = obj.snapshot_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/core/snapshot/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> {}',
                snap.pk,
                snap.abid,
                snap.downloaded_at.strftime('%Y-%m-%d %H:%M') if snap.downloaded_at else 'pending...',
                snap.url[:64],
            )
            for snap in obj.snapshot_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/snapshot/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='Archive Result Logs')
    def archiveresult_set(self, obj):
        total_count = obj.archiveresult_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/core/archiveresult/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> <b>📄 {}</b> {}',
                result.pk,
                result.abid,
                result.snapshot.downloaded_at.strftime('%Y-%m-%d %H:%M') if result.snapshot.downloaded_at else 'pending...',
                result.extractor,
                result.snapshot.url[:64],
            )
            for result in obj.archiveresult_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/archiveresult/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='Tags')
    def tag_set(self, obj):
        total_count = obj.tag_set.count()
        return mark_safe(', '.join(
            format_html(
                '<code><a href="/admin/core/tag/{}/change"><b>{}</b></a></code>',
                tag.pk,
                tag.name,
            )
            for tag in obj.tag_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/tag/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='API Tokens')
    def apitoken_set(self, obj):
        total_count = obj.apitoken_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/api/apitoken/{}/change"><b>[{}]</b></a></code> {} (expires {})',
                apitoken.pk,
                apitoken.abid,
                apitoken.token_redacted[:64],
                apitoken.expires,
            )
            for apitoken in obj.apitoken_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/api/apitoken/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='API Outbound Webhooks')
    def outboundwebhook_set(self, obj):
        total_count = obj.outboundwebhook_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/api/outboundwebhook/{}/change"><b>[{}]</b></a></code> {} -> {}',
                outboundwebhook.pk,
                outboundwebhook.abid,
                outboundwebhook.referenced_model,
                outboundwebhook.endpoint,
            )
            for outboundwebhook in obj.outboundwebhook_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/api/outboundwebhook/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')




@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(get_user_model(), CustomUserAdmin)
