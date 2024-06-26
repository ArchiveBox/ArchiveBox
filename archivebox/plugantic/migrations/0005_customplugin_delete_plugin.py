# Generated by Django 5.0.6 on 2024-05-18 01:42

import abid_utils.models
import charidfield.fields
import django.db.models.deletion
import pathlib
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plugantic', '0004_remove_plugin_schema_plugin_configs_plugin_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomPlugin',
            fields=[
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('uuid', models.UUIDField(blank=True, null=True, unique=True)),
                ('abid', charidfield.fields.CharIDField(blank=True, db_index=True, default=None, help_text='ABID-format identifier for this entity (e.g. snp_01BJQMF54D093DXEAWZ6JYRPAQ)', max_length=30, null=True, prefix='plg_', unique=True)),
                ('name', models.CharField(max_length=64, unique=True)),
                ('path', models.FilePathField(path=pathlib.PurePosixPath('/Volumes/NVME/Users/squash/Local/Code/archiveboxes/ArchiveBox/archivebox/plugins'))),
                ('created_by', models.ForeignKey(default=abid_utils.models.get_or_create_system_user_pk, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.DeleteModel(
            name='Plugin',
        ),
    ]
