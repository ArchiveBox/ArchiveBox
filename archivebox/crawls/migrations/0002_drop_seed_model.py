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
        # Remove the seed foreign key from Crawl
        migrations.RemoveField(
            model_name='crawl',
            name='seed',
        ),
        # Delete the Seed model entirely
        migrations.DeleteModel(
            name='Seed',
        ),
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
    ]
