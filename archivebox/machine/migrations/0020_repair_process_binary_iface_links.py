import json

from django.db import migrations
from django.utils import timezone


def _cmd_array(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        return parsed if isinstance(parsed, list) else []
    return []


def _ensure_placeholder_iface(NetworkInterface, machine_id, hostname):
    iface = NetworkInterface.objects.filter(machine_id=machine_id).order_by("-modified_at", "-created_at").first()
    if iface is not None:
        return iface

    now = timezone.now()
    return NetworkInterface.objects.create(
        machine_id=machine_id,
        created_at=now,
        modified_at=now,
        mac_address="00:00:00:00:00:00",
        ip_public="0.0.0.0",
        ip_local="0.0.0.0",
        dns_server="0.0.0.0",
        hostname=(hostname or "unknown")[:63],
        iface="unknown",
        isp="",
        city="",
        region="",
        country="",
    )


def _find_existing_binary(Binary, machine_id, reference):
    # Old command lines preserve what was recorded, not proof of an installation.
    return (
        Binary.objects.filter(machine_id=machine_id, abspath=reference, status="installed")
        .exclude(version="", sha256="")
        .order_by("-modified_at", "-created_at")
        .first()
    )


def repair_process_binary_iface_links(apps, schema_editor):
    Binary = apps.get_model("machine", "Binary")
    Machine = apps.get_model("machine", "Machine")
    NetworkInterface = apps.get_model("machine", "NetworkInterface")
    Process = apps.get_model("machine", "Process")

    machines = {machine.id: machine for machine in Machine.objects.only("id", "hostname").iterator(chunk_size=100)}
    iface_by_machine = {}
    binary_by_key = {}

    qs = Process.objects.filter(machine_id__isnull=False).filter(binary_id__isnull=True) | Process.objects.filter(
        machine_id__isnull=False,
        iface_id__isnull=True,
    )
    for process in qs.distinct().only("id", "machine_id", "binary_id", "iface_id", "cmd").iterator(chunk_size=500):
        update_fields = []
        machine = machines.get(process.machine_id)

        if process.iface_id is None:
            iface = iface_by_machine.get(process.machine_id)
            if iface is None:
                iface = _ensure_placeholder_iface(
                    NetworkInterface,
                    process.machine_id,
                    machine.hostname if machine is not None else "",
                )
                iface_by_machine[process.machine_id] = iface
            process.iface_id = iface.id
            update_fields.append("iface_id")

        if process.binary_id is None:
            cmd = _cmd_array(process.cmd)
            reference = str(cmd[0]).strip() if cmd else ""
            if reference:
                key = (process.machine_id, reference)
                if key not in binary_by_key:
                    binary_by_key[key] = _find_existing_binary(Binary, process.machine_id, reference)
                binary = binary_by_key[key]
                if binary is not None:
                    process.binary_id = binary.id
                    update_fields.append("binary_id")

        if update_fields:
            process.modified_at = timezone.now()
            process.save(update_fields=[*update_fields, "modified_at"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("machine", "0019_single_active_runner_constraint"),
    ]

    operations = [
        migrations.RunPython(repair_process_binary_iface_links, migrations.RunPython.noop),
    ]
