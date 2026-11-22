from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0064_snapshot_uuid_suffix_idx")]

    # Retained for migration history. Public pages reuse the existing order
    # index; 0066 removes this index from installations that already built it.
    operations = []
