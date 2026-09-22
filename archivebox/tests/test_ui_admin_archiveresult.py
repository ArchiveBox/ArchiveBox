"""ArchiveResult admin UI tests."""

import asyncio
import os
from importlib.resources import files
from pathlib import Path

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST, resolve_abxpkg_binary_env

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def projected_noresults(snapshot, cached_abxpkg_lib_dir):
    from abx_dl.events import ProcessEvent, SnapshotEvent
    from abx_dl.orchestrator import create_bus
    from abx_dl.services.archive_result_service import ArchiveResultService as HookArchiveResultService
    from abx_dl.services.process_service import ProcessService as HookProcessService
    from archivebox.core.models import ArchiveResult
    from archivebox.services.archive_result_service import ArchiveResultService
    from archivebox.services.process_service import ProcessService as PersistedProcessService

    plugin = "parse_txt_urls"
    hook_name = "on_Snapshot__71_parse_txt_urls.py"
    hook_path = Path(str(files("abx_plugins.plugins.parse_txt_urls").joinpath(hook_name)))
    binary_env = resolve_abxpkg_binary_env(cached_abxpkg_lib_dir, deps_from=hook_path.parent / "config.json")
    staticfile_dir = snapshot.output_dir / "staticfile"
    output_dir = snapshot.output_dir / plugin
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("plain text without links", encoding="utf-8")
    bus = create_bus(name=f"test_admin_noresults_{snapshot.id}")
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False)
    HookArchiveResultService(bus, emit_jsonl=False)
    PersistedProcessService(bus)
    ArchiveResultService(bus)

    async def run() -> None:
        try:
            snapshot_event = SnapshotEvent(
                url=snapshot.url,
                snapshot_id=str(snapshot.id),
                output_dir=str(snapshot.output_dir),
            )
            await bus.emit(snapshot_event).now()
            await bus.emit(
                ProcessEvent(
                    plugin_name=plugin,
                    hook_name=hook_name,
                    hook_path=str(hook_path),
                    hook_args=[f"--url={snapshot.url}"],
                    env={
                        **binary_env,
                        "ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir),
                        "SNAP_DIR": str(snapshot.output_dir),
                        "PATH": f"{Path(os.sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                    },
                    output_dir=str(output_dir),
                    timeout=60,
                    is_background=False,
                    url=snapshot.url,
                    process_type="hook",
                    worker_type="hook",
                    event_parent_id=snapshot_event.event_id,
                ),
            ).now()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run())
    return ArchiveResult.objects.get(snapshot=snapshot, plugin=plugin, hook_name=hook_name)


class TestArchiveResultAdminListView:
    def test_list_view_renders_readonly_tags_and_noresults_status(self, client, admin_user, snapshot, projected_noresults):
        from archivebox.core.models import ArchiveResult, Tag

        tag = Tag.objects.create(name="Alpha Research")
        snapshot.tags.add(tag)
        assert projected_noresults.status == ArchiveResult.StatusChoices.NORESULTS
        assert projected_noresults.process_id is not None

        client.force_login(admin_user)
        response = client.get(reverse("admin:core_archiveresult_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Alpha Research" in response.content
        assert b"tag-editor-inline readonly" in response.content
        assert b"No Results" in response.content

    def test_archiveresult_model_has_retry_at_field(self):
        from archivebox.core.models import ArchiveResult

        assert "retry_at" in {field.name for field in ArchiveResult._meta.fields}

    def test_change_view_loads_output_json_with_main_result_query(self, client, admin_user, projected_noresults):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        projected_noresults.output_json = {"detail": "output-json-loaded-once"}
        projected_noresults.save(update_fields=["output_json", "modified_at"])
        client.force_login(admin_user)

        with CaptureQueriesContext(connection) as captured_queries:
            response = client.get(
                reverse("admin:core_archiveresult_change", args=[projected_noresults.pk]),
                HTTP_HOST=ADMIN_TEST_HOST,
            )

        result_queries = [query for query in captured_queries if 'FROM "core_archiveresult"' in query["sql"]]
        assert response.status_code == 200
        assert b"output-json-loaded-once" in response.content
        assert len(result_queries) == 1

    def test_admin_delete_removes_output_directory_and_refreshes_snapshot_size(self, client, admin_user, snapshot):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "screenshot"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "output.png").write_bytes(b"archive output")
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            hook_name="on_Snapshot__50_screenshot.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"output.png": {"size": 14, "mimetype": "image/png"}},
            output_size=14,
        )
        client.force_login(admin_user)

        response = client.post(
            reverse("admin:core_archiveresult_delete", args=[result.pk]),
            {"post": "yes"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert response.status_code == 302
        assert not ArchiveResult.objects.filter(pk=result.pk).exists()
        assert not output_dir.exists()
        snapshot.refresh_from_db()
        assert snapshot.output_size == 0

    def test_deleting_sibling_hook_preserves_shared_plugin_output(self, snapshot):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "responses"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "index.jsonl"
        output_file.write_text("captured response\n")
        primary = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="on_Snapshot__24_responses.daemon.bg",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_size=18,
        )
        duplicate = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            hook_name="on_Snapshot__24_responses.daemon.bg.replayed",
            status=ArchiveResult.StatusChoices.NORESULTS,
        )

        duplicate.delete()

        assert ArchiveResult.objects.filter(pk=primary.pk).exists()
        assert output_file.read_text() == "captured response\n"
