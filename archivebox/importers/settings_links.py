"""Link to shared effective plugin configuration; never copy config values."""

from django.urls import reverse

from archivebox.config.common import ArchiveBoxConfig
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.plugins.forms import _plugin_config_input_name


def importer_settings_links(definition, source):
    if not definition:
        return []
    persona_scopes = {"crawl_frozen", "crawl_execution"}
    persona_url = reverse("admin:personas_persona_change", args=[source.persona_id]) if source.persona_id else ""
    links = []
    if definition.auth == "persona" or (definition.auth == "optional" and source.persona_id):
        if source.persona_id:
            links.append(
                {
                    "url": persona_url + "#persona-browser-state",
                    "label": "Open Persona browser state",
                },
            )
        else:
            links.append({"url": reverse("admin:personas_persona_changelist"), "label": "Set up a Persona"})
    if definition.settings_fields:
        from archivebox.machine.models import Machine

        machine = Machine.current_readonly(fields=("id",))
        machine_url = reverse("admin:machine_machine_change", args=[machine.pk]) if machine else reverse("admin:machine_machine_changelist")
        properties = get_plugin_catalog()[definition.plugin].manifest.get("properties", {})
        for key in definition.settings_fields:
            fragment = f"#id_{_plugin_config_input_name(definition.plugin, key)}"
            persona_allowed = ArchiveBoxConfig.scope_for_key(key) in persona_scopes
            machine_target = machine_url + fragment if machine else machine_url
            links.append(
                {
                    "url": persona_url + fragment if persona_allowed and persona_url else machine_target,
                    "label": f"Configure {properties.get(key, {}).get('title') or key}",
                    "persona_fragment": fragment if persona_allowed else "",
                    "machine_url": machine_target,
                },
            )
    return links
