from __future__ import annotations

from asgiref.sync import sync_to_async

from abx_dl.events import BinaryRequestEvent, BinaryEvent
from abx_dl.services.base import BaseService


class BinaryService(BaseService):
    LISTENS_TO = [BinaryRequestEvent, BinaryEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(BinaryRequestEvent, self.on_BinaryRequestEvent)
        self.bus.on(BinaryEvent, self.on_BinaryEvent)

    async def on_BinaryRequestEvent(self, event: BinaryRequestEvent) -> None:
        from archivebox.machine.models import Binary, Machine

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        existing = await Binary.objects.filter(machine=machine, name=event.name).afirst()
        if existing and existing.status == Binary.StatusChoices.INSTALLED:
            changed = False
            if event.binproviders and existing.binproviders != event.binproviders:
                existing.binproviders = event.binproviders
                changed = True
            if event.overrides and existing.overrides != event.overrides:
                existing.overrides = event.overrides
                changed = True
            if changed:
                await existing.asave(update_fields=["binproviders", "overrides", "modified_at"])
        elif existing is None:
            await Binary.objects.acreate(
                machine=machine,
                name=event.name,
                binproviders=event.binproviders,
                overrides=event.overrides or {},
                status=Binary.StatusChoices.QUEUED,
            )

        installed = (
            await Binary.objects.filter(machine=machine, name=event.name, status=Binary.StatusChoices.INSTALLED)
            .exclude(abspath="")
            .exclude(abspath__isnull=True)
            .order_by("-modified_at")
            .afirst()
        )
        cached = None
        if installed is not None:
            cached = {
                "abspath": installed.abspath,
                "version": installed.version or "",
                "sha256": installed.sha256 or "",
                "binproviders": installed.binproviders or "",
                "binprovider": installed.binprovider or "",
                "machine_id": str(installed.machine_id),
                "overrides": installed.overrides or {},
            }
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
                    machine_id=cached["machine_id"],
                ),
            )

    async def on_BinaryEvent(self, event: BinaryEvent) -> None:
        from archivebox.machine.models import Binary, Machine

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        binary, _ = await Binary.objects.aget_or_create(
            machine=machine,
            name=event.name,
            defaults={
                "status": Binary.StatusChoices.QUEUED,
            },
        )
        binary.abspath = event.abspath
        if event.version:
            binary.version = event.version
        if event.sha256:
            binary.sha256 = event.sha256
        if event.binproviders:
            binary.binproviders = event.binproviders
        if event.binprovider:
            binary.binprovider = event.binprovider
        if event.overrides and binary.overrides != event.overrides:
            binary.overrides = event.overrides
        binary.status = Binary.StatusChoices.INSTALLED
        binary.retry_at = None
        await binary.asave(
            update_fields=["abspath", "version", "sha256", "binproviders", "binprovider", "overrides", "status", "retry_at", "modified_at"],
        )
