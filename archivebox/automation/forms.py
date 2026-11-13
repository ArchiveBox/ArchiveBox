from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Rule, RuleCondition


class CapturePreviewForm(forms.Form):
    url = forms.URLField(label="Seed / page URL", initial="https://news.ycombinator.com/")
    tags = forms.CharField(required=False, label="Crawl tags", help_text="Comma-separated; inherited by new pages.")
    label = forms.CharField(required=False, label="Crawl label")
    plugins = forms.CharField(
        required=False,
        label="Initial plugins",
        help_text="Comma-separated installed names; blank uses current defaults.",
    )
    max_depth = forms.IntegerField(min_value=0, max_value=4, initial=0)

    def clean_plugins(self):
        from archivebox.plugins.discovery import get_plugins

        names = [name.strip() for name in self.cleaned_data["plugins"].split(",") if name.strip()]
        if set(names) - set(get_plugins()):
            raise forms.ValidationError("Use installed plugin names.")
        return ",".join(names)


class RuleForm(forms.ModelForm):
    enable_plugins = forms.MultipleChoiceField(required=False, label="Enable plugins")
    disable_plugins = forms.MultipleChoiceField(required=False, label="Disable plugins")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from archivebox.plugins.discovery import get_plugins

        choices = [(name, name) for name in get_plugins()]
        self.fields["enable_plugins"].choices = choices
        self.fields["disable_plugins"].choices = choices
        self.fields["config_overrides"].widget.attrs.update({"rows": 6, "style": "width:100%;box-sizing:border-box"})
        self.fields[
            "position"
        ].help_text = (
            "Lower numbers run first; ties use creation order. Later matching settings override earlier ones unless processing stops."
        )

    class Meta:
        model = Rule
        fields = (
            "name",
            "enabled",
            "position",
            "trigger",
            "match",
            "add_tags",
            "remove_tags",
            "permissions",
            "folder",
            "stop_processing",
            "config_overrides",
            "enable_plugins",
            "disable_plugins",
            "max_depth",
        )

    def clean_config_overrides(self):
        value = self.cleaned_data.get("config_overrides")
        if value is not None and not isinstance(value, dict):
            raise forms.ValidationError("Use a JSON object of configuration names and values.")
        return value or {}


class ConditionForm(forms.ModelForm):
    group = forms.ChoiceField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, groups=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].choices = [("", "Root"), *((key, key) for key in (groups or {}))]


class ConditionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(form.cleaned_data and not form.cleaned_data.get("DELETE") for form in self.forms):
            raise forms.ValidationError("Add at least one condition. Empty rules never match everything.")
        occupied = {form.cleaned_data.get("group", "") for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")}
        for form in self.forms:
            data = form.cleaned_data
            if not data or data.get("DELETE"):
                continue
            if self.instance.trigger == "before_crawl" and data.get("field") not in ("domain", "url", "crawl_tag", "crawl_label"):
                raise forms.ValidationError("Before-crawl conditions can use seed URL, domain, crawl tag, or crawl label.")
            if self.instance.trigger == "before_snapshot" and data.get("field") == "event_tag":
                raise forms.ValidationError("Changed tag is available only for tag events.")
        for key in self.instance.groups:
            if key not in occupied and not any(group.get("parent", "") == key for group in self.instance.groups.values()):
                raise forms.ValidationError("Each condition group needs a condition or another group.")


RuleConditions = inlineformset_factory(
    Rule,
    RuleCondition,
    fields=("field", "operator", "value", "group"),
    form=ConditionForm,
    formset=ConditionFormSet,
    extra=1,
    can_delete=True,
    max_num=20,
    validate_max=True,
)
