from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("api", "0006_rule_event_scopes")]

    operations = [
        migrations.AddField(model_name="outboundwebhook", name="any_tag", field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name="outboundwebhook",
            name="tag",
            field=models.ForeignKey(blank=True, db_index=False, null=True, on_delete=django.db.models.deletion.CASCADE, to="core.tag"),
        ),
    ]
