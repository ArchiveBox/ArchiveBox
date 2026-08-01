import sqlite3
import textwrap

import pytest

from archivebox.tests.conftest import run_archivebox_cmd


def _run_archivebox(data_dir, args):
    result = run_archivebox_cmd(
        args,
        cwd=data_dir,
        timeout=120,
        env={"SHOW_PROGRESS": "False", "USE_COLOR": "False"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_migration_0045_preserves_legacy_empty_hook_history(tmp_path):
    _run_archivebox(tmp_path, ["init", "--quick"])

    seed_script = textwrap.dedent(
        """
        from django.contrib.auth import get_user_model

        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl

        user = get_user_model().objects.create_user(username="migration-history")
        crawl = Crawl.objects.create(urls="https://example.com", created_by=user)
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            timestamp="20240101000000.000000",
            crawl=crawl,
        )
        for index in range(3):
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="wget",
                hook_name=f"legacy-seed-{index}",
                output_str=f"legacy-{index}",
            )
        for index in range(2):
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="title",
                hook_name=f"modern-seed-{index}",
                output_str=f"modern-{index}",
            )
        """,
    )
    _run_archivebox(tmp_path, ["manage", "shell", "-c", seed_script])
    _run_archivebox(tmp_path, ["manage", "migrate", "core", "0044", "--noinput"])

    database_path = tmp_path / "index.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE core_archiveresult SET hook_name = '' WHERE output_str LIKE 'legacy-%'")
        connection.execute(
            "UPDATE core_archiveresult SET hook_name = 'on_Snapshot__01_title' WHERE output_str LIKE 'modern-%'",
        )
        connection.commit()

    _run_archivebox(tmp_path, ["init", "--quick"])

    with sqlite3.connect(database_path) as connection:
        legacy_outputs = {
            row[0]
            for row in connection.execute(
                "SELECT output_str FROM core_archiveresult WHERE plugin = 'wget' AND hook_name = ''",
            )
        }
        modern_count = connection.execute(
            """
            SELECT COUNT(*) FROM core_archiveresult
            WHERE plugin = 'title' AND hook_name = 'on_Snapshot__01_title'
            """,
        ).fetchone()[0]
        assert legacy_outputs == {"legacy-0", "legacy-1", "legacy-2"}
        assert modern_count == 1

        constraint_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'unique_archiveresult_per_snapshot_hook'",
        ).fetchone()[0]
        assert "WHERE" in constraint_sql
        assert "hook_name" in constraint_sql

        legacy_id = connection.execute(
            "SELECT id FROM core_archiveresult WHERE plugin = 'wget' AND hook_name = '' LIMIT 1",
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE core_archiveresult
                SET plugin = 'title', hook_name = 'on_Snapshot__01_title'
                WHERE id = ?
                """,
                (legacy_id,),
            )
