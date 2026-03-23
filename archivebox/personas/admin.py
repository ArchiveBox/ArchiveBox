__package__ = "archivebox.personas"

import shutil

from django.contrib import admin, messages
from django.utils.html import format_html, format_html_join

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.personas.forms import PersonaAdminForm
from archivebox.personas.importers import discover_local_browser_profiles
from archivebox.personas.models import Persona


class PersonaAdmin(ConfigEditorMixin, BaseModelAdmin):
    form = PersonaAdminForm
    change_form_template = "admin/personas/persona/change_form.html"

    list_display = ("name", "created_by", "created_at", "chrome_profile_state", "cookies_state", "auth_state")
    search_fields = ("name", "created_by__username")
    list_filter = ("created_by",)
    ordering = ["name"]
    list_per_page = 100
    readonly_fields = ("id", "created_at", "persona_paths", "import_artifact_status")

    add_fieldsets = (
        (
            "Persona",
            {
                "fields": ("name", "created_by"),
                "classes": ("card",),
            },
        ),
        (
            "Browser Import",
            {
                "fields": (
                    "import_mode",
                    "import_discovered_profile",
                    "import_source",
                    "import_profile_name",
                    "import_copy_profile",
                    "import_extract_cookies",
                    "import_capture_storage",
                ),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Advanced",
            {
                "fields": ("config",),
                "classes": ("card", "wide"),
            },
        ),
    )

    change_fieldsets = add_fieldsets + (
        (
            "Artifacts",
            {
                "fields": ("persona_paths", "import_artifact_status"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("id", "created_at"),
                "classes": ("card",),
            },
        ),
    )

    @admin.display(description="Chrome Profile")
    def chrome_profile_state(self, obj: Persona) -> str:
        return "yes" if (obj.path / "chrome_user_data").exists() else "no"

    @admin.display(description="cookies.txt")
    def cookies_state(self, obj: Persona) -> str:
        return "yes" if obj.COOKIES_FILE else "no"

    @admin.display(description="auth.json")
    def auth_state(self, obj: Persona) -> str:
        return "yes" if obj.AUTH_STORAGE_FILE else "no"

    @admin.display(description="Persona Paths")
    def persona_paths(self, obj: Persona) -> str:
        return format_html(
            "<div class='abx-persona-path-list'>"
            "<div><strong>Persona root</strong><code>{}</code></div>"
            "<div><strong>chrome_user_data</strong><code>{}</code></div>"
            "<div><strong>chrome_extensions</strong><code>{}</code></div>"
            "<div><strong>chrome_downloads</strong><code>{}</code></div>"
            "<div><strong>cookies.txt</strong><code>{}</code></div>"
            "<div><strong>auth.json</strong><code>{}</code></div>"
            "</div>",
            obj.path,
            obj.CHROME_USER_DATA_DIR,
            obj.CHROME_EXTENSIONS_DIR,
            obj.CHROME_DOWNLOADS_DIR,
            obj.COOKIES_FILE or (obj.path / "cookies.txt"),
            obj.AUTH_STORAGE_FILE or (obj.path / "auth.json"),
        )

    @admin.display(description="Import Artifacts")
    def import_artifact_status(self, obj: Persona) -> str:
        entries = [
            ("Browser profile", (obj.path / "chrome_user_data").exists(), obj.CHROME_USER_DATA_DIR),
            ("cookies.txt", bool(obj.COOKIES_FILE), obj.COOKIES_FILE or (obj.path / "cookies.txt")),
            ("auth.json", bool(obj.AUTH_STORAGE_FILE), obj.AUTH_STORAGE_FILE or (obj.path / "auth.json")),
        ]
        return format_html(
            "<div class='abx-persona-artifacts'>{}</div>",
            format_html_join(
                "",
                "<div class='abx-persona-artifact'><strong>{}</strong><span class='{}'>{}</span><code>{}</code></div>",
                (
                    (
                        label,
                        "abx-artifact-state abx-artifact-state--yes" if enabled else "abx-artifact-state abx-artifact-state--no",
                        "present" if enabled else "missing",
                        path,
                    )
                    for label, enabled, path in entries
                ),
            ),
        )

    def get_fieldsets(self, request, obj=None):
        return self.change_fieldsets if obj else self.add_fieldsets

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context["detected_profile_count"] = len(discover_local_browser_profiles())
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def save_model(self, request, obj, form, change):
        old_path = None
        new_path = None
        if change:
            previous = Persona.objects.get(pk=obj.pk)
            if previous.name != obj.name:
                old_path = previous.path
                new_path = obj.path

        super().save_model(request, obj, form, change)

        if old_path and new_path and old_path != new_path and old_path.exists():
            if new_path.exists():
                raise FileExistsError(f"Cannot rename Persona directory because the destination already exists: {new_path}")
            shutil.move(str(old_path), str(new_path))

        obj.ensure_dirs()

        import_result = form.apply_import(obj)
        if import_result is None:
            return

        completed_actions = []
        if import_result.profile_copied:
            completed_actions.append("profile copied")
        if import_result.cookies_imported:
            completed_actions.append("cookies.txt generated")
        if import_result.storage_captured:
            completed_actions.append("auth.json captured")
        if import_result.user_agent_imported:
            completed_actions.append("USER_AGENT copied")

        if completed_actions:
            messages.success(
                request,
                f"Imported {', '.join(completed_actions)} from {import_result.source.display_label}.",
            )
        else:
            messages.warning(
                request,
                f"Persona saved, but no browser artifacts were imported from {import_result.source.display_label}.",
            )

        for warning in import_result.warnings:
            messages.warning(request, warning)


def register_admin(admin_site: admin.AdminSite) -> None:
    admin_site.register(Persona, PersonaAdmin)
