"""Native export subprocesses retain the request's trace and registered Process."""

import gzip
import time
from pathlib import Path

import pytest
import requests
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from archivebox.tests.conftest import create_admin_and_token, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


@pytest.mark.parametrize("send_pii", [True, False])
def test_export_subprocess_continues_request_trace(initialized_archive, httpserver, free_tcp_port, send_pii):
    httpserver.expect_request("/api/1/envelope/", method="POST").respond_with_json({})
    httpserver.expect_request("/api/1/integration/otlp/v1/traces/", method="POST").respond_with_data(
        b"",
        content_type="application/x-protobuf",
    )
    run_archivebox_cmd(["install", "sentry"], cwd=initialized_archive, env={"SENTRY_ENABLED": "false"}, check=True, timeout=120)
    token = create_admin_and_token(initialized_archive)
    fixture = Path(__file__).parent / "fixtures/original-domain-replay/front.html.gz"
    run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            f"""
import gzip
from pathlib import Path
from archivebox.core.models import Snapshot, ArchiveResult
from archivebox.crawls.models import Crawl
crawl = Crawl.objects.create(urls='https://news.ycombinator.com/')
snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={{'PERMISSIONS': 'public'}})
body = gzip.decompress(Path({str(fixture)!r}).read_bytes())
output = snapshot.output_dir / 'dom/output.html'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(body)
ArchiveResult.objects.create(snapshot=snapshot, plugin='dom', status='succeeded', output_str='dom/output.html', output_files={{'dom/output.html': {{'size': len(body)}}}})
""",
        ],
        cwd=initialized_archive,
        check=True,
    )
    origin = f"http://localhost:{free_tcp_port}"
    server = start_archivebox_server(
        initialized_archive,
        port=free_tcp_port,
        env={
            "BASE_URL": origin,
            "SENTRY_ENABLED": "true",
            "SENTRY_DSN": httpserver.url_for("/1").replace("http://", "http://public@"),
            "SENTRY_TRACES_SAMPLE_RATE": "1",
            "SENTRY_SEND_DEFAULT_PII": str(send_pii),
        },
        log_name="sentry-export-server.log",
    )
    try:
        headers = {
            "X-ArchiveBox-API-Key": token,
            "X-Forwarded-For": "198.51.100.23",
            "baggage": "user.id=spoofed,user.email=spoofed,unexpected=secret",
        }
        response = requests.post(origin + "/api/v1/core/snapshots/export/html_zip", json={}, headers=headers, timeout=20)
        assert response.status_code == 202, response.text
        job = response.json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = requests.get(origin + job["status_url"], headers=headers, timeout=10)
            assert status.status_code == 200, status.text
            if status.json()["status"] == "exited":
                break
            time.sleep(0.1)
        assert status.json()["exit_code"] == 0, status.text
        download = requests.get(origin + job["download_url"], headers=headers, timeout=10)
        assert download.status_code == 200, download.text
        assert download.content.startswith(b"PK")
    finally:
        stop_archivebox_process(server)
    # Inspect the actual stored Process carrier after the authenticated request.
    # Arbitrary incoming HTTP baggage must never become subprocess identity.
    run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            f"from archivebox.machine.models import Process; "
            f"env = Process.objects.get(pk={job['id']!r}).env; "
            "assert 'spoofed' not in env.get('BAGGAGE', ''); assert 'secret' not in env.get('BAGGAGE', '')",
        ],
        cwd=initialized_archive,
        env={"SENTRY_ENABLED": "false"},
        check=True,
    )
    spans = []
    for request, _ in httpserver.log:
        if not request.path.endswith("/otlp/v1/traces/"):
            continue
        data = gzip.decompress(request.data) if request.headers.get("Content-Encoding") == "gzip" else request.data
        for resource in ExportTraceServiceRequest.FromString(data).resource_spans:
            for scope in resource.scope_spans:
                for span in scope.spans:
                    spans.append((span, {a.key: getattr(a.value, a.value.WhichOneof("value")) for a in span.attributes}))
    launch, launch_attrs = next((span, attrs) for span, attrs in spans if span.name == "site_export.launch")
    exported, attrs = next((span, attrs) for span, attrs in spans if span.name == "site_export")
    assert launch.trace_id == exported.trace_id, [
        (s.name, s.trace_id.hex(), s.span_id.hex(), s.parent_span_id.hex(), a)
        for s, a in spans
        if s.name in ("archivebox manage", "site_export", "site_export.launch")
    ]
    by_id = {span.span_id: span for span, _ in spans}
    cli = by_id[exported.parent_span_id]
    assert cli.name == "archivebox manage" and cli.parent_span_id == launch.span_id
    assert by_id[launch.parent_span_id].kind == 2
    assert attrs["process.id"] == job["id"] == launch_attrs["process.id"]
    assert attrs["process.parent_id"] == launch_attrs["process.parent_id"]
    assert attrs["process.pid"] != launch_attrs["process.pid"]
    if send_pii:
        assert attrs["user.id"] == launch_attrs["user.id"]
        assert attrs["user.name"] == "apitestadmin"
        assert attrs["user.email"] == "apitestadmin@example.com"
        assert attrs["user.ip_address"] == "198.51.100.23"
    else:
        assert not any(key.startswith("user.") or key == "client.address" for key in attrs)
    queries = [
        (span, data)
        for span, data in spans
        if span.trace_id == exported.trace_id
        and data.get("db.system") == "sqlite"
        and data.get("process.id") == job["id"]
        and data.get("process.pid") == attrs["process.pid"]
    ]
    assert queries
    for span, _ in queries:
        ancestor = span.parent_span_id
        seen = set()
        while ancestor != exported.span_id:
            assert ancestor and ancestor not in seen, span.name
            seen.add(ancestor)
            ancestor = by_id[ancestor].parent_span_id
    if send_pii:
        assert all(data["user.id"] == attrs["user.id"] for _, data in queries)


def test_disabled_export_context_never_imports_sdk(initialized_archive):
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import sys; from archivebox.plugins.discovery import get_subprocess_env; "
            "assert get_subprocess_env({'SENTRY_ENABLED': False}) == {}; "
            "assert not any(name.startswith(('sentry_sdk', 'opentelemetry')) for name in sys.modules)",
        ],
        cwd=initialized_archive,
        env={"SENTRY_ENABLED": "false"},
        check=True,
    )
    assert result.returncode == 0
