# Initial migration for crawls app
# This is a new app, no previous migrations to replace

from uuid import uuid4
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Seed',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('uri', models.URLField(max_length=2048)),
                ('extractor', models.CharField(default='auto', max_length=32)),
                ('tags_str', models.CharField(blank=True, default='', max_length=255)),
                ('label', models.CharField(blank=True, default='', max_length=255)),
                ('config', models.JSONField(default=dict)),
                ('output_dir', models.CharField(blank=True, default='', max_length=512)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Seed',
                'verbose_name_plural': 'Seeds',
                'unique_together': {('created_by', 'label'), ('created_by', 'uri', 'extractor')},
            },
        ),
        migrations.CreateModel(
            name='Crawl',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('urls', models.TextField(blank=True, default='')),
                ('config', models.JSONField(default=dict)),
                ('max_depth', models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])),
                ('tags_str', models.CharField(blank=True, default='', max_length=1024)),
                ('persona_id', models.UUIDField(blank=True, null=True)),
                ('label', models.CharField(blank=True, default='', max_length=64)),
                ('notes', models.TextField(blank=True, default='')),
                ('output_dir', models.CharField(blank=True, default='', max_length=512)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('started', 'Started'), ('sealed', 'Sealed')], db_index=True, default='queued', max_length=15)),
                ('retry_at', models.DateTimeField(blank=True, db_index=True, default=django.utils.timezone.now, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('seed', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='crawl_set', to='crawls.seed')),
            ],
            options={
                'verbose_name': 'Crawl',
                'verbose_name_plural': 'Crawls',
            },
        ),
        migrations.CreateModel(
            name='CrawlSchedule',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('schedule', models.CharField(max_length=64)),
                ('is_enabled', models.BooleanField(default=True)),
                ('label', models.CharField(blank=True, default='', max_length=64)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='crawls.crawl')),
            ],
            options={
                'verbose_name': 'Scheduled Crawl',
                'verbose_name_plural': 'Scheduled Crawls',
            },
        ),
        migrations.AddField(
            model_name='crawl',
            name='schedule',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='crawls.crawlschedule'),
        ),
    ]
