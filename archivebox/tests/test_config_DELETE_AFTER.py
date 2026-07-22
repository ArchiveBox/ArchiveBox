import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from archivebox.tests.conftest import run_archivebox_cmd, run_queued_crawls, cli_env


pytestmark = pytest.mark.django_db(transaction=True)

ADMIN_HOST = "admin.archivebox.localhost:8000"
API_HOST = "api.archivebox.localhost:8000"


def test_delete_after_real_cli_and_orchestrator_paths_cover_all_retained_models(tmp_path, recursive_test_site):
    env = cli_env(disable_extractors=True)
    _cmd_result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, timeout=90)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr

    run_env = {
        **env,
        "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
        "DELETE_AFTER": "1hr",
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
    }
    url = recursive_test_site["root_url"]
    _cmd_result = run_archivebox_cmd(
        ["add", "--plugins=wget,hashes", "--depth=0", url],
        cwd=tmp_path,
        timeout=120,
        env=run_env,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox add failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    run_queued_crawls(tmp_path, run_env)

    lookup_script = f"""
import json
from archivebox.core.models import Snapshot
snapshot = Snapshot.objects.select_related("crawl").get(url={url!r})
print(json.dumps({{
    "crawl_id": str(snapshot.crawl.id),
    "crawl_delete_at": bool(snapshot.crawl.delete_at),
    "snapshot_id": str(snapshot.id),
    "snapshot_delete_at": bool(snapshot.delete_at),
}}))
"""
    _cmd_result = run_archivebox_cmd(
        ["manage", "shell", "-c", lookup_script],
        cwd=tmp_path,
        timeout=90,
        env=run_env,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"retention lookup failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    created = json.loads(stdout.strip().splitlines()[-1])
    assert created["crawl_delete_at"]
    assert created["snapshot_delete_at"]

    setup_script = f"""
import json
import os
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.machine.models import Process

snapshot = Snapshot.objects.select_related("crawl").get(id="{created["snapshot_id"]}")
crawl = snapshot.crawl
if snapshot.status != snapshot.StatusChoices.SEALED or crawl.status != crawl.StatusChoices.SEALED:
    raise RuntimeError(f"expected sealed snapshot/crawl, got {{snapshot.status}}/{{crawl.status}}")

result = ArchiveResult.objects.select_related("process").get(
    snapshot=snapshot,
    plugin="hashes",
    hook_name="on_Snapshot__93_hashes",
)
if result.status != ArchiveResult.StatusChoices.SUCCEEDED or result.process_id is None:
    raise RuntimeError(f"expected successful projected hashes result, got {{result.status}}/{{result.process_id}}")
process = result.process
if process.status != Process.StatusChoices.EXITED or process.exit_code != 0:
    raise RuntimeError(f"expected successful real hook process, got {{process.status}}/{{process.exit_code}}")
if not Path(result.output_dir).is_dir():
    raise RuntimeError(f"expected real hook output directory at {{result.output_dir}}")
runner = next(
    (row for row in Process.objects.filter(worker_type="worker_runner").order_by("created_at") if "--no-stdin" in row.cmd),
    None,
)
if runner is None:
    raise RuntimeError("expected persisted worker_runner process")
archivebox_projection = Path(os.environ["ABXPKG_LIB_DIR"]) / "env" / "bin" / "archivebox"
if not archivebox_projection.is_symlink() or str(archivebox_projection) not in runner.cmd or "-m" in runner.cmd:
    raise RuntimeError(f"worker did not execute projected archivebox: {{runner.cmd}}")

due_at = timezone.now() - timedelta(hours=1)
ArchiveResult.objects.filter(pk=result.pk).update(delete_at=due_at)
Snapshot.objects.filter(pk=snapshot.pk).update(delete_at=due_at)
Crawl = type(crawl)
Crawl.objects.filter(pk=crawl.pk).update(delete_at=due_at)
Process.objects.filter(pk=process.pk).update(delete_at=due_at)

print(json.dumps({{
    "crawl_id": str(crawl.id),
    "snapshot_id": str(snapshot.id),
    "archiveresult_id": str(result.id),
        "process_id": str(process.id),
        "runner_cmd": runner.cmd,
    "crawl_dir": str(crawl.output_dir),
    "snapshot_dir": str(snapshot.output_dir),
    "archiveresult_dir": str(result.output_dir),
}}))
"""
    _cmd_result = run_archivebox_cmd(
        ["manage", "shell", "-c", setup_script],
        cwd=tmp_path,
        timeout=90,
        env=run_env,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"retention setup failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    retained = json.loads(stdout.strip().splitlines()[-1])
    assert retained["crawl_id"] == created["crawl_id"]

    _cmd_result = run_archivebox_cmd(["run", "--maintenance-only"], cwd=tmp_path, timeout=120, env=run_env)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"archivebox run failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    remaining_script = f"""
import json
from archivebox.crawls.models import Crawl
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.machine.models import Process
print(json.dumps({{
    "crawl": Crawl.objects.filter(id="{retained["crawl_id"]}").count(),
    "snapshot": Snapshot.objects.filter(id="{retained["snapshot_id"]}").count(),
    "archiveresult": ArchiveResult.objects.filter(id="{retained["archiveresult_id"]}").count(),
    "process": Process.objects.filter(id="{retained["process_id"]}").count(),
}}))
"""
    _cmd_result = run_archivebox_cmd(
        ["manage", "shell", "-c", remaining_script],
        cwd=tmp_path,
        timeout=90,
        env=run_env,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, f"retention remaining lookup failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    remaining = json.loads(stdout.strip().splitlines()[-1])
    assert remaining == {"crawl": 0, "snapshot": 0, "archiveresult": 0, "process": 0}
    assert not Path(retained["crawl_dir"]).exists()
    assert not Path(retained["snapshot_dir"]).exists()
    assert not Path(retained["archiveresult_dir"]).exists()


def test_delete_after_real_add_page_and_rest_create_paths(client):
    User = get_user_model()
    admin_user = User.objects.create_superuser(
        username="retentionadmin",
        email="retentionadmin@test.com",
        password="testpassword",
    )

    client.force_login(admin_user)
    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    assert 'name="delete_after"' in response.content.decode()

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/delete-after-ui",
            "tag": "retention-ui",
            "depth": "0",
            "max_urls": "1",
            "crawl_max_size": "0",
            "crawl_timeout": "60",
            "snapshot_max_size": "0",
            "delete_after": "2h",
            "crawl_max_concurrent_snapshots": "1",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "notes": "delete-after ui test",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "index_only": "on",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()

    from archivebox.crawls.models import Crawl

    ui_crawl = Crawl.objects.get(urls__contains="https://example.com/delete-after-ui")
    assert ui_crawl.config["DELETE_AFTER"] == "2h"
    assert ui_crawl.delete_at is not None
    from archivebox.services.runner import run_due_crawl

    assert run_due_crawl(ui_crawl, lock_seconds=10)
    ui_snapshot = ui_crawl.snapshot_set.get(url="https://example.com/delete-after-ui")
    assert ui_snapshot.delete_at is not None
    assert not ui_snapshot.output_dir.joinpath("staticfile", "stdin.txt").exists()

    from archivebox.api.auth import get_or_create_api_token

    api_token = get_or_create_api_token(admin_user)
    assert api_token is not None
    response = client.post(
        "/api/v1/crawls/crawls",
        data=json.dumps(
            {
                "urls": ["https://example.com/delete-after-rest"],
                "max_depth": 0,
                "max_urls": 1,
                "config": {"DELETE_AFTER": "3h"},
            },
        ),
        content_type="application/json",
        HTTP_HOST=API_HOST,
        HTTP_X_ARCHIVEBOX_API_KEY=api_token.token,
    )
    assert response.status_code == 200
    rest_crawl = Crawl.objects.get(urls__contains="https://example.com/delete-after-rest")
    assert rest_crawl.config["DELETE_AFTER"] == "3h"
    assert rest_crawl.delete_at is not None
    assert run_due_crawl(rest_crawl, lock_seconds=10)
    rest_snapshot = rest_crawl.snapshot_set.get(url="https://example.com/delete-after-rest")
    assert rest_snapshot.delete_at is not None
