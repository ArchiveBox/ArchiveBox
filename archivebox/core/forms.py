__package__ = 'archivebox.core'

from django import forms

from ..util import URL_REGEX
from ..vendor.taggit_utils import edit_string_for_tags, parse_tags

CHOICES = (
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
    depth = forms.ChoiceField(label="Archive depth", choices=CHOICES, widget=forms.RadioSelect, initial='0')
    archive_methods = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple,
        choices=ARCHIVE_METHODS,
    )
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
