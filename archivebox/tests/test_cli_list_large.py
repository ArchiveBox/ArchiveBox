"""Large-collection CLI regression tests.

Keep the million-row export in its own discovered CI job: competing CLI tests
initialize collections and launch captures, making its unchanged 60-second
command deadline depend on other xdist workers rather than export performance.
The real database, complete output count, and command deadline remain required.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone
import pytest

from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_list_limit_zero_streams_one_million_snapshots_without_materializing(initialized_archive, tmp_path):
    """Regression: archivebox list --limit=0 must stream unbounded result sets."""
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="million-snapshot-list")
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by=user,
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        now = timezone.now().isoformat()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE seq(n) AS (
                    SELECT 1
                    UNION ALL
                    SELECT n + 1 FROM seq WHERE n < 1000000
                )
                INSERT INTO core_snapshot (
                    id,
                    url,
                    timestamp,
                    title,
                    bookmarked_at,
                    created_at,
                    modified_at,
                    downloaded_at,
                    fs_version,
                    crawl_id,
                    config,
                    depth,
                    notes,
                    num_uses_failed,
                    num_uses_succeeded,
                    retry_at,
                    status,
                    delete_at,
                    output_size,
                    parent_snapshot_id
                )
                SELECT
                    lower(hex(randomblob(16))),
                    'https://example.com/page-' || n,
                    printf('9%031d', n),
                    '',
                    %s,
                    %s,
                    %s,
                    NULL,
                    '0.9.0',
                    %s,
                    '{}',
                    0,
                    '',
                    0,
                    0,
                    NULL,
                    'sealed',
                    NULL,
                    0,
                    NULL
                FROM seq
                """,
                [now, now, now, str(crawl.id).replace("-", "")],
            )

    output_path = tmp_path / "million-snapshots.jsonl"
    with output_path.open("w") as stdout:
        result = run_archivebox_cmd(
            ["list", "--limit=0"],
            cwd=initialized_archive,
            stdout=stdout,
            default_cli_env=True,
            disable_extractors=True,
        )

    assert result.returncode == 0, result.stderr
    with output_path.open() as stdout:
        assert sum(1 for line in stdout if line.startswith("{")) == 1000000
