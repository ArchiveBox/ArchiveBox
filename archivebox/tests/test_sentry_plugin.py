"""Exercise optional monitoring through real collection commands and Django requests."""

import gzip
import json
from io import BytesIO

import pytest
import requests

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
)


@pytest.mark.parametrize("dsn", ["", "http://public@127.0.0.1:1/1"])
def test_sentry_disabled_never_imports_sdk(initialized_archive, dsn, free_tcp_port):
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import sys, asyncio; from django.apps import apps; from django.conf import settings; "
            "from abx_dl.orchestrator import create_bus; from archivebox.plugins.discovery import get_plugin_catalog; "
            "bus = create_bus(config=settings.CONFIG.model_dump(mode='json'), catalog=get_plugin_catalog()); "
            "assert not bus.middlewares; asyncio.run(bus.destroy()); "
            "assert apps.get_app_config('abx_sentry').name == 'abx_plugins.plugins.sentry'; "
            "assert 'abx_plugins.plugins.sentry.runtime' not in sys.modules; "
            "assert not any(name.startswith(('sentry_sdk', 'opentelemetry')) for name in sys.modules); "
            "print('SENTRY_DISABLED_OK')",
        ],
        cwd=initialized_archive,
        env={"SENTRY_ENABLED": "false", "SENTRY_DSN": dsn},
        check=True,
    )
    assert "SENTRY_DISABLED_OK" in result.stdout
    server = start_archivebox_server(initialized_archive, port=free_tcp_port, env={"SENTRY_ENABLED": "false", "SENTRY_DSN": dsn})
    try:
        response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
        assert response.status_code == 200
        assert "sentry-config" not in response.text
        assert "sentry-cdn.com" not in response.text
    finally:
        stop_archivebox_process(server)


def test_sentry_sends_logging_and_django_errors(initialized_archive, httpserver, free_tcp_port):
    httpserver.expect_request("/api/1/envelope/", method="POST").respond_with_json({})
    env = {"SENTRY_ENABLED": "false"}
    install = run_archivebox_cmd(
        ["install", "sentry"],
        cwd=initialized_archive,
        env=env,
        timeout=120,
        check=True,
    )
    assert install.returncode == 0
    dsn = httpserver.url_for("/1").replace("http://", "http://public@")
    run_archivebox_cmd(
        [
            "config",
            "--set",
            "SENTRY_ENABLED=True",
            f"SENTRY_DSN={dsn}",
            "SENTRY_ENVIRONMENT=plugin-test",
            "SENTRY_RELEASE=plugin-test@1",
            "SENTRY_ENABLE_LOGS=True",
            "SENTRY_ENABLE_METRICS=True",
            "SENTRY_TRACES_SAMPLE_RATE=1",
        ],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    server = start_archivebox_server(initialized_archive, port=free_tcp_port, env={"DEBUG": "False"})
    try:
        response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
        assert response.status_code == 200
        assert "bundle.tracing.logs.metrics.min.js" in response.text
        assert "bundle.tracing.replay" not in response.text
        assert "replaysOnErrorSampleRate: 0" in response.text
        assert "&lt;script" not in response.text
    finally:
        stop_archivebox_process(server)
    # A broken custom template is a real request-time failure in a supported
    # collection customization, not a test-only view or fabricated exception.
    template = initialized_archive / "custom_templates" / "admin" / "login.html"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("{% sentry_acceptance_invalid_tag %}")
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import logging, sentry_sdk; "
            "client = sentry_sdk.get_client(); assert client.is_active(); "
            "assert 'django' in client.integrations; "
            "assert client.options['send_default_pii'] is False; "
            "assert client.options['include_local_variables'] is False; "
            "assert client.options['max_request_body_size'] == 'never'; "
            "assert client.options['enable_metrics'] is True; "
            "logging.getLogger('archivebox.sentry_test').warning('Sentry breadcrumb acceptance'); "
            "logging.getLogger('archivebox.sentry_test').error('Sentry logging acceptance'); "
            "sentry_sdk.flush(timeout=10); print('SENTRY_ENABLED_OK')",
        ],
        cwd=initialized_archive,
        env={"DEBUG": "False"},
        check=True,
    )
    assert "SENTRY_ENABLED_OK" in result.stdout
    # This goes through ArchiveBox's real embedded EventBus, including native
    # package requests and database projections, with persisted config only.
    run_archivebox_cmd(["install", "sentry"], cwd=initialized_archive, check=True, timeout=120)
    server = start_archivebox_server(
        initialized_archive,
        port=free_tcp_port,
        env={"DEBUG": "False", "SEARCH_BACKEND_SONIC_ENABLED": "False"},
        log_name="sentry-server.log",
    )
    try:
        response = requests.get(
            f"http://127.0.0.1:{free_tcp_port}/admin/login/",
            headers={"Host": "localhost", "Authorization": "Bearer sentry-private-authorization"},
            data="sentry-private-request-body",
            timeout=10,
        )
        assert response.status_code == 500
    finally:
        stop_archivebox_process(server)
    items = []
    for request, response in httpserver.log:
        assert response.status_code == 200
        data = request.data
        if request.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        envelope = BytesIO(data)
        json.loads(envelope.readline())
        while header := envelope.readline():
            metadata = json.loads(header)
            payload = json.loads(envelope.read(metadata["length"]))
            envelope.readline()
            items.append((metadata["type"], payload))
    events = [payload for kind, payload in items if kind == "event"]
    logged = next(event for event in events if event.get("logger") == "archivebox.sentry_test")
    assert logged["logentry"]["formatted"] == "Sentry logging acceptance"
    assert logged["environment"] == "plugin-test"
    assert logged["release"] == "plugin-test@1"
    assert any(crumb["message"] == "Sentry breadcrumb acceptance" for crumb in logged["breadcrumbs"]["values"])
    failure = next(event for event in events if event.get("exception"))
    assert failure["exception"]["values"][-1]["type"] == "TemplateSyntaxError"
    assert failure["request"]["url"].endswith("/admin/login/")
    assert failure["request"]["data"] == ""
    assert "sentry-private-request-body" not in json.dumps(items)
    assert "sentry-private-authorization" not in json.dumps(items)
    assert all("vars" not in frame for exc in failure["exception"]["values"] for frame in exc["stacktrace"]["frames"])
    logs = [item for kind, payload in items if kind == "log" for item in payload["items"]]
    assert any(item["body"] == "Sentry logging acceptance" for item in logs)
    transactions = [payload for kind, payload in items if kind == "transaction"]
    install_trace = next(item for item in transactions if item["transaction"] == "ArchiveBox_install.emit(InstallEvent)")
    assert install_trace["contexts"]["otel"]["attributes"]["abxbus.event_type"] == "InstallEvent"
    assert install_trace["contexts"]["otel"]["attributes"]["abxbus.event_bus.name"] == "ArchiveBox_install"
    assert any("BinaryRequestEvent" in item["transaction"] for item in transactions)
    assert any("admin/login" in item["transaction"] for item in transactions), sorted({item["transaction"] for item in transactions})
    metrics = [item for kind, payload in items if kind == "trace_metric" for item in payload["items"]]
    assert any(item["name"] == "archivebox.spans" for item in metrics)
    assert any(item["name"] == "archivebox.span.duration" for item in metrics)
