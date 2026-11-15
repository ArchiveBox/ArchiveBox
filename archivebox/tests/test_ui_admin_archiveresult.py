"""ArchiveResult admin UI tests."""

import asyncio
import os
from importlib.resources import files
from pathlib import Path

import pytest
from django.db import connections, transaction
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
    @pytest.mark.django_db(transaction=False)
    @pytest.mark.parametrize(
        "params",
        [{}, {"status__exact": "succeeded"}, {"plugin__exact": "title"}, {"o": "3.-1"}, {"o": "5"}, {"q": "matching"}],
    )
    def test_pages_use_bounded_ids_without_counting_matches(self, admin_client, snapshot, settings, params):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from archivebox.core.models import ArchiveResult, Tag

        settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
        snapshot.tags.set([Tag.objects.create(name="matching alpha"), Tag.objects.create(name="matching beta")])
        ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(
                    snapshot=snapshot,
                    plugin="title" if index % 5 else "headers",
                    hook_name=f"page-{index}",
                    status="succeeded" if index % 5 else "failed",
                    output_str=f"matching result {index}",
                )
                for index in range(28)
            ],
        )
        url = reverse("admin:core_archiveresult_changelist")
        for page in (1, 2, 3):
            with CaptureQueriesContext(connection) as queries:
                response = admin_client.get(url, {**params, "p": page}, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200
            cl = response.context["cl"]
            expected = list(cl.queryset.values_list("pk", flat=True))
            assert [row.pk for row in cl.result_list] == expected[(page - 1) * 10 : page * 10]
            assert bool(cl.next_page_url) == (len(expected) > page * 10)
            assert bool(cl.previous_page_url) == (page > 1)
            assert cl.result_count_exact == (len(expected) <= page * 10)
            if params.get("o") == "5":
                assert all(row.snapshot_first_tag == "matching alpha" for row in cl.result_list)
            result_queries = [query["sql"] for query in queries if 'FROM "core_archiveresult"' in query["sql"]]
            assert not any("COUNT(" in sql.upper() for sql in result_queries)
            page_queries = [sql for sql in result_queries if "LIMIT 11" in sql]
            assert len(page_queries) == (2 if page == 3 and any(key in params for key in ("status__exact", "plugin__exact", "q")) else 1)
            assert all('"output_str"' not in sql.split(" FROM ")[0] for sql in page_queries)
            if page < 3:
                assert b"Select all matching rows" in response.content
            if page == 1 and "status__exact" in params:
                probes = [sql for sql in result_queries if 'FROM "core_archiveresult" ORDER BY' in sql and "LIMIT 88" in sql]
                assert len(probes) == 1
                if connection.vendor == "sqlite":
                    with connection.cursor() as cursor:
                        cursor.execute("EXPLAIN QUERY PLAN " + probes[0])
                        plan = " ".join(str(row[-1]) for row in cursor.fetchall())
                    assert "USING COVERING INDEX archiveresult_start_idx" in plan, plan

    @pytest.mark.django_db(transaction=False)
    def test_select_across_deletes_all_matches_beyond_displayed_page(self, admin_client, snapshot, settings):
        from archivebox.core.models import ArchiveResult

        settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
        results = ArchiveResult.objects.bulk_create(
            [ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"selected-{index}", status="succeeded") for index in range(25)],
        )
        excluded = ArchiveResult.objects.create(snapshot=snapshot, plugin="title", status="failed")
        response = admin_client.post(
            reverse("admin:core_archiveresult_changelist") + "?status__exact=succeeded",
            {"action": "delete_selected", "_selected_action": str(results[0].pk), "select_across": "1", "post": "yes"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
        assert list(ArchiveResult.objects.values_list("pk", flat=True)) == [excluded.pk]

    @pytest.mark.django_db(transaction=False)
    @pytest.mark.parametrize("total", [25, 205])
    @pytest.mark.parametrize("page", [1, 2])
    @pytest.mark.parametrize("model_name", ["archiveresult", "snapshot"])
    def test_show_all_keeps_existing_limit(self, admin_client, snapshot, total, page, model_name):
        from archivebox.core.models import ArchiveResult, Snapshot

        if model_name == "archiveresult":
            ArchiveResult.objects.bulk_create(
                [ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"show-all-{index}") for index in range(total)],
            )
        else:
            Snapshot.objects.bulk_create(
                [
                    Snapshot(url=f"https://example.com/{index}", crawl=snapshot.crawl, timestamp=str(1900800000 + index))
                    for index in range(total - 1)
                ],
            )
        response = admin_client.get(reverse(f"admin:core_{model_name}_changelist"), {"all": "", "p": page}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        cl = response.context["cl"]
        assert len(cl.result_list) == (25 if total == 25 else 50)
        assert cl.show_all == (total == 25)
        assert cl.result_count_exact == (total == 25)
        expected = list(cl.queryset.values_list("pk", flat=True))
        assert [row.pk for row in cl.result_list] == (expected if total == 25 else expected[(page - 1) * 50 : page * 50])
        assert "all=" not in (cl.next_page_url or "")
        assert "all=" not in (cl.previous_page_url or "")

    @pytest.mark.django_db(transaction=False)
    def test_empty_filter_and_out_of_range_page(self, admin_client, snapshot, settings):
        from archivebox.core.models import ArchiveResult

        settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
        ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"out-of-range-{index}", status="succeeded")
                for index in range(25)
            ],
        )
        url = reverse("admin:core_archiveresult_changelist")
        response = admin_client.get(url, {"status__exact": "paused"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert response.context["cl"].result_list == []
        assert response.context["cl"].result_count_exact
        response = admin_client.get(url, {"p": 4}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 302
        assert response.url == url + "?e=1"

    def test_display_total_uses_background_count(self, admin_client, snapshot, settings):
        from threading import enumerate as threads
        from archivebox.core.models import ArchiveResult

        settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
        ArchiveResult.objects.bulk_create(
            [ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"cached-count-{index}") for index in range(25)],
        )
        url = reverse("admin:core_archiveresult_changelist")
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        for thread in threads():
            if thread.name == "snapshot-list-count":
                thread.join(timeout=10)
                assert not thread.is_alive()
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        cl = response.context["cl"]
        assert cl.result_count_cached
        assert cl.display_result_count == 25
        assert not cl.result_count_exact
        assert len(cl.result_list) == 10

    def test_list_does_not_load_process_logs_or_machine_telemetry(self, admin_client, snapshot):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        machine = Machine.current()
        process = Process.objects.create(
            machine=machine,
            pwd="/tmp/archivebox-log-list",
            cmd=["title", snapshot.url],
            env={"TITLE_TIMEOUT": "60"},
            stdout="unused stdout\n" * 10000,
            stderr="unused stderr\n" * 10000,
        )
        result = ArchiveResult.objects.create(snapshot=snapshot, plugin="title", process=process, output_str="Title result")
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.get(reverse("admin:core_archiveresult_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b"Title result" in response.content
        assert b"TITLE_TIMEOUT=60" in response.content
        loaded = next(row for row in response.context["cl"].result_list if row.pk == result.pk)
        assert {"stdout", "stderr"} <= loaded.process.get_deferred_fields()
        assert {"stats", "config"} <= loaded.process.machine.get_deferred_fields()
        process_queries = [query["sql"] for query in queries if 'FROM "machine_process"' in query["sql"]]
        assert process_queries
        assert all('"stdout"' not in query and '"stderr"' not in query for query in process_queries)

    def test_created_sort_uses_date_index_without_redundant_default_order(self, admin_client, snapshot):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from django.utils import timezone
        from archivebox.core.models import ArchiveResult

        created = timezone.now()
        results = ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"created-sort-{index}", created_at=created)
                for index in range(60)
            ],
        )
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.get(
                reverse("admin:core_archiveresult_changelist"),
                {"o": "3.-1"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
        assert response.status_code == 200
        assert [result.pk for result in response.context["cl"].result_list] == sorted((result.pk for result in results), reverse=True)[:50]
        page_queries = [query["sql"] for query in queries if 'FROM "core_archiveresult"' in query["sql"] and "LIMIT 51" in query["sql"]]
        assert len(page_queries) == 1
        ordering = page_queries[0].split(" ORDER BY ")[1]
        assert '"start_ts"' not in ordering
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("EXPLAIN QUERY PLAN " + page_queries[0])
                plan = " ".join(str(row[-1]) for row in cursor.fetchall())
            assert "USING INDEX core_archiveresult_created_at" in plan, plan

    @pytest.mark.parametrize("ordering", [None, "", "invalid", "99"])
    def test_default_and_invalid_sort_keep_start_time_order(self, admin_client, snapshot, ordering):
        from datetime import timedelta
        from django.utils import timezone
        from archivebox.core.models import ArchiveResult

        now = timezone.now()
        results = ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(snapshot=snapshot, plugin="title", hook_name=f"start-sort-{index}", start_ts=now - timedelta(minutes=index))
                for index in range(3)
            ],
        )
        response = admin_client.get(
            reverse("admin:core_archiveresult_changelist"),
            {} if ordering is None else {"o": ordering},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 200
        assert [result.pk for result in response.context["cl"].result_list] == [result.pk for result in results]
        assert response.context["cl"].queryset.query.order_by[0] == "-start_ts"

    def test_plugin_icons_and_names_stay_on_one_line(self, live_server, admin_user, snapshot, browser_runtime, tmp_path):
        from playwright.sync_api import sync_playwright
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine

        machine = Machine.current()
        machine.config = {**machine.config, "BASE_URL": live_server.url, "SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay"}
        machine.save(update_fields=["config"])
        plugins = ("playwright", "archivewebpage", "screenshot", "parse_txt_urls")
        for plugin in plugins:
            ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, hook_name=f"on_Snapshot__{plugin}", status="queued")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page()
            page.goto(f"{live_server.url}/admin/login/?next=/admin/core/archiveresult/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            for width in (1600, 800, 390):
                page.set_viewport_size({"width": width, "height": 1000})
                page.locator("#result_list").wait_for()
                page.evaluate("document.fonts.ready")
                page.locator("td.field-plugin_with_icon").first.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                for plugin in plugins:
                    cell = page.locator("td.field-plugin_with_icon").filter(has=page.get_by_text(plugin, exact=True))
                    icon = cell.locator(".abx-output-icon").bounding_box()
                    name = cell.locator("code").bounding_box()
                    assert abs(icon["y"] + icon["height"] / 2 - name["y"] - name["height"] / 2) < 2
                    assert icon["x"] + icon["width"] <= name["x"]
                    assert cell.locator("code").inner_text() == plugin
                page.screenshot(path=str(tmp_path / f"archiveresult-plugins-{width}.png"), full_page=True)
            browser.close()

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

    def test_admin_delete_schedules_archive_result_webhook_with_deferred_fields(self, client, admin_user, snapshot):
        from archivebox.api.models import OutboundWebhook
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            hook_name="on_Snapshot__50_screenshot.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_json={"captured": "before-delete"},
        )
        OutboundWebhook.objects.create(
            name="archive-result-delete-test",
            signal="DELETE",
            ref="archivebox.core.models.ArchiveResult",
            endpoint="https://example.invalid/archive-result-delete-test",
            created_by=admin_user,
        )
        client.force_login(admin_user)

        # Inspect the real library's scheduled delivery after the admin request,
        # then roll back the outer transaction so no HTTP webhook is sent.
        connection = connections["default"]
        callback_offset = len(connection.run_on_commit)
        with transaction.atomic():
            response = client.post(
                reverse("admin:core_archiveresult_delete", args=[result.pk]),
                {"post": "yes"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
            deleted_inside_transaction = not ArchiveResult.objects.filter(pk=result.pk).exists()
            callbacks = [func for _sids, func, _robust in connection.run_on_commit[callback_offset:]]
            transaction.set_rollback(True)

        assert response.status_code == 302
        assert deleted_inside_transaction
        webhook_callbacks = [callback for callback in callbacks if callback.__name__ == "run_webhook"]
        assert len(webhook_callbacks) == 1
        callback_locals = dict(
            zip(
                webhook_callbacks[0].__code__.co_freevars,
                (cell.cell_contents for cell in webhook_callbacks[0].__closure__ or ()),
            ),
        )
        queued_kwargs = callback_locals["kwargs"]
        assert queued_kwargs["method"] == "DELETE"
        data = queued_kwargs["data"]
        assert data["model"] == "core.archiveresult"
        assert data["pk"] == str(result.pk)
        assert data["fields"]["snapshot"] == str(snapshot.pk)
        assert data["fields"]["output_json"] == {"captured": "before-delete"}

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
