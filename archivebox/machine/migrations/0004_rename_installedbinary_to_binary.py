# Generated migration - Clean slate for Binary model
# Drops old InstalledBinary and Dependency tables, creates new Binary table

from django.db import migrations, models
import django.utils.timezone
import archivebox.uuid_compat


def drop_old_tables(apps, schema_editor):
    """Drop old tables using raw SQL"""
    schema_editor.execute('DROP TABLE IF EXISTS machine_installedbinary')
    schema_editor.execute('DROP TABLE IF EXISTS machine_dependency')
    schema_editor.execute('DROP TABLE IF EXISTS machine_binary')  # In case rename happened


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0003_alter_dependency_id_alter_installedbinary_dependency_and_more'),
    ]

    operations = [
        # Drop old tables using raw SQL
        migrations.RunPython(drop_old_tables, migrations.RunPython.noop),

        # Create new Binary model from scratch
        migrations.CreateModel(
            name='Binary',
            fields=[
                ('id', models.UUIDField(default=archivebox.uuid_compat.uuid7, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, db_index=True, default=None, max_length=63)),
                ('binproviders', models.CharField(blank=True, default='env', help_text='Comma-separated list of allowed providers: apt,brew,pip,npm,env', max_length=127)),
                ('overrides', models.JSONField(blank=True, default=dict, help_text="Provider-specific overrides: {'apt': {'packages': ['pkg']}, ...}")),
                ('binprovider', models.CharField(blank=True, default=None, help_text='Provider that successfully installed this binary', max_length=31)),
                ('abspath', models.CharField(blank=True, default=None, max_length=255)),
                ('version', models.CharField(blank=True, default=None, max_length=32)),
                ('sha256', models.CharField(blank=True, default=None, max_length=64)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('started', 'Started'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], db_index=True, default='queued', max_length=16)),
                ('retry_at', models.DateTimeField(blank=True, db_index=True, default=django.utils.timezone.now, help_text='When to retry this binary installation', null=True)),
                ('output_dir', models.CharField(blank=True, default='', help_text='Directory where installation hook logs are stored', max_length=255)),
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('machine', models.ForeignKey(blank=True, default=None, on_delete=models.deletion.CASCADE, to='machine.machine')),
            ],
            options={
                'verbose_name': 'Binary',
                'verbose_name_plural': 'Binaries',
            },
        ),
        migrations.AddIndex(
            model_name='binary',
            index=models.Index(fields=['machine', 'name', 'abspath', 'version', 'sha256'], name='machine_bin_machine_idx'),
        ),
    ]
