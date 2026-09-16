"""Base admin classes for models using UUIDv7."""

__package__ = "archivebox.base_models"

import json
import uuid
from collections.abc import Mapping
from typing import ClassVar, NotRequired, TypedDict, cast

from django import forms
from django.contrib import admin
from django.db import DatabaseError, models
from django.forms.renderers import BaseRenderer
from django.http import HttpRequest, QueryDict
from django.urls import path, register_converter
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from django_object_actions import DjangoObjectActions


def card_fieldset(title: str | None, fields: tuple, *, wide: bool = False, **options):
    """Build a Django fieldset using the shared card layout."""
    return title, {"fields": fields, "classes": ("card", "wide") if wide else ("card",), **options}


class HexUUIDConverter:
    """URL path converter that canonicalizes UUIDs to their 32-char hex form.

    Accepts both the hyphenated (``aaaaaaaa-bbbb-...``) and bare-hex
    (``aaaaaaaabbbb...``) UUID strings on the way in (Django's UUIDField
    parses either), but ``to_url`` always emits the bare-hex form. This is
    what makes ``reverse("admin:app_model_change", args=[obj.pk])`` produce
    ``/admin/app/model/06a1a8facb0d.../change/`` instead of the default
    hyphenated rendering — admin links throughout the app reverse through
    this converter once ``BaseModelAdmin.get_urls`` swaps in
    ``<hexuuid:object_id>`` below.
    """

    regex = r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def to_python(self, value: str) -> str:
        # Strip hyphens but stay as a string — Django admin treats the
        # captured object_id as a string and calls ``model._meta.pk.to_python``
        # itself, so we don't want to short-circuit that.
        return value.replace("-", "")

    def to_url(self, value) -> str:
        if isinstance(value, uuid.UUID):
            return value.hex
        return str(value).replace("-", "")


register_converter(HexUUIDConverter, "hexuuid")


class ConfigOption(TypedDict):
    plugin: str
    type: str | list[str]
    default: object
    description: str
    enum: NotRequired[list[object]]
    pattern: NotRequired[str]
    minimum: NotRequired[int | float]
    maximum: NotRequired[int | float]


