from __future__ import annotations

import asyncio

from abx_dl.events import BinaryRequestEvent, BinaryEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class BinaryService(BaseService):
    LISTENS_TO = [BinaryRequestEvent, BinaryEvent]
    EMITS = []

    async def on_BinaryRequestEvent__Outer(self, event: BinaryRequestEvent) -> None:
        await run_db_op(self._project_binary, event)
        cached = await run_db_op(self._load_cached_binary, event)
        if cached is not None:
            await self.bus.emit(
                BinaryEvent(
                    name=event.name,
                    plugin_name=event.plugin_name,
                    hook_name=event.hook_name,
                    abspath=cached["abspath"],
                    version=cached["version"],
                    sha256=cached["sha256"],
                    binproviders=event.binproviders or cached["binproviders"],
                    binprovider=cached["binprovider"],
                    overrides=event.overrides or cached["overrides"],
                    binary_id=event.binary_id,
                    machine_id=event.machine_id or cached["machine_id"],
                ),
            )

    async def on_BinaryEvent__Outer(self, event: BinaryEvent) -> None:
        resolved = await asyncio.to_thread(self._resolve_installed_binary_metadata, event)
        await run_db_op(self._project_installed_binary, event, resolved)

    def _project_binary(self, event: BinaryRequestEvent) -> None:
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
                "binproviders": event.binproviders,
                "overrides": event.overrides or {},
            },
        )

    def _load_cached_binary(self, event: BinaryRequestEvent) -> dict[str, str] | None:
        from archivebox.machine.models import Binary, Machine

        machine = Machine.current()
        installed = (
            Binary.objects.filter(machine=machine, name=event.name, status=Binary.StatusChoices.INSTALLED)
            .exclude(abspath="")
            .exclude(abspath__isnull=True)
            .order_by("-modified_at")
            .first()
        )
        if installed is None:
            return None
        return {
            "abspath": installed.abspath,
            "version": installed.version or "",
            "sha256": installed.sha256 or "",
            "binproviders": installed.binproviders or "",
            "binprovider": installed.binprovider or "",
            "machine_id": str(installed.machine_id),
            "overrides": installed.overrides or {},
        }

    def _resolve_installed_binary_metadata(self, event: BinaryEvent) -> dict[str, str]:
        resolved = {
            "abspath": event.abspath or "",
            "version": event.version or "",
            "sha256": event.sha256 or "",
            "binproviders": event.binproviders or "",
            "binprovider": event.binprovider or "",
        }
        if resolved["abspath"] and resolved["version"] and resolved["binprovider"]:
            return resolved

        if resolved["abspath"] and not resolved["version"]:
            try:
                from abx_pkg.semver import bin_version

                detected_version = bin_version(resolved["abspath"])
            except Exception:
                detected_version = None
            if detected_version:
                resolved["version"] = str(detected_version)
                if resolved["version"] and resolved["binprovider"]:
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
            resolved["abspath"] = str(binary.abspath or resolved["abspath"] or "")
            resolved["version"] = str(binary.version or resolved["version"] or "")
            resolved["sha256"] = str(binary.sha256 or resolved["sha256"] or "")
            if binary.loaded_binprovider is not None and binary.loaded_binprovider.name:
                resolved["binprovider"] = str(binary.loaded_binprovider.name)
        except Exception:
            pass

        return resolved

    def _project_installed_binary(self, event: BinaryEvent, resolved: dict[str, str]) -> None:
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
