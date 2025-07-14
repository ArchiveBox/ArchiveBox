# Generated manually for IPFS support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_archiveresult'),
    ]

    operations = [
        migrations.AddField(
            model_name='archiveresult',
            name='ipfs_hash',
            field=models.CharField(blank=True, default=None, help_text='IPFS hash of the archived file', max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='archiveresult',
            name='storage_type',
            field=models.CharField(choices=[('local', 'Local Storage'), ('ipfs', 'IPFS Storage'), ('hybrid', 'Hybrid Storage (Local + IPFS)')], default='local', help_text='Type of storage used for this archive result', max_length=16),
        ),
    ] 