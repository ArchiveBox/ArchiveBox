"""Superuser-only, CSRF-protected rule management."""

import hashlib
import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot
from .forms import RuleForm, RuleConditions, CapturePreviewForm
from .models import Rule, RuleRun
from .service import apply_rule, matches


def automation_admin(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def page(request, template, context):
    return render(request, template, {**archivebox_admin.each_context(request), **context})


def rule_fingerprint(rule):
    data = {field.name: getattr(rule, field.attname) for field in rule._meta.fields}
    data["conditions"] = list(rule.conditions.values("field", "operator", "value", "group"))
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()


@automation_admin
@require_http_methods(["GET"])
def index(request):
    return page(
        request,
        "automation/index.html",
        {
            "title": "Rules",
            "rules": Rule.objects.prefetch_related("conditions"),
            "runs": RuleRun.objects.select_related("snapshot", "crawl", "event")[:30],
        },
    )


@automation_admin
@require_http_methods(["GET", "POST"])
def edit(request, rule_id=None):
    rule = get_object_or_404(Rule, pk=rule_id) if rule_id else Rule(created_by=request.user)
    group_error = ""
    if request.method == "POST":
        try:
            groups = json.loads(request.POST.get("condition-groups", "{}"))
            if not isinstance(groups, dict) or len(groups) > 20:
                raise ValueError()
            rule.groups = groups
        except (ValueError, TypeError):
            group_error = "Condition groups could not be read. Reload the editor and try again."
    form = RuleForm(request.POST or None, instance=rule)
    conditions = RuleConditions(request.POST or None, instance=rule, form_kwargs={"groups": rule.groups})
    if rule_id:
        conditions.extra = 0
    if request.method == "POST" and form.is_valid() and conditions.is_valid() and not group_error:
        with transaction.atomic():
            form.save()
            conditions.save()
        messages.success(
            request,
            "Rule saved. Capture configuration applies before execution; other actions respond to future matching events.",
        )
        return redirect("automation:preview", rule_id=rule.pk)
    from .capture import configurable_fields

    return page(
        request,
        "automation/edit.html",
        {
            "title": "Edit rule" if rule_id else "New rule",
            "form": form,
            "conditions": conditions,
            "rule": rule,
            "group_error": group_error,
            "config_fields": configurable_fields(),
        },
    )


@automation_admin
@require_http_methods(["GET", "POST"])
def preview(request, rule_id):
    rule = get_object_or_404(Rule.objects.prefetch_related("conditions"), pk=rule_id)
    if rule.is_capture_configuration:
        return capture_preview(request, rule)
    query = request.GET.get("q", "").strip()
    candidates = Snapshot.objects.order_by("-created_at").prefetch_related("tags")
    if query:
        candidates = candidates.filter(Q(url__icontains=query) | Q(title__icontains=query))
    examined = list(candidates[:500])
    snapshots = [snapshot for snapshot in examined if matches(rule, snapshot)][:100]
    if request.method == "POST":
        try:
            payload = signing.loads(request.POST.get("preview", ""), salt="archivebox-rule-preview", max_age=3600)
            if payload["rule"] != str(rule.pk) or payload["fingerprint"] != rule_fingerprint(rule):
                raise signing.BadSignature("Rule changed since the preview.")
        except (signing.BadSignature, KeyError, TypeError):
            messages.error(request, "The preview expired or the rule changed. Review this preview and try again.")
        else:
            count = 0
            for snapshot in Snapshot.objects.filter(pk__in=payload["snapshots"]):
                run = apply_rule(rule, snapshot)
                count += int(run.matched)
            messages.success(request, f"Applied rule to {count} matching snapshots. Captures changed since preview are checked again.")
            return redirect("automation:index")
    token = signing.dumps(
        {"rule": str(rule.pk), "fingerprint": rule_fingerprint(rule), "snapshots": [str(snapshot.pk) for snapshot in snapshots]},
        salt="archivebox-rule-preview",
    )
    return page(
        request,
        "automation/preview.html",
        {
            "title": "Preview rule",
            "rule": rule,
            "snapshots": snapshots,
            "preview_token": token,
            "query": query,
            "examined_count": len(examined),
        },
    )


@automation_admin
@require_POST
def toggle(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id)
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled"])
    return redirect("automation:index")


@automation_admin
@require_http_methods(["GET"])
def history(request):
    runs = Paginator(RuleRun.objects.select_related("snapshot", "crawl", "event"), 50).get_page(request.GET.get("page"))
    return page(request, "automation/history.html", {"title": "Rule history", "runs": runs})


def capture_preview(request, rule):
    from django.core.exceptions import ValidationError
    from archivebox.crawls.models import Crawl
    from archivebox.config.common import get_config, build_crawl_config_snapshot
    from .capture import evaluate_capture_rules, configurable_fields

    if request.method != "GET":
        raise PermissionDenied("Capture configuration previews cannot modify saved captures.")
    form = CapturePreviewForm(request.GET if request.GET else None)
    context = {"title": "Preview capture configuration", "rule": rule, "form": form}
    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        crawl = Crawl(
            urls=data["url"],
            tags_str=data["tags"],
            label=data["label"],
            max_depth=data["max_depth"],
            config={"PLUGINS": data["plugins"]} if data["plugins"] else {},
            created_by=request.user,
        )
        try:
            # Use the same native resolution and ordered rule evaluation as the
            # actual lifecycle, without saving preview models or emitting events.
            if rule.trigger == "before_snapshot":
                crawl.config, crawl.max_depth, _ = evaluate_capture_rules(crawl)
                crawl.config = build_crawl_config_snapshot(overrides=crawl.config)
                snapshot = Snapshot(url=data["url"], crawl=crawl, config={})
            else:
                snapshot = None
            config, depth, runs = evaluate_capture_rules(crawl, snapshot=snapshot)
            effective = get_config(crawl=crawl if snapshot is not None else None, snapshot=snapshot, overrides=config).model_dump(
                mode="json",
            )
            context.update(
                {
                    "evaluations": [
                        {"rule": item, "matched": matched, "changes": json.dumps(changes, indent=2)} for item, matched, changes in runs
                    ],
                    "effective_config": json.dumps({key: effective.get(key) for key in sorted(configurable_fields())}, indent=2),
                    "effective_depth": depth,
                    "effective_plugins": effective["PLUGINS"],
                    "preview_ready": True,
                },
            )
        except (ValidationError, ValueError) as error:
            form.add_error(None, str(error))
    return page(request, "automation/capture_preview.html", context)
