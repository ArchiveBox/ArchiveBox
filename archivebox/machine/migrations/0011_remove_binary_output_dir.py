from django.db import migrations


def remove_output_dir_if_exists(apps, schema_editor):
    cursor = schema_editor.connection.cursor()
    cursor.execute("PRAGMA table_info(machine_binary)")
    columns = {row[1] for row in cursor.fetchall()}

    if 'output_dir' not in columns:
        return

    Binary = apps.get_model('machine', 'Binary')
    schema_editor.remove_field(Binary, Binary._meta.get_field('output_dir'))


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0010_alter_process_process_type'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(remove_output_dir_if_exists, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='binary',
                    name='output_dir',
                ),
            ],
        ),
    ]
