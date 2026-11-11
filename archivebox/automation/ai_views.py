from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.config.common import get_request_config
from archivebox.core.models import Snapshot
from .ai_models import AISettings, Enrichment
from .ai import enqueue, prompt_instructions
from .views import automation_admin, page


class AISettingsForm(forms.ModelForm):
    class Meta:
        model = AISettings
        fields = ("enabled", "model", "apply_tags", "language", "tag_style", "allowed_tags", "instructions")
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "allowed_tags": forms.Textarea(attrs={"rows": 4}),
            "tag_style": forms.RadioSelect,
        }

    def clean_allowed_tags(self):
        tags = list(dict.fromkeys(tag.strip() for tag in self.cleaned_data["allowed_tags"].splitlines() if tag.strip()))
        if len(tags) > 100 or any(len(tag) > 100 for tag in tags):
            raise forms.ValidationError("Choose at most 100 curated topics, each at most 100 characters.")
        return "\n".join(tags)

    def clean_model(self):
        value = self.cleaned_data["model"].strip()
        if value and ("/" not in value or not all(value.split("/", 1))):
            raise forms.ValidationError("Use provider/model or leave blank for the default model.")
        return value


@automation_admin
@require_http_methods(["GET", "POST"])
def index(request):
    settings, _ = AISettings.objects.get_or_create(pk=1)
    previously_enabled = settings.enabled
    form = AISettingsForm(request.POST or None, instance=settings)
    config = get_request_config(request)
    available = bool(getattr(config, "OPENCODE_ENABLED", False))
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["enabled"] and not available:
            form.add_error("enabled", "Enable OpenCode and connect a model provider in the Agent first.")
        else:
            updated = form.save(commit=False)
            if updated.enabled and not previously_enabled:
                updated.enabled_at = timezone.now()
            updated.save()
            messages.success(request, "AI settings saved. Existing summaries and manually added tags are preserved.")
            return redirect("automation:ai")
    jobs_query = Enrichment.objects.select_related("snapshot")
    if selected := request.GET.getlist("snapshot"):
        try:
            selected_ids = [Snapshot._meta.pk.to_python(value) for value in selected[:100]]
        except ValidationError:
            messages.error(request, "Choose valid captures from the list.")
            return redirect("automation:ai")
        jobs_query = jobs_query.filter(snapshot_id__in=selected_ids)
    jobs = Paginator(jobs_query, 30).get_page(request.GET.get("page"))
    snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED).order_by("-created_at")[:100]
    return page(
        request,
        "automation/ai.html",
        {
            "title": "AI summaries & tags",
            "form": form,
            "jobs": jobs,
            "snapshots": snapshots,
            "available": available,
            "prompt_preview": prompt_instructions(
                settings.instructions,
                {
                    "language": settings.language,
                    "tag_style": settings.tag_style,
                    "allowed_tags": [tag for tag in settings.allowed_tags.splitlines() if tag],
                },
            ),
        },
    )


@automation_admin
@require_POST
def queue(request):
    if not getattr(get_request_config(request), "OPENCODE_ENABLED", False):
        messages.error(request, "Enable OpenCode and configure a provider in the Agent first.")
        return redirect("automation:ai")
    settings, _ = AISettings.objects.get_or_create(pk=1)
    try:
        selected = [Snapshot._meta.pk.to_python(value) for value in request.POST.getlist("snapshots")[:100]]
    except ValidationError:
        messages.error(request, "Choose valid captures from the list.")
        return redirect("automation:ai")
    count = 0
    for snapshot in Snapshot.objects.filter(pk__in=selected, status=Snapshot.StatusChoices.SEALED):
        enqueue(snapshot, settings, retry=True)
        count += 1
    messages.success(request, f"Queued {count} captures for AI enrichment. Follow progress below.")
    return redirect("automation:ai")
