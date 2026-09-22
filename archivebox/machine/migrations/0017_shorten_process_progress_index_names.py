from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0016_process_delete_at"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="process",
            name="machine_pro_progress_recent_idx",
        ),
        migrations.RemoveIndex(
            model_name="process",
            name="machine_pro_progress_running_idx",
        ),
        migrations.AddIndex(
            model_name="process",
            index=models.Index(fields=["machine", "process_type", "-modified_at"], name="mach_proc_recent_idx"),
        ),
        migrations.AddIndex(
            model_name="process",
            index=models.Index(fields=["machine", "status", "process_type"], name="mach_proc_running_idx"),
        ),
    ]
