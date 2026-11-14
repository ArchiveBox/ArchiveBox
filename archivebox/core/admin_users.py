__package__ = "archivebox.core"

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string

from archivebox.core.routes_util import build_snapshot_export_urls


class CustomUserAdmin(UserAdmin):
    sort_fields = ["id", "email", "username", "is_superuser", "last_login", "date_joined"]
    list_display = ["username", "snapshot_exports", "snapshot_count_column", "id", "email", "is_superuser", "last_login", "date_joined"]
    readonly_fields = ("snapshot_set", "archiveresult_set", "tag_set", "apitoken_set", "outboundwebhook_set")
    change_form_template = "admin/auth/user/change_form.html"

    # Preserve Django's default user creation form and fieldsets
    # This ensures passwords are properly hashed and permissions are set correctly
    add_fieldsets = UserAdmin.add_fieldsets

    # Extend fieldsets for change form only (not user creation)
    fieldsets = [*(UserAdmin.fieldsets or ()), ("Data", {"fields": readonly_fields})]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(snapshot_count=Count("crawl__snapshot_set", distinct=True))

    @admin.display(description="Export snapshots")
    def snapshot_exports(self, obj):
        return mark_safe(
            render_to_string(
                "core/snapshot_export_links.html",
                {
                    "export_urls": build_snapshot_export_urls({"crawl__created_by__id__exact": obj.pk}),
                },
            ),
        )

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj:
            context["snapshot_export_urls"] = build_snapshot_export_urls({"crawl__created_by__id__exact": obj.pk})
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def snapshot_count_badge(self, obj):
        snapshots_url = f"/admin/core/snapshot/?crawl__created_by__id__exact={obj.pk}"
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
            + f'<br/><a href="/admin/core/snapshot/?crawl__created_by__id__exact={obj.pk}">{total_count} total records...<a>',
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
