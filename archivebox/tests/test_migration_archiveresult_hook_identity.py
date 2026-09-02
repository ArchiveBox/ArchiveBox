import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


pytestmark = pytest.mark.django_db(transaction=True)


def test_published_plugin_constraint_preserves_existing_hook_rows():
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0051_postgres_url_pattern_ops_index")])
        old_apps = executor.loader.project_state([("core", "0051_postgres_url_pattern_ops_index")]).apps
        Crawl = old_apps.get_model("crawls", "Crawl")
        Snapshot = old_apps.get_model("core", "Snapshot")
        ArchiveResult = old_apps.get_model("core", "ArchiveResult")
        crawl = Crawl.objects.create(urls="https://example.com")
        snapshot = Snapshot.objects.create(url="https://example.com/history", crawl=crawl)
        first = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="browser-upload",
            output_json={"source": "browser"},
        )
        second = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="server-capture",
            output_json={"source": "server"},
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0054_restore_archiveresult_hook_identity")])
        new_apps = executor.loader.project_state([("core", "0054_restore_archiveresult_hook_identity")]).apps
        ArchiveResult = new_apps.get_model("core", "ArchiveResult")
        rows = list(
            ArchiveResult.objects.filter(snapshot_id=snapshot.id, plugin="responses")
            .order_by("hook_name")
            .values_list("id", "hook_name", "output_json"),
        )

        assert rows == [
            (first.id, "browser-upload", {"source": "browser"}),
            (second.id, "server-capture", {"source": "server"}),
        ]

        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0053_alter_archiveresult_options")])
        temporary_apps = executor.loader.project_state([("core", "0053_alter_archiveresult_options")]).apps
        ArchiveResult = temporary_apps.get_model("core", "ArchiveResult")
        temporary_rows = list(
            ArchiveResult.objects.filter(snapshot_id=snapshot.id).values_list("plugin", "output_json"),
        )
        assert len(temporary_rows) == 2
        assert len({plugin for plugin, _output_json in temporary_rows}) == 2

        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0054_restore_archiveresult_hook_identity")])
        restored_apps = executor.loader.project_state([("core", "0054_restore_archiveresult_hook_identity")]).apps
        ArchiveResult = restored_apps.get_model("core", "ArchiveResult")
        assert (
            list(
                ArchiveResult.objects.filter(snapshot_id=snapshot.id, plugin="responses")
                .order_by("hook_name")
                .values_list("id", "hook_name", "output_json"),
            )
            == rows
        )
    finally:
        MigrationExecutor(connection).migrate([("core", "0054_restore_archiveresult_hook_identity")])


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
