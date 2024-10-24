__package__ = 'archivebox.core'

from django import forms

from archivebox.misc.util import URL_REGEX
from ..parsers import PARSERS
from taggit.utils import edit_string_for_tags, parse_tags

PARSER_CHOICES = [
    (parser_key, parser[0])
    for parser_key, parser in PARSERS.items()
]
DEPTH_CHOICES = (
    ('0', 'depth = 0 (archive just these URLs)'),
    ('1', 'depth = 1 (archive these URLs and all URLs one hop away)'),
)

from ..extractors import get_default_archive_methods

ARCHIVE_METHODS = [
    (name, name)
    for name, _, _ in get_default_archive_methods()
]


class AddLinkForm(forms.Form):
    url = forms.RegexField(label="URLs (one per line)", regex=URL_REGEX, min_length='6', strip=True, widget=forms.Textarea, required=True)
    parser = forms.ChoiceField(label="URLs format", choices=[('auto', 'Auto-detect parser'), *PARSER_CHOICES], initial='auto')
    tag = forms.CharField(label="Tags (comma separated tag1,tag2,tag3)", strip=True, required=False)
    depth = forms.ChoiceField(label="Archive depth", choices=DEPTH_CHOICES, initial='0', widget=forms.RadioSelect(attrs={"class": "depth-selection"}))
    archive_methods = forms.MultipleChoiceField(
        label="Archive methods (select at least 1, otherwise all will be used by default)",
        required=False,
        widget=forms.SelectMultiple,
        choices=ARCHIVE_METHODS,
    )
    # TODO: hook these up to the view and put them 
    # in a collapsible UI section labeled "Advanced"
    #
    # exclude_patterns = forms.CharField(
    #     label="Exclude patterns",
    #     min_length='1',
    #     required=False,
    #     initial=URL_DENYLIST,
    # )
    # timeout = forms.IntegerField(
    #     initial=TIMEOUT,
    # )
    # overwrite = forms.BooleanField(
    #     label="Overwrite any existing Snapshots",
    #     initial=False,
    # )
    # index_only = forms.BooleanField(
    #     label="Add URLs to index without Snapshotting",
    #     initial=False,
    # )

class TagWidgetMixin:
    def format_value(self, value):
        if value is not None and not isinstance(value, str):
            value = edit_string_for_tags(value)
        return super().format_value(value)

class TagWidget(TagWidgetMixin, forms.TextInput):
    pass

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

    def has_changed(self, initial_value, data_value):
        # Always return False if the field is disabled since self.bound_data
        # always uses the initial value in this case.
        if self.disabled:
            return False

        try:
            data_value = self.clean(data_value)
        except forms.ValidationError:
            pass

        if initial_value is None:
            initial_value = []

        initial_value = [tag.name for tag in initial_value]
        initial_value.sort()

        return initial_value != data_value