class KeyValueWidget(forms.Widget):
    """
    A widget that renders JSON dict as editable key-value input fields
    with + and - buttons to add/remove rows.
    Includes autocomplete for available config keys from the plugin system.
    """

    template_name = ""  # We render manually

    class Media:
        css: ClassVar[dict[str, list[str]]] = {
            "all": [],
        }
        js: ClassVar[list[str]] = []

    def _get_config_options(self) -> dict[str, ConfigOption]:
        """Get available config options from plugins."""
        try:
            from archivebox.config.common import config_field_metadata

            options: dict[str, ConfigOption] = {}
            for key, metadata in config_field_metadata().items():
                option_type = metadata.get("type", "string")
                # Core fields expose Python type names; plugins use JSON Schema.
                # The editor should apply the same typed validation to both.
                type_names = {"bool": "boolean", "int": "integer", "float": "number", "str": "string", "dict": "object", "list": "array"}
                if isinstance(option_type, str):
                    option_type = type_names.get(option_type, option_type)
                option: ConfigOption = {
                    "plugin": str(metadata.get("plugin", "archivebox")),
                    "type": cast(str | list[str], option_type if isinstance(option_type, (str, list)) else str(option_type)),
                    "default": metadata.get("default", ""),
                    "description": str(metadata.get("description", "")),
                }
                schema = metadata.get("schema")
                if isinstance(schema, Mapping):
                    for schema_key in ("enum", "pattern", "minimum", "maximum"):
                        if schema_key in schema:
                            option[schema_key] = schema[schema_key]
                options[key] = option
            return options
        except (ImportError, KeyError, TypeError, ValueError):
            return {}

    def _parse_value(self, value: object) -> dict[str, object]:
        # Parse JSON value to dict
        if value is None:
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else {}
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
        return {}

    def render(
        self,
        name: str,
        value: object,
        attrs: Mapping[str, str] | None = None,
        renderer: BaseRenderer | None = None,
    ) -> SafeString:
        from django.template.loader import render_to_string

        widget_id = attrs.get("id", name) if attrs else name
        options = self._get_config_options()
        rows = [
            mark_safe(self._render_row(widget_id, key, val if isinstance(val, str) else json.dumps(val)))
            for key, val in self._parse_value(value).items()
        ]
        empty_row = mark_safe(self._render_row(widget_id, "", ""))
        # JSON is embedded in a script, so escape HTML delimiters without changing data.
        metadata = json.dumps(options).translate({ord("<"): r"\u003C", ord(">"): r"\u003E", ord("&"): r"\u0026"})
        return mark_safe(
            render_to_string(
                "admin/widgets/config.html",
                {
                    "name": name,
                    "widget_id": widget_id,
                    "datalist_options": mark_safe(
                        "\n".join(
                            f'<option value="{self._escape(key)}">{self._escape(opt["description"][:60] or opt["type"])}</option>'
                            for key, opt in sorted(options.items())
                        ),
                    ),
                    "config_meta_json": metadata,
                    "rows": [*rows, empty_row],
                    "empty_row": empty_row,
                },
            ),
        )

    def _render_row(self, widget_id: str, key: str, value: str) -> str:
        from archivebox.config.common import is_sensitive_config_key

        # Sensitive keys (``*TOKEN*``, ``*SECRET*``, ``*API_KEY*``, ``*APIKEY*``) are
        # rendered write-only: the input is a password field with a placeholder
        # showing the value is set, but the raw value is NEVER sent to the browser.
        # When the user submits the form with the field left blank, the
        # ``ConfigEditorMixin.save_model`` hook re-merges the previously-saved
        # value so leaving it untouched is a no-op rather than a destructive clear.
        is_sensitive = is_sensitive_config_key(key)
        has_value = bool(value)
        if is_sensitive:
            input_type = "password"
            rendered_value = ""
            placeholder = (
                "•••••• (saved — enter new value to replace, clear by deleting row)" if has_value else "value (will be saved write-only)"
            )
            extra_attrs = ' autocomplete="off" data-sensitive="1"' + (' data-had-value="1"' if has_value else "")
        else:
            input_type = "text"
            rendered_value = self._escape(value)
            placeholder = "value"
            extra_attrs = ""
        return f'''
            <div class="key-value-row" style="margin-bottom: 6px;">
                <div class="kv-inputs" style="display: flex; gap: 8px; align-items: center;">
                    <input type="text" class="kv-key" value="{self._escape(key)}" placeholder="KEY" list="{widget_id}_keys"
                           style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    <input type="{input_type}" class="kv-value" value="{rendered_value}" placeholder="{self._escape(placeholder)}"{extra_attrs}
                           style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    <datalist class="kv-value-options"></datalist>
                    <button type="button" onclick="removeKeyValueRow_{widget_id}(this)"
                            style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>
                </div>
                <div class="kv-help" style="margin-top: 4px; font-size: 11px; color: #666; font-style: italic;"></div>
            </div>
        '''

    def _escape(self, s: object) -> str:
        """Escape HTML special chars in attribute values."""
        if not s:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def value_from_datadict(
        self,
        data: QueryDict | Mapping[str, object],
        files: object,
        name: str,
    ) -> str:
        value = data.get(name, "{}")
        return value if isinstance(value, str) else "{}"


