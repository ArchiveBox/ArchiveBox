import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


pytestmark = pytest.mark.django_db(transaction=True)


def test_migration_restores_exact_hook_identity_after_plugin_constraint():
    latest = [("core", "0053_restore_archiveresult_hook_identity")]
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0052_unique_archiveresult_per_snapshot_plugin")])
        old_apps = executor.loader.project_state([("core", "0052_unique_archiveresult_per_snapshot_plugin")]).apps
        Crawl = old_apps.get_model("crawls", "Crawl")
        Snapshot = old_apps.get_model("core", "Snapshot")
        ArchiveResult = old_apps.get_model("core", "ArchiveResult")
        crawl = Crawl.objects.create(urls="https://example.com")
        snapshot = Snapshot.objects.create(url="https://example.com/migration", crawl=crawl)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="archivewebpage",
            hook_name="on_Snapshot__16_archivewebpage_start",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        new_apps = executor.loader.project_state(latest).apps
        ArchiveResult = new_apps.get_model("core", "ArchiveResult")
        ArchiveResult.objects.create(
            snapshot_id=snapshot.id,
            plugin="archivewebpage",
            hook_name="on_Snapshot__65_archivewebpage_stop",
        )

        assert ArchiveResult.objects.filter(snapshot_id=snapshot.id, plugin="archivewebpage").count() == 2
        with pytest.raises(IntegrityError), transaction.atomic():
            ArchiveResult.objects.create(
                snapshot_id=snapshot.id,
                plugin="archivewebpage",
                hook_name="on_Snapshot__65_archivewebpage_stop",
            )
    finally:
        MigrationExecutor(connection).migrate(latest)
