# Generated on 2025-12-31
# Adds parent FK and process_type field to Process model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                -- Add parent_id FK column to machine_process
                ALTER TABLE machine_process ADD COLUMN parent_id TEXT REFERENCES machine_process(id) ON DELETE SET NULL;
                CREATE INDEX IF NOT EXISTS machine_process_parent_id_idx ON machine_process(parent_id);

                -- Add process_type column with default 'binary'
                ALTER TABLE machine_process ADD COLUMN process_type VARCHAR(16) NOT NULL DEFAULT 'binary';
                CREATE INDEX IF NOT EXISTS machine_process_process_type_idx ON machine_process(process_type);

                -- Add composite index for parent + status queries
                CREATE INDEX IF NOT EXISTS machine_process_parent_status_idx ON machine_process(parent_id, status);

                -- Add composite index for machine + pid + started_at (for PID reuse protection)
                CREATE INDEX IF NOT EXISTS machine_process_machine_pid_started_idx ON machine_process(machine_id, pid, started_at);
            """,
                    reverse_sql="""
                        DROP INDEX IF EXISTS machine_process_machine_pid_started_idx;
                        DROP INDEX IF EXISTS machine_process_parent_status_idx;
                        DROP INDEX IF EXISTS machine_process_process_type_idx;
                        DROP INDEX IF EXISTS machine_process_parent_id_idx;

                        -- SQLite doesn't support DROP COLUMN directly, but we record the intent
                        -- In practice, this migration is forward-only for SQLite
                        -- For PostgreSQL/MySQL: ALTER TABLE machine_process DROP COLUMN process_type;
                        -- For PostgreSQL/MySQL: ALTER TABLE machine_process DROP COLUMN parent_id;
                    """
                ),
            ],
            state_operations=[
                # Add parent FK
                migrations.AddField(
                    model_name='process',
                    name='parent',
                    field=models.ForeignKey(
                        blank=True,
                        help_text='Parent process that spawned this one',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='children',
                        to='machine.process',
                    ),
                ),
                # Add process_type field
                migrations.AddField(
                    model_name='process',
                    name='process_type',
                    field=models.CharField(
                        choices=[
                            ('cli', 'CLI Command'),
                            ('supervisord', 'Supervisord Daemon'),
                            ('orchestrator', 'Orchestrator'),
                            ('worker', 'Worker Process'),
                            ('hook', 'Hook Script'),
                            ('binary', 'Binary Execution'),
                        ],
                        db_index=True,
                        default='binary',
                        help_text='Type of process in the execution hierarchy',
                        max_length=16,
                    ),
                ),
                # Add indexes
                migrations.AddIndex(
                    model_name='process',
                    index=models.Index(
                        fields=['parent', 'status'],
                        name='machine_pro_parent__status_idx',
                    ),
                ),
                migrations.AddIndex(
                    model_name='process',
                    index=models.Index(
                        fields=['machine', 'pid', 'started_at'],
                        name='machine_pro_machine_pid_idx',
                    ),
                ),
            ],
        ),
    ]
