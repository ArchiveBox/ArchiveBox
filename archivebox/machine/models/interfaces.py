from __future__ import annotations

import uuid
from datetime import timedelta

from django.db import IntegrityError, models
from django.utils import timezone

from archivebox.base_models.models import ModelWithHealthStats
from archivebox.machine import models as state
from archivebox.uuid_compat import CompactUUIDField, uuid7

from ..detect import get_host_network
from .constants import NETWORK_INTERFACE_RECHECK_INTERVAL
from .machines import Machine


class NetworkInterfaceManager(models.Manager):
    def current(self) -> NetworkInterface:
        return NetworkInterface.current()


class NetworkInterface(ModelWithHealthStats):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False)
    mac_address = models.CharField(max_length=17, default=None, null=False, editable=False)
    ip_public = models.GenericIPAddressField(default=None, null=False, editable=False)
    ip_local = models.GenericIPAddressField(default=None, null=False, editable=False)
    dns_server = models.GenericIPAddressField(default=None, null=False, editable=False)
    hostname = models.CharField(max_length=63, default="", null=False)
    iface = models.CharField(max_length=15, default="", null=False)
    isp = models.CharField(max_length=63, default="", null=False)
    city = models.CharField(max_length=63, default="", null=False)
    region = models.CharField(max_length=63, default="", null=False)
    country = models.CharField(max_length=63, default="", null=False)
    objects = NetworkInterfaceManager()  # pyright: ignore[reportIncompatibleVariableOverride]
    machine_id: uuid.UUID

    class Meta(ModelWithHealthStats.Meta):
        app_label = "machine"
        unique_together = (("machine", "ip_public", "ip_local", "dns_server"),)
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "ip_public", "ip_local", "dns_server"],
                name="unique_network_interface_identity",
            ),
        ]

    @classmethod
    def current(cls, refresh: bool = False) -> NetworkInterface:
        from archivebox.machine.models import Machine

        machine = Machine.current(refresh=refresh)
        if state._CURRENT_INTERFACE and state._CURRENT_INTERFACE.machine_id == machine.id:
            if not refresh:
                # Callers that pass refresh=False are asking for attribution to
                # the currently known interface, not for public-IP/ISP probing.
                # Maintenance paths create many short-lived services per run;
                # expiring this in-memory object by age forced every crawl to
                # hit external network APIs even though Process rows only need
                # a stable existing FK. Active downloading paths opt into live
                # detection with refresh=True.
                return state._CURRENT_INTERFACE
            if timezone.now() < state._CURRENT_INTERFACE.modified_at + timedelta(seconds=NETWORK_INTERFACE_RECHECK_INTERVAL):
                return state._CURRENT_INTERFACE
        state._CURRENT_INTERFACE = None

        if not refresh:
            state._CURRENT_INTERFACE = cls.objects.filter(machine=machine).order_by("-modified_at", "-created_at").first()
            if state._CURRENT_INTERFACE is not None:
                return state._CURRENT_INTERFACE

        net_info = get_host_network()
        lookup = dict(
            machine=machine,
            ip_public=net_info.pop("ip_public"),
            ip_local=net_info.pop("ip_local"),
            dns_server=net_info.pop("dns_server"),
        )
        state._CURRENT_INTERFACE = cls.objects.filter(**lookup).order_by("-modified_at", "-created_at").first()
        if state._CURRENT_INTERFACE is None:
            try:
                state._CURRENT_INTERFACE = cls.objects.create(**lookup, **net_info)
            except IntegrityError:
                state._CURRENT_INTERFACE = cls.objects.filter(**lookup).order_by("-modified_at", "-created_at").first()
                if state._CURRENT_INTERFACE is None:
                    raise
        else:
            # Avoid update_or_create() here: command startup calls this before
            # leadership handoff, and SQLite should not take a write lock unless
            # the cached interface metadata is actually stale.
            if refresh or timezone.now() >= state._CURRENT_INTERFACE.modified_at + timedelta(seconds=NETWORK_INTERFACE_RECHECK_INTERVAL):
                updates = ["modified_at"]
                for key, value in net_info.items():
                    if state._CURRENT_INTERFACE.__dict__.get(key) != value:
                        setattr(state._CURRENT_INTERFACE, key, value)
                        updates.append(key)
                if len(updates) > 1:
                    state._CURRENT_INTERFACE.save(update_fields=updates)
        return state._CURRENT_INTERFACE
