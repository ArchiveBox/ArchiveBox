# Data migration to clear config fields that may contain invalid JSON
# This runs before 0025 to prevent CHECK constraint failures

from django.db import migrations


def clear_config_fields(apps, schema_editor):
    """Clear all config fields in related tables to avoid JSON validation errors."""
    db_alias = schema_editor.connection.alias

    # Disable foreign key checks temporarily to allow updates
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=OFF")

    tables_to_clear = [
        ('crawls_seed', 'config'),
        ('crawls_crawl', 'config'),
        ('crawls_crawlschedule', 'config') if 'crawlschedule' in dir() else None,
        ('machine_machine', 'stats'),
        ('machine_machine', 'config'),
    ]

    for table_info in tables_to_clear:
        if table_info is None:
            continue
        table_name, field_name = table_info

        try:
            with schema_editor.connection.cursor() as cursor:
                # Check if table exists first
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if not cursor.fetchone():
                    print(f"  Skipping {table_name}.{field_name}: table does not exist")
                    continue

                # Set all to empty JSON object
                cursor.execute(f"UPDATE {table_name} SET {field_name} = '{{}}' WHERE {field_name} IS NOT NULL")
                print(f"  Cleared {field_name} in {table_name}: {cursor.rowcount} rows")
        except Exception as e:
            print(f"  Skipping {table_name}.{field_name}: {e}")

    # Re-enable foreign key checks
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=ON")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_new_schema'),
        ('crawls', '0001_initial'),
        ('machine', '0001_squashed'),
    ]

    operations = [
        migrations.RunPython(clear_config_fields, reverse_code=migrations.RunPython.noop),
    ]
