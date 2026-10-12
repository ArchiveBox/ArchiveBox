from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("importers", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="importerrun",
            name="action",
            field=models.CharField(
                choices=[("check", "Check access"), ("preview", "Preview"), ("import", "Import"), ("reset_code", "Reset learned code")],
                default="import",
                max_length=16,
            ),
        ),
    ]
