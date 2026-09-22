from django.db import migrations


def drop_stale_crawl_timeout_column(apps, schema_editor):
    table_name = "crawls_crawl"
    column_name = "crawl_timeout"
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, table_name)}
        if column_name not in columns:
            return
        schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(table_name)} DROP COLUMN {schema_editor.quote_name(column_name)}")


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0011_move_crawl_limits_to_config"),
    ]

    operations = [
        migrations.RunPython(drop_stale_crawl_timeout_column, migrations.RunPython.noop),
    ]
