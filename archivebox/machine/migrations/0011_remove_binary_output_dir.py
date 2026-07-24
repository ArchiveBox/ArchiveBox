from django.db import migrations


def remove_output_dir_if_exists(apps, schema_editor):
    # On non-sqlite the RemoveField below is state-only, so the real
    # ALTER TABLE DROP COLUMN must run here too (a fresh DB has machine_binary
    # with output_dir from 0001). Portable introspection works on both backends.
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {col.name for col in connection.introspection.get_table_description(cursor, "machine_binary")}

    if "output_dir" not in columns:
        return

    Binary = apps.get_model("machine", "Binary")
    schema_editor.remove_field(Binary, Binary._meta.get_field("output_dir"))


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0010_alter_process_process_type"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(remove_output_dir_if_exists, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="binary",
                    name="output_dir",
                ),
            ],
        ),
    ]
