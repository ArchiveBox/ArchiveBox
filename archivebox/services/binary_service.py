from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone

from abxpkg import Binary as AbxBinary
from abxpkg import BinProvider, PROVIDER_CLASS_BY_NAME
from abxpkg.binary_service import BinaryEvent, BinaryRequestEvent
from abxbus import BaseEvent, EventBus
from abx_dl.services.base import BaseService


_LIB_DIR_MANAGED_PROVIDERS = {
    "bash",
    "cargo",
    "deno",
    "gem",
    "goget",
    "chromewebstore",
    "nix",
    "npm",
    "pip",
    "puppeteer",
    "uv",
}


class ArchiveBoxDBBinaryCacheBackend:
    """ArchiveBox machine.Binary projection backend for abxpkg BinaryCacheService."""

    async def get(self, request: BinaryRequestEvent) -> AbxBinary | None:
        from archivebox.config.common import get_config
        from archivebox.machine.models import Binary, Machine, _canonical_binary_name

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        binary_name = _canonical_binary_name(request.name)
        if not binary_name:
            return None

        existing = await Binary.objects.filter(machine=machine, name=binary_name).afirst()
        persisted_overrides = _persisted_overrides_for_request(request)
        native_overrides = request.overrides or {}
        cache_invalidated = False
        if existing and existing.status == Binary.StatusChoices.INSTALLED:
            changed = False
            requested_binproviders = _binproviders_to_str(request.binproviders)
            if requested_binproviders and existing.binproviders != requested_binproviders:
                existing.binproviders = requested_binproviders
                changed = True
            if persisted_overrides and existing.overrides != persisted_overrides:
                existing.overrides = persisted_overrides
                changed = True
            if changed:
                existing.status = Binary.StatusChoices.QUEUED
                existing.retry_at = None
                cache_invalidated = True
                await existing.asave(update_fields=["binproviders", "overrides", "status", "retry_at", "modified_at"])
        elif existing is None:
            await Binary.objects.acreate(
                machine=machine,
                name=binary_name,
                binproviders=_binproviders_to_str(request.binproviders),
                overrides=persisted_overrides,
                status=Binary.StatusChoices.QUEUED,
            )

        installed = None
        if not cache_invalidated:
            installed = (
                await Binary.objects.filter(machine=machine, name=binary_name, status=Binary.StatusChoices.INSTALLED)
                .exclude(abspath="")
                .exclude(abspath__isnull=True)
                .order_by("-modified_at")
                .afirst()
            )
            if installed is not None and not await sync_to_async(Path(installed.abspath).expanduser().exists, thread_sensitive=True)():
                installed.status = Binary.StatusChoices.QUEUED
                installed.retry_at = None
                await installed.asave(update_fields=["status", "retry_at", "modified_at"])
                installed = None
            if installed is not None and persisted_overrides and installed.overrides != persisted_overrides:
                installed.status = Binary.StatusChoices.QUEUED
                installed.retry_at = None
                await installed.asave(update_fields=["status", "retry_at", "modified_at"])
                installed = None
        if installed is None:
            return None

        installed_path = Path(installed.abspath).expanduser().resolve(strict=False)
        active_lib_dir = (
            Path(str((await sync_to_async(get_config, thread_sensitive=True)()).get("LIB_DIR", ""))).expanduser().resolve(strict=False)
        )
        provider_name = (installed.binprovider or installed.binproviders.split(",", 1)[0]).strip()
        if active_lib_dir and provider_name in _LIB_DIR_MANAGED_PROVIDERS:
            try:
                installed_path.relative_to(active_lib_dir)
            except ValueError:
                installed.status = Binary.StatusChoices.QUEUED
                installed.retry_at = None
                await installed.asave(update_fields=["status", "retry_at", "modified_at"])
                return None

        provider = _provider_for_name(provider_name, installed.name, native_overrides)
        binary_env = BinProvider.build_exec_env(providers=[provider], base_env={}) if provider is not None else {}
        provider_names = _provider_names(installed.binproviders or request.binproviders or "env")
        return AbxBinary.model_validate(
            {
                "name": request.name,
                "description": request.description,
                "binproviders": _providers_for_names(provider_names),
                "overrides": native_overrides,
                "loaded_binprovider": provider,
                "loaded_abspath": installed.abspath,
                "loaded_version": installed.version or None,
                "loaded_sha256": installed.sha256 or None,
                "env": binary_env,
            },
        )

    async def set(self, request: BinaryRequestEvent | None, binary: AbxBinary) -> None:
        from archivebox.config.common import get_config
        from archivebox.machine.models import Binary, Machine, _canonical_binary_name

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        binary_name = _canonical_binary_name(binary.name)
        if not binary_name:
            return
        request_context = request.extra_context if request is not None else {}
        binary_id = str(request_context.get("binary_id") or "")
        if binary_id:
            existing = await Binary.objects.filter(id=binary_id).afirst()
        else:
            existing = None
        if existing is None:
            existing, _created = await Binary.objects.aget_or_create(
                machine=machine,
                name=binary_name,
                defaults={"status": Binary.StatusChoices.QUEUED},
            )

        existing.abspath = str(binary.loaded_abspath or "")
        if binary.loaded_version:
            existing.version = str(binary.loaded_version)
        if binary.loaded_sha256:
            existing.sha256 = str(binary.loaded_sha256)
        existing.binproviders = _binproviders_to_str(
            request.binproviders if request is not None else [provider.name for provider in binary.binproviders],
        )
        if binary.loaded_binprovider is not None:
            existing.binprovider = binary.loaded_binprovider.name
        existing.overrides = _persisted_overrides_for_request(request) if request is not None else binary.overrides
        existing.status = Binary.StatusChoices.INSTALLED
        existing.retry_at = None
        await existing.asave(
            update_fields=["abspath", "version", "sha256", "binproviders", "binprovider", "overrides", "status", "retry_at", "modified_at"],
        )
        lib_bin_dir = await sync_to_async(lambda: get_config().LIB_BIN_DIR, thread_sensitive=True)()
        await sync_to_async(existing.symlink_to_lib_bin_after_commit, thread_sensitive=True)(lib_bin_dir)

    async def invalidate(self, request: BinaryRequestEvent, binary: AbxBinary, reason: str) -> None:
        from archivebox.machine.models import Binary, Machine, _canonical_binary_name

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        binary_name = _canonical_binary_name(request.name)
        if not binary_name:
            return
        installed = (
            await Binary.objects.filter(machine=machine, name=binary_name, status=Binary.StatusChoices.INSTALLED)
            .exclude(abspath="")
            .exclude(abspath__isnull=True)
            .order_by("-modified_at")
            .afirst()
        )
        if installed is None:
            return
        installed.status = Binary.StatusChoices.QUEUED
        installed.retry_at = None
        await installed.asave(update_fields=["status", "retry_at", "modified_at"])


