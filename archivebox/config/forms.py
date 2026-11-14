from django import forms
from copy import copy

from archivebox.config.common import get_config, get_config_with_sources
from archivebox.plugins.forms import PLUGIN_GROUPS, PluginConfigFormMixin


class MachineSettingsForm(PluginConfigFormMixin, forms.Form):
    include_core_settings = True
    system_settings = True
    plugin_group_specs = (*PLUGIN_GROUPS, ("importers", "importers_plugins", "Importers"))
    config = forms.JSONField(required=False)

    def resolve_settings(self, config):
        machine = copy(self.machine)
        machine.config = config
        return get_config(machine=machine, include_file=False)

    def __init__(self, *args, machine, **kwargs):
        super().__init__(*args, **kwargs)
        self.machine = machine
        self.inherited = get_config(include_machine=False, include_file=False)
        resolved = get_config_with_sources(machine=machine)
        self.settings_sources = {key: item["source"] for key, item in resolved.items()}
        self.build_plugin_groups({key: item["value"] for key, item in resolved.items()})

    def clean(self):
        cleaned = super().clean()
        config = self.merge_settings(self.machine.config, self.inherited)
        cleaned["config"] = config
        return cleaned