class ConfigEditorMixin(admin.ModelAdmin):
    """
    Mixin for admin classes with a config JSON field.

    Provides a key-value editor widget with autocomplete for available config keys.
    """

    def formfield_for_dbfield(
        self,
        db_field: models.Field,
        request: HttpRequest,
        **kwargs: object,
    ) -> forms.Field | None:
        """Use KeyValueWidget for the config JSON field."""
        if db_field.name == "config":
            kwargs["widget"] = KeyValueWidget()
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request: HttpRequest, obj, form, change):
        """Preserve write-only redacted credentials on save.

        The KeyValueWidget renders sensitive keys (``*TOKEN*``, ``*SECRET*``,
        ``*API_KEY*``, ``*APIKEY*``) with an empty value + password input —
        the real value never leaves the server. On submit, an empty value
        for a sensitive key that was previously set means "leave untouched",
        not "clear it." We honor that here by re-merging the stored value
        before the row is written. Explicitly removing the row in the UI
        still clears it (the key is gone from the submitted JSON, so there's
        nothing to merge over).
        """
        from archivebox.config.common import is_sensitive_config_key

        if change and obj.pk and obj.config is not None:
            try:
                stored = type(obj).objects.filter(pk=obj.pk).values_list("config", flat=True).first() or {}
            except (AttributeError, DatabaseError, TypeError, ValueError):
                stored = {}
            if isinstance(stored, dict):
                new_config = dict(obj.config or {})
                for key, new_value in list(new_config.items()):
                    if not is_sensitive_config_key(key):
                        continue
                    if new_value not in (None, "") and new_value != "********":
                        continue
                    if key in stored:
                        new_config[key] = stored[key]
                obj.config = new_config
        super().save_model(request, obj, form, change)


class BaseModelAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ("id", "created_at", "created_by")
    readonly_fields = ("id", "created_at", "modified_at")
    show_search_mode_selector = False
    change_form_template = "admin/archivebox_change_form.html"

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)

    def get_ordering_fields(self, request):
        ordering = request.GET.get("o")
        if not ordering:
            return set()
        fields = set()
        for part in ordering.split("."):
            if not part:
                continue
            try:
                idx = abs(int(part)) - 1
            except ValueError:
                continue
            if 0 <= idx < len(self.list_display):
                fields.add(self.list_display[idx])
        return fields

    def get_admin_toolbar_actions(self, request, obj):
        """Return extra action button dicts for the shared change-form toolbar.

        See ``templates/admin/includes/archivebox_toolbar.html`` for the
        accepted keys. Default: no extras (toolbar renders Save/History/Delete
        plus any ``django-object-actions`` change_actions).
        """
        return []

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context.setdefault("archivebox_admin_actions", self.get_admin_toolbar_actions(request, obj))
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_default_search_mode(self) -> str:
        # The shared changelist template always asks every admin for a default
        # search mode, even when the search-mode toggle is hidden.
        return "meta"

    def get_form(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
        change: bool = False,
        **kwargs: object,
    ):
        form = super().get_form(request, obj, change=change, **kwargs)
        if "created_by" in form.base_fields:
            form.base_fields["created_by"].initial = request.user
        return form

    def get_urls(self):
        """Swap the per-object admin URLs from ``<path:object_id>`` to
        ``<hexuuid:object_id>`` so canonical change/delete/history URLs use the
        32-char hex form. The hyphenated form still resolves because the
        converter's regex accepts both — Django reverses through ``to_url``
        which always emits hex, so links in templates / changelists / inline
        formsets all canonicalize automatically.

        Non-UUID PKs (an ``IntegerField`` PK on some legacy table, for example)
        won't match the converter's regex and fall back to the default
        ``<path:object_id>`` patterns we still include after our swap.
        """
        info = self.opts.app_label, self.opts.model_name
        object_routes = [
            path("<hexuuid:object_id>/history/", self.admin_site.admin_view(self.history_view), name="{}_{}_history".format(*info)),
            path("<hexuuid:object_id>/delete/", self.admin_site.admin_view(self.delete_view), name="{}_{}_delete".format(*info)),
            path("<hexuuid:object_id>/change/", self.admin_site.admin_view(self.change_view), name="{}_{}_change".format(*info)),
        ]
        # Append after super().get_urls() so our patterns are the
        # *last-registered* ones with the canonical admin URL names — Django's
        # reverse() picks the later registration when names collide, which is
        # how we make ``reverse("admin:app_model_change", args=[obj.pk])``
        # emit the hex form. The original ``<path:object_id>`` routes stay in
        # place as a fallback for non-UUID PKs and for resolving inbound
        # hyphenated URLs (the ``hexuuid`` regex accepts both forms anyway).
        return super().get_urls() + object_routes
