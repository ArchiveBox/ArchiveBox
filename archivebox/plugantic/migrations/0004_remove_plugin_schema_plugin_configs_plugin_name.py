# Generated by Django 5.0.6 on 2024-05-18 01:28

import archivebox.plugantic.configs
import django.core.serializers.json
import django_pydantic_field.compat.django
import django_pydantic_field.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plugantic', '0003_alter_plugin_schema'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='plugin',
            name='schema',
        ),
        migrations.AddField(
            model_name='plugin',
            name='configs',
            field=django_pydantic_field.fields.PydanticSchemaField(config=None, default=[], encoder=django.core.serializers.json.DjangoJSONEncoder, schema=django_pydantic_field.compat.django.GenericContainer(list, (archivebox.plugantic.configs.ConfigSet,))),
        ),
        migrations.AddField(
            model_name='plugin',
            name='name',
            field=models.CharField(default='name', max_length=64, unique=True),
            preserve_default=False,
        ),
    ]
