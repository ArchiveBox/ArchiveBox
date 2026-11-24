__package__ = "archivebox.api"

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.pagination import paginate
from pydantic import Field, field_validator
from atomicwrites import atomic_write

from archivebox.api.v1_core import CustomPagination
from archivebox.personas.importers import validate_persona_name
from archivebox.personas.models import Persona


router = Router(tags=["Personas"])


class PersonaBrowserSettingsSchema(Schema):
    user_agent: str = ""
    viewport_size: str = Field(default="", pattern=r"^(?:[1-9]\d*,[1-9]\d*)?$")
    viewport_device_scale_factor: float | None = Field(default=None, gt=0)
    color_scheme: Literal["", "light", "dark"] = ""
    language: str = ""
    timezone: str = ""
    platform: str = ""
    user_agent_metadata: dict[str, Any] | None = None
    geolocation: dict[str, Any] | None = None


class PersonaSyncSchema(Schema):
    extension_persona_id: str
    name: str
    settings: PersonaBrowserSettingsSchema = Field(default_factory=PersonaBrowserSettingsSchema)
    cookies_txt: str = ""
    auth_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("auth_json")
    @classmethod
    def validate_auth_origins(cls, auth):
        if "origins" not in auth:
            return auth
        if not isinstance(auth["origins"], list):
            raise ValueError("auth_json.origins must be a list")
        for entry in auth["origins"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("origin"), str) or not entry["origin"]:
                raise ValueError("Each auth_json origin must have a nonempty origin string")
            for field in ("localStorage", "sessionStorage", "indexedDB"):
                if field in entry and not isinstance(entry[field], list):
                    raise ValueError(f"auth_json origin {field} must be a list")
        return auth


class PersonaSchema(Schema):
    TYPE: str = "personas.models.Persona"
    id: UUID
    name: str
    created_at: datetime
    created_by_id: str
    created_by_username: str
    config: dict[str, Any] | None

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by.pk)

    @staticmethod
    def resolve_created_by_username(obj) -> str:
        return obj.created_by.username

    @staticmethod
    def resolve_config(obj):
        # Redact credential values so REST responses don't leak the raw
        # token/secret/api-key the operator stored in Persona.config.
        from archivebox.config.common import redact_sensitive_config

        return redact_sensitive_config(obj.config)


class PersonaSyncResponseSchema(Schema):
    success: bool
    created: bool
    persona: PersonaSchema
    cookies_file_written: bool
    auth_file_written: bool


def browser_settings_to_config(extension_persona_id: str, settings: PersonaBrowserSettingsSchema) -> dict[str, Any]:
    config: dict[str, Any] = {
        "BROWSER_EXTENSION_PERSONA_ID": extension_persona_id,
        "BROWSER_EXTENSION_SYNCED_AT": datetime.utcnow().isoformat() + "Z",
    }

    if "user_agent" in settings.model_fields_set:
        config.update(
            {
                "USER_AGENT": settings.user_agent,
                "CHROME_USER_AGENT": settings.user_agent,
                "WGET_USER_AGENT": settings.user_agent,
                "CURL_USER_AGENT": settings.user_agent,
            },
        )
    if "viewport_size" in settings.model_fields_set:
        config.update(
            {
                "RESOLUTION": settings.viewport_size or "1440,2000",
                "CHROME_RESOLUTION": settings.viewport_size or "1440,2000",
            },
        )
    if "viewport_device_scale_factor" in settings.model_fields_set:
        config["BROWSER_DEVICE_SCALE_FACTOR"] = settings.viewport_device_scale_factor or 1
    if "color_scheme" in settings.model_fields_set:
        config["BROWSER_COLOR_SCHEME"] = settings.color_scheme
    if "language" in settings.model_fields_set:
        config["BROWSER_LANGUAGE"] = settings.language
    if "timezone" in settings.model_fields_set:
        config["BROWSER_TIMEZONE"] = settings.timezone
    if "platform" in settings.model_fields_set:
        config["BROWSER_PLATFORM"] = settings.platform
    if "user_agent_metadata" in settings.model_fields_set:
        config["BROWSER_USER_AGENT_METADATA"] = settings.user_agent_metadata or {}
    if "geolocation" in settings.model_fields_set:
        config["BROWSER_GEOLOCATION"] = settings.geolocation or {}

    return config


