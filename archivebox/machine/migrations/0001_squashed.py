# Squashed migration: replaces 0001-0004
# For fresh installs: creates final schema
# For dev users with 0001-0004 applied: marked as applied (no-op)

from uuid import uuid4
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ('machine', '0001_initial'),
        ('machine', '0002_alter_machine_stats_installedbinary'),
        ('machine', '0003_alter_installedbinary_options_and_more'),
        ('machine', '0004_alter_installedbinary_abspath_and_more'),
    ]

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Machine',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('guid', models.CharField(default=None, editable=False, max_length=64, unique=True)),
                ('hostname', models.CharField(default=None, max_length=63)),
                ('hw_in_docker', models.BooleanField(default=False)),
                ('hw_in_vm', models.BooleanField(default=False)),
                ('hw_manufacturer', models.CharField(default=None, max_length=63)),
                ('hw_product', models.CharField(default=None, max_length=63)),
                ('hw_uuid', models.CharField(default=None, max_length=255)),
                ('os_arch', models.CharField(default=None, max_length=15)),
                ('os_family', models.CharField(default=None, max_length=15)),
                ('os_platform', models.CharField(default=None, max_length=63)),
                ('os_release', models.CharField(default=None, max_length=63)),
                ('os_kernel', models.CharField(default=None, max_length=255)),
                ('stats', models.JSONField(default=dict)),
                ('config', models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.CreateModel(
            name='NetworkInterface',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('mac_address', models.CharField(default=None, editable=False, max_length=17)),
                ('ip_public', models.GenericIPAddressField(default=None, editable=False)),
                ('ip_local', models.GenericIPAddressField(default=None, editable=False)),
                ('dns_server', models.GenericIPAddressField(default=None, editable=False)),
                ('hostname', models.CharField(default=None, max_length=63)),
                ('iface', models.CharField(default=None, max_length=15)),
                ('isp', models.CharField(default=None, max_length=63)),
                ('city', models.CharField(default=None, max_length=63)),
                ('region', models.CharField(default=None, max_length=63)),
                ('country', models.CharField(default=None, max_length=63)),
                ('machine', models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, to='machine.machine')),
            ],
            options={
                'unique_together': {('machine', 'ip_public', 'ip_local', 'mac_address', 'dns_server')},
            },
        ),
        # Dependency model removed - not needed anymore
        migrations.CreateModel(
            name='Binary',
            fields=[
                ('num_uses_failed', models.PositiveIntegerField(default=0)),
                ('num_uses_succeeded', models.PositiveIntegerField(default=0)),
                ('id', models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, db_index=True, default=None, max_length=63)),
                ('binprovider', models.CharField(blank=True, default=None, max_length=31)),
                ('abspath', models.CharField(blank=True, default=None, max_length=255)),
                ('version', models.CharField(blank=True, default=None, max_length=32)),
                ('sha256', models.CharField(blank=True, default=None, max_length=64)),
                ('machine', models.ForeignKey(blank=True, default=None, on_delete=django.db.models.deletion.CASCADE, to='machine.machine')),
                # Fields added in migration 0005 (included here for fresh installs)
                ('binproviders', models.CharField(blank=True, default='env', max_length=127)),
                ('output_dir', models.CharField(blank=True, default='', max_length=255)),
                ('overrides', models.JSONField(blank=True, default=dict)),
                ('retry_at', models.DateTimeField(blank=True, db_index=True, default=django.utils.timezone.now, null=True)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('started', 'Started'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], db_index=True, default='queued', max_length=16)),
                # dependency FK removed - Dependency model deleted
            ],
            options={
                'verbose_name': 'Binary',
                'verbose_name_plural': 'Binaries',
                'unique_together': {('machine', 'name', 'abspath', 'version', 'sha256')},
            },
        ),
    ]
