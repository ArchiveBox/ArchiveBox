from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0005_rule_display_names")]
    operations = [
        migrations.AddField(model_name="outboundwebhook", name="any_folder", field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name="outboundwebhook",
            name="relationship",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