def find_persona(extension_persona_id: str, name: str) -> Persona | None:
    named = Persona.find_named(name)
    return (
        Persona.objects.filter(Q(config__BROWSER_EXTENSION_PERSONA_ID=extension_persona_id) | Q(pk=named.pk if named else None))
        .order_by("created_at")
        .first()
    )


@router.get("/personas", response=list[PersonaSchema], url_name="get_personas")
@paginate(CustomPagination)
def get_personas(request: HttpRequest):
    """List personas available on this ArchiveBox server."""
    return Persona.objects.all().order_by("name")


def _merge_synced_auth(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if not incoming:
        return {}  # An explicitly empty auth artifact still means clear all.
    merged = {**existing, **incoming}
    if "origins" in incoming:
        previous_origins = existing.get("origins", [])
        previous = (
            {entry["origin"]: entry for entry in previous_origins if isinstance(entry, dict) and isinstance(entry.get("origin"), str)}
            if isinstance(previous_origins, list)
            else {}
        )
        # Membership/order follows the submitted list, so removed domains stay
        # removed. Omitted fields on a retained origin preserve saved IndexedDB
        # during light sync; explicit empty arrays clear just that field.
        merged["origins"] = [{**previous.get(entry["origin"], {}), **entry} for entry in incoming["origins"]]
    return merged


@router.post("/sync", response=PersonaSyncResponseSchema, url_name="sync_persona")
def sync_persona(request: HttpRequest, payload: PersonaSyncSchema):
    """
    Create or update a Persona from a browser extension profile export.

    The extension sends browser settings plus portable auth artifacts. The server
    keeps browser override settings in Persona.config and writes cookies.txt /
    auth.json into the persona directory for extractors to consume. Omitted
    auth fields are preserved; an empty auth object clears the artifact. A
    supplied origins list replaces membership while retaining omitted fields
    of each matching origin, allowing light and IndexedDB sync independently.
    """
    name = payload.name.strip()
    is_valid, error_message = validate_persona_name(name)
    if not is_valid:
        raise ValueError(error_message)

    try:
        persona = find_persona(payload.extension_persona_id, name)
        (persona or Persona(name=name)).validate_name(persona.name if persona else name)
    except ValidationError as err:
        raise HttpError(409, "; ".join(err.messages)) from err
    created = persona is None
    if persona is None:
        persona = Persona(name=name)
        if request.user.is_authenticated:
            persona.created_by = request.user

    auth = None
    if "auth_json" in payload.model_fields_set:
        existing = {}
        if payload.auth_json:
            try:
                existing = json.loads((persona.path / "auth.json").read_text())
            except FileNotFoundError:
                pass
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                raise HttpError(409, "Existing persona auth.json is invalid; repair it or explicitly clear it before syncing") from err
            if not isinstance(existing, dict):
                raise HttpError(409, "Existing persona auth.json must contain an object")
        auth = _merge_synced_auth(existing, payload.auth_json)

    persona.config = {
        **(persona.config or {}),
        **browser_settings_to_config(payload.extension_persona_id, payload.settings),
    }
    persona.save()
    persona.ensure_dirs()

    cookies_written = False
    if "cookies_txt" in payload.model_fields_set:
        with atomic_write(persona.path / "cookies.txt", overwrite=True, encoding="utf-8") as stream:
            stream.write(payload.cookies_txt)
        cookies_written = True

    auth_written = auth is not None
    if auth_written:
        with atomic_write(persona.path / "auth.json", overwrite=True, encoding="utf-8") as stream:
            json.dump(auth, stream, indent=2, sort_keys=True)
            stream.write("\n")

    return {
        "success": True,
        "created": created,
        "persona": persona,
        "cookies_file_written": cookies_written,
        "auth_file_written": auth_written,
    }
