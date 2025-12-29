# Generated migration

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_catchall_crawls_and_assign_snapshots(apps, schema_editor):
    """
    Create one catchall Crawl per user for all snapshots without a crawl.
    Assign those snapshots to their user's catchall crawl.
    """
    Snapshot = apps.get_model('core', 'Snapshot')
    Crawl = apps.get_model('crawls', 'Crawl')
    User = apps.get_model(settings.AUTH_USER_MODEL)

    # Get all snapshots without a crawl
    snapshots_without_crawl = Snapshot.objects.filter(crawl__isnull=True)

    if not snapshots_without_crawl.exists():
        return

    # Group by created_by_id
    snapshots_by_user = {}
    for snapshot in snapshots_without_crawl:
        user_id = snapshot.created_by_id
        if user_id not in snapshots_by_user:
            snapshots_by_user[user_id] = []
        snapshots_by_user[user_id].append(snapshot)

    # Create one catchall crawl per user and assign snapshots
    for user_id, snapshots in snapshots_by_user.items():
        try:
            user = User.objects.get(pk=user_id)
            username = user.username
        except User.DoesNotExist:
            username = 'unknown'

        # Create catchall crawl for this user
        crawl = Crawl.objects.create(
            urls=f'# Catchall crawl for {len(snapshots)} snapshots without a crawl',
            max_depth=0,
            label=f'[migration] catchall for user {username}',
            created_by_id=user_id,
        )

        # Assign all snapshots to this crawl
        for snapshot in snapshots:
            snapshot.crawl = crawl
            snapshot.save(update_fields=['crawl'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_snapshot_current_step'),
        ('crawls', '0004_alter_crawl_output_dir'),
    ]

    operations = [
        # Step 1: Assign all snapshots without a crawl to catchall crawls
        migrations.RunPython(
            create_catchall_crawls_and_assign_snapshots,
            reverse_code=migrations.RunPython.noop,
        ),

        # Step 2: Make crawl non-nullable
        migrations.AlterField(
            model_name='snapshot',
            name='crawl',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='snapshot_set', to='crawls.crawl'),
        ),

        # Step 3: Remove created_by field
        migrations.RemoveField(
            model_name='snapshot',
            name='created_by',
        ),
    ]
