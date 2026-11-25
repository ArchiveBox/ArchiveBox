from django.db import migrations
from django.utils import timezone


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


def repair_process_iface_links(apps, schema_editor):
    Machine = apps.get_model("machine", "Machine")
    NetworkInterface = apps.get_model("machine", "NetworkInterface")
    Process = apps.get_model("machine", "Process")

    machines = {machine.id: machine for machine in Machine.objects.only("id", "hostname").iterator(chunk_size=100)}
    iface_by_machine = {}

    qs = Process.objects.filter(machine_id__isnull=False, iface_id__isnull=True)
    for process in qs.only("id", "machine_id").iterator(chunk_size=500):
        iface = iface_by_machine.get(process.machine_id)
        if iface is None:
            machine = machines.get(process.machine_id)
            iface = _ensure_placeholder_iface(
                NetworkInterface,
                process.machine_id,
                machine.hostname if machine is not None else "",
            )
            iface_by_machine[process.machine_id] = iface

        process.iface_id = iface.id
        process.modified_at = timezone.now()
        process.save(update_fields=["iface_id", "modified_at"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("machine", "0019_single_active_runner_constraint"),
    ]

    operations = [
        migrations.RunPython(repair_process_iface_links, migrations.RunPython.noop),
    ]
