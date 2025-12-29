# Generated migration - removes Dependency model entirely
# NOTE: This is a cleanup migration for users upgrading from old dev versions
# that had the Dependency model. Fresh installs never create this table.

from django.db import migrations


def drop_dependency_table(apps, schema_editor):
    """
    Drop old Dependency table if it exists (from dev versions that had it).
    Safe to run multiple times, safe if table doesn't exist.

    Does NOT touch machine_binary - that's our current Binary model table!
    """
    schema_editor.execute('DROP TABLE IF EXISTS machine_dependency')
    # Also drop old InstalledBinary table if it somehow still exists
    schema_editor.execute('DROP TABLE IF EXISTS machine_installedbinary')


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0003_alter_dependency_id_alter_installedbinary_dependency_and_more'),
    ]

    operations = [
        migrations.RunPython(drop_dependency_table, migrations.RunPython.noop),
    ]
