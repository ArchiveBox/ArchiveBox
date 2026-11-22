from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0064_snapshot_uuid_suffix_idx")]

    # NEVER add new composite indexes when existing indexes can be combined or
    # queried smartly to get reasonable performance. Exact display totals are
    # not always necessary: public pages use lookahead and missing/stale totals.
    # Reusing the existing order index avoids another index's storage and write
    # overhead. Retain this migration for history; 0066 removes the index from
    # installations that already built it.
    operations = []
