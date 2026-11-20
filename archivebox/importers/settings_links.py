"""Link to shared effective plugin configuration; never copy config values."""

from django.urls import reverse

from archivebox.config.common import ArchiveBoxConfig


def importer_settings_links(definition, source):
    if not definition:
        return []
    # These stable panel IDs are shared by the Persona and Machine settings
    # forms. A Persona is an override only when explicitly selected.
    panel = f"#plugin-panel-importers_plugins-{definition.plugin}"
    keys = definition.settings_fields
    persona_scopes = {"crawl_frozen", "crawl_execution"}
    links = []
    if definition.auth == "persona" or (definition.auth == "optional" and source.persona_id):
        if source.persona_id:
            links.append(
                {
                    "url": reverse("admin:personas_persona_change", args=[source.persona_id]) + "#persona-browser-state",
                    "label": "Open Persona browser state",
                },
            )
        else:
            links.append({"url": reverse("admin:personas_persona_changelist"), "label": "Set up a Persona"})
    if source.persona_id and any(ArchiveBoxConfig.scope_for_key(key) in persona_scopes for key in keys):
        links.append(
            {"url": reverse("admin:personas_persona_change", args=[source.persona_id]) + panel, "label": "Open Persona plugin settings"},
        )
    if keys and (not source.persona_id or any(ArchiveBoxConfig.scope_for_key(key) not in persona_scopes for key in keys)):
        from archivebox.machine.models import Machine

        machine = Machine.current_readonly()
        if machine:
            links.append(
                {"url": reverse("admin:machine_machine_change", args=[machine.pk]) + panel, "label": "Open machine plugin settings"},
            )
    return links
