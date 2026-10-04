from django.db import migrations, models


def repair_binary_field_indexes(apps, schema_editor):
    Binary = apps.get_model("machine", "Binary")
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Binary._meta.db_table)
    indexed_columns = {
        tuple(constraint["columns"])
        for constraint in constraints.values()
        if constraint.get("index") or constraint.get("unique") or constraint.get("primary_key")
    }
    # 0005's legacy raw-SQL table creation omitted field indexes even though
    # migration state declares them. Editing 0005 alone cannot repair already
    # upgraded collections. Restore only missing single-field indexes, checking
    # columns rather than generated names so fresh SQLite/PostgreSQL installs
    # retain their existing indexes without duplicates or a schema-state change.
    for field in Binary._meta.local_fields:
        if field.db_index and not field.unique and (field.column,) not in indexed_columns:
            schema_editor.add_index(Binary, models.Index(fields=[field.name], name=f"mach_binary_{field.column}_idx"))


class Migration(migrations.Migration):
    dependencies = [("machine", "0022_networkinterface_identity_without_mac")]

    operations = [migrations.RunPython(repair_binary_field_indexes, migrations.RunPython.noop)]