class ArchiveBoxBinaryService(BaseService):
    """Preserve ArchiveBox's legacy Binary Process rows around abxpkg requests."""

    LISTENS_TO = [BinaryRequestEvent, BinaryEvent]
    EMITS: list[type[BaseEvent]] = []

    def __init__(self, bus: EventBus):
        super().__init__(bus)
        self.process_ids_by_request_id: dict[str, str] = {}
        self._missing_finalize_tasks: set[asyncio.Task] = set()
        self.bus.on(BinaryRequestEvent, self.on_BinaryRequestEvent__project_process)
        self.bus.on(BinaryRequestEvent, self.on_BinaryRequestEvent__schedule_missing_finalize)
        self.bus.on(BinaryEvent, self.on_BinaryEvent__finalize_process)

    async def on_BinaryRequestEvent__project_process(self, request: BinaryRequestEvent) -> None:
        from archivebox.machine.models import Machine, Process, _canonical_binary_name

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        binary_name = _canonical_binary_name(request.name)
        if not binary_name:
            return
        binary = await self._get_or_create_binary(machine, binary_name, request)
        started_at = timezone.now()
        output_dir = self._process_output_dir(binary, request)
        await sync_to_async(output_dir.mkdir, thread_sensitive=True)(parents=True, exist_ok=True)
        process = await Process.objects.acreate(
            machine=machine,
            iface=None,
            process_type=Process.TypeChoices.BINARY,
            worker_type="",
            pwd=str(output_dir),
            cmd=self._process_cmd(request),
            env={},
            timeout=int(request.event_timeout or request.install_timeout or 600),
            pid=None,
            url=None,
            started_at=started_at,
            ended_at=None,
            stdout="",
            stderr="",
            exit_code=None,
            status=Process.StatusChoices.RUNNING,
            retry_at=None,
            binary=binary,
        )
        self.process_ids_by_request_id[request.event_id] = str(process.id)

    async def on_BinaryEvent__finalize_process(self, event: BinaryEvent) -> None:
        from archivebox.machine.models import Binary, Process, _canonical_binary_name

        request = await self.bus.find(
            BinaryRequestEvent,
            past=True,
            future=False,
            where=lambda candidate: self.bus.event_is_child_of(event, candidate),
        )
        request = request if isinstance(request, BinaryRequestEvent) else None
        process_id = self.process_ids_by_request_id.pop(request.event_id, "") if request is not None else ""
        if not process_id:
            return
        process = await Process.objects.filter(id=process_id).select_related("binary").afirst()
        if process is None:
            return
        binary_name = _canonical_binary_name(event.name)
        binary = process.binary
        if binary is not None and binary_name:
            binary.abspath = event.abspath
            if event.version:
                binary.version = str(event.version)
            if event.sha256:
                binary.sha256 = str(event.sha256)
            binary.binproviders = event.binproviders or binary.binproviders
            binary.binprovider = event.binprovider or binary.binprovider
            binary.status = Binary.StatusChoices.INSTALLED
            binary.retry_at = None
            await binary.asave(
                update_fields=["abspath", "version", "sha256", "binproviders", "binprovider", "status", "retry_at", "modified_at"],
            )
        process.ended_at = timezone.now()
        process.stdout = json.dumps(self._binary_event_json(event, binary)) + "\n"
        process.stderr = ""
        process.exit_code = 0
        process.status = Process.StatusChoices.EXITED
        await process.asave(update_fields=["ended_at", "stdout", "stderr", "exit_code", "status", "modified_at"])
        if binary is not None:
            await sync_to_async(self._write_binary_index, thread_sensitive=True)(binary, process, Path(process.pwd))

    async def _get_or_create_binary(self, machine, binary_name: str, request: BinaryRequestEvent):
        from archivebox.machine.models import Binary

        binary_id = str(request.extra_context.get("binary_id") or "")
        if binary_id:
            binary = await Binary.objects.filter(id=binary_id).afirst()
            if binary is not None:
                return binary
        binary = await Binary.objects.filter(machine=machine, name=binary_name).order_by("-modified_at").afirst()
        if binary is not None:
            return binary
        return await Binary.objects.acreate(
            machine=machine,
            name=binary_name,
            binproviders=_binproviders_to_str(request.binproviders),
            overrides=_persisted_overrides_for_request(request),
            status=Binary.StatusChoices.QUEUED,
        )

    def _process_cmd(self, request: BinaryRequestEvent) -> list[str]:
        cmd = [
            "abxpkg",
            "install",
            f"--name={request.name}",
            f"--binproviders={_binproviders_to_str(request.binproviders)}",
        ]
        if request.overrides:
            cmd.append(f"--overrides={json.dumps(request.overrides, sort_keys=True)}")
        return cmd

    def _binary_event_json(self, event: BinaryEvent, binary) -> dict[str, Any]:
        if binary is not None:
            data = binary.to_json()
        else:
            data = {"type": "Binary", "name": event.name}
        data.update(
            {
                "type": "Binary",
                "name": event.name,
                "binproviders": event.binproviders,
                "binprovider": event.binprovider,
                "abspath": event.abspath,
                "version": str(event.version or ""),
                "sha256": event.sha256 or "",
                "status": "installed",
            },
        )
        return data

    async def _finalize_missing_process(self, request: BinaryRequestEvent) -> None:
        from archivebox.machine.models import Process

        process_id = self.process_ids_by_request_id.pop(request.event_id, "")
        if not process_id:
            return
        process = await Process.objects.filter(id=process_id).afirst()
        if process is None or process.status == Process.StatusChoices.EXITED:
            return
        process.ended_at = timezone.now()
        process.stderr = f"Binary request did not resolve: {request.name}"
        process.exit_code = 1
        process.status = Process.StatusChoices.EXITED
        await process.asave(update_fields=["ended_at", "stderr", "exit_code", "status", "modified_at"])

    async def _finalize_request_when_done(self, request: BinaryRequestEvent) -> None:
        try:
            await request.wait(timeout=request.event_timeout)
        except TimeoutError:
            await self._finalize_missing_process(request)
            return
        binary_event = await self.bus.find(
            BinaryEvent,
            child_of=request,
            past=True,
            future=False,
            name=request.name,
            where=lambda candidate: bool(candidate.abspath),
        )
        if not isinstance(binary_event, BinaryEvent):
            await self._finalize_missing_process(request)

    def _schedule_missing_finalize(self, request: BinaryRequestEvent) -> None:
        task = asyncio.create_task(self._finalize_request_when_done(request))
        self._missing_finalize_tasks.add(task)
        task.add_done_callback(lambda done: self._missing_finalize_tasks.discard(done) or (None if done.cancelled() else done.exception()))

    async def flush_missing_finalizers(self) -> None:
        if self._missing_finalize_tasks:
            await asyncio.gather(*tuple(self._missing_finalize_tasks), return_exceptions=False)

    async def on_BinaryRequestEvent__schedule_missing_finalize(self, request: BinaryRequestEvent) -> None:
        self._schedule_missing_finalize(request)

    def _process_output_dir(self, binary, request: BinaryRequestEvent) -> Path:
        raw_output_dir = str(request.extra_context.get("output_dir") or "").strip()
        if raw_output_dir:
            output_dir = Path(raw_output_dir).expanduser()
            if output_dir.name == str(binary.id):
                return output_dir.parent
            return output_dir
        return binary.output_dir.parent

    def _write_binary_index(self, binary, process, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        index_path = output_dir / "index.jsonl"
        with index_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(binary.to_json()) + "\n")
            f.write(json.dumps(process.to_json()) + "\n")


