__package__ = 'archivebox.core'

from django import forms

from ..util import URL_REGEX

CHOICES = (
    ('0', 'depth = 0 (archive just these URLs)'),
    ('1', 'depth = 1 (archive these URLs and all URLs one hop away)'),
)

class AddLinkForm(forms.Form):
    url = forms.RegexField(label="URLs (one per line)", regex=URL_REGEX, min_length='6', strip=True, widget=forms.Textarea, required=True)
    depth = forms.ChoiceField(label="Archive depth", choices=CHOICES, widget=forms.RadioSelect, initial='0')
