import datetime
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from archivebox.tests.conftest import cli_env, wait_for_log


def test_plugin_preview_access_logs_remain_quiet_without_hiding_errors():
    import logging
    from archivebox.misc.monkey_patches import ModifiedAccessLogGenerator

    stream = io.StringIO()
    logger = logging.getLogger("django.server")
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        daphne = ModifiedAccessLogGenerator(stream)
        for path in (
            "/api/v1/core/snapshot/0123456789abcdef0123456789abcdef/screencast.jpg?after=1",
            "/api/v1/crawls/crawl/0123456789abcdef0123456789abcdef/files/chrome_screencast/latest.jpg",
        ):
            for status in (200, 404):
                logger.info('"GET %s HTTP/1.1" %s 0', path, status)
                daphne.write_entry(host="localhost", date=datetime.datetime.now(), request=f"GET {path}", status=status)
            assert stream.getvalue() == ""
            logger.error('"GET %s HTTP/1.1" 500 0', path)
            assert path in stream.getvalue() and "500" in stream.getvalue()
            stream.seek(0)
            stream.truncate()
    finally:
        logger.removeHandler(handler)


def test_daphne_access_log_redacts_sensitive_query_params():
    from archivebox.misc.monkey_patches import ModifiedAccessLogGenerator

    stream = io.StringIO()
    logger = ModifiedAccessLogGenerator(stream)

    logger.write_entry(
        host="127.0.0.1:54321",
        date=datetime.datetime(2026, 5, 29, 12, 0, 0),
        request="GET /api/v1/crawls/crawl/a1000000-0000-0000-0000-00000003cea2?api_key=d837c273f6e8f4950e706ebd67d95889&limit=1",
        status=200,
    )

    output = stream.getvalue()
    assert "api_key=[REDACTED]" in output
    assert "d837c273f6e8f4950e706ebd67d95889" not in output
    assert "limit=1" in output


def test_daphne_access_log_accepts_unix_socket_client(initialized_archive):
    with tempfile.TemporaryDirectory(prefix="abx-access-", dir="/tmp") as socket_dir:
        socket_path = Path(socket_dir) / "http.sock"
        log_path = initialized_archive / "daphne.log"
        access_path = initialized_archive / "access.log"
        with log_path.open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "daphne",
                    "--endpoint",
                    f"unix:{socket_path}",
                    "--endpoint",
                    "tcp:port=0:interface=127.0.0.1",
                    "--access-log",
                    str(access_path),
                    "archivebox.core.asgi:application",
                ],
                cwd=initialized_archive,
                env=cli_env(ALLOWED_HOSTS="*", BASE_URL="http://localhost"),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for_log(log_path, "Listening on TCP address")
                response = subprocess.run(
                    [
                        "curl",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--unix-socket",
                        str(socket_path),
                        "http://localhost/api/v1/docs?token=access-log-test-secret",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                assert response.returncode == 0, response.stderr
                assert "<html" in response.stdout.lower()
            finally:
                server.terminate()
                server.wait(timeout=15)
        access_log = access_path.read_text()
        assert "GET /api/v1/docs?token=[REDACTED] 200 -\n" in access_log, log_path.read_text()
        assert "access-log-test-secret" not in access_log
        assert "Traceback" not in log_path.read_text()
