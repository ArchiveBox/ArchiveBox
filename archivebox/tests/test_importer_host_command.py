"""Exercise browser importer connection ownership through real command runs."""

import json
import time
from pathlib import Path

import psutil
import pytest

from archivebox.tests.conftest import run_archivebox_cmd, wait_for_pid_to_disappear
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("connection", ["cold", "persona", "cdp"])
def test_browser_importer_preserves_connection_ownership_on_cancel(initialized_archive, installed_opencode, connection):
    from django.contrib.auth import get_user_model

    from archivebox.importers.models import ImporterRun, ImporterSource
    from archivebox.importers.service import enqueue, pause
    from archivebox.personas.models import Persona
    from archivebox.plugins.discovery import get_plugin_catalog

    command = get_plugin_catalog().command("importers_browser", "import")
    assert command is not None
    assert command.path.name == "importer.py"
    assert get_plugin_catalog().command("importers_browser", "import_archivebox") is None
    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="importer-reader")
        persona = Persona.get_or_create_named("Importer command acceptance")
        existing = None
        owner = None
        endpoint = None
        if connection != "cold":
            launched = run_archivebox_cmd(
                ["persona", "open", persona.name, "--headless", "--background"],
                cwd=initialized_archive,
                timeout=90,
            )
            assert launched.returncode == 0, launched.stderr + launched.stdout
            existing = psutil.Process(json.loads(launched.stdout.splitlines()[-1])["browser_pid"])
            owner = existing.parent()
            endpoint = (persona.path / ".browser" / "cdp_url.txt").read_text().strip()
        source = ImporterSource.objects.create(
            name="Browser host cancellation",
            plugin="importers_browser",
            feed="reddit_saves",
            persona=persona,
            created_by=user,
            settings={"IMPORTERS_BROWSER_ACCOUNT": "", "IMPORTERS_BROWSER_URL": ""},
        )
        run = enqueue(source, ImporterRun.Action.CHECK)
        process = run_archivebox_cmd(
            ["shell", "-c", "from archivebox.importers.service import run_next_importer; assert run_next_importer()"],
            cwd=initialized_archive,
            env={"BU_CDP_URL": endpoint} if connection == "cdp" else {},
            wait=False,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                run.refresh_from_db()
                if run.message.startswith("Learning or repairing browser importer") or process.poll() is not None:
                    break
                time.sleep(0.1)
            # This progress event occurs only after browser-harness has created
            # the real task tab. Cancel before relying on any model response.
            assert run.message.startswith("Learning or repairing browser importer"), (run.status, run.message)
            browser_pid = int((Path(persona.path) / ".browser" / "chrome.pid").read_text())
            assert psutil.pid_exists(browser_pid)
            pause(source)
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stdout + stderr
            if existing:
                assert browser_pid == existing.pid
                assert existing.is_running()
                assert (persona.path / ".browser" / "cdp_url.txt").read_text().strip() == endpoint
            else:
                wait_for_pid_to_disappear(browser_pid)
            run.refresh_from_db()
            source.refresh_from_db()
            assert run.status == ImporterRun.Status.CANCELLED
            assert run.finished_at is not None
            assert source.account == {}
            assert source.checkpoint == {}
            assert run.items == []
            assert run.crawl_id is None
            browser_log = initialized_archive / "importers" / str(source.id) / str(run.id) / "browser.log"
            assert browser_log.exists() == (connection != "cdp")
        finally:
            if process.poll() is None:
                pause(source)
                process.communicate(timeout=30)
            if existing and existing.is_running():
                existing.terminate()
                existing.wait(timeout=15)
            if owner:
                owner.wait(timeout=15)
