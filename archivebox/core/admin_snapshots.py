__package__ = "archivebox.core"

import json
import re
from functools import lru_cache
from pathlib import Path
from datetime import datetime

from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Q, Sum, Count, Prefetch
from django.db.models.functions import Coalesce
from django import forms
from django.template import Template, RequestContext
from django.contrib.admin.helpers import ActionForm
from django.http import HttpResponse

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.util import htmldecode, urldecode
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.misc.logging_util import printable_filesize
from archivebox.search.admin import SearchResultsAdminMixin
from archivebox.core.host_utils import build_snapshot_url, build_web_url
from archivebox.hooks import get_plugin_icon, get_plugin_name, get_plugins

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.workers.tasks import bg_archive_snapshots, bg_add

from archivebox.core.models import Tag, Snapshot, ArchiveResult
from archivebox.core.admin_archiveresults import render_archiveresults_list
from archivebox.core.widgets import TagEditorWidget, InlineTagEditorWidget


# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': [], 'CAN_UPGRADE': False}
GLOBAL_CONTEXT = {}


@lru_cache(maxsize=1)
def _plugin_sort_order() -> dict[str, int]:
    return {get_plugin_name(plugin): idx for idx, plugin in enumerate(get_plugins())}


@lru_cache(maxsize=256)
def _expected_snapshot_hook_total(config_json: str) -> int:
    from archivebox.hooks import discover_hooks

    try:
        config = json.loads(config_json) if config_json else {}
    except Exception:
        return 0

    return len(discover_hooks("Snapshot", config=config))


