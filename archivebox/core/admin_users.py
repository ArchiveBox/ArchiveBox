__package__ = "archivebox.core"

from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils.html import format_html
from django.utils.safestring import mark_safe


class CustomUserAdmin(UserAdmin):
    sort_fields = ["id", "email", "username", "is_superuser", "last_login", "date_joined"]
    list_display = ["username", "id", "email", "is_superuser", "last_login", "date_joined"]
    readonly_fields = ("snapshot_set", "archiveresult_set", "tag_set", "apitoken_set", "outboundwebhook_set")
    change_form_template = "admin/auth/user/change_form.html"

    # Preserve Django's default user creation form and fieldsets
    # This ensures passwords are properly hashed and permissions are set correctly
    add_fieldsets = UserAdmin.add_fieldsets

    # Extend fieldsets for change form only (not user creation)
    fieldsets = [*(UserAdmin.fieldsets or ()), ("Data", {"fields": readonly_fields})]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(snapshot_count=Count("crawl__snapshot_set", distinct=True))

    def snapshot_rss_badge(self, obj, api_token: str = ""):
        params = {"created_by": obj.username, "limit": 50}
        if api_token:
            params["api_key"] = api_token
        rss_url = f"/api/v1/core/snapshots.rss?{urlencode(params)}"
        return format_html(
            (
                '<a href="{}" title="Snapshot RSS feed for {}" '
                'style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:4px;'
                "background:#fff3e0;border:1px solid #f59e0b;color:#7c2d12;font-weight:700;"
                'font-size:12px;line-height:1.2;text-decoration:none;white-space:nowrap;">'
                '<span aria-hidden="true" style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                'background:#f97316;box-shadow:0 0 0 3px rgba(249,115,22,.18);"></span>'
                "RSS</a>"
            ),
            rss_url,
            obj.username,
        )

    def snapshot_count_badge(self, obj):
        snapshots_url = f"/admin/core/snapshot/?created_by__id__exact={obj.pk}"
        snapshot_count = obj.__dict__.get("snapshot_count", 0)
        snapshot_label = "snapshot" if snapshot_count == 1 else "snapshots"
        return format_html(
            (
                '<a href="{}" title="View snapshots for {}" '
                'style="display:inline-flex;align-items:center;padding:3px 8px;border-radius:4px;'
                "background:#f7f8fa;border:1px solid #d0d7de;color:#24292f;font-weight:600;"
                'font-size:12px;line-height:1.2;text-decoration:none;white-space:nowrap;">'
                "{} {}</a>"
            ),
            snapshots_url,
            obj.username,
            snapshot_count,
            snapshot_label,
        )

    @admin.display(description="Snapshots", ordering="snapshot_count")
    def snapshot_count_column(self, obj):
        return self.snapshot_count_badge(obj)

    def get_list_display(self, request):
        from archivebox.api.auth import get_or_create_api_token

        api_token = get_or_create_api_token(request.user)
        token = api_token.token if api_token else ""

        @admin.display(description="RSS Feed")
        def snapshot_rss_feed(obj):
            return self.snapshot_rss_badge(obj, api_token=token)

        return ["username", snapshot_rss_feed, "snapshot_count_column", "id", "email", "is_superuser", "last_login", "date_joined"]

    @admin.display(description="Snapshots")
    def snapshot_set(self, obj):
        total_count = obj.snapshot_set.count()
        return mark_safe(
            "<br/>".join(
                format_html(
                    '<code><a href="/admin/core/snapshot/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> {}',
                    snap.pk,
                    str(snap.id)[:8],
                    snap.downloaded_at.strftime("%Y-%m-%d %H:%M") if snap.downloaded_at else "pending...",
                    snap.url[:64],
                )
                for snap in obj.snapshot_set.order_by("-modified_at")[:10]
            )
            + f'<br/><a href="/admin/core/snapshot/?created_by__id__exact={obj.pk}">{total_count} total records...<a>',
        )

    @admin.display(description="Archive Results")
    def archiveresult_set(self, obj):
        total_count = obj.archiveresult_set.count()
        return mark_safe(
            "<br/>".join(
                format_html(
                    '<code><a href="/admin/core/archiveresult/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> <b>📄 {}</b> {}',
                    result.pk,
                    str(result.id)[:8],
                    result.snapshot.downloaded_at.strftime("%Y-%m-%d %H:%M") if result.snapshot.downloaded_at else "pending...",
                    result.extractor,
                    result.snapshot.url[:64],
                )
                for result in obj.archiveresult_set.order_by("-modified_at")[:10]
            )
            + f'<br/><a href="/admin/core/archiveresult/?created_by__id__exact={obj.pk}">{total_count} total records...<a>',
        )

    @admin.display(description="Tags")
    def tag_set(self, obj):
        total_count = obj.tag_set.count()
        return mark_safe(
            ", ".join(
                format_html(
                    '<code><a href="/admin/core/tag/{}/change"><b>{}</b></a></code>',
                    tag.pk,
                    tag.name,
                )
                for tag in obj.tag_set.order_by("-modified_at")[:10]
            )
            + f'<br/><a href="/admin/core/tag/?created_by__id__exact={obj.pk}">{total_count} total records...<a>',
        )

    @admin.display(description="API Tokens")
    def apitoken_set(self, obj):
        total_count = obj.apitoken_set.count()
        return mark_safe(
            "<br/>".join(
                format_html(
                    '<code><a href="/admin/api/apitoken/{}/change"><b>[{}]</b></a></code> {} (expires {})',
                    apitoken.pk,
                    str(apitoken.id)[:8],
                    apitoken.token_redacted[:64],
                    apitoken.expires,
                )
                for apitoken in obj.apitoken_set.order_by("-modified_at")[:10]
            )
            + f'<br/><a href="/admin/api/apitoken/?created_by__id__exact={obj.pk}">{total_count} total records...<a>',
        )

    @admin.display(description="API Outbound Webhooks")
    def outboundwebhook_set(self, obj):
        total_count = obj.outboundwebhook_set.count()
        return mark_safe(
            "<br/>".join(
                format_html(
                    '<code><a href="/admin/api/outboundwebhook/{}/change"><b>[{}]</b></a></code> {} -> {}',
                    outboundwebhook.pk,
                    str(outboundwebhook.id)[:8],
                    outboundwebhook.referenced_model,
                    outboundwebhook.endpoint,
                )
                for outboundwebhook in obj.outboundwebhook_set.order_by("-modified_at")[:10]
            )
            + f'<br/><a href="/admin/api/outboundwebhook/?created_by__id__exact={obj.pk}">{total_count} total records...<a>',
        )


def register_admin(admin_site):
    admin_site.register(get_user_model(), CustomUserAdmin)
