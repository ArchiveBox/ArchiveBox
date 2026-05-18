__package__ = "archivebox.api"

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.http import HttpRequest
from ninja import Router, Schema
from pydantic import Field

from archivebox.personas.importers import validate_persona_name
from archivebox.personas.models import Persona


router = Router(tags=["Personas"])


class PersonaBrowserSettingsSchema(Schema):
    user_agent: str = ""
    viewport_size: str = ""
    viewport_device_scale_factor: float | None = None
    language: str = ""
    timezone: str = ""
    geolocation: dict[str, Any] | None = None


class PersonaSyncSchema(Schema):
    extension_persona_id: str
    name: str
    settings: PersonaBrowserSettingsSchema = Field(default_factory=PersonaBrowserSettingsSchema)
    cookies_txt: str = ""
    auth_json: dict[str, Any] = Field(default_factory=dict)


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

    if settings.user_agent:
        config.update(
            {
                "USER_AGENT": settings.user_agent,
                "CHROME_USER_AGENT": settings.user_agent,
                "WGET_USER_AGENT": settings.user_agent,
                "CURL_USER_AGENT": settings.user_agent,
            },
        )
    if settings.viewport_size:
        config.update(
            {
                "RESOLUTION": settings.viewport_size,
                "CHROME_RESOLUTION": settings.viewport_size,
            },
        )
    if settings.viewport_device_scale_factor is not None:
        config["BROWSER_DEVICE_SCALE_FACTOR"] = settings.viewport_device_scale_factor
    if settings.language:
        config["BROWSER_LANGUAGE"] = settings.language
    if settings.timezone:
        config["BROWSER_TIMEZONE"] = settings.timezone
    if settings.geolocation:
        config["BROWSER_GEOLOCATION"] = settings.geolocation

    return config


def find_persona(extension_persona_id: str, name: str) -> Persona | None:
    return (
        Persona.objects.filter(
            Q(config__BROWSER_EXTENSION_PERSONA_ID=extension_persona_id) | Q(name=name),
        )
        .order_by("created_at")
        .first()
    )


@router.get("/personas", response=list[PersonaSchema], url_name="get_personas")
def get_personas(request: HttpRequest):
    """List personas available on this ArchiveBox server."""
    return Persona.objects.all().order_by("name")


@router.post("/sync", response=PersonaSyncResponseSchema, url_name="sync_persona")
def sync_persona(request: HttpRequest, payload: PersonaSyncSchema):
    """
    Create or update a Persona from a browser extension profile export.

    The extension sends browser settings plus portable auth artifacts. The server
    keeps browser override settings in Persona.config and writes cookies.txt /
    auth.json into the persona directory for extractors to consume.
    """
    name = payload.name.strip()
    is_valid, error_message = validate_persona_name(name)
    if not is_valid:
        raise ValueError(error_message)

    persona = find_persona(payload.extension_persona_id, name)
    created = persona is None
    if persona is None:
        persona = Persona(name=name)
        if getattr(request.user, "is_authenticated", False):
            persona.created_by = request.user

    persona.config = {
        **(persona.config or {}),
        **browser_settings_to_config(payload.extension_persona_id, payload.settings),
    }
    persona.save()
    persona.ensure_dirs()

    cookies_written = False
    if payload.cookies_txt.strip():
        (persona.path / "cookies.txt").write_text(payload.cookies_txt)
        cookies_written = True

    auth_written = False
    if payload.auth_json:
        (persona.path / "auth.json").write_text(json.dumps(payload.auth_json, indent=2, sort_keys=True) + "\n")
        auth_written = True

    return {
        "success": True,
        "created": created,
        "persona": persona,
        "cookies_file_written": cookies_written,
        "auth_file_written": auth_written,
    }
