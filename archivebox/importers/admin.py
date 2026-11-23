from copy import copy

from django.contrib import admin
from django.contrib.admin.options import IncorrectLookupParameters
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html

from archivebox.core.admin_site import archivebox_admin

from .diagnostics import diagnostics
from .models import ImporterRun


class ImporterRunAdmin(admin.ModelAdmin):
    list_display = ("run_link", "discovery", "item_count", "ai_sessions", "crawl_links")
    list_display_links = None
    list_per_page = 20
    list_max_show_all = 0
    show_full_result_count = False
    actions = None
    ordering = ("-created_at", "-id")

    def __init__(self, source_id):
        super().__init__(ImporterRun, archivebox_admin)
        self.source_id = source_id

    def get_queryset(self, request):
        return super().get_queryset(request).filter(source_id=self.source_id).select_related("crawl").defer("request", "result")

    def history(self, request, *, activity_loaded=False):
        request = copy(request)
        params = request.GET
        request.GET = params.copy()
        request.GET.clear()
        request.GET.update({"p": params.get("p", params.get("page", "1"))})
        if "o" in params:
            request.GET["o"] = params["o"]
        try:
            changelist = self.get_changelist_instance(request)
        except IncorrectLookupParameters:
            request.GET.pop("p", None)
            changelist = self.get_changelist_instance(request)
        changelist.result_list = list(changelist.result_list)
        if activity_loaded:
            for run in changelist.result_list:
                run.diagnostics = diagnostics(run)
        return changelist

    @admin.display(description="Run", ordering="created_at")
    def run_link(self, run):
        return format_html(
            '<a href="{}"><strong>{}</strong> · {}</a><br><small>{}</small>',
            reverse("importers:run", args=[run.pk]),
            run.get_action_display(),
            str(run.pk)[-8:],
            date_format(timezone.localtime(run.created_at), "SHORT_DATETIME_FORMAT"),
        )

    @admin.display(description="Discovery", ordering="status")
    def discovery(self, run):
        return render_to_string("importers/history_status.html", {"run": run})

    @admin.display(description="Items")
    def item_count(self, run):
        return len(run.items)

    @admin.display(description="AI sessions")
    def ai_sessions(self, run):
        if not getattr(run, "diagnostics", {}).get("sessions"):
            return "—"
        return render_to_string("importers/sessions.html", {"run": run}) or "—"

    @admin.display(description="Crawl / snapshots")
    def crawl_links(self, run):
        return render_to_string("importers/run_links.html", {"run": run})
