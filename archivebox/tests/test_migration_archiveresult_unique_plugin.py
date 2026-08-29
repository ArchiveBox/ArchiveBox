import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


pytestmark = pytest.mark.django_db(transaction=True)


def test_migration_consolidates_plugin_rows_and_enforces_uniqueness():
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0051_postgres_url_pattern_ops_index")])
        old_apps = executor.loader.project_state([("core", "0051_postgres_url_pattern_ops_index")]).apps
        Crawl = old_apps.get_model("crawls", "Crawl")
        Snapshot = old_apps.get_model("core", "Snapshot")
        ArchiveResult = old_apps.get_model("core", "ArchiveResult")
        crawl = Crawl.objects.create(urls="https://example.com")
        snapshot = Snapshot.objects.create(url="https://example.com/migration", crawl=crawl, output_size=10)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="browser-upload",
            status="succeeded",
            output_files={"browser.png": {"size": 7}},
            output_size=7,
            output_mimetypes="image/png",
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="server-capture",
            status="noresults",
            output_files={"server.json": {"size": 3}},
            output_size=3,
            output_mimetypes="application/json",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0052_unique_archiveresult_per_snapshot_plugin")])
        new_apps = executor.loader.project_state([("core", "0052_unique_archiveresult_per_snapshot_plugin")]).apps
        Snapshot = new_apps.get_model("core", "Snapshot")
        ArchiveResult = new_apps.get_model("core", "ArchiveResult")
        snapshot = Snapshot.objects.get(id=snapshot.id)
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="responses")

        assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="responses").count() == 1
        assert result.status == "succeeded"
        assert set(result.output_files) == {"browser.png", "server.json"}
        assert result.output_size == 10
        assert snapshot.output_size == 10
        assert set(result.output_mimetypes.split(",")) == {"application/json", "image/png"}
    finally:
        MigrationExecutor(connection).migrate([("core", "0052_unique_archiveresult_per_snapshot_plugin")])
