from django.db import migrations


def revoke_exposed_sessions(apps, schema_editor):
    # Legacy replay grants/cookies included the readable admin session key.
    # Rejecting old replay signatures cannot revoke that key on the admin host.
    # Invalidate existing sessions once on upgrade; accounts and API keys remain.
    apps.get_model("sessions", "Session").objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0058_snapshot_deleting_status"),
        ("sessions", "0001_initial"),
    ]

    operations = [migrations.RunPython(revoke_exposed_sessions, migrations.RunPython.noop)]
