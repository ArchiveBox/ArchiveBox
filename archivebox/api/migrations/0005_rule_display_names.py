from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("api", "0004_retain_webhook_health_counters")]
    operations = [
        migrations.AlterModelOptions(
            name="outboundwebhook",
            options={"ordering": ("position", "created_at", "pk"), "verbose_name": "Rule", "verbose_name_plural": "Rules"},
        ),
    ]
