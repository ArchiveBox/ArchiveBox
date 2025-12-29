# Fix crawls_crawl config field to avoid CHECK constraint errors during table rebuilds

from django.db import migrations


def fix_crawls_config(apps, schema_editor):
    """
    Rebuild crawls_crawl table to fix CHECK constraints and make seed_id nullable.
    Only runs for UPGRADES from 0.8.x (when crawls.0001_initial didn't exist yet).
    For fresh installs, crawls.0001_initial creates the correct schema.
    """
    with schema_editor.connection.cursor() as cursor:
        # Check if this is an upgrade from old 0.8.x or a fresh install
        # In fresh installs, crawls.0001_initial was applied, creating seed FK
        # In upgrades, the table was created by old migrations before 0001_initial existed
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations
            WHERE app='crawls' AND name='0001_initial'
        """)
        has_crawls_0001 = cursor.fetchone()[0] > 0

        if has_crawls_0001:
            # Fresh install - crawls.0001_initial already created the correct schema
            # Just clear config to avoid CHECK constraint issues
            print("  Fresh install detected - clearing config field only")
            try:
                cursor.execute('UPDATE "crawls_crawl" SET "config" = NULL')
            except Exception as e:
                print(f"  Skipping config clear: {e}")
            return

        # Upgrade from 0.8.x - rebuild table to make seed_id nullable and remove CHECK constraint
        print("  Upgrading from 0.8.x - rebuilding crawls_crawl table")
        cursor.execute("PRAGMA foreign_keys=OFF")

        # Backup
        cursor.execute("CREATE TABLE crawls_crawl_backup AS SELECT * FROM crawls_crawl")

        # Recreate without config CHECK constraint, with nullable seed_id
        cursor.execute("DROP TABLE crawls_crawl")
        cursor.execute("""
            CREATE TABLE "crawls_crawl" (
                "num_uses_failed" integer unsigned NOT NULL CHECK ("num_uses_failed" >= 0),
                "num_uses_succeeded" integer unsigned NOT NULL CHECK ("num_uses_succeeded" >= 0),
                "id" char(32) NOT NULL PRIMARY KEY,
                "created_at" datetime NOT NULL,
                "modified_at" datetime NOT NULL,
                "urls" text NOT NULL,
                "config" text,
                "max_depth" smallint unsigned NOT NULL CHECK ("max_depth" >= 0),
                "tags_str" varchar(1024) NOT NULL,
                "persona_id" char(32) NULL,
                "label" varchar(64) NOT NULL,
                "notes" text NOT NULL,
                "output_dir" varchar(512) NOT NULL,
                "status" varchar(15) NOT NULL,
                "retry_at" datetime NULL,
                "created_by_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED,
                "seed_id" char(32) NULL DEFAULT NULL,
                "schedule_id" char(32) NULL REFERENCES "crawls_crawlschedule" ("id") DEFERRABLE INITIALLY DEFERRED
            )
        """)

        # Restore data
        cursor.execute("""
            INSERT INTO "crawls_crawl" (
                "num_uses_failed", "num_uses_succeeded", "id", "created_at", "modified_at",
                "urls", "config", "max_depth", "tags_str", "persona_id", "label", "notes",
                "output_dir", "status", "retry_at", "created_by_id", "seed_id", "schedule_id"
            )
            SELECT
                "num_uses_failed", "num_uses_succeeded", "id", "created_at", "modified_at",
                "urls", "config", "max_depth", "tags_str", "persona_id", "label", "notes",
                "output_dir", "status", "retry_at", "created_by_id", "seed_id", "schedule_id"
            FROM crawls_crawl_backup
        """)

        cursor.execute("DROP TABLE crawls_crawl_backup")

        # NULL out config to avoid any invalid JSON
        cursor.execute('UPDATE "crawls_crawl" SET "config" = NULL')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_c_disable_fk_checks'),
        ('crawls', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(fix_crawls_config, reverse_code=migrations.RunPython.noop),
    ]
