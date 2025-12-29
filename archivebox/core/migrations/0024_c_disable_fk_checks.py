# Disable foreign key checks before 0025 to prevent CHECK constraint validation errors

from django.db import migrations


def disable_fk_checks(apps, schema_editor):
    """Temporarily disable foreign key checks."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=OFF")
        print("  Disabled foreign key checks")


def enable_fk_checks(apps, schema_editor):
    """Re-enable foreign key checks."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=ON")
        print("  Enabled foreign key checks")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_b_clear_config_fields'),
    ]

    operations = [
        migrations.RunPython(disable_fk_checks, reverse_code=enable_fk_checks),
    ]
