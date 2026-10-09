"""A failed optional dependency must not stop unrelated real captures."""

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.machine.models import Process
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_add_preserves_failed_dependency_and_captures_healthy_plugin(initialized_archive, tmp_path, httpserver):
    missing_binary = tmp_path / "missing-yt-dlp"
    env = cli_env(YTDLP_BINARY=str(missing_binary))
    installed = run_archivebox_cmd(["install", "ytdlp"], cwd=initialized_archive, env=env)
    assert installed.returncode != 0
    assert "BinaryInstallError:" in installed.stderr
    assert missing_binary.name in installed.stderr
    content = "<html><body>Healthy ArchiveBox capture despite missing yt-dlp.</body></html>"
    httpserver.expect_request("/index.html").respond_with_data(content, content_type="text/html")
    result = run_archivebox_cmd(
        ["add", "--plugins=ytdlp,wget", httpserver.url_for("/index.html")],
        cwd=initialized_archive,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        failed_hook = ArchiveResult.objects.get(snapshot=snapshot, plugin="ytdlp")
        assert failed_hook.status == ArchiveResult.StatusChoices.FAILED
        assert failed_hook.process.exit_code == 1
        assert failed_hook.process.status == Process.StatusChoices.EXITED
        assert failed_hook.process.ended_at is not None
        assert str(missing_binary) in failed_hook.process.stderr
        wget = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget")
        assert wget.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert wget.process.exit_code == 0
        assert (snapshot.output_dir / wget.output_str).read_text() == content
        installs = Process.objects.filter(process_type=Process.TypeChoices.BINARY, binary__name="missing-yt-dlp")
        assert installs.exists()
        assert all(process.status == Process.StatusChoices.EXITED and process.exit_code == 1 and process.ended_at for process in installs)
