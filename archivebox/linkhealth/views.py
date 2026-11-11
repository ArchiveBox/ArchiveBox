from datetime import timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot

from .models import LinkCheck, LinkHealthSettings, LinkScan
from .service import enqueue


class ScheduleForm(forms.Form):
    interval_days = forms.IntegerField(
        min_value=0,
        max_value=365,
        label="Check every (days)",
        help_text="0 means manual checks only. Scheduled checks include newly saved snapshots.",
    )


class RecheckSelectionForm(forms.Form):
    snapshot_ids = forms.ModelMultipleChoiceField(queryset=Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED))

    def clean_snapshot_ids(self):
        snapshots = self.cleaned_data["snapshot_ids"]
        if snapshots.count() > 50:
            raise forms.ValidationError("Select at most 50 captures at a time.")
        return snapshots


def health_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Link checks require a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


@health_admin
@require_http_methods(["GET", "POST"])
def index(request):
    policy = LinkHealthSettings.objects.filter(pk=1).first()
    form = ScheduleForm(
        request.POST if request.method == "POST" else None,
        initial={"interval_days": policy.interval_days if policy else 0},
    )
    if request.method == "POST" and form.is_valid():
        days = form.cleaned_data["interval_days"]
        LinkHealthSettings.objects.update_or_create(
            pk=1,
            defaults={"interval_days": days, "next_scan_at": timezone.now() + timedelta(days=days) if days else None},
        )
        messages.success(request, "Link-check schedule saved.")
        return redirect("linkhealth:index")
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "recent")
    orderings = {
        "recent": ("-checked_at", "snapshot_id"),
        "oldest": ("checked_at", "snapshot_id"),
        "title": ("snapshot__title", "snapshot_id"),
    }
    if sort not in orderings:
        sort = "recent"
    checks = LinkCheck.objects.select_related("snapshot").order_by(*orderings[sort])
    if query:
        checks = checks.filter(Q(snapshot__title__icontains=query) | Q(checked_url__icontains=query))
    selected = request.GET.get("status", "")
    if selected in LinkCheck.Status.values:
        checks = checks.filter(status=selected)
    elif selected == "attention":
        checks = checks.exclude(status=LinkCheck.Status.OK)
    counts = dict(LinkCheck.objects.values_list("status").annotate(count=Count("snapshot_id")))
    attention = sum(count for status, count in counts.items() if status != LinkCheck.Status.OK)
    exact_groups = list(Snapshot.objects.values("url").annotate(count=Count("pk")).filter(count__gt=1).order_by("-count", "url")[:20])
    for group in exact_groups:
        group["snapshots"] = Snapshot.objects.filter(url=group["url"]).order_by("-created_at").only("id", "title", "created_at", "url")[:5]
    equivalent_groups = list(
        LinkCheck.objects.values("normalized_url")
        .annotate(count=Count("snapshot_id"), distinct_urls=Count("checked_url", distinct=True))
        .filter(distinct_urls__gt=1)
        .order_by("-count", "normalized_url")[:20],
    )
    for group in equivalent_groups:
        group["checks"] = LinkCheck.objects.filter(normalized_url=group["normalized_url"]).select_related("snapshot")[:5]
    content_groups = list(
        LinkCheck.objects.exclude(content_hash="")
        .values("content_hash")
        .annotate(count=Count("snapshot_id"))
        .filter(count__gt=1)
        .order_by("-count", "content_hash")[:20],
    )
    for group in content_groups:
        group["checks"] = LinkCheck.objects.filter(content_hash=group["content_hash"]).select_related("snapshot")[:5]
    return render(
        request,
        "linkhealth/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Link health",
            "form": form,
            "policy": policy,
            "checks": Paginator(checks, 50).get_page(request.GET.get("page")),
            "statuses": LinkCheck.Status.choices,
            "selected_status": selected,
            "query": query,
            "sort": sort,
            "duplicate_review": request.GET.get("review") == "duplicates",
            "attention_count": attention,
            "restricted_count": counts.get(LinkCheck.Status.RESTRICTED, 0),
            "duplicates": exact_groups,
            "equivalent_groups": equivalent_groups,
            "content_groups": content_groups,
            "runs": LinkScan.objects.order_by("-created_at")[:5],
            "active": LinkScan.objects.filter(status__in=["queued", "running"]).first(),
            "snapshot_count": Snapshot.objects.count(),
            "checked_count": LinkCheck.objects.count(),
            "broken_count": LinkCheck.objects.filter(status=LinkCheck.Status.BROKEN).count(),
        },
    )


@health_admin
@require_POST
def scan(request):
    enqueue()
    messages.success(request, "Link check queued. Saved captures are retained; results appear as the worker checks them.")
    return redirect("linkhealth:index")


@health_admin
@require_POST
def retry(request, snapshot_id):
    snapshot = get_object_or_404(Snapshot, pk=snapshot_id, status=Snapshot.StatusChoices.SEALED)
    ids = [str(snapshot.pk)]
    run = enqueue(snapshot_ids=ids)
    if run.snapshot_ids == ids:
        messages.success(request, "This link is queued for another check. Its saved capture is preserved.")
    else:
        messages.info(request, "Another link check is already queued or running. Wait for it to finish before checking this link again.")
    return redirect("linkhealth:index")


@health_admin
@require_POST
def recheck_selected(request):
    form = RecheckSelectionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Select between 1 and 50 existing sealed captures.")
    ids = sorted(str(snapshot.pk) for snapshot in form.cleaned_data["snapshot_ids"])
    run = enqueue(snapshot_ids=ids)
    if run.snapshot_ids == ids:
        messages.success(request, f"Queued {len(ids)} selected links for another check. Saved captures are preserved.")
    else:
        messages.info(request, "Another link check is already queued or running. Wait for it to finish before rechecking your selection.")
    return redirect("linkhealth:index")
