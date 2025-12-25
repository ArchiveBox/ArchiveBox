# Squashed migration: replaces 0001-0009
# For fresh installs: creates final schema
# For dev users with 0001-0009 applied: marked as applied (no-op)

from uuid import uuid4
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import api.models


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ('api', '0001_initial'),
        ('api', '0002_alter_apitoken_options'),
        ('api', '0003_rename_user_apitoken_created_by_apitoken_abid_and_more'),
        ('api', '0004_alter_apitoken_id_alter_apitoken_uuid'),
        ('api', '0005_remove_apitoken_uuid_remove_outboundwebhook_uuid_and_more'),
        ('api', '0006_remove_outboundwebhook_uuid_apitoken_id_and_more'),
        ('api', '0007_alter_apitoken_created_by'),
        ('api', '0008_alter_apitoken_created_alter_apitoken_created_by_and_more'),
        ('api', '0009_rename_created_apitoken_created_at_and_more'),
    ]

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='APIToken',
            fields=[
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_by', models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('token', models.CharField(default=api.models.generate_secret_token, max_length=32, unique=True)),
                ('expires', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'API Key',
                'verbose_name_plural': 'API Keys',
            },
        ),
        migrations.CreateModel(
            name='OutboundWebhook',
            fields=[
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_by', models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, default='', max_length=255)),
                ('signal', models.CharField(choices=[], db_index=True, max_length=255)),
                ('ref', models.CharField(db_index=True, max_length=255)),
                ('endpoint', models.URLField(max_length=2083)),
                ('headers', models.JSONField(blank=True, default=dict)),
                ('auth_token', models.CharField(blank=True, default='', max_length=4000)),
                ('enabled', models.BooleanField(db_index=True, default=True)),
                ('keep_last_response', models.BooleanField(default=False)),
                ('last_response', models.TextField(blank=True, default='')),
                ('last_success', models.DateTimeField(blank=True, null=True)),
                ('last_failure', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'API Outbound Webhook',
                'ordering': ['name', 'ref'],
                'abstract': False,
            },
        ),
    ]
