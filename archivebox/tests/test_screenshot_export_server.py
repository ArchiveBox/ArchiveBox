"""The real gallery server must serve unchanged recordings with byte ranges."""

from pathlib import Path
import shutil
import subprocess

import requests

from archivebox.tests.conftest import assert_port_open, cli_env, wait_for_log


def test_gallery_server_serves_recorded_wacz_ranges(initialized_archive, free_tcp_port):
    repo = Path(__file__).resolve().parents[2]
    exports = initialized_archive / "exports"
    exports.mkdir()
    fixture = Path(__file__).parent / "fixtures/memento/iframetest.wacz"
    shutil.copyfile(fixture, exports / "site.wacz")
    original = fixture.read_bytes()
    with (initialized_archive / "exports-server.log").open("w") as log:
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "--no-sync",
                "--project",
                str(repo),
                "python",
                str(repo / "bin/serve_ui_screenshot_exports.py"),
                str(free_tcp_port),
                "--directory",
                str(exports),
            ],
            cwd=initialized_archive,
            env=cli_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_log(initialized_archive / "exports-server.log", "Serving gallery exports on", timeout=10)
            assert_port_open("127.0.0.1", free_tcp_port)
            url = f"http://127.0.0.1:{free_tcp_port}/site.wacz"
            for header, status, expected in [(None, 200, original), ("bytes=0-63", 206, original[:64]), ("bytes=-64", 206, original[-64:])]:
                response = requests.get(url, headers={"Range": header} if header else {}, timeout=10)
                assert response.status_code == status
                assert response.content == expected
                assert response.headers["Accept-Ranges"] == "bytes"
            for header in [f"bytes={len(original)}-", f"bytes={len(original) + 100}-{len(original) + 200}"]:
                response = requests.get(url, headers={"Range": header}, timeout=10)
                assert response.status_code == 416
                assert response.headers["Content-Range"] == f"bytes */{len(original)}"
                assert not response.content
            head = requests.head(url, headers={"Range": "bytes=-64"}, timeout=10)
            assert head.status_code == 206 and head.headers["Content-Length"] == "64" and not head.content
            assert (exports / "site.wacz").read_bytes() == original
        finally:
            process.terminate()
            process.wait(timeout=10)
