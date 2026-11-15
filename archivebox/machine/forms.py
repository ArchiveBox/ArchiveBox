from django import forms

from archivebox.config.forms import MachineSettingsMixin
from archivebox.machine.models import Machine


class MachineAdminForm(MachineSettingsMixin, forms.ModelForm):
    class Meta:
        model = Machine
        fields = "__all__"
