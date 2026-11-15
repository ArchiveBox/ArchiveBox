from django.db import migrations


def ensure_health_counters(apps, schema_editor):
    # Releases that already rebuilt this table without the legacy columns need
    # the columns restored. Historical values lost by that rebuild require an
    # existing collection backup; zero here is only the new-column default.
    table = apps.get_model("api", "OutboundWebhook")._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        columns = {field.name for field in schema_editor.connection.introspection.get_table_description(cursor, table)}
    quote = schema_editor.quote_name
    for name in ("num_uses_failed", "num_uses_succeeded"):
        if name not in columns:
            schema_editor.execute(
                f"ALTER TABLE {quote(table)} ADD COLUMN {quote(name)} integer NOT NULL DEFAULT 0 CHECK ({quote(name)} >= 0)",
            )


class Migration(migrations.Migration):
    dependencies = [("api", "0003_webhook_signal_choices")]
    operations = [migrations.RunPython(ensure_health_counters, migrations.RunPython.noop)]
