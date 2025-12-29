# Drop seed_id column from Django's state (leave in database to avoid FK issues)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('crawls', '0004_alter_crawl_output_dir'),
    ]

    operations = [
        # Update Django's state only - leave seed_id column in database (unused but harmless)
        # This avoids FK mismatch errors with crawls_crawlschedule
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Remove seed field from Django's migration state
                migrations.RemoveField(
                    model_name='crawl',
                    name='seed',
                ),
            ],
            database_operations=[
                # No database changes - seed_id column remains to avoid FK rebuild issues
                # crawls_seed table can be manually dropped by DBA if needed
            ],
        ),
    ]
