__package__ = "archivebox.core"

from django import forms
from django.utils.html import format_html

from archivebox.misc.util import URL_REGEX, find_all_urls, parse_filesize_to_bytes
from taggit.utils import edit_string_for_tags, parse_tags
from archivebox.base_models.admin import KeyValueWidget
from archivebox.crawls.schedule_utils import validate_schedule
from archivebox.config.common import SEARCH_BACKEND_CONFIG
from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.hooks import get_plugins, discover_plugin_configs, get_plugin_icon
from archivebox.personas.models import Persona

DEPTH_CHOICES = (
    ("0", "depth = 0 (archive just these URLs)"),
    ("1", "depth = 1 (+ URLs one hop away)"),
    ("2", "depth = 2 (+ URLs two hops away)"),
    ("3", "depth = 3 (+ URLs three hops away)"),
    ("4", "depth = 4 (+ URLs four hops away)"),
)


def get_plugin_choices():
    """Get available extractor plugins from discovered hooks."""
    return [(name, name) for name in get_plugins()]


def get_plugin_choice_label(plugin_name: str, plugin_configs: dict[str, dict]) -> str:
    schema = plugin_configs.get(plugin_name, {})
    description = str(schema.get("description") or "").strip()
    if not description:
        return plugin_name
    icon_html = get_plugin_icon(plugin_name)

    return format_html(
        '<span class="plugin-choice-icon">{}</span><span class="plugin-choice-name">{}</span><a class="plugin-choice-description" href="https://archivebox.github.io/abx-plugins/#{}" target="_blank" rel="noopener noreferrer">{}</a>',
        icon_html,
        plugin_name,
        plugin_name,
        description,
    )


def get_choice_field(form: forms.Form, name: str) -> forms.ChoiceField:
    field = form.fields[name]
    if not isinstance(field, forms.ChoiceField):
        raise TypeError(f"{name} must be a ChoiceField")
    return field


class AddLinkForm(forms.Form):
    # Basic fields
    url = forms.CharField(
        label="URLs",
        strip=True,
        widget=forms.Textarea(
            attrs={
                "data-url-regex": URL_REGEX.pattern,
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
        label="Max URLs",
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
    max_size = forms.CharField(
        label="Max size",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = unlimited, or e.g. 45mb / 1gb",
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
    chrome_plugins = forms.MultipleChoiceField(
        label="Chrome-dependent plugins",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],  # populated in __init__
    )
    archiving_plugins = forms.MultipleChoiceField(
        label="Archiving",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    parsing_plugins = forms.MultipleChoiceField(
        label="Parsing",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    search_plugins = forms.MultipleChoiceField(
        label="Search",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    binary_plugins = forms.MultipleChoiceField(
        label="Binary providers",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    extension_plugins = forms.MultipleChoiceField(
        label="Browser extensions",
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
        label="Persona (authentication profile)",
        required=False,
        queryset=Persona.objects.none(),
        empty_label=None,
        to_field_name="name",
    )
    index_only = forms.BooleanField(
        label="Index only dry run (add crawl but don't archive yet)",
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
        super().__init__(*args, **kwargs)

        default_persona = Persona.get_or_create_default()
        self.fields["persona"].queryset = Persona.objects.order_by("name")
        self.fields["persona"].initial = default_persona.name

        # Get all plugins
        all_plugins = get_plugins()
        plugin_configs = discover_plugin_configs()

        # Define plugin groups
        chrome_dependent = {
            "accessibility",
            "chrome",
            "consolelog",
            "dom",
            "headers",
            "parse_dom_outlinks",
            "pdf",
            "redirects",
            "responses",
            "screenshot",
            "seo",
            "singlefile",
            "ssl",
            "staticfile",
            "title",
        }
        archiving = {
            "archivedotorg",
            "defuddle",
            "favicon",
            "forumdl",
            "gallerydl",
            "git",
            "htmltotext",
            "mercury",
            "papersdl",
            "readability",
            "trafilatura",
            "wget",
            "ytdlp",
        }
        parsing = {
            "parse_html_urls",
            "parse_jsonl_urls",
            "parse_netscape_urls",
            "parse_rss_urls",
            "parse_txt_urls",
        }
        search = {
            "search_backend_ripgrep",
            "search_backend_sonic",
            "search_backend_sqlite",
        }
        binary = {"apt", "brew", "custom", "env", "npm", "pip"}
        extensions = {"twocaptcha", "istilldontcareaboutcookies", "ublock"}

        # Populate plugin field choices
        get_choice_field(self, "chrome_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in chrome_dependent
        ]
        get_choice_field(self, "archiving_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in archiving
        ]
        get_choice_field(self, "parsing_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in parsing
        ]
        get_choice_field(self, "search_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in search
        ]
        get_choice_field(self, "binary_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in binary
        ]
        get_choice_field(self, "extension_plugins").choices = [
            (p, get_plugin_choice_label(p, plugin_configs)) for p in sorted(all_plugins) if p in extensions
        ]

        required_search_plugin = f"search_backend_{SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE}".strip()
        search_choices = [choice[0] for choice in get_choice_field(self, "search_plugins").choices]
        if required_search_plugin in search_choices:
            get_choice_field(self, "search_plugins").initial = [required_search_plugin]

    def clean(self):
        cleaned_data = super().clean() or {}

        # Combine all plugin groups into single list
        all_selected_plugins = []
        for field in [
            "chrome_plugins",
            "archiving_plugins",
            "parsing_plugins",
            "search_plugins",
            "binary_plugins",
            "extension_plugins",
        ]:
            selected = cleaned_data.get(field)
            if isinstance(selected, list):
                all_selected_plugins.extend(selected)

        # Store combined list for easy access
        cleaned_data["plugins"] = all_selected_plugins

        return cleaned_data

    def clean_url(self):
        value = self.cleaned_data.get("url") or ""
        urls = "\n".join(find_all_urls(value))
        if not urls:
            raise forms.ValidationError("Enter at least one valid URL.")
        return urls

    def clean_url_filters(self):
        from archivebox.crawls.models import Crawl

        value = self.cleaned_data.get("url_filters") or {}
        return {
            "allowlist": "\n".join(Crawl.split_filter_patterns(value.get("allowlist", ""))),
            "denylist": "\n".join(Crawl.split_filter_patterns(value.get("denylist", ""))),
            "same_domain_only": bool(value.get("same_domain_only")),
        }

    def clean_max_urls(self):
        value = self.cleaned_data.get("max_urls")
        return int(value or 0)

    def clean_max_size(self):
        raw_value = str(self.cleaned_data.get("max_size") or "").strip()
        if not raw_value:
            return 0
        try:
            value = parse_filesize_to_bytes(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        if value < 0:
            raise forms.ValidationError("Max size must be 0 or a positive number of bytes.")
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
            value = edit_string_for_tags(value)
        return super().format_value(value)


class TagField(forms.CharField):
    widget = TagWidget

    def clean(self, value):
        value = super().clean(value)
        try:
            return parse_tags(value)
        except ValueError:
            raise forms.ValidationError(
                "Please provide a comma-separated list of tags.",
            )

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
