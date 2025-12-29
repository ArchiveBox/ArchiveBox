# Fix num_uses_failed and num_uses_succeeded string values to integers

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_fix_missing_columns'),
    ]

    operations = [
        # Fix string values that got inserted as literals instead of integers
        migrations.RunSQL(
            sql="""
                UPDATE core_snapshot
                SET num_uses_failed = 0
                WHERE typeof(num_uses_failed) = 'text' OR num_uses_failed = 'num_uses_failed';

                UPDATE core_snapshot
                SET num_uses_succeeded = 0
                WHERE typeof(num_uses_succeeded) = 'text' OR num_uses_succeeded = 'num_uses_succeeded';

                UPDATE core_snapshot
                SET depth = 0
                WHERE typeof(depth) = 'text' OR depth = 'depth';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
