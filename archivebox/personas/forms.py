__package__ = "archivebox.personas"

from typing import Any

from django import forms
from django.utils.safestring import mark_safe

from archivebox.personas.importers import (
    PersonaImportResult,
    PersonaImportSource,
    discover_local_browser_profiles,
    import_persona_from_source,
    resolve_custom_import_source,
    validate_persona_name,
)
from archivebox.personas.models import Persona


def _mode_label(title: str, description: str) -> str:
    return mark_safe(
        f'<span class="abx-import-mode-option"><strong>{title}</strong><span>{description}</span></span>'
    )


class PersonaAdminForm(forms.ModelForm):
    import_mode = forms.ChoiceField(
        required=False,
        initial="none",
        label="Bootstrap this persona",
        widget=forms.RadioSelect,
        choices=(
            ("none", _mode_label("Blank Persona", "Create the persona without importing browser state yet.")),
            ("discovered", _mode_label("Use a detected profile", "Pick from Chromium profiles auto-discovered on this host.")),
            ("custom", _mode_label("Use a custom path or CDP URL", "Paste an absolute Chromium path or attach to a live browser debugging endpoint.")),
        ),
        help_text="These options run after the Persona row is saved, using the same backend import helpers as the CLI.",
    )
    import_discovered_profile = forms.ChoiceField(
        required=False,
        label="Autodiscovered profiles",
        widget=forms.RadioSelect,
        choices=(),
        help_text="Detected from local Chrome, Chromium, Brave, and Edge profile roots.",
    )
    import_source = forms.CharField(
        required=False,
        label="Absolute path or CDP URL",
        widget=forms.TextInput(
            attrs={
                "placeholder": "/Users/alice/Library/Application Support/Google/Chrome  or  ws://127.0.0.1:9222/devtools/browser/...",
                "style": "width: 100%; font-family: monospace;",
            }
        ),
        help_text="Accepts an absolute Chromium user-data dir, an exact profile dir, or a live HTTP/WS CDP endpoint.",
    )
    import_profile_name = forms.CharField(
        required=False,
        label="Profile directory name",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Default or Profile 1",
                "style": "width: 100%; font-family: monospace;",
            }
        ),
        help_text="Only used when the custom path points at a browser root containing multiple profiles.",
    )
    import_copy_profile = forms.BooleanField(
        required=False,
        initial=True,
        label="Copy browser profile into this persona",
        help_text="Copies the chosen Chromium user-data tree into `chrome_user_data` for future archiving runs.",
    )
    import_extract_cookies = forms.BooleanField(
        required=False,
        initial=True,
        label="Generate `cookies.txt`",
        help_text="Extracts cookies through Chrome DevTools Protocol and writes a Netscape cookie jar for wget/curl-based plugins.",
    )
    import_capture_storage = forms.BooleanField(
        required=False,
        initial=True,
        label="Capture open-tab storage into `auth.json`",
        help_text="Snapshots currently open tab `localStorage` / `sessionStorage` values by origin. This is most useful for live CDP imports.",
    )

    class Meta:
        model = Persona
        fields = ("name", "created_by", "config")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.discovered_profiles = discover_local_browser_profiles()
        self._resolved_import_source: PersonaImportSource | None = None

        self.fields["import_mode"].widget.attrs["class"] = "abx-import-mode"
        self.fields["import_discovered_profile"].widget.attrs["class"] = "abx-profile-picker"

        if self.discovered_profiles:
            self.fields["import_discovered_profile"].choices = [
                (profile.choice_value, profile.as_choice_label()) for profile in self.discovered_profiles
            ]
        else:
            self.fields["import_discovered_profile"].choices = []
            self.fields["import_discovered_profile"].help_text = (
                "No local Chromium profiles were detected on this host right now. "
                "Use the custom path/CDP option if the browser data lives elsewhere."
            )

    def clean_name(self) -> str:
        name = str(self.cleaned_data.get("name") or "").strip()
        is_valid, error_message = validate_persona_name(name)
        if not is_valid:
            raise forms.ValidationError(error_message)
        return name

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        self._resolved_import_source = None

        import_mode = str(cleaned_data.get("import_mode") or "none").strip() or "none"
        if import_mode == "none":
            return cleaned_data

        if import_mode == "discovered":
            selection = str(cleaned_data.get("import_discovered_profile") or "").strip()
            if not selection:
                self.add_error("import_discovered_profile", "Choose one of the discovered profiles to import.")
                return cleaned_data
            try:
                self._resolved_import_source = PersonaImportSource.from_choice_value(selection)
            except ValueError as err:
                self.add_error("import_discovered_profile", str(err))
                return cleaned_data
        elif import_mode == "custom":
            raw_value = str(cleaned_data.get("import_source") or "").strip()
            if not raw_value:
                self.add_error("import_source", "Provide an absolute Chromium profile path or a CDP URL.")
                return cleaned_data
            try:
                self._resolved_import_source = resolve_custom_import_source(
                    raw_value,
                    profile_dir=str(cleaned_data.get("import_profile_name") or "").strip() or None,
                )
            except ValueError as err:
                self.add_error("import_source", str(err))
                return cleaned_data
        else:
            self.add_error("import_mode", "Choose how this Persona should be bootstrapped.")
            return cleaned_data

        copy_profile = bool(cleaned_data.get("import_copy_profile"))
        import_cookies = bool(cleaned_data.get("import_extract_cookies"))
        capture_storage = bool(cleaned_data.get("import_capture_storage"))

        if self._resolved_import_source.kind == "cdp":
            if not (import_cookies or capture_storage):
                self.add_error(
                    "import_extract_cookies",
                    "CDP imports can only capture cookies and/or open-tab storage. Profile copying is not available for a remote browser endpoint.",
                )
        elif not (copy_profile or import_cookies or capture_storage):
            raise forms.ValidationError("Select at least one import action.")

        return cleaned_data

    def apply_import(self, persona: Persona) -> PersonaImportResult | None:
        if not self._resolved_import_source:
            return None

        return import_persona_from_source(
            persona,
            self._resolved_import_source,
            copy_profile=bool(self.cleaned_data.get("import_copy_profile")),
            import_cookies=bool(self.cleaned_data.get("import_extract_cookies")),
            capture_storage=bool(self.cleaned_data.get("import_capture_storage")),
        )
