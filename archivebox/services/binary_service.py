from __future__ import annotations

import asyncio

from abx_dl.events import BinaryEvent, BinaryInstalledEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class BinaryService(BaseService):
    LISTENS_TO = [BinaryEvent, BinaryInstalledEvent]
    EMITS = []

    async def on_BinaryEvent__Outer(self, event: BinaryEvent) -> None:
        await run_db_op(self._project_binary, event)

    async def on_BinaryInstalledEvent__Outer(self, event: BinaryInstalledEvent) -> None:
        resolved = await asyncio.to_thread(self._resolve_installed_binary_metadata, event)
        await run_db_op(self._project_installed_binary, event, resolved)

    def _project_binary(self, event: BinaryEvent) -> None:
        from archivebox.machine.models import Binary, Machine

        machine = Machine.current()
        existing = Binary.objects.filter(machine=machine, name=event.name).first()
        if existing and existing.status == Binary.StatusChoices.INSTALLED:
            changed = False
            if event.binproviders and existing.binproviders != event.binproviders:
                existing.binproviders = event.binproviders
                changed = True
            if event.overrides and existing.overrides != event.overrides:
                existing.overrides = event.overrides
                changed = True
            if changed:
                existing.save(update_fields=["binproviders", "overrides", "modified_at"])
            return

        Binary.from_json(
            {
                "name": event.name,
                "abspath": event.abspath,
                "version": event.version,
                "sha256": event.sha256,
                "binproviders": event.binproviders,
                "binprovider": event.binprovider,
                "overrides": event.overrides or {},
            },
        )

    def _resolve_installed_binary_metadata(self, event: BinaryInstalledEvent) -> dict[str, str]:
        resolved = {
            "abspath": event.abspath or "",
            "version": event.version or "",
            "sha256": event.sha256 or "",
            "binproviders": event.binproviders or "",
            "binprovider": event.binprovider or "",
        }
        if resolved["abspath"] and resolved["version"] and resolved["binprovider"]:
            return resolved

        try:
            from abx_dl.dependencies import load_binary

            allowed_providers = resolved["binproviders"] or resolved["binprovider"] or "env,pip,npm,brew,apt"
            spec = {
                "name": event.name,
                "binproviders": allowed_providers,
                "overrides": event.overrides or {},
            }
            binary = load_binary(spec)
            resolved["abspath"] = str(getattr(binary, "abspath", None) or resolved["abspath"] or "")
            resolved["version"] = str(getattr(binary, "version", None) or resolved["version"] or "")
            resolved["sha256"] = str(getattr(binary, "sha256", None) or resolved["sha256"] or "")
            provider_name = getattr(getattr(binary, "loaded_binprovider", None), "name", None)
            if provider_name:
                resolved["binprovider"] = str(provider_name)
        except Exception:
            pass

        return resolved

    def _project_installed_binary(self, event: BinaryInstalledEvent, resolved: dict[str, str]) -> None:
        from archivebox.machine.models import Binary, Machine

        machine = Machine.current()
        binary, _ = Binary.objects.get_or_create(
            machine=machine,
            name=event.name,
            defaults={
                "status": Binary.StatusChoices.QUEUED,
            },
        )
        binary.abspath = resolved["abspath"] or binary.abspath
        binary.version = resolved["version"] or binary.version
        binary.sha256 = resolved["sha256"] or binary.sha256
        if resolved["binproviders"]:
            binary.binproviders = resolved["binproviders"]
        binary.binprovider = resolved["binprovider"] or binary.binprovider
        if event.overrides and binary.overrides != event.overrides:
            binary.overrides = event.overrides
        binary.status = Binary.StatusChoices.INSTALLED
        binary.retry_at = None
        binary.save(
            update_fields=["abspath", "version", "sha256", "binproviders", "binprovider", "overrides", "status", "retry_at", "modified_at"],
        )
