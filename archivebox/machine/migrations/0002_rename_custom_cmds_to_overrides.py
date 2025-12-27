# Generated manually on 2025-12-26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0001_squashed'),
    ]

    operations = [
        migrations.RenameField(
            model_name='dependency',
            old_name='custom_cmds',
            new_name='overrides',
        ),
        migrations.AlterField(
            model_name='dependency',
            name='bin_name',
            field=models.CharField(db_index=True, help_text='Binary executable name (e.g., wget, yt-dlp, chromium)', max_length=63, unique=True),
        ),
        migrations.AlterField(
            model_name='dependency',
            name='bin_providers',
            field=models.CharField(default='*', help_text='Comma-separated list of allowed providers: apt,brew,pip,npm,gem,nix,custom or * for any', max_length=127),
        ),
        migrations.AlterField(
            model_name='dependency',
            name='overrides',
            field=models.JSONField(blank=True, default=dict, help_text="JSON map matching abx-pkg Binary.overrides format: {'pip': {'packages': ['pkg']}, 'apt': {'packages': ['pkg']}}"),
        ),
        migrations.AlterField(
            model_name='dependency',
            name='config',
            field=models.JSONField(blank=True, default=dict, help_text='JSON map of env var config to use during install'),
        ),
    ]
