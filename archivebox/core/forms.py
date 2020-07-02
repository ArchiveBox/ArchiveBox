from django import forms

CHOICES = (('url', 'URL'), ('feed', 'Feed'))

class AddLinkForm(forms.Form):
    url = forms.URLField()
    source = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect, initial='url')
