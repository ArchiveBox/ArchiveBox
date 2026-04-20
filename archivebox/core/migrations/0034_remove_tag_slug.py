from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_alter_archiveresult_status"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tag",
            name="slug",
        ),
    ]
