__package__ = "archivebox.personas"

import shutil
from copy import deepcopy
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.personas.forms import PersonaAdminForm
from archivebox.personas.importers import discover_local_browser_profiles
from archivebox.personas.models import Persona
from archivebox.personas.state_forms import PersonaStateForm, browser_state_summary


class PersonaSnapshotDomainListFilter(admin.SimpleListFilter):
    title = "snapshot domain"
    parameter_name = "snapshot__domain"

    def lookups(self, request, model_admin):
        return [(self.value(), self.value())] if self.value() else []

    def queryset(self, request, queryset):
        from archivebox.core.models import Snapshot

        if self.value():
            try:
                return queryset.filter(pk__in=Snapshot.objects.filter_by_domain(self.value()).values("crawl__persona_id"))
            except ValueError:
                return queryset.none()
        return queryset


class PersonaAdmin(ConfigEditorMixin, BaseModelAdmin):
    form = PersonaAdminForm
    change_form_template = "admin/personas/persona/change_form.html"

    list_display = ("name", "created_by", "created_at", "chrome_profile_state", "cookies_state", "auth_state")
    search_fields = ("name", "created_by__username")
    list_filter = ("created_by", PersonaSnapshotDomainListFilter)
    ordering = ["name"]
    list_per_page = 100
    readonly_fields = ("id", "created_at", "persona_paths", "import_artifact_status")

    add_fieldsets = (
        (
            "Persona",
            {
                "fields": (("name", "created_by", "permissions"),),
                "classes": ("card", "wide", "persona-card-primary"),
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
                "classes": ("card", "wide", "persona-card-import"),
            },
        ),
        (
            "Advanced",
            {
                "fields": ("config",),
                "classes": ("card", "wide", "collapse", "persona-card-config"),
            },
        ),
    )

    change_fieldsets = (
        add_fieldsets[0],
        (
            "Browser state",
            {
                "fields": ("import_artifact_status", "persona_paths"),
                "classes": ("card", "wide", "persona-card-browser"),
            },
        ),
        add_fieldsets[2],
        (
            "Details",
            {
                "fields": (("id", "created_at"),),
                "classes": ("card", "wide", "collapse", "persona-card-timestamps"),
            },
        ),
    )

    @admin.display(description="Chrome Profile")
    def chrome_profile_state(self, obj: Persona) -> str:
        return "yes" if (obj.path / "chrome_profile").exists() else "no"

    @admin.display(description="cookies.txt")
    def cookies_state(self, obj: Persona) -> str:
        return "yes" if obj.COOKIES_FILE else "no"

    @admin.display(description="auth.json")
    def auth_state(self, obj: Persona) -> str:
        return "yes" if obj.AUTH_STORAGE_FILE else "no"

    @admin.display(description="Persona Paths")
    def persona_paths(self, obj: Persona) -> str:
        return format_html(
            "<details class='abx-persona-storage'><summary>Storage locations</summary>"
            "<div class='abx-persona-path-list'>"
            "<div><strong>Persona root</strong><code>{}</code></div>"
            "<div><strong>chrome_profile</strong><code>{}</code></div>"
            "<div><strong>chrome_downloads</strong><code>{}</code></div>"
            "<div><strong>cookies.txt</strong><code>{}</code></div>"
            "<div><strong>auth.json</strong><code>{}</code></div>"
            "</div></details>",
            obj.path,
            obj.CHROME_USER_DATA_DIR,
            obj.CHROME_DOWNLOADS_DIR,
            obj.COOKIES_FILE or (obj.path / "cookies.txt"),
            obj.AUTH_STORAGE_FILE or (obj.path / "auth.json"),
        )

    @admin.display(description="Import Artifacts")
    def import_artifact_status(self, obj: Persona) -> str:
        return render_to_string(
            "admin/personas/persona/browser_state.html",
            {
                "persona": obj,
                "cards": browser_state_summary(obj),
                "can_change": getattr(obj, "_browser_state_can_change", False),
                "server_url": getattr(obj, "_browser_state_server_url", ""),
                "state_url": reverse("admin:personas_persona_browser_state", args=[obj.pk]),
            },
        )

    def get_fieldsets(self, request, obj=None):
        return self.change_fieldsets if obj else self.add_fieldsets

    def get_admin_toolbar_actions(self, request, obj):
        actions = super().get_admin_toolbar_actions(request, obj)
        if obj is None or not self.has_view_or_change_permission(request, obj):
            return actions
        if self.has_add_permission(request):
            actions.append(
                {
                    "label": "Duplicate settings",
                    "icon": "⧉",
                    "title": "Create a new persona from these saved settings",
                    "formaction": reverse("admin:personas_persona_duplicate_settings", args=[obj.pk]),
                    "formmethod": "post",
                },
            )
        # /add/ permits custom persona selection for administrators.
        if request.user.is_superuser:
            actions.append(
                {
                    "label": "Test capture",
                    "icon": "▶",
                    "title": "Choose a URL to capture with this persona's saved settings",
                    "url": f"{reverse('add')}?{urlencode({'persona': obj.name, 'depth': 0, 'max_urls': 1})}",
                },
            )
        return actions

    def get_urls(self):
        return [
            path(
                "<hexuuid:object_id>/browser-state/",
                self.admin_site.admin_view(require_POST(self.browser_state_view)),
                name="personas_persona_browser_state",
            ),
            path(
                "<hexuuid:object_id>/duplicate-settings/",
                self.admin_site.admin_view(require_POST(self.duplicate_settings_view)),
                name="personas_persona_duplicate_settings",
            ),
        ] + super().get_urls()

    def browser_state_view(self, request, object_id):
        persona = self.get_object(request, str(object_id))
        if persona is None:
            raise Http404
        if not self.has_change_permission(request, persona):
            raise PermissionDenied
        form = PersonaStateForm(request.POST)
        if form.is_valid():
            from django.core.exceptions import ValidationError

            try:
                form.apply(persona)
            except ValidationError as error:
                form.add_error(None, error)
            except OSError:
                form.add_error(None, "Unable to write browser state. Check the persona directory permissions.")
            else:
                self.log_change(
                    request,
                    persona,
                    f"{form.cleaned_data['action'].capitalize()} {form.cleaned_data['artifact']} browser state.",
                )
                return JsonResponse({"saved": True, "cards": browser_state_summary(persona)})
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)

    def duplicate_settings_view(self, request, object_id):
        source = self.get_object(request, str(object_id))
        if source is None:
            raise Http404
        if not self.has_view_or_change_permission(request, source) or not self.has_add_permission(request):
            raise PermissionDenied

        from archivebox.config.common import is_sensitive_config_key

        # Browser-state references would make the new persona reuse the source's
        # identity even without copying files. Credentials stay write-only.
        identity_keys = {
            "COOKIES_FILE",
            "AUTH_STORAGE_FILE",
            "CHROME_USER_DATA_DIR",
            "CHROME_DOWNLOADS_DIR",
            "CHROME_CDP_URL",
            "PERSONAS_DIR",
            "ACTIVE_PERSONA",
        }
        config = {
            key: deepcopy(value)
            for key, value in (source.config or {}).items()
            if key not in identity_keys and not key.endswith("_COOKIES_FILE") and not is_sensitive_config_key(key)
        }
        existing_names = {name.casefold() for name in Persona.objects.values_list("name", flat=True)}
        if source.path.parent.exists():
            existing_names.update(entry.name.casefold() for entry in source.path.parent.iterdir())
        number = 1
        while True:
            suffix = " copy" if number == 1 else f" copy {number}"
            name = source.name[: 64 - len(suffix)] + suffix
            if name.casefold() not in existing_names:
                break
            number += 1
        duplicate = Persona.objects.create(name=name, created_by=request.user, config=config)
        self.log_addition(request, duplicate, f"Duplicated settings from {source.name}.")
        self.message_user(request, f"Created {duplicate.name} from saved settings.", messages.SUCCESS)
        return redirect("admin:personas_persona_change", duplicate.pk)

    def get_form(self, request, obj=None, change=False, **kwargs):
        if kwargs.get("fields"):
            kwargs["fields"] = [field for field in kwargs["fields"] if field != "permissions"]
        return super().get_form(request, obj=obj, change=change, **kwargs)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            obj._browser_state_can_change = self.has_change_permission(request, obj)
            obj._browser_state_server_url = request.build_absolute_uri("/")
        context["detected_profile_count"] = len(discover_local_browser_profiles()) if add else 0
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
