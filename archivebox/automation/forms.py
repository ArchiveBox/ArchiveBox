from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Rule, RuleCondition


class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ("name", "enabled", "position", "trigger", "match", "add_tags", "remove_tags", "permissions", "folder", "stop_processing")


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
