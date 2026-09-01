__package__ = "archivebox.core"

import re
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django import forms

from archivebox.base_models.admin import KeyValueWidget
from archivebox.config.common import get_config, parse_delete_after
from archivebox.core.permissions import PERMISSIONS_CHOICES, PERMISSIONS_PUBLIC, filter_personas_by_permissions
from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.crawls.schedule_util import validate_schedule
from archivebox.misc.util import URL_REGEX, find_all_urls, parse_filesize_to_bytes
from archivebox.personas.models import Persona
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.plugins.forms import (
    PLUGIN_GROUPS,
    TIMEOUT_INPUT_PATTERN,
    PluginConfigFormMixin,
    get_choice_field,
)

DEPTH_CHOICES = (
    ("0", "depth = 0 (archive just these URLs)"),
    ("1", "depth = 1 (+ URLs one hop away)"),
    ("2", "depth = 2 (+ URLs two hops away)"),
    ("3", "depth = 3 (+ URLs three hops away)"),
    ("4", "depth = 4 (+ URLs four hops away)"),
)


def _split_strip(value: str, delimiter: str) -> list[str]:
    return [part.strip() for part in value.split(delimiter) if part.strip()]


def parse_tag_string(value: str | None) -> list[str]:
    """Parse the legacy tag-editing format used by the admin tag field."""
    if not value:
        return []

    if "," not in value and '"' not in value:
        return sorted(set(_split_strip(value, " ")))

    tags: list[str] = []
    buffer: list[str] = []
    deferred_chunks: list[str] = []
    saw_unquoted_comma = False
    in_quote = False
    chars = iter(value)

    try:
        while True:
            char = next(chars)
            if char == '"':
                if buffer:
                    deferred_chunks.append("".join(buffer))
                    buffer = []
                in_quote = True
                char = next(chars)
                while char != '"':
                    buffer.append(char)
                    char = next(chars)
                tag = "".join(buffer).strip()
                if tag:
                    tags.append(tag)
                buffer = []
                in_quote = False
            else:
                if not saw_unquoted_comma and char == ",":
                    saw_unquoted_comma = True
                buffer.append(char)
    except StopIteration:
        if buffer:
            if in_quote and "," in buffer:
                saw_unquoted_comma = True
            deferred_chunks.append("".join(buffer))

    delimiter = "," if saw_unquoted_comma else " "
    for chunk in deferred_chunks:
        tags.extend(_split_strip(chunk, delimiter))

    return sorted(set(tags))


def edit_string_for_tag_names(tags) -> str:
    names = []
    for tag in tags:
        name = tag.name
        names.append(f'"{name}"' if "," in name or " " in name else name)
    return ", ".join(sorted(names))