def _provider_names(binproviders: str | list[str] | None) -> list[str]:
    if isinstance(binproviders, str):
        raw_names = [part.strip() for part in binproviders.split(",")]
    elif binproviders:
        raw_names = [str(part).strip() for part in binproviders]
    else:
        raw_names = ["env"]
    names: list[str] = []
    for name in raw_names:
        if name and name not in names:
            names.append(name)
    return names or ["env"]


def _binproviders_to_str(binproviders: str | list[str] | None) -> str:
    return ",".join(_provider_names(binproviders))


def _providers_for_names(names: list[str]) -> list[BinProvider]:
    providers: list[BinProvider] = []
    for name in names:
        provider_class = PROVIDER_CLASS_BY_NAME.get(name)
        if provider_class is not None:
            providers.append(provider_class())
    return providers


def _provider_for_name(provider_name: str, binary_name: str, overrides: dict[str, Any] | None) -> BinProvider | None:
    provider_class = PROVIDER_CLASS_BY_NAME.get(provider_name)
    if provider_class is None:
        return None
    provider = provider_class()
    provider_overrides = overrides.get(provider_name) if isinstance(overrides, dict) else None
    if isinstance(provider_overrides, dict):
        provider = provider.get_provider_with_overrides(
            overrides={binary_name: provider_overrides},
        )
    return provider


def _persisted_overrides_for_request(request: BinaryRequestEvent | None) -> dict[str, Any]:
    if request is None:
        return {}
    raw_overrides = request.extra_context.get("raw_overrides")
    if isinstance(raw_overrides, Mapping):
        return dict(raw_overrides)
    return dict(request.overrides or {})
