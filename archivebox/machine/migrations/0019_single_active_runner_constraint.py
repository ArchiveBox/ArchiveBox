from django.db import migrations, models
from django.db.models import Count, Q
from django.utils import timezone


def dedupe_network_interfaces(apps, schema_editor):
    NetworkInterface = apps.get_model("machine", "NetworkInterface")
    duplicate_groups = (
        NetworkInterface.objects.values(
            "machine_id",
            "ip_public",
            "ip_local",
            "mac_address",
            "dns_server",
        )
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups.iterator(chunk_size=100):
        lookup = {
            "machine_id": group["machine_id"],
            "ip_public": group["ip_public"],
            "ip_local": group["ip_local"],
            "mac_address": group["mac_address"],
            "dns_server": group["dns_server"],
        }
        keep = NetworkInterface.objects.filter(**lookup).order_by("-modified_at", "-created_at").first()
        if keep is not None:
            NetworkInterface.objects.filter(**lookup).exclude(id=keep.id).delete()


def dedupe_active_runners(apps, schema_editor):
    Process = apps.get_model("machine", "Process")
    duplicate_groups = (
        Process.objects.filter(status="running", process_type="orchestrator", worker_type="worker_runner")
        .values("machine_id", "pwd")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups.iterator(chunk_size=100):
        lookup = {
            "machine_id": group["machine_id"],
            "pwd": group["pwd"],
            "status": "running",
            "process_type": "orchestrator",
            "worker_type": "worker_runner",
        }
        keep = Process.objects.filter(**lookup).order_by("-started_at", "-created_at").first()
        if keep is not None:
            Process.objects.filter(**lookup).exclude(id=keep.id).update(
                status="exited",
                ended_at=timezone.now(),
                exit_code=0,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0018_alter_process_process_type"),
    ]

    operations = [
        migrations.RunPython(dedupe_network_interfaces, migrations.RunPython.noop),
        migrations.RunPython(dedupe_active_runners, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="networkinterface",
            constraint=models.UniqueConstraint(
                fields=("machine", "ip_public", "ip_local", "mac_address", "dns_server"),
                name="unique_network_interface_identity",
            ),
        ),
        migrations.AlterField(
            model_name="process",
            name="worker_type",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Worker role name for worker/orchestrator subprocesses",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="process",
            constraint=models.UniqueConstraint(
                condition=Q(process_type="orchestrator", status="running", worker_type="worker_runner"),
                fields=("machine", "pwd"),
                name="single_active_runner_per_data_dir",
            ),
        ),
    ]
