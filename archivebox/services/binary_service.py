from __future__ import annotations

from asgiref.sync import sync_to_async
from abx_dl.events import BinaryEvent, BinaryInstalledEvent
from abx_dl.services.base import BaseService


class BinaryService(BaseService):
    LISTENS_TO = [BinaryEvent, BinaryInstalledEvent]
    EMITS = []

    async def on_BinaryEvent(self, event: BinaryEvent) -> None:
        await sync_to_async(self._project_binary, thread_sensitive=True)(event)

    async def on_BinaryInstalledEvent(self, event: BinaryInstalledEvent) -> None:
        await sync_to_async(self._project_installed_binary, thread_sensitive=True)(event)

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

    def _project_installed_binary(self, event: BinaryInstalledEvent) -> None:
        from archivebox.machine.models import Binary, Machine

        machine = Machine.current()
        binary, _ = Binary.objects.get_or_create(
            machine=machine,
            name=event.name,
            defaults={
                "status": Binary.StatusChoices.QUEUED,
            },
        )
        binary.abspath = event.abspath or binary.abspath
        binary.version = event.version or binary.version
        binary.sha256 = event.sha256 or binary.sha256
        binary.binprovider = event.binprovider or binary.binprovider
        binary.status = Binary.StatusChoices.INSTALLED
        binary.retry_at = None
        binary.save(update_fields=["abspath", "version", "sha256", "binprovider", "status", "retry_at", "modified_at"])