class SnapshotActionForm(ActionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define tags field in __init__ to avoid database access during app initialization
        self.fields["tags"] = forms.CharField(
            label="",
            required=False,
            widget=TagEditorWidget(),
        )

    def clean_tags(self):
        """Parse comma-separated tag names into Tag objects."""
        tags_str = self.cleaned_data.get("tags", "")
        if not tags_str:
            return []

        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        tags = []
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(
                name__iexact=name,
                defaults={"name": name},
            )
            # Use the existing tag if found by case-insensitive match
            tag = Tag.objects.filter(name__iexact=name).first() or tag
            tags.append(tag)
        return tags

    # TODO: allow selecting actions for specific extractor plugins? is this useful?
    # plugin = forms.ChoiceField(
    #     choices=ArchiveResult.PLUGIN_CHOICES,
    #     required=False,
    #     widget=forms.MultileChoiceField(attrs={'class': "form-control"})
    # )


class TagNameListFilter(admin.SimpleListFilter):
    title = "By tag name"
    parameter_name = "tag"

    def lookups(self, request, model_admin):
        return [(str(tag.pk), tag.name) for tag in Tag.objects.order_by("name")]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(tags__id=self.value())
        return queryset


class SnapshotAdminForm(forms.ModelForm):
    """Custom form for Snapshot admin with tag editor widget."""

    tags_editor = forms.CharField(
        label="Tags",
        required=False,
        widget=TagEditorWidget(),
        help_text="Type tag names and press Enter or Space to add. Click × to remove.",
    )

    class Meta:
        model = Snapshot
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize tags_editor with current tags
        if self.instance and self.instance.pk:
            self.initial["tags_editor"] = ",".join(
                sorted(tag.name for tag in self.instance.tags.all()),
            )

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Handle tags_editor field
        if commit:
            instance.save()
            save_m2m = getattr(self, "_save_m2m", None)
            if callable(save_m2m):
                save_m2m()

            # Parse and save tags from tags_editor
            tags_str = self.cleaned_data.get("tags_editor", "")
            if tags_str:
                tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
                tags = []
                for name in tag_names:
                    tag, _ = Tag.objects.get_or_create(
                        name__iexact=name,
                        defaults={"name": name},
                    )
                    tag = Tag.objects.filter(name__iexact=name).first() or tag
                    tags.append(tag)
                instance.tags.set(tags)
            else:
                instance.tags.clear()

        return instance


class SnapshotAdmin(SearchResultsAdminMixin, ConfigEditorMixin, BaseModelAdmin):
    form = SnapshotAdminForm
    list_display = ("created_at", "preview_icon", "title_str", "tags_inline", "status_with_progress", "files", "size_with_stats")
    sort_fields = ("title_str", "created_at", "status", "crawl")
    readonly_fields = (
        "admin_actions",
        "snapshot_summary",
        "url_favicon",
        "tags_badges",
        "imported_timestamp",
        "created_at",
        "modified_at",
        "downloaded_at",
        "output_dir",
        "archiveresults_list",
    )
    search_fields = ("id", "url", "timestamp", "title", "tags__name")
    list_filter = ("created_at", "downloaded_at", "archiveresult__status", "crawl__created_by", TagNameListFilter)

    fieldsets = (
        (
            "Actions",
            {
                "fields": ("admin_actions",),
                "classes": ("card", "actions-card"),
            },
        ),
        (
            "Snapshot",
            {
                "fields": ("snapshot_summary",),
                "classes": ("card",),
            },
        ),
        (
            "URL",
            {
                "fields": (("url_favicon", "url"), ("title", "tags_badges")),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Tags",
            {
                "fields": ("tags_editor",),
                "classes": ("card",),
            },
        ),
        (
            "Status",
            {
                "fields": ("status", "retry_at"),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("bookmarked_at", "created_at", "modified_at", "downloaded_at"),
                "classes": ("card",),
            },
        ),
        (
            "Relations",
            {
                "fields": ("crawl",),
                "classes": ("card",),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "description": '<span style="display:block; margin:-4px 0 6px; font-size:11px; line-height:1.35; color:#94a3b8;">Uses <code>Crawl.config</code> by default. Only set per-snapshot overrides here when needed.</span>',
                "classes": ("card",),
            },
        ),
        (
            "Files",
            {
                "fields": ("output_dir",),
                "classes": ("card",),
            },
        ),
        (
            "Archive Results",
            {
                "fields": ("archiveresults_list",),
                "classes": ("card", "wide"),
            },
        ),
    )

    ordering = ["-created_at"]
    actions = ["add_tags", "remove_tags", "resnapshot_snapshot", "update_snapshots", "overwrite_snapshots", "delete_snapshots"]
    inlines = []  # Removed TagInline, using TagEditorWidget instead
    list_per_page = min(max(5, SERVER_CONFIG.SNAPSHOTS_PER_PAGE), 5000)

    action_form = SnapshotActionForm
    paginator = AcceleratedPaginator

    save_on_top = True
    show_full_result_count = False

    def changelist_view(self, request, extra_context=None):
        self.request = request
        extra_context = extra_context or {}
        
        failed_snapshots = self.get_failed_snapshots()
        extra_context["failed_snapshots_count"] = failed_snapshots.count()
        
        try:
            return super().changelist_view(request, extra_context | GLOBAL_CONTEXT)
        except Exception as e:
            self.message_user(request, f"Error occurred while loading the page: {str(e)} {request.GET} {request.POST}")
            return super().changelist_view(request, GLOBAL_CONTEXT)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not actions:
            return {}
        actions.pop("delete_selected", None)
        return actions

    def get_snapshot_view_url(self, obj: Snapshot) -> str:
        return build_snapshot_url(str(obj.id), request=getattr(self, "request", None))

    def get_snapshot_files_url(self, obj: Snapshot) -> str:
        return f"{build_snapshot_url(str(obj.id), request=getattr(self, 'request', None))}/?files=1"

    def get_snapshot_zip_url(self, obj: Snapshot) -> str:
        return f"{self.get_snapshot_files_url(obj)}&download=zip"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("grid/", self.admin_site.admin_view(self.grid_view), name="grid"),
            path("delete-all-failed/", self.admin_site.admin_view(self.delete_all_failed_view), name="core_snapshot_delete_all_failed"),
            path("<path:object_id>/redo-failed/", self.admin_site.admin_view(self.redo_failed_view), name="core_snapshot_redo_failed"),
            path("<path:object_id>/export-markdown/", self.admin_site.admin_view(self.export_markdown_view), name="core_snapshot_export_markdown"),
        ]
        return custom_urls + urls

    def get_failed_snapshots(self):
        """Get all snapshots that have at least one failed ArchiveResult."""
        from archivebox.core.models import ArchiveResult
        
        failed_snapshot_ids = ArchiveResult.objects.filter(
            status=ArchiveResult.StatusChoices.FAILED
        ).values_list("snapshot_id", flat=True).distinct()
        
        return Snapshot.objects.filter(id__in=failed_snapshot_ids)

    def delete_all_failed_view(self, request):
        """Delete all snapshots that have failed ArchiveResults."""
        from django.db import transaction
        from django.shortcuts import redirect
        
        if request.method != "POST":
            messages.warning(request, "Please use POST method to delete failed snapshots.")
            return redirect("admin:core_snapshot_changelist")
        
        failed_snapshots = self.get_failed_snapshots()
        total = failed_snapshots.count()
        
        if total == 0:
            messages.info(request, "No failed snapshots found.")
            return redirect("admin:core_snapshot_changelist")
        
        ids_to_delete = list(failed_snapshots.values_list("pk", flat=True))
        
        with transaction.atomic():
            deleted_count, _ = Snapshot.objects.filter(pk__in=ids_to_delete).delete()
        
        messages.success(
            request,
            mark_safe(
                f"Successfully deleted {total} failed Snapshots ({deleted_count} total objects including related records). "
                f"Don't forget to scrub URLs from import logs (data/sources) and error logs (data/logs) if needed."
            ),
        )
        
        return redirect("admin:core_snapshot_changelist")

    def redo_failed_view(self, request, object_id):
        snapshot = get_object_or_404(Snapshot, pk=object_id)

        if request.method == "POST":
            retried = snapshot.retry_failed_archiveresults()
            if retried:
                messages.success(
                    request,
                    f"Queued {retried} failed/skipped extractors for retry on this snapshot.",
                )
            else:
                messages.info(
                    request,
                    "No failed/skipped extractors were found on this snapshot.",
                )

        return redirect(snapshot.admin_change_url)

    def _html_to_markdown(self, html_content: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return self._simple_html_to_markdown(html_content)
        
        soup = BeautifulSoup(html_content, "html.parser")
        
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
        
        text_parts = []
        
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li", "a", "img", "blockquote", "pre", "code", "strong", "em", "b", "i", "br"]):
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(element.name[1])
                text_parts.append(f"\n{'#' * level} {element.get_text().strip()}\n")
            elif element.name == "p":
                text = element.get_text().strip()
                if text:
                    text_parts.append(f"{text}\n\n")
            elif element.name in ["ul", "ol"]:
                items = element.find_all("li", recursive=False)
                for i, item in enumerate(items, 1):
                    prefix = "- " if element.name == "ul" else f"{i}. "
                    text_parts.append(f"{prefix}{item.get_text().strip()}\n")
                text_parts.append("\n")
            elif element.name == "a":
                href = element.get("href", "")
                text = element.get_text().strip() or href
                if href and text:
                    text_parts.append(f"[{text}]({href})")
            elif element.name == "img":
                src = element.get("src", "")
                alt = element.get("alt", "") or "image"
                if src:
                    text_parts.append(f"![{alt}]({src})\n\n")
            elif element.name == "blockquote":
                text = element.get_text().strip()
                if text:
                    for line in text.split("\n"):
                        text_parts.append(f"> {line.strip()}\n")
                    text_parts.append("\n")
            elif element.name == "pre":
                code = element.get_text()
                text_parts.append(f"\n```\n{code}\n```\n\n")
            elif element.name == "code":
                if element.parent and element.parent.name != "pre":
                    text_parts.append(f"`{element.get_text()}`")
            elif element.name in ["strong", "b"]:
                text = element.get_text().strip()
                if text:
                    text_parts.append(f"**{text}**")
            elif element.name in ["em", "i"]:
                text = element.get_text().strip()
                if text:
                    text_parts.append(f"*{text}*")
            elif element.name == "br":
                text_parts.append("\n")
        
        return "".join(text_parts).strip()

    def _simple_html_to_markdown(self, html_content: str) -> str:
        text = html_content
        
        text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<h[4-6][^>]*>(.*?)</h[4-6]>', r'\n#### \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*>', r'![\2](\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*>', r'![image](\1)', text, flags=re.IGNORECASE)
        
        text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', r'\n```\n\1\n```\n', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=re.IGNORECASE | re.DOTALL)
        
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        
        text = re.sub(r'<[^>]+>', ' ', text)
        
        text = re.sub(r' {2,}', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()

    def _read_file_from_snapshot(self, snapshot: Snapshot, relative_path: str) -> str | None:
        try:
            file_path = Path(snapshot.output_dir) / relative_path
            if file_path.exists() and file_path.is_file():
                return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return None

    def _get_article_content_from_snapshot(self, snapshot: Snapshot) -> tuple[str | None, str]:
        readability_result = snapshot.archiveresult_set.filter(
            plugin="readability",
            status="succeeded"
        ).first()
        
        if readability_result:
            readability_html = self._read_file_from_snapshot(snapshot, "readability/content.html")
            if readability_html:
                return self._html_to_markdown(readability_html), "readability"
        
        singlefile_result = snapshot.archiveresult_set.filter(
            plugin="singlefile",
            status="succeeded"
        ).first()
        
        if singlefile_result:
            singlefile_html = self._read_file_from_snapshot(snapshot, "singlefile.html")
            if singlefile_html:
                return self._html_to_markdown(singlefile_html), "singlefile"
        
        dom_result = snapshot.archiveresult_set.filter(
            plugin="dom",
            status="succeeded"
        ).first()
        
        if dom_result:
            dom_html = self._read_file_from_snapshot(snapshot, "dom.html")
            if dom_html:
                return self._html_to_markdown(dom_html), "dom"
        
        wget_result = snapshot.archiveresult_set.filter(
            plugin="wget",
            status="succeeded"
        ).first()
        
        if wget_result:
            output_files = wget_result.output_file_map()
            for file_path in output_files.keys():
                if file_path.endswith(".html") or file_path.endswith(".htm"):
                    html_content = self._read_file_from_snapshot(snapshot, file_path)
                    if html_content:
                        return self._html_to_markdown(html_content), "wget"
        
        return None, "none"

    def _generate_markdown_from_snapshot(self, snapshot: Snapshot) -> str:
        title = snapshot.title or snapshot.url
        url = snapshot.url
        tags = ", ".join(tag.name for tag in snapshot.tags.all()) if snapshot.tags.exists() else "无标签"
        bookmarked_at = snapshot.bookmarked_at.strftime("%Y-%m-%d %H:%M:%S") if snapshot.bookmarked_at else "未知"
        downloaded_at = snapshot.downloaded_at.strftime("%Y-%m-%d %H:%M:%S") if snapshot.downloaded_at else "未知"
        timestamp = snapshot.timestamp
        snapshot_id = str(snapshot.id)
        
        article_content, source = self._get_article_content_from_snapshot(snapshot)
        
        archive_results = snapshot.archiveresult_set.filter(status="succeeded").order_by("start_ts")
        archive_files_info = []
        for result in archive_results:
            files = result.output_file_paths()
            if files:
                for file_path in files:
                    file_size = result.output_size or 0
                    archive_files_info.append(f"- `{file_path}` ({result.plugin})")
        
        md_parts = []
        
        md_parts.append(f"# {title}")
        md_parts.append(f"\n")
        
        md_parts.append(f"**原始URL**: [{url}]({url})")
        md_parts.append(f"\n")
        md_parts.append(f"**标签**: {tags}")
        md_parts.append(f"\n")
        md_parts.append(f"**收藏时间**: {bookmarked_at}")
        md_parts.append(f"\n")
        md_parts.append(f"**下载时间**: {downloaded_at}")
        md_parts.append(f"\n")
        md_parts.append(f"**快照ID**: {snapshot_id}")
        md_parts.append(f"\n")
        md_parts.append(f"**时间戳**: {timestamp}")
        md_parts.append(f"\n")
        
        if article_content:
            md_parts.append(f"\n---\n")
            md_parts.append(f"## 文章内容 (来源: {source})")
            md_parts.append(f"\n")
            md_parts.append(article_content)
        else:
            md_parts.append(f"\n---\n")
            md_parts.append(f"## 文章内容")
            md_parts.append(f"\n")
            md_parts.append(f"*未提取到可读的文章内容。可以通过以下方式查看原始归档：*")
            md_parts.append(f"\n")
            md_parts.append(f"- 查看 SingleFile 保存的完整页面")
            md_parts.append(f"\n")
            md_parts.append(f"- 查看截图或PDF文件")
            md_parts.append(f"\n")
        
        if archive_files_info:
            md_parts.append(f"\n---\n")
            md_parts.append(f"## 归档文件")
            md_parts.append(f"\n")
            md_parts.append("\n".join(archive_files_info))
            md_parts.append(f"\n")
        
        md_parts.append(f"\n---\n")
        md_parts.append(f"*由 ArchiveBox 于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 导出*")
        
        return "\n".join(md_parts)

    def export_markdown_view(self, request, object_id):
        snapshot = get_object_or_404(Snapshot, pk=object_id)
        
        markdown_content = self._generate_markdown_from_snapshot(snapshot)
        
        safe_title = re.sub(r'[^\w\s-]', '', snapshot.title or 'untitled')
        safe_title = re.sub(r'[-\s]+', '-', safe_title).strip('-_')
        filename = f"{safe_title or 'archive'}_{snapshot.timestamp}.md"
        
        response = HttpResponse(
            markdown_content.encode('utf-8'),
            content_type='text/markdown; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response

    # def get_queryset(self, request):
    #     # tags_qs = SnapshotTag.objects.all().select_related('tag')
    #     # prefetch = Prefetch('snapshottag_set', queryset=tags_qs)

    #     self.request = request
    #     return super().get_queryset(request).prefetch_related('archiveresult_set').distinct()  # .annotate(archiveresult_count=Count('archiveresult'))
    def get_queryset(self, request):
        self.request = request
        ordering_fields = self._get_ordering_fields(request)
        needs_size_sort = "size_with_stats" in ordering_fields
        needs_files_sort = "files" in ordering_fields
        needs_tags_sort = "tags_inline" in ordering_fields
        is_change_view = getattr(getattr(request, "resolver_match", None), "url_name", "") == "core_snapshot_change"

        prefetch_qs = ArchiveResult.objects.only(
            "id",
            "snapshot_id",
            "plugin",
            "status",
            "output_size",
            "output_files",
            "output_str",
        )
        if not is_change_view:
            prefetch_qs = prefetch_qs.filter(Q(status="succeeded"))

        qs = (
            super()
            .get_queryset(request)
            .select_related("crawl__created_by")
            .defer("config", "notes")
            .prefetch_related("tags")
            .prefetch_related(Prefetch("archiveresult_set", queryset=prefetch_qs))
        )

        if needs_size_sort:
            qs = qs.annotate(
                output_size_sum=Coalesce(
                    Sum("archiveresult__output_size"),
                    0,
                ),
            )

        if needs_files_sort:
            qs = qs.annotate(
                ar_succeeded_count=Count(
                    "archiveresult",
                    filter=Q(archiveresult__status="succeeded"),
                ),
            )
        if needs_tags_sort:
            qs = qs.annotate(tag_count=Count("tags", distinct=True))

        return qs

    @admin.display(description="Imported Timestamp")
    def imported_timestamp(self, obj):
        context = RequestContext(
            self.request,
            {
                "bookmarked_date": obj.bookmarked_at,
                "timestamp": obj.timestamp,
            },
        )

        html = Template("""{{bookmarked_date}} (<code>{{timestamp}}</code>)""")
        return mark_safe(html.render(context))

        # pretty_time = obj.bookmarked.strftime('%Y-%m-%d %H:%M:%S')
        # return f'{pretty_time} ({obj.timestamp})'

    # TODO: figure out a different way to do this, you cant nest forms so this doenst work
    # def action(self, obj):
    #     # csrfmiddlewaretoken: Wa8UcQ4fD3FJibzxqHN3IYrrjLo4VguWynmbzzcPYoebfVUnDovon7GEMYFRgsh0
    #     # action: update_snapshots
    #     # select_across: 0
    #     # _selected_action: 76d29b26-2a88-439e-877c-a7cca1b72bb3
    #     return format_html(
    #         '''
    #             <form action="/admin/core/snapshot/" method="post" onsubmit="e => e.stopPropagation()">
    #                 <input type="hidden" name="csrfmiddlewaretoken" value="{}">
    #                 <input type="hidden" name="_selected_action" value="{}">
    #                 <button name="update_snapshots">Check</button>
    #                 <button name="update_titles">Pull title + favicon</button>
    #                 <button name="update_snapshots">Update</button>
    #                 <button name="overwrite_snapshots">Re-Archive (overwrite)</button>
    #                 <button name="delete_snapshots">Permanently delete</button>
    #             </form>
    #         ''',
    #         csrf.get_token(self.request),
    #         obj.pk,
    #     )

    @admin.display(description="")
    def admin_actions(self, obj):
        summary_url = self.get_snapshot_view_url(obj)
        files_url = self.get_snapshot_files_url(obj)
        zip_url = self.get_snapshot_zip_url(obj)
        export_md_url = f"/admin/core/snapshot/{obj.pk}/export-markdown/"
        redo_failed_url = f"/admin/core/snapshot/{obj.pk}/redo-failed/"
        return format_html(
            """
            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📄 View Snapshot
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📁 All files
                </a>
                <a class="btn archivebox-zip-button" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1d4ed8; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   data-loading-label="Preparing..."
                   onclick="return window.archiveboxHandleZipClick(this, event);"
                   onmouseover="this.style.background='#dbeafe'; this.style.borderColor='#93c5fd';"
                   onmouseout="this.style.background='#eff6ff'; this.style.borderColor='#bfdbfe';">
                    <span class="archivebox-zip-spinner" aria-hidden="true"></span>
                    <span class="archivebox-zip-label">⬇ Download Zip</span>
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; color: #166534; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#dcfce7'; this.style.borderColor='#4ade80';"
                   onmouseout="this.style.background='#f0fdf4'; this.style.borderColor='#86efac';">
                    📝 Export Markdown
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   target="_blank"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    🔗 Original URL
                </a>

                <span style="border-left: 1px solid #e2e8f0; height: 24px; margin: 0 4px;"></span>

                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1e40af; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Create a fresh new snapshot of this URL"
                   onmouseover="this.style.background='#dbeafe';"
                   onmouseout="this.style.background='#eff6ff';">
                    🆕 Snapshot Again
                </a>
                <button type="submit"
                        formaction="{}"
                        formmethod="post"
                        formnovalidate
                        class="btn"
                        style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; color: #065f46; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s; cursor: pointer;"
                        title="Redo failed extractors (missing outputs)"
                        onmouseover="this.style.background='#d1fae5';"
                        onmouseout="this.style.background='#ecfdf5';">
                    🔁 Retry Failed Extractors
                </button>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; color: #92400e; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Re-run all extractors (overwrite existing)"
                   onmouseover="this.style.background='#fef3c7';"
                   onmouseout="this.style.background='#fffbeb';">
                    🔄 Reset &amp; Retry All Extractors
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; color: #991b1b; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Permanently delete this snapshot"
                   onmouseover="this.style.background='#fee2e2';"
                   onmouseout="this.style.background='#fef2f2';">
                    ☠️ Delete
                </a>
            </div>
            """,
            summary_url,
            files_url,
            zip_url,
            export_md_url,
            obj.url,
            obj.pk,
            redo_failed_url,
            obj.pk,
            obj.pk,
        )

    def status_info(self, obj):
        favicon_url = build_snapshot_url(str(obj.id), "favicon.ico")
        return format_html(
            """
            Archived: {} ({} files {}) &nbsp; &nbsp;
            Favicon: <img src="{}" style="height: 20px"/> &nbsp; &nbsp;
            Extension: {} &nbsp; &nbsp;
            """,
            "✅" if obj.is_archived else "❌",
            obj.num_outputs,
            self.size(obj) or "0kb",
            favicon_url,
            obj.extension or "-",
        )

    @admin.display(description="Archive Results")
    def archiveresults_list(self, obj):
        return render_archiveresults_list(obj.archiveresult_set.all())

    @admin.display(
        description="Title",
        ordering="title",
    )
    def title_str(self, obj):
        title_raw = (obj.title or "").strip()
        url_raw = (obj.url or "").strip()
        title_normalized = title_raw.lower()
        url_normalized = url_raw.lower()
        show_title = bool(title_raw) and title_normalized != "pending..." and title_normalized != url_normalized
        css_class = "fetched" if show_title else "pending"

        detail_url = build_web_url(f"/{obj.archive_path_from_db}/index.html")
        title_html = ""
        if show_title:
            title_html = format_html(
                '<a href="{}"><b class="status-{}">{}</b></a>',
                detail_url,
                css_class,
                urldecode(htmldecode(title_raw))[:128],
            )

        return format_html(
            "{}"
            '<div style="font-size: 11px; color: #64748b; margin-top: 2px;">'
            '<a href="{}"><code style="user-select: all;">{}</code></a>'
            "</div>",
            title_html,
            url_raw or obj.url,
            (url_raw or obj.url)[:128],
        )

    @admin.display(description="Tags", ordering="tag_count")
    def tags_inline(self, obj):
        widget = InlineTagEditorWidget(snapshot_id=str(obj.pk))
        tags = self._get_prefetched_tags(obj)
        tags_html = widget.render(
            name=f"tags_{obj.pk}",
            value=tags if tags is not None else obj.tags.all(),
            attrs={"id": f"tags_{obj.pk}"},
            snapshot_id=str(obj.pk),
        )
        return mark_safe(f'<span class="tags-inline-editor">{tags_html}</span>')

    @admin.display(description="Tags")
    def tags_badges(self, obj):
        widget = InlineTagEditorWidget(snapshot_id=str(obj.pk), editable=False)
        tags = self._get_prefetched_tags(obj)
        tags_html = widget.render(
            name=f"tags_readonly_{obj.pk}",
            value=tags if tags is not None else obj.tags.all(),
            attrs={"id": f"tags_readonly_{obj.pk}"},
            snapshot_id=str(obj.pk),
        )
        return mark_safe(f'<span class="tags-inline-editor">{tags_html}</span>')

    def _get_preview_data(self, obj):
        results = self._get_prefetched_results(obj)
        if results is not None:
            has_screenshot = any(r.plugin == "screenshot" for r in results)
            has_favicon = any(r.plugin == "favicon" for r in results)
        else:
            available_plugins = set(obj.archiveresult_set.filter(plugin__in=("screenshot", "favicon")).values_list("plugin", flat=True))
            has_screenshot = "screenshot" in available_plugins
            has_favicon = "favicon" in available_plugins

        if not has_screenshot and not has_favicon:
            return None

        if has_screenshot:
            img_url = build_snapshot_url(str(obj.id), "screenshot/screenshot.png")
            fallbacks = [
                build_snapshot_url(str(obj.id), "screenshot.png"),
                build_snapshot_url(str(obj.id), "favicon/favicon.ico"),
                build_snapshot_url(str(obj.id), "favicon.ico"),
            ]
            img_alt = "Screenshot"
            preview_class = "screenshot"
        else:
            img_url = build_snapshot_url(str(obj.id), "favicon/favicon.ico")
            fallbacks = [
                build_snapshot_url(str(obj.id), "favicon.ico"),
            ]
            img_alt = "Favicon"
            preview_class = "favicon"

        fallback_list = ",".join(fallbacks)
        onerror_js = (
            "this.dataset.fallbacks && this.dataset.fallbacks.length ? "
            "(this.src=this.dataset.fallbacks.split(',').shift(), "
            "this.dataset.fallbacks=this.dataset.fallbacks.split(',').slice(1).join(',')) : "
            "this.remove()"
        )

        return {
            "img_url": img_url,
            "img_alt": img_alt,
            "preview_class": preview_class,
            "onerror_js": onerror_js,
            "fallback_list": fallback_list,
        }

    @admin.display(description="", empty_value="")
    def url_favicon(self, obj):
        preview = self._get_preview_data(obj)
        if not preview:
            return ""

        favicon_url = build_snapshot_url(str(obj.id), "favicon/favicon.ico")
        fallback_list = ",".join([build_snapshot_url(str(obj.id), "favicon.ico")])
        onerror_js = (
            "this.dataset.fallbacks && this.dataset.fallbacks.length ? "
            "(this.src=this.dataset.fallbacks.split(',').shift(), "
            "this.dataset.fallbacks=this.dataset.fallbacks.split(',').slice(1).join(',')) : "
            "this.closest('a') && this.closest('a').remove()"
        )

        return format_html(
            '<a href="{}" title="Open favicon" style="display:inline-flex; align-items:center; justify-content:center; width:32px; height:32px;">'
            '<img src="{}" alt="Favicon" decoding="async" loading="lazy" onerror="{}" data-fallbacks="{}" '
            'style="display:block; width:24px; height:24px; border-radius:6px; border:1px solid #e2e8f0; background:#fff; object-fit:contain; padding:2px;">'
            "</a>",
            favicon_url,
            favicon_url,
            onerror_js,
            fallback_list,
        )

    @admin.display(description="Preview", empty_value="")
    def preview_icon(self, obj):
        preview = self._get_preview_data(obj)
        if not preview:
            return None

        return format_html(
            '<img src="{}" alt="{}" class="snapshot-preview {}" decoding="async" loading="lazy" onerror="{}" data-fallbacks="{}">',
            preview["img_url"],
            preview["img_alt"],
            preview["preview_class"],
            preview["onerror_js"],
            preview["fallback_list"],
        )

    @admin.display(description=" ", empty_value="")
    def snapshot_summary(self, obj):
        preview = self._get_preview_data(obj)
        stats = self._get_progress_stats(obj)
        archive_size = stats["output_size"] or 0
        size_txt = printable_filesize(archive_size) if archive_size else "pending"
        screenshot_html = ""

        if preview:
            screenshot_html = format_html(
                '<a href="{href}" title="Open snapshot live view" style="display:block; flex:0 0 220px; width:220px;">'
                '<img src="{src}" alt="{alt}" decoding="async" loading="lazy" onerror="{onerror}" data-fallbacks="{fallbacks}" '
                'style="display:block; width:100%; max-width:220px; aspect-ratio: 16 / 10; object-fit: cover; object-position: top; '
                'border-radius: 10px; border: 1px solid #e2e8f0; background: #f8fafc;">'
                "</a>",
                href=build_web_url(f"/{obj.archive_path}"),
                src=preview["img_url"],
                alt=preview["img_alt"],
                onerror=preview["onerror_js"],
                fallbacks=preview["fallback_list"],
            )

        return format_html(
            '<div style="display:flex; gap:16px; align-items:flex-start;">'
            "{}"
            '<div style="min-width:0; flex:1;">'
            '<div style="font: 600 12px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">snap_dir size</div>'
            '<div style="font: 700 28px/1.1 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif; color:#0f172a; margin-bottom:8px;">{}</div>'
            '<div style="font-size:13px; line-height:1.5; color:#64748b;">'
            'Open <a href="{}"><code>{}</code></a> to inspect files.'
            "</div>"
            "</div>"
            "</div>",
            screenshot_html,
            size_txt,
            build_web_url(f"/{obj.archive_path}"),
            obj.archive_path,
        )

    @admin.display(
        description="Files Saved",
        ordering="ar_succeeded_count",
    )
    def files(self, obj):
        results = self._get_prefetched_results(obj)
        if results is None:
            results = obj.archiveresult_set.only("plugin", "status", "output_files", "output_str")

        plugins_with_output: dict[str, ArchiveResult] = {}
        for result in results:
            if result.status != ArchiveResult.StatusChoices.SUCCEEDED:
                continue
            if not (result.output_files or str(result.output_str or "").strip()):
                continue
            plugins_with_output.setdefault(result.plugin, result)

        if not plugins_with_output:
            return mark_safe('<span style="opacity: 0.35;">...</span>')

        sorted_results = sorted(
            plugins_with_output.values(),
            key=lambda result: (_plugin_sort_order().get(result.plugin, 9999), result.plugin),
        )
        output = [
            format_html(
                '<a href="{}" class="exists-True" title="{}">{}</a>',
                self._result_output_href(obj, result),
                result.plugin,
                get_plugin_icon(result.plugin),
            )
            for result in sorted_results
        ]

        return format_html(
            '<span class="files-icons files-icons--compact" style="font-size: 1em; opacity: 0.8;">{}</span>',
            mark_safe("".join(output)),
        )

    @admin.display(
        # ordering='archiveresult_count'
    )
    def size(self, obj):
        archive_size = self._get_progress_stats(obj)["output_size"] or 0
        if archive_size:
            size_txt = printable_filesize(archive_size)
            if archive_size > 52428800:
                size_txt = mark_safe(f"<b>{size_txt}</b>")
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')
        return format_html(
            '<a href="{}" title="View all files">{}</a>',
            build_web_url(f"/{obj.archive_path}"),
            size_txt,
        )

    @admin.display(
        description="Status",
        ordering="status",
    )
    def status_with_progress(self, obj):
        """Show status with progress bar for in-progress snapshots."""
        stats = self._get_progress_stats(obj)

        # Status badge colors
        status_colors = {
            "queued": ("#f59e0b", "#fef3c7"),  # amber
            "started": ("#3b82f6", "#dbeafe"),  # blue
            "sealed": ("#10b981", "#d1fae5"),  # green
            "succeeded": ("#10b981", "#d1fae5"),  # green
            "failed": ("#ef4444", "#fee2e2"),  # red
            "backoff": ("#f59e0b", "#fef3c7"),  # amber
            "skipped": ("#6b7280", "#f3f4f6"),  # gray
        }
        fg_color, bg_color = status_colors.get(obj.status, ("#6b7280", "#f3f4f6"))

        # For started snapshots, show progress bar
        if obj.status == "started" and stats["total"] > 0:
            percent = stats["percent"]
            running = stats["running"]
            succeeded = stats["succeeded"]
            failed = stats["failed"]

            return format_html(
                """<div style="min-width: 90px;">
                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                        <span class="snapshot-progress-spinner"></span>
                        <span style="font-size: 11px; color: #64748b;">{}/{} hooks</span>
                    </div>
                    <div style="background: #e2e8f0; border-radius: 4px; height: 6px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #10b981 0%, #10b981 {}%, #ef4444 {}%, #ef4444 {}%, #3b82f6 {}%, #3b82f6 100%);
                                    width: {}%; height: 100%; transition: width 0.3s;"></div>
                    </div>
                    <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">
                        ✓{} ✗{} ⏳{}
                    </div>
                </div>""",
                succeeded + failed + stats["skipped"],
                stats["total"],
                int(succeeded / stats["total"] * 100) if stats["total"] else 0,
                int(succeeded / stats["total"] * 100) if stats["total"] else 0,
                int((succeeded + failed) / stats["total"] * 100) if stats["total"] else 0,
                int((succeeded + failed) / stats["total"] * 100) if stats["total"] else 0,
                percent,
                succeeded,
                failed,
                running,
            )

        # For other statuses, show simple badge
        return format_html(
            '<span style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 500; background: {}; color: {};">{}</span>',
            bg_color,
            fg_color,
            obj.status.upper(),
        )

    @admin.display(
        description="Size",
        ordering="output_size_sum",
    )
    def size_with_stats(self, obj):
        """Show archive size with output size from archive results."""
        stats = self._get_progress_stats(obj)
        output_size = stats["output_size"]
        size_bytes = output_size or 0
        zip_url = self.get_snapshot_zip_url(obj)
        zip_link = format_html(
            '<a href="{}" class="archivebox-zip-button" data-loading-mode="spinner-only" onclick="return window.archiveboxHandleZipClick(this, event);" style="display:inline-flex; align-items:center; justify-content:center; gap:4px; width:48px; min-width:48px; height:22px; margin-top:4px; padding:0; box-sizing:border-box; border-radius:999px; border:1px solid #cbd5e1; background:#f8fafc; color:#64748b; font-size:10px; font-weight:600; line-height:1; text-decoration:none; transition:all 0.15s;" onmouseover="this.style.color=\'#1d4ed8\'; this.style.borderColor=\'#93c5fd\'; this.style.background=\'#eff6ff\';" onmouseout="this.style.color=\'#64748b\'; this.style.borderColor=\'#cbd5e1\'; this.style.background=\'#f8fafc\';"><span class="archivebox-zip-spinner" aria-hidden="true"></span><span class="archivebox-zip-label">⬇ ZIP</span></a>',
            zip_url,
        )

        if size_bytes:
            size_txt = printable_filesize(size_bytes)
            if size_bytes > 52428800:  # 50MB
                size_txt = mark_safe(f"<b>{size_txt}</b>")
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')

        # Show hook statistics
        if stats["total"] > 0:
            return format_html(
                '<a href="{}" title="View all files" style="white-space: nowrap;">'
                "{}</a>"
                '<div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">'
                "{}/{} hooks</div>"
                "{}",
                build_web_url(f"/{obj.archive_path_from_db}"),
                size_txt,
                stats["succeeded"],
                stats["total"],
                zip_link,
            )

        return format_html(
            '<a href="{}" title="View all files">{}</a>{}',
            build_web_url(f"/{obj.archive_path_from_db}"),
            size_txt,
            zip_link,
        )

    def _get_progress_stats(self, obj):
        results = self._get_prefetched_results(obj)
        if results is None:
            stats = obj.get_progress_stats()
            expected_total = self._get_expected_hook_total(obj)
            total = max(stats["total"], expected_total)
            completed = stats["succeeded"] + stats["failed"] + stats.get("skipped", 0) + stats.get("noresults", 0)
            stats["total"] = total
            stats["pending"] = max(total - completed - stats["running"], 0)
            stats["percent"] = int((completed / total * 100) if total > 0 else 0)
            return stats

        expected_total = self._get_expected_hook_total(obj)
        observed_total = len(results)
        total = max(observed_total, expected_total)
        succeeded = sum(1 for r in results if r.status == "succeeded")
        failed = sum(1 for r in results if r.status == "failed")
        running = sum(1 for r in results if r.status == "started")
        skipped = sum(1 for r in results if r.status == "skipped")
        noresults = sum(1 for r in results if r.status == "noresults")
        pending = max(total - succeeded - failed - running - skipped - noresults, 0)
        completed = succeeded + failed + skipped + noresults
        percent = int((completed / total * 100) if total > 0 else 0)
        is_sealed = obj.status not in (obj.StatusChoices.QUEUED, obj.StatusChoices.STARTED)
        output_size = None

        if hasattr(obj, "output_size_sum"):
            output_size = obj.output_size_sum or 0
        else:
            output_size = sum(r.output_size or 0 for r in results)

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "running": running,
            "pending": pending,
            "skipped": skipped,
            "noresults": noresults,
            "percent": percent,
            "output_size": output_size or 0,
            "is_sealed": is_sealed,
        }

    def _get_prefetched_results(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "archiveresult_set" in obj._prefetched_objects_cache:
            return obj.archiveresult_set.all()
        return None

    def _get_expected_hook_total(self, obj) -> int:
        from archivebox.config.configset import get_config

        try:
            config = get_config(crawl=obj.crawl, snapshot=obj)
            config_json = json.dumps(config, sort_keys=True, default=str, separators=(",", ":"))
            return _expected_snapshot_hook_total(config_json)
        except Exception:
            return 0

    def _get_prefetched_tags(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "tags" in obj._prefetched_objects_cache:
            return list(obj._prefetched_objects_cache["tags"])
        return None

    def _result_output_href(self, obj, result: ArchiveResult) -> str:
        ignored = {"stdout.log", "stderr.log", "hook.pid", "listener.pid", "cmd.sh"}

        for rel_path in result.output_file_paths():
            raw_path = str(rel_path or "").strip().lstrip("/")
            if not raw_path:
                continue
            basename = raw_path.rsplit("/", 1)[-1]
            if basename in ignored or raw_path.endswith((".pid", ".log", ".sh")):
                continue
            relative_path = raw_path if raw_path.startswith(f"{result.plugin}/") else f"{result.plugin}/{raw_path}"
            return f"/{obj.archive_path_from_db}/{relative_path}"

        raw_output = str(result.output_str or "").strip().lstrip("/")
        if raw_output and raw_output not in {".", "./"} and "://" not in raw_output and not raw_output.startswith("/"):
            relative_path = raw_output if raw_output.startswith(f"{result.plugin}/") else f"{result.plugin}/{raw_output}"
            return f"/{obj.archive_path_from_db}/{relative_path}"

        return f"/{obj.archive_path_from_db}/{result.plugin}/"

    def _get_ordering_fields(self, request):
        ordering = request.GET.get("o")
        if not ordering:
            return set()
        fields = set()
        for part in ordering.split("."):
            if not part:
                continue
            try:
                idx = abs(int(part)) - 1
            except ValueError:
                continue
            if 0 <= idx < len(self.list_display):
                fields.add(self.list_display[idx])
        return fields

    @admin.display(
        description="Original URL",
        ordering="url",
    )
    def url_str(self, obj):
        return format_html(
            '<a href="{}"><code style="user-select: all;">{}</code></a>',
            obj.url,
            obj.url[:128],
        )

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)

    def grid_view(self, request, extra_context=None):

        # cl = self.get_changelist_instance(request)

        # Save before monkey patching to restore for changelist list view
        admin_cls = type(self)
        saved_change_list_template = admin_cls.change_list_template
        saved_list_per_page = admin_cls.list_per_page
        saved_list_max_show_all = admin_cls.list_max_show_all

        # Monkey patch here plus core_tags.py
        admin_cls.change_list_template = "private_index_grid.html"
        admin_cls.list_per_page = SERVER_CONFIG.SNAPSHOTS_PER_PAGE
        admin_cls.list_max_show_all = admin_cls.list_per_page

        # Call monkey patched view
        rendered_response = self.changelist_view(request, extra_context=extra_context)

        # Restore values
        admin_cls.change_list_template = saved_change_list_template
        admin_cls.list_per_page = saved_list_per_page
        admin_cls.list_max_show_all = saved_list_max_show_all

        return rendered_response

    # for debugging, uncomment this to print all requests:
    # def changelist_view(self, request, extra_context=None):
    #     print('[*] Got request', request.method, request.POST)
    #     return super().changelist_view(request, extra_context=None)

    @admin.action(
        description="🔁 Redo Failed",
    )
    def update_snapshots(self, request, queryset):
        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": False, "out_dir": DATA_DIR})

        messages.success(
            request,
            f"Queued {queued} snapshots for re-archiving. The background runner will process them.",
        )

    @admin.action(
        description="🆕 Archive Now",
    )
    def resnapshot_snapshot(self, request, queryset):
        snapshots = list(queryset)
        if not snapshots:
            messages.info(request, "No snapshots selected.")
            return

        urls = "\n".join(snapshot.url for snapshot in snapshots if snapshot.url)
        if not urls:
            messages.info(request, "No valid snapshot URLs were found to archive.")
            return

        bg_add({"urls": urls})

        messages.success(
            request,
            f"Creating 1 new crawl with {len(snapshots)} fresh snapshots. The background runner will process them.",
        )

    @admin.action(
        description="🔄 Redo",
    )
    def overwrite_snapshots(self, request, queryset):
        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": True, "out_dir": DATA_DIR})

        messages.success(
            request,
            f"Queued {queued} snapshots for full re-archive (overwriting existing). The background runner will process them.",
        )

    @admin.action(
        description="🗑️ Delete",
    )
    def delete_snapshots(self, request, queryset):
        """Delete snapshots in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list("pk", flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Snapshot.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(
            request,
            mark_safe(
                f"Successfully deleted {total} Snapshots ({deleted_count} total objects including related records). Don't forget to scrub URLs from import logs (data/sources) and error logs (data/logs) if needed.",
            ),
        )

    @admin.action(
        description="+",
    )
    def add_tags(self, request, queryset):
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get("tags", "")
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        # Parse comma-separated tag names and get/create Tag objects
        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        tags = []
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(
                name__iexact=name,
                defaults={"name": name},
            )
            tag = Tag.objects.filter(name__iexact=name).first() or tag
            tags.append(tag)

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list("id", flat=True))
        num_snapshots = len(snapshot_ids)

        print("[+] Adding tags", [t.name for t in tags], "to", num_snapshots, "Snapshots")

        # Bulk create M2M relationships (1 query per tag, not per snapshot)
        for tag in tags:
            SnapshotTag.objects.bulk_create(
                [SnapshotTag(snapshot_id=sid, tag=tag) for sid in snapshot_ids],
                ignore_conflicts=True,  # Skip if relationship already exists
            )

        messages.success(
            request,
            f"Added {len(tags)} tag(s) to {num_snapshots} Snapshot(s).",
        )

    @admin.action(
        description="–",
    )
    def remove_tags(self, request, queryset):
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get("tags", "")
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        # Parse comma-separated tag names and find matching Tag objects (case-insensitive)
        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        tags = []
        for name in tag_names:
            tag = Tag.objects.filter(name__iexact=name).first()
            if tag:
                tags.append(tag)

        if not tags:
            messages.warning(request, "No matching tags found.")
            return

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list("id", flat=True))
        num_snapshots = len(snapshot_ids)
        tag_ids = [t.pk for t in tags]

        print("[-] Removing tags", [t.name for t in tags], "from", num_snapshots, "Snapshots")

        # Bulk delete M2M relationships (1 query total, not per snapshot)
        deleted_count, _ = SnapshotTag.objects.filter(
            snapshot_id__in=snapshot_ids,
            tag_id__in=tag_ids,
        ).delete()

        messages.success(
            request,
            f"Removed {len(tags)} tag(s) from {num_snapshots} Snapshot(s) ({deleted_count} associations deleted).",
        )
