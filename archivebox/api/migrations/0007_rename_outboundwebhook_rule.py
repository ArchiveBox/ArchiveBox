from django.db import migrations


def rename_permissions(apps, schema_editor, old_name, new_name):
    db = schema_editor.connection.alias
    # Django renames the content type on migration. Rename its permissions in
    # place so existing user and group assignments keep their permission IDs.
    permission = apps.get_model("auth", "Permission")
    permissions = permission.objects.using(db).filter(content_type__app_label="api", content_type__model="rule")
    for action in ("add", "change", "delete", "view"):
        target = f"{action}_{new_name}"
        if not permissions.filter(codename=target).exists():
            permissions.filter(codename=f"{action}_{old_name}").update(codename=target, name=f"Can {action} Rule")


def forwards(apps, schema_editor):
    rename_permissions(apps, schema_editor, "outboundwebhook", "rule")


def backwards(apps, schema_editor):
    rename_permissions(apps, schema_editor, "rule", "outboundwebhook")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_rule_event_scopes"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [
        # Pin the current table so the ORM rename never changes stored rules.
        migrations.AlterModelTable(name="outboundwebhook", table="api_outboundwebhook"),
        migrations.RenameModel(old_name="OutboundWebhook", new_name="Rule"),
        migrations.RunPython(forwards, backwards),
    ]
