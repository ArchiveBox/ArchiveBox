import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


pytestmark = pytest.mark.django_db(transaction=True)


def test_migration_restores_distinct_hook_rows_after_published_plugin_constraint():
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0052_unique_archiveresult_per_snapshot_plugin")])
        old_apps = executor.loader.project_state([("core", "0052_unique_archiveresult_per_snapshot_plugin")]).apps
        Crawl = old_apps.get_model("crawls", "Crawl")
        Snapshot = old_apps.get_model("core", "Snapshot")
        ArchiveResult = old_apps.get_model("core", "ArchiveResult")
        crawl = Crawl.objects.create(urls="https://example.com")
        snapshot = Snapshot.objects.create(url="https://example.com/migration", crawl=crawl)
        ArchiveResult.objects.create(snapshot=snapshot, plugin="responses", hook_name="browser-upload")

        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0054_restore_archiveresult_hook_identity")])
        new_apps = executor.loader.project_state([("core", "0054_restore_archiveresult_hook_identity")]).apps
        ArchiveResult = new_apps.get_model("core", "ArchiveResult")

        ArchiveResult.objects.create(snapshot_id=snapshot.id, plugin="responses", hook_name="server-capture")
        assert ArchiveResult.objects.filter(snapshot_id=snapshot.id, plugin="responses").count() == 2
        with pytest.raises(IntegrityError), transaction.atomic():
            ArchiveResult.objects.create(snapshot_id=snapshot.id, plugin="responses", hook_name="browser-upload")
    finally:
        MigrationExecutor(connection).migrate([("core", "0054_restore_archiveresult_hook_identity")])
