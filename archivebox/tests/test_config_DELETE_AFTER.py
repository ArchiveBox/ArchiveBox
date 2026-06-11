import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from archivebox.tests.conftest import run_archivebox_cmd, run_queued_crawls, cli_env


pytestmark = pytest.mark.django_db(transaction=True)

ADMIN_HOST = "admin.archivebox.localhost:8000"
API_HOST = "api.archivebox.localhost:8000"


def test_delete_after_real_cli_and_orchestrator_paths_cover_all_retained_models(tmp_path):
    env = cli_env(disable_extractors=True)
    _cmd_result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, timeout=90)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr

    run_env = {
        **env,
        "DELETE_AFTER": "1hr",
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
    }
    url = "https://example.com/delete-after-cli"
    _cmd_result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", url],
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
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.machine.models import Machine, NetworkInterface, Process

snapshot = Snapshot.objects.select_related("crawl").get(id="{created["snapshot_id"]}")
crawl = snapshot.crawl
if snapshot.status == snapshot.StatusChoices.QUEUED:
    snapshot.sm.tick()
    snapshot.refresh_from_db()
if snapshot.status == snapshot.StatusChoices.STARTED:
    snapshot.sm.seal()
    snapshot.refresh_from_db()
crawl.refresh_from_db()
if crawl.status == crawl.StatusChoices.QUEUED:
    crawl.sm.tick()
    crawl.refresh_from_db()
if crawl.status == crawl.StatusChoices.STARTED:
    crawl.sm.seal()
    crawl.refresh_from_db()
if snapshot.status != snapshot.StatusChoices.SEALED or crawl.status != crawl.StatusChoices.SEALED:
    raise RuntimeError(f"expected sealed snapshot/crawl, got {{snapshot.status}}/{{crawl.status}}")

Path(crawl.output_dir).mkdir(parents=True, exist_ok=True)
Path(snapshot.output_dir).mkdir(parents=True, exist_ok=True)
(Path(crawl.output_dir) / "crawl-retention.txt").write_text("crawl")
(Path(snapshot.output_dir) / "snapshot-retention.txt").write_text("snapshot")

result = ArchiveResult.objects.create(
    snapshot=snapshot,
    plugin="title",
    hook_name="on_Snapshot__54_title.py",
    status=ArchiveResult.StatusChoices.SUCCEEDED,
)
Path(result.output_dir).mkdir(parents=True, exist_ok=True)
(Path(result.output_dir) / "title.txt").write_text("Example")

machine = Machine.current()
iface = NetworkInterface.objects.filter(machine=machine).first()
if iface is None:
    iface = NetworkInterface.objects.create(
        machine=machine,
        mac_address="00:00:00:00:00:00",
        ip_public="203.0.113.10",
        ip_local="127.0.0.1",
        dns_server="1.1.1.1",
        hostname=machine.hostname,
        iface="lo",
        isp="Test ISP",
        city="Test City",
        region="Test Region",
        country="Test Country",
    )
process = Process.objects.create(
    machine=machine,
    iface=iface,
    process_type=Process.TypeChoices.HOOK,
    pwd=str(result.output_dir),
    cmd=["echo", "ok"],
    env={{"DELETE_AFTER": "1hr"}},
    status=Process.StatusChoices.EXITED,
)

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
    ui_snapshot = ui_crawl.snapshot_set.filter(url="https://example.com/delete-after-ui").first()
    if ui_snapshot is None:
        ui_internal_snapshot = ui_crawl.snapshot_set.get(url="archivebox://internal")
        assert ui_internal_snapshot.output_dir.joinpath("staticfile", "stdin.txt").read_text() == "https://example.com/delete-after-ui"
        ui_snapshot = ui_crawl.create_discovered_snapshot(
            ui_internal_snapshot,
            url="https://example.com/delete-after-ui",
            depth=1,
        )
    assert ui_snapshot is not None
    assert ui_snapshot.delete_at is not None

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
    rest_snapshot = rest_crawl.snapshot_set.filter(url="https://example.com/delete-after-rest").first()
    if rest_snapshot is None:
        rest_snapshot = rest_crawl.create_discovered_snapshot(
            rest_crawl.snapshot_set.get(url="archivebox://internal"),
            url="https://example.com/delete-after-rest",
            depth=1,
        )
    assert rest_snapshot is not None
    assert rest_snapshot.delete_at is not None
