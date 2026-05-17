from django.db import migrations


def add_machine_config_if_missing(apps, schema_editor):
    cursor = schema_editor.connection.cursor()
    cursor.execute("PRAGMA table_info(machine_machine)")
    columns = {row[1] for row in cursor.fetchall()}
    if "config" not in columns:
        cursor.execute("ALTER TABLE machine_machine ADD COLUMN config TEXT")


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0011_remove_binary_output_dir"),
    ]

    operations = [
        migrations.RunPython(
            add_machine_config_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
