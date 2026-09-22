from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0036_snapshot_snapshot_public_order_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="snapshot",
            name="url",
            field=models.CharField(db_index=True, max_length=65535),
        ),
    ]
