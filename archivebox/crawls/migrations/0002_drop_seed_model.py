# Migration to remove Seed model and seed FK from Crawl
# Handles migration from 0.8.x (has Seed) to 0.9.x (no Seed)

import archivebox.base_models.models
import django.db.models.deletion
from archivebox import uuid_compat
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crawls', '0001_initial'),
        ('core', '0026_remove_archiveresult_output_dir_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Remove the seed foreign key from Crawl (no-op if already removed by core/0024_d)
        migrations.RunPython(
            code=lambda apps, schema_editor: None,
            reverse_code=migrations.RunPython.noop,
        ),
        # Delete the Seed model entirely (already done)
        migrations.RunPython(
            code=lambda apps, schema_editor: None,
            reverse_code=migrations.RunPython.noop,
        ),
        # Drop seed_id column if it exists, then update Django's migration state
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Update fields to new schema
                migrations.AlterField(
                    model_name='crawl',
                    name='created_by',
                    field=models.ForeignKey(default=archivebox.base_models.models.get_or_create_system_user_pk, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                migrations.AlterField(
                    model_name='crawl',
                    name='id',
                    field=models.UUIDField(default=uuid_compat.uuid7, editable=False, primary_key=True, serialize=False, unique=True),
                ),
                migrations.AlterField(
                    model_name='crawl',
                    name='urls',
                    field=models.TextField(help_text='Newline-separated list of URLs to crawl'),
                ),
                migrations.AlterField(
                    model_name='crawlschedule',
                    name='created_by',
                    field=models.ForeignKey(default=archivebox.base_models.models.get_or_create_system_user_pk, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                migrations.AlterField(
                    model_name='crawlschedule',
                    name='id',
                    field=models.UUIDField(default=uuid_compat.uuid7, editable=False, primary_key=True, serialize=False, unique=True),
                ),
            ],
            database_operations=[
                # Drop seed table and NULL out seed_id FK values
                migrations.RunSQL(
                    sql="""
                        PRAGMA foreign_keys=OFF;

                        -- NULL out seed_id values in crawls_crawl
                        UPDATE crawls_crawl SET seed_id = NULL;

                        -- Drop seed table if it exists
                        DROP TABLE IF EXISTS crawls_seed;

                        PRAGMA foreign_keys=ON;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
