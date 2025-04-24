from django.db import migrations, models

class Migration(migrations.Migration):
     dependencies = [
         ("core", "0074_alter_snapshot_downloaded_at"),  # adjust to match your
latest migration
     ]

     operations = [
         migrations.AddField(
             model_name="snapshot",
             name="retry_count",
             field=models.IntegerField(default=0, help_text="Number of
fetch attempts so far"),
         ),
     ]
