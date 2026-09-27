"""Repair process links after both core's legacy copy and machine migrations."""

from importlib import import_module

from django.db import migrations


repair_process_binary_iface_links = import_module(
    "archivebox.machine.migrations.0020_repair_process_binary_iface_links",
).repair_process_binary_iface_links


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0056_progress_covering_indexes"),
        ("machine", "0022_networkinterface_identity_without_mac"),
    ]

    operations = [
        # The original repair can run before core.0027 creates legacy Process
        # rows. Repair again after the copy, including already upgraded DBs.
        migrations.RunPython(repair_process_binary_iface_links, migrations.RunPython.noop),
    ]