class AddLinkForm(PluginConfigFormMixin, forms.Form):
    allow_crawl_execution_config_fields = False

    # Basic fields
    url = forms.CharField(
        label="URLs",
        strip=False,
        widget=forms.Textarea(
            attrs={
                "data-url-regex": URL_REGEX.pattern,
                "placeholder": (
                    "Enter URL(s) to archive. Any format is ok: one per line, CSV, JSON, RSS, embedded in text, etc.\n\n"
                    "Examples:\n\n"
                    "https://example.com\n\n"
                    "https://news.ycombinator.com,https://news.google.com\n\n"
                    "Or any text-based format [containing URLs](https://github.com/ArchiveBox/ArchiveBox)..."
                ),
            },
        ),
        required=True,
    )
    tag = forms.CharField(
        label="Tags",
        strip=True,
        required=False,
        widget=TagEditorWidget(),
    )
    depth = forms.ChoiceField(
        label="Archive depth",
        choices=DEPTH_CHOICES,
        initial="0",
        widget=forms.RadioSelect(attrs={"class": "depth-selection"}),
    )
    max_urls = forms.IntegerField(
        label="Max crawl URLs",
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(
            attrs={
                "min": 0,
                "step": 1,
                "placeholder": "0 = unlimited",
            },
        ),
    )
    crawl_max_size = forms.CharField(
        label="Max crawl size",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = unlimited, or e.g. 45mb / 1gb",
            },
        ),
    )
    crawl_timeout = forms.CharField(
        label="Max crawl time",
        required=False,
        initial=0,
        widget=forms.TextInput(
            attrs={
                "pattern": TIMEOUT_INPUT_PATTERN,
                "title": "Use 0, integer seconds, or a duration like 1.5m or 1hr. Non-zero values must be greater than 10 seconds.",
                "placeholder": "0, 300, 1.5m, or 1hr",
            },
        ),
    )
    timeout = forms.CharField(
        label="Max subtask time",
        required=False,
        widget=forms.TextInput(
            attrs={
                "pattern": TIMEOUT_INPUT_PATTERN,
                "title": "Use integer seconds or a duration like 1.5m or 1hr. Non-zero values must be greater than 10 seconds.",
                "placeholder": "60, 1.5m, or 1hr",
            },
        ),
    )
    snapshot_max_size = forms.CharField(
        label="Max snapshot size",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = unlimited, or e.g. 45mb / 1gb",
            },
        ),
    )
    delete_after = forms.CharField(
        label="Delete after",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = keep forever, or e.g. 1d / 6mo",
            },
        ),
    )
    crawl_max_concurrent_snapshots = forms.IntegerField(
        label="Max in parallel",
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "min": 1,
                "step": 1,
            },
        ),
    )
    notes = forms.CharField(
        label="Notes",
        strip=True,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional notes about this crawl",
            },
        ),
    )
    url_filters = forms.Field(
        label="URL allowlist / denylist",
        required=False,
        widget=URLFiltersWidget(source_selector='textarea[name="url"]'),
    )

    # Plugin groups
    main_plugins = forms.MultipleChoiceField(
        label="Main",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],  # populated in __init__
    )
    page_setup_plugins = forms.MultipleChoiceField(
        label="Page Setup",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    media_plugins = forms.MultipleChoiceField(
        label="Media",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    text_plugins = forms.MultipleChoiceField(
        label="Text",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    metadata_plugins = forms.MultipleChoiceField(
        label="Metadata",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    postprocessing_plugins = forms.MultipleChoiceField(
        label="Postprocessing",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    other_plugins = forms.MultipleChoiceField(
        label="Other",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )

    # Advanced options
    schedule = forms.CharField(
        label="Repeat schedule",
        max_length=64,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g., daily, weekly, 0 */6 * * * (every 6 hours)",
            },
        ),
    )
    persona = forms.ModelChoiceField(
        label="Persona (configuration profile)",
        required=False,
        queryset=Persona.objects.none(),
        empty_label=None,
        to_field_name="name",
    )
    permissions = forms.ChoiceField(
        label="Permissions",
        choices=PERMISSIONS_CHOICES,
        initial="public",
        required=True,
    )
    start_paused = forms.BooleanField(
        label="Start paused",
        initial=False,
        required=False,
    )
    config = forms.JSONField(
        label="Custom config overrides",
        widget=KeyValueWidget(),
        initial=dict,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.can_override_crawl_config = False
        if self.request is not None:
            user = self.request.user
            self.can_override_crawl_config = bool(user.is_authenticated and user.is_active and user.is_superuser)
        super().__init__(*args, **kwargs)

        default_persona = Persona.get_or_create_default()
        persona_queryset = Persona.objects.order_by("name")
        if not self.can_override_crawl_config:
            persona_queryset = filter_personas_by_permissions(persona_queryset, {PERMISSIONS_PUBLIC})
        self.fields["persona"].queryset = persona_queryset

        selected_persona = persona_queryset.filter(id=default_persona.id).first() or persona_queryset.first()
        default_config = get_config(persona=selected_persona) if selected_persona else get_config()
        if selected_persona:
            self.fields["persona"].initial = selected_persona.name
        self.fields["permissions"].initial = default_config.PERMISSIONS
        self.fields["timeout"].initial = default_config.TIMEOUT
        self.fields["crawl_max_concurrent_snapshots"].initial = default_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS
        self.fields["delete_after"].initial = default_config.DELETE_AFTER
        self.fields["url_filters"].initial = {
            "allowlist": "",
            "denylist": "",
            "same_domain_only": False,
            "subpaths_only": False,
            "only_new": bool(default_config.ONLY_NEW),
        }

        if self.is_bound:
            selected_persona = (
                persona_queryset.filter(name=str(self.data.get(self.add_prefix("persona")) or "")).first() or selected_persona
            )
        if self.can_override_crawl_config:
            self.build_plugin_groups(get_config(persona=selected_persona) if selected_persona else get_config())
        else:
            grouped_plugins = get_plugin_catalog().groups()
            for category, field_name, _title in PLUGIN_GROUPS:
                get_choice_field(self, field_name).choices = [(plugin.name, plugin.name) for plugin in grouped_plugins.get(category, [])]
            self.plugin_groups = []

    def clean(self):
        cleaned_data = super().clean() or {}

        if not self.can_override_crawl_config:
            cleaned_data["plugins"] = []
            cleaned_data["plugin_config"] = {}
            cleaned_data["config"] = {}
            return cleaned_data

        # Combine all plugin groups into single list
        all_selected_plugins = []
        for field in [
            "main_plugins",
            "page_setup_plugins",
            "media_plugins",
            "text_plugins",
            "metadata_plugins",
            "postprocessing_plugins",
            "other_plugins",
        ]:
            selected = cleaned_data.get(field)
            if isinstance(selected, list):
                all_selected_plugins.extend(selected)

        # Store combined list for easy access
        cleaned_data["plugins"] = all_selected_plugins

        plugin_config_overrides = self.clean_plugin_config_overrides(get_config(persona=cleaned_data.get("persona")))
        custom_config = cleaned_data.get("config") or {}
        if not isinstance(custom_config, dict):
            custom_config = {}
        cleaned_data["plugin_config"] = plugin_config_overrides
        cleaned_data["config"] = {**plugin_config_overrides, **custom_config}

        return cleaned_data

    def clean_url(self):
        value = self.cleaned_data.get("url") or ""
        if not list(find_all_urls(value)):
            raise forms.ValidationError("Enter at least one valid URL.")
        return value

    def clean_url_filters(self):
        from archivebox.crawls.models import Crawl

        value = self.cleaned_data.get("url_filters") or {}
        return {
            "allowlist": "\n".join(Crawl.split_filter_patterns(value.get("allowlist", ""))),
            "denylist": "\n".join(Crawl.split_filter_patterns(value.get("denylist", ""))),
            "same_domain_only": bool(value.get("same_domain_only")),
            "subpaths_only": bool(value.get("subpaths_only")),
            "only_new": bool(value.get("only_new")),
        }

    def clean_max_urls(self):
        value = self.cleaned_data.get("max_urls")
        return int(value or 0)

    def clean_crawl_max_size(self):
        raw_value = str(self.cleaned_data.get("crawl_max_size") or "").strip()
        if not raw_value:
            return 0
        try:
            value = parse_filesize_to_bytes(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        if value < 0:
            raise forms.ValidationError("Max crawl size must be 0 or a positive number of bytes.")
        return value

    def clean_crawl_timeout(self):
        return self._clean_timeout_seconds(self.cleaned_data.get("crawl_timeout"), "Max crawl time", blank_value=0)

    def clean_timeout(self):
        return self._clean_timeout_seconds(self.cleaned_data.get("timeout"), "Max subtask time", blank_value=None)

    def _clean_timeout_seconds(self, raw_value, field_label: str, *, blank_value):
        raw_value = str(raw_value or "").strip().lower()
        if not raw_value:
            return blank_value
        if raw_value.isdigit():
            value = int(raw_value)
        else:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", raw_value)
            if not match:
                raise forms.ValidationError(f"{field_label} must be seconds or a duration like 1.5m or 1hr.")
            amount_str, unit = match.groups()
            try:
                amount = Decimal(amount_str)
            except InvalidOperation as err:
                raise forms.ValidationError(f"{field_label} must be seconds or a duration like 1.5m or 1hr.") from err
            multiplier = 1
            if unit in {"m", "min", "mins", "minute", "minutes"}:
                multiplier = 60
            elif unit in {"h", "hr", "hrs", "hour", "hours"}:
                multiplier = 60 * 60
            value = int((amount * multiplier).to_integral_value(rounding=ROUND_CEILING))
        if 0 < value <= 10:
            raise forms.ValidationError(f"{field_label} must be 0 or greater than 10 seconds.")
        return value

    def clean_snapshot_max_size(self):
        raw_value = str(self.cleaned_data.get("snapshot_max_size") or "").strip()
        if not raw_value:
            return 0
        try:
            value = parse_filesize_to_bytes(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        if value < 0:
            raise forms.ValidationError("Max snapshot size must be 0 or a positive number of bytes.")
        return value

    def clean_delete_after(self):
        raw_value = str(self.cleaned_data.get("delete_after") or "0").strip() or "0"
        try:
            parse_delete_after(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        return raw_value

    def clean_crawl_max_concurrent_snapshots(self):
        value = self.cleaned_data.get("crawl_max_concurrent_snapshots")
        if value in (None, ""):
            value = get_config().CRAWL_MAX_CONCURRENT_SNAPSHOTS
        value = int(value)
        if value < 1:
            raise forms.ValidationError("Max concurrent snapshots must be at least 1.")
        return value

    def clean_schedule(self):
        schedule = (self.cleaned_data.get("schedule") or "").strip()
        if not schedule:
            return ""

        try:
            validate_schedule(schedule)
        except ValueError as err:
            raise forms.ValidationError(str(err))

        return schedule


class TagWidget(forms.TextInput):
    def format_value(self, value):
        if value is not None and not isinstance(value, str):
            value = edit_string_for_tag_names(value)
        return super().format_value(value)


class TagField(forms.CharField):
    widget = TagWidget

    def clean(self, value):
        value = super().clean(value)
        return parse_tag_string(value)

    def has_changed(self, initial, data):
        # Always return False if the field is disabled since self.bound_data
        # always uses the initial value in this case.
        if self.disabled:
            return False

        try:
            cleaned_data = self.clean(data)
        except forms.ValidationError:
            cleaned_data = data

        initial_value = [] if initial is None else initial

        if not isinstance(initial_value, list):
            initial_value = list(initial_value)

        normalized_initial = sorted(tag.name for tag in initial_value)
        return normalized_initial != cleaned_data
