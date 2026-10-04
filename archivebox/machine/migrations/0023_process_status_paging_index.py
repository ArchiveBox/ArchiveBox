from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0022_networkinterface_identity_without_mac"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="process",
            index=models.Index(fields=["status", "id"], name="mach_proc_status_id_idx"),
        ),
    ]
