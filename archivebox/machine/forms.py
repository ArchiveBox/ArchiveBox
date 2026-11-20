from django import forms
from copy import copy
from django.utils.functional import cached_property

from archivebox.config.common import get_config, get_config_with_sources
from archivebox.plugins.forms import PLUGIN_GROUPS, PluginConfigFormMixin
from archivebox.machine.models import Machine


class MachineAdminForm(PluginConfigFormMixin, forms.ModelForm):
    class Meta:
        model = Machine
        fields = "__all__"

    include_core_settings = True
    system_settings = True
    plugin_group_specs = (*PLUGIN_GROUPS, ("importers", "importers_plugins", "Importers"))

    def resolve_settings(self, config):
        machine = copy(self.machine)
        machine.config = config
        return get_config(machine=machine, include_file=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.machine = self.instance
        # The writer handles only the submission; the grid renders after it.
        self._plugin_grid_machine = copy(self.instance)

    @cached_property
    def plugin_groups(self):
        resolved = get_config_with_sources(machine=self._plugin_grid_machine)
        self.settings_sources = {key: item["source"] for key, item in resolved.items()}
        self.build_plugin_groups({key: item["value"] for key, item in resolved.items()})
        return self.__dict__["plugin_groups"]

    def clean(self):
        cleaned = super().clean()
        config = cleaned.get("config") if "config" in self.data else self.machine.config
        if config is not None and not isinstance(config, dict):
            self.add_error("config", "Enter a JSON object.")
            config = {}
        config = self.merge_settings(config, get_config(include_machine=False, include_file=False))
        cleaned["config"] = config
        return cleaned
