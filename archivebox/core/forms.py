__package__ = 'archivebox.core'

from django import forms

from archivebox.misc.util import URL_REGEX
from taggit.utils import edit_string_for_tags, parse_tags
from archivebox.base_models.admin import KeyValueWidget
from archivebox.crawls.schedule_utils import validate_schedule
from archivebox.hooks import get_plugins

DEPTH_CHOICES = (
    ('0', 'depth = 0 (archive just these URLs)'),
    ('1', 'depth = 1 (+ URLs one hop away)'),
    ('2', 'depth = 2 (+ URLs two hops away)'),
    ('3', 'depth = 3 (+ URLs three hops away)'),
    ('4', 'depth = 4 (+ URLs four hops away)'),
)


def get_plugin_choices():
    """Get available extractor plugins from discovered hooks."""
    return [(name, name) for name in get_plugins()]


def get_choice_field(form: forms.Form, name: str) -> forms.ChoiceField:
    field = form.fields[name]
    if not isinstance(field, forms.ChoiceField):
        raise TypeError(f'{name} must be a ChoiceField')
    return field


class AddLinkForm(forms.Form):
    # Basic fields
    url = forms.RegexField(
        label="URLs (one per line)",
        regex=URL_REGEX,
        min_length=6,
        strip=True,
        widget=forms.Textarea,
        required=True
    )
    tag = forms.CharField(
        label="Tags (comma separated tag1,tag2,tag3)",
        strip=True,
        required=False,
        widget=forms.TextInput(attrs={
            'list': 'tag-datalist',
            'autocomplete': 'off',
        })
    )
    depth = forms.ChoiceField(
        label="Archive depth",
        choices=DEPTH_CHOICES,
        initial='0',
        widget=forms.RadioSelect(attrs={"class": "depth-selection"})
    )
    notes = forms.CharField(
        label="Notes",
        strip=True,
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Optional notes about this crawl (e.g., purpose, project name, context...)',
        })
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
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g., daily, weekly, 0 */6 * * * (every 6 hours)',
        })
    )
    persona = forms.CharField(
        label="Persona (authentication profile)",
        max_length=100,
        initial='Default',
        required=False,
    )
    overwrite = forms.BooleanField(
        label="Overwrite existing snapshots",
        initial=False,
        required=False,
    )
    update = forms.BooleanField(
        label="Update/retry previously failed URLs",
        initial=False,
        required=False,
    )
    index_only = forms.BooleanField(
        label="Index only (don't archive yet)",
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

        # Import at runtime to avoid circular imports
        from archivebox.config.common import ARCHIVING_CONFIG

        # Get all plugins
        all_plugins = get_plugins()

        # Define plugin groups
        chrome_dependent = {
            'accessibility', 'chrome', 'consolelog', 'dom', 'headers',
            'parse_dom_outlinks', 'pdf', 'redirects', 'responses',
            'screenshot', 'seo', 'singlefile', 'ssl', 'staticfile', 'title'
        }
        archiving = {
            'archivedotorg', 'defuddle', 'favicon', 'forumdl', 'gallerydl', 'git',
            'htmltotext', 'mercury', 'papersdl', 'readability', 'trafilatura', 'wget', 'ytdlp'
        }
        parsing = {
            'parse_html_urls', 'parse_jsonl_urls',
            'parse_netscape_urls', 'parse_rss_urls', 'parse_txt_urls'
        }
        search = {
            'search_backend_ripgrep', 'search_backend_sonic', 'search_backend_sqlite'
        }
        binary = {'apt', 'brew', 'custom', 'env', 'npm', 'pip'}
        extensions = {'twocaptcha', 'istilldontcareaboutcookies', 'ublock'}

        # Populate plugin field choices
        get_choice_field(self, 'chrome_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in chrome_dependent
        ]
        get_choice_field(self, 'archiving_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in archiving
        ]
        get_choice_field(self, 'parsing_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in parsing
        ]
        get_choice_field(self, 'search_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in search
        ]
        get_choice_field(self, 'binary_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in binary
        ]
        get_choice_field(self, 'extension_plugins').choices = [
            (p, p) for p in sorted(all_plugins) if p in extensions
        ]

        # Set update default from config
        self.fields['update'].initial = not ARCHIVING_CONFIG.ONLY_NEW

    def clean(self):
        cleaned_data = super().clean() or {}

        # Combine all plugin groups into single list
        all_selected_plugins = []
        for field in ['chrome_plugins', 'archiving_plugins', 'parsing_plugins',
                      'search_plugins', 'binary_plugins', 'extension_plugins']:
            selected = cleaned_data.get(field)
            if isinstance(selected, list):
                all_selected_plugins.extend(selected)

        # Store combined list for easy access
        cleaned_data['plugins'] = all_selected_plugins

        return cleaned_data

    def clean_schedule(self):
        schedule = (self.cleaned_data.get('schedule') or '').strip()
        if not schedule:
            return ''

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
                "Please provide a comma-separated list of tags."
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
