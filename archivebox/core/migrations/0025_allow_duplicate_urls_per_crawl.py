from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_snapshot_crawl'),
    ]

    operations = [
        # Remove the unique constraint on url
        migrations.AlterField(
            model_name='snapshot',
            name='url',
            field=models.URLField(db_index=True, unique=False),
        ),
        # Add unique constraint on (url, crawl) combination
        migrations.AddConstraint(
            model_name='snapshot',
            constraint=models.UniqueConstraint(fields=['url', 'crawl'], name='unique_url_per_crawl'),
        ),
    ]
