from django import forms

CHOICES = (
    ('0', 'depth=0 (archive just this url)'),
    ('1', 'depth=1 (archive this url and all sites one link away)'),
)

class AddLinkForm(forms.Form):
    url = forms.URLField()
    depth = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect, initial='0')
