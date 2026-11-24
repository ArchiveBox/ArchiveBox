"""Exercise optional monitoring through real collection commands and Django requests."""

import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from io import BytesIO
from datetime import datetime, timezone
from uuid import UUID
from importlib.metadata import version

import pytest
import requests
from playwright.sync_api import expect, sync_playwright
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    create_admin_and_token,
    start_archivebox_server,
    stop_archivebox_process,
)


def test_standalone_bus_ignores_sentry_configuration():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, asyncio; from abx_dl.orchestrator import create_bus; "
            "from abx_dl.catalog import PluginCatalog; assert 'sentry' not in PluginCatalog.discover(runtime='abx-dl'); "
            "bus = create_bus(); assert not bus.middlewares; asyncio.run(bus.destroy()); "
            "assert 'abx_plugins.plugins.sentry.runtime' not in sys.modules; "
            "assert not any(n.startswith(('sentry_sdk', 'opentelemetry')) for n in sys.modules)",
        ],
        env={**os.environ, "SENTRY_ENABLED": "true", "SENTRY_DSN": "http://public@127.0.0.1:1/1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_sentry_settings_are_machine_only(initialized_archive, browser_runtime, free_tcp_port):
    run_archivebox_cmd(
        ["config", "--set", f"BASE_URL=http://localhost:{free_tcp_port}"],
        cwd=initialized_archive,
        check=True,
    )
    create_admin_and_token(initialized_archive)
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            """
import json
from archivebox.config.common import ArchiveBoxConfig, get_config, host_config_keys
from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
persona = Persona.objects.create(name='Sentry scope', config={'SENTRY_ENABLED': True, 'SENTRY_ENVIRONMENT': 'persona-override'})
keys = {key for key in ArchiveBoxConfig.model_fields if key.startswith('SENTRY_')}
assert keys and keys <= host_config_keys()
assert all(ArchiveBoxConfig.scope_for_key(key) == 'server' for key in keys)
assert not keys & ArchiveBoxConfig._crawl_frozen_keys()
assert not keys & ArchiveBoxConfig._crawl_runtime_keys()
assert get_config(persona=persona).SENTRY_ENABLED is False
assert get_config(persona=persona).SENTRY_ENVIRONMENT != 'persona-override'
print(json.dumps({'persona': str(persona.pk), 'machine': str(Machine.current().pk)}))
""",
        ],
        cwd=initialized_archive,
        check=True,
    )
    ids = json.loads(result.stdout.splitlines()[-1])
    server = start_archivebox_server(initialized_archive, port=free_tcp_port, log_name="sentry-settings-server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page()
            origin = f"http://localhost:{free_tcp_port}"
            page.goto(origin + "/admin/login/")
            page.locator("#id_username").fill("apitestadmin")
            page.locator("#id_password").fill("testpass123")
            page.locator('input[type="submit"]').click()
            page.wait_for_url(origin + "/admin/")
            for path in ("/add/", f"/admin/personas/persona/{ids['persona']}/change/"):
                page.goto(origin + path)
                expect(page.locator("#plugin-settings")).to_be_visible()
                expect(page.locator('[role="tab"][data-plugin="sentry"]')).to_have_count(0)
                expect(page.locator('[data-config-key^="SENTRY_"][name]')).to_have_count(0)
            page.goto(origin + f"/admin/machine/machine/{ids['machine']}/change/")
            page.locator('[role="tab"][data-plugin="sentry"]').click()
            expect(page.locator('[data-config-key="SENTRY_ENVIRONMENT"][name]')).to_be_visible()
            browser.close()
    finally:
        stop_archivebox_process(server)


@pytest.mark.parametrize("dsn", ["", "http://public@127.0.0.1:1/1"])
def test_sentry_disabled_never_imports_sdk(initialized_archive, dsn, free_tcp_port):
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import sys, asyncio; from django.apps import apps; from django.conf import settings; "
            "from archivebox.workers.runner import create_bus; "
            "from archivebox.core.asgi import application; "
            "bus = create_bus(config=settings.CONFIG); "
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


def test_sentry_asgi_transport_cancellation(initialized_archive, httpserver):
    httpserver.expect_request("/api/1/envelope/", method="POST").respond_with_json({})
    httpserver.expect_request("/api/1/integration/otlp/v1/traces/", method="POST").respond_with_data(
        b"",
        content_type="application/x-protobuf",
    )
    run_archivebox_cmd(["install", "sentry"], cwd=initialized_archive, env={"SENTRY_ENABLED": "false"}, timeout=120, check=True)
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            """
import asyncio, gc, json, logging
from asgiref.testing import ApplicationCommunicator
from archivebox.core.asgi import application
from archivebox.workers.request_activity import request_activity
from opentelemetry.trace import get_current_span

scope = {
    'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
    'method': 'GET', 'scheme': 'http', 'path': '/health/', 'raw_path': b'/health/',
    'query_string': b'', 'headers': [(b'host', b'localhost')],
    'server': ('127.0.0.1', 80), 'client': ('127.0.0.1', 12345),
}
records = []
class ObserveContextErrors(logging.Handler):
    def emit(self, record):
        records.append(record)
logging.getLogger('opentelemetry.context').addHandler(ObserveContextErrors())

async def run():
    caller_context = get_current_span().get_span_context()
    assert caller_context.is_valid
    # Real Django waits for an HTTP body before constructing the request.
    for cancel in (False, True):
        client = ApplicationCommunicator(application, dict(scope))
        assert not client.future.done()
        await asyncio.sleep(0)
        assert sum(request_activity().values()) == 1
        if cancel:
            client.future.cancel()
        else:
            await client.send_input({'type': 'http.disconnect'})
        await client.wait(timeout=5)
        assert client.output_queue.empty()
        assert sum(request_activity().values()) == 0

    spans = []
    for cancel in (False, True):
        incoming = asyncio.Queue()
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def send(message):
            if message['type'] == 'http.response.body':
                span = get_current_span()
                assert span.is_recording(), 'request span ended before transport delivery'
                spans.append(span)
                entered.set()
                await release.wait()
            messages.append(message)
        task = asyncio.create_task(application(dict(scope), incoming.get, send))
        await incoming.put({'type': 'http.request', 'body': b'', 'more_body': False})
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert spans[-1].is_recording()
            assert messages[0]['status'] == 200
        finally:
            if cancel:
                task.cancel()
                try:
                    await asyncio.wait_for(task, 5)
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError('request cancellation was swallowed')
            else:
                release.set()
                await asyncio.wait_for(task, 5)
        assert not spans[-1].is_recording()
        assert sum(request_activity().values()) == 0
        assert get_current_span().get_span_context() == caller_context
        if not cancel:
            assert b'OK' in b''.join(m.get('body', b'') for m in messages)
    gc.collect()
    assert not records, [(r.getMessage(), str(r.exc_info)) for r in records]
    return [format(span.get_span_context().span_id, '016x') for span in spans]

ids = asyncio.run(run())
print(json.dumps(ids))
""",
        ],
        cwd=initialized_archive,
        env={
            "SENTRY_ENABLED": "true",
            "SENTRY_DSN": httpserver.url_for("/1").replace("http://", "http://public@"),
            "SENTRY_TRACES_SAMPLE_RATE": "1",
        },
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = set(json.loads(result.stdout.splitlines()[-1]))
    spans = []
    for request, response in httpserver.log:
        assert response.status_code == 200
        if request.path.endswith("/otlp/v1/traces/"):
            data = gzip.decompress(request.data) if request.headers.get("Content-Encoding") == "gzip" else request.data
            spans.extend(
                span
                for resource in ExportTraceServiceRequest.FromString(data).resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            )
    # Direct ASGI calls inherit the real manage-command span. Verify restoration
    # and native HTTP child spans; network requests are checked separately below.
    command_span = next(span for span in spans if span.name == "archivebox manage")
    server_spans = [span for span in spans if any(attr.key == "http.method" for attr in span.attributes)]
    assert len(server_spans) == 4  # Both pre-body disconnects and both real responses.
    assert expected <= {span.span_id.hex() for span in server_spans}
    body_spans = [span for span in server_spans if span.span_id.hex() in expected]
    disconnected_spans = [span for span in server_spans if span.span_id.hex() not in expected]
    assert len({span.trace_id for span in disconnected_spans}) == 2
    assert all(not span.parent_span_id and span.kind == 2 for span in disconnected_spans)
    assert all(span.parent_span_id == command_span.span_id and span.trace_id == command_span.trace_id for span in body_spans)
    assert all(span.end_time_unix_nano > span.start_time_unix_nano for span in server_spans)


def test_sentry_sends_logging_and_django_errors(initialized_archive, httpserver, free_tcp_port, recursive_test_site, browser_runtime):
    httpserver.expect_request("/api/1/envelope/", method="POST").respond_with_json({}, headers={"Access-Control-Allow-Origin": "*"})
    httpserver.expect_request("/api/1/integration/otlp/v1/traces/", method="POST").respond_with_data(
        b"",
        content_type="application/x-protobuf",
    )
    env = {"SENTRY_ENABLED": "false"}
    install = run_archivebox_cmd(
        ["install", "sentry"],
        cwd=initialized_archive,
        env=env,
        timeout=120,
        check=True,
    )
    assert install.returncode == 0
    create_admin_and_token(initialized_archive)
    dsn = httpserver.url_for("/1").replace("http://", "http://public@")
    run_archivebox_cmd(
        [
            "config",
            "--set",
            "SENTRY_ENABLED=True",
            f"SENTRY_DSN={dsn}",
            "SENTRY_ENVIRONMENT=plugin-test",
            "SENTRY_RELEASE=",
            "SENTRY_ENABLE_LOGS=True",
            "SENTRY_ENABLE_METRICS=True",
            "SENTRY_TRACES_SAMPLE_RATE=1",
            "SENTRY_PROFILE_SESSION_SAMPLE_RATE=1",
        ],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    installed_release = f"archivebox@{version('archivebox')}"
    server = start_archivebox_server(initialized_archive, port=free_tcp_port, env={"DEBUG": "False", "WEB_CONCURRENCY": "2"})
    try:
        response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
        assert response.status_code == 200
        assert "bundle.tracing.logs.metrics.min.js" in response.text
        assert "bundle.tracing.replay" not in response.text
        assert "replaysOnErrorSampleRate: 0" in response.text
        assert "&lt;script" not in response.text
        browser_config = json.loads(re.search(r'<script id="sentry-config" type="application/json">(.*?)</script>', response.text).group(1))
        assert browser_config["release"] == installed_release
        # Continuous profiling publishes native 60-second chunks. Keep a real
        # request workload alive through that interval instead of altering SDK
        # internals or forcing a test-only profiler flush.
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
            assert response.status_code == 200
            time.sleep(1)
        run_archivebox_cmd(
            ["config", "--set", "SENTRY_RELEASE=plugin-test@1"],
            cwd=initialized_archive,
            env=env,
            check=True,
        )
        capture = run_archivebox_cmd(
            # Two completions in one worker exercise its persistent completion queue:
            # the second write must not inherit the first event's trace context.
            ["add", "--plugins=wget", recursive_test_site["root_url"], recursive_test_site["root_url"] + "about"],
            cwd=initialized_archive,
            check=True,
            timeout=120,
        )
        (initialized_archive / "sentry-capture.log").write_text(capture.stdout + capture.stderr)
        # The already-running worker reads machine config, not the environment
        # of this separate CLI process. Exercise a real invalid wget setting.
        run_archivebox_cmd(
            ["config", "--set", 'WGET_ARGS_EXTRA=["--timeout=invalid"]'],
            cwd=initialized_archive,
            check=True,
        )
        failed_capture = run_archivebox_cmd(
            ["add", "--plugins=wget", recursive_test_site["root_url"] + "missing-sentry-acceptance-page"],
            cwd=initialized_archive,
            timeout=120,
        )
        (initialized_archive / "sentry-failed-capture.log").write_text(failed_capture.stdout + failed_capture.stderr)
        run_archivebox_cmd(["config", "--set", "WGET_ARGS_EXTRA=[]"], cwd=initialized_archive, check=True)
    finally:
        stop_archivebox_process(server)
    # A plugin-owned head template must not take down the host's login page.
    head_template = initialized_archive / "custom_templates" / "sentry" / "head.html"
    head_template.parent.mkdir(parents=True, exist_ok=True)
    head_template.write_text("{% sentry_head_invalid_tag %}")
    server = start_archivebox_server(
        initialized_archive,
        port=free_tcp_port,
        env={"DEBUG": "False"},
        log_name="sentry-head-server.log",
    )
    try:
        response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
        assert response.status_code == 200
        assert "sentry-config" not in response.text
    finally:
        stop_archivebox_process(server)
        head_template.unlink()
    crawl_check = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            """
import asyncio
from django.contrib.auth import get_user_model
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.workers.runner import CrawlRunner

user, _ = get_user_model().objects.get_or_create(username='sentry-acceptance')
for enabled in [False, True]:
    persona = Persona.objects.create(name=f'sentry-{enabled}', config={'SENTRY_ENABLED': enabled})
    crawl = Crawl.objects.create(urls='', created_by=user, persona=persona, config={'PLUGINS': 'wget'})
    runner = CrawlRunner(crawl, show_progress=False, wait_for_resources=False)
    asyncio.run(runner.run())
    # Monitoring is machine-owned; stale persona flags cannot change it.
    assert runner.base_config.SENTRY_ENABLED is True
    assert len(runner.bus.middlewares) == 1, (enabled, runner.bus.middlewares)
""",
        ],
        cwd=initialized_archive,
    )
    assert crawl_check.returncode == 0, crawl_check.stdout + crawl_check.stderr
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
            "assert client.options['profile_session_sample_rate'] == 1; "
            "assert client.options['profile_lifecycle'] == 'manual'; "
            "logging.getLogger('archivebox.sentry_test').warning('Sentry breadcrumb acceptance'); "
            "logging.getLogger('archivebox.sentry_test').error('Sentry logging acceptance'); "
            "sentry_sdk.flush(timeout=10); print('SENTRY_ENABLED_OK')",
        ],
        cwd=initialized_archive,
        env={"DEBUG": "False"},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
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
    template.unlink()
    run_archivebox_cmd(
        ["config", "--set", "SENTRY_SEND_DEFAULT_PII=True"],
        cwd=initialized_archive,
        env={"SENTRY_ENABLED": "false"},
        check=True,
    )
    with sqlite3.connect(initialized_archive / "index.sqlite3") as database:
        replay_snapshot_id, replay_crawl_id, replay_path = database.execute(
            "SELECT s.id, s.crawl_id, a.output_str FROM core_snapshot s "
            "JOIN core_archiveresult a ON a.snapshot_id = s.id "
            "WHERE s.url = ? AND a.plugin = 'wget' AND a.status = 'succeeded'",
            (recursive_test_site["root_url"],),
        ).fetchone()
    server = start_archivebox_server(initialized_archive, port=free_tcp_port, log_name="sentry-user-server.log")
    try:
        origin = f"http://localhost:{free_tcp_port}"
        with requests.Session() as session:
            login = session.get(f"{origin}/admin/login/", timeout=10)
            assert login.status_code == 200
            assert '"user": null' in login.text
            csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text).group(1)
            logged_in = session.post(
                f"{origin}/admin/login/",
                data={"csrfmiddlewaretoken": csrf, "username": "apitestadmin", "password": "testpass123", "next": "/admin/core/snapshot/"},
                headers={"Referer": f"{origin}/admin/login/"},
                allow_redirects=False,
                timeout=10,
            )
            assert logged_in.status_code == 302, logged_in.text
            page = session.get(f"{origin}/admin/core/snapshot/", timeout=10)
            assert page.status_code == 200, page.text
            browser_config = json.loads(re.search(r'<script id="sentry-config" type="application/json">(.*?)</script>', page.text).group(1))
            assert browser_config["user"]["username"] == "apitestadmin"
            assert browser_config["user"]["email"] == "apitestadmin@example.com"
            assert browser_config["release"] == "plugin-test@1"
            user_id = browser_config["user"]["id"]
            replay = session.get(f"{origin}/snapshot/{replay_snapshot_id}/{replay_path}", timeout=10)
            assert replay.status_code == 200, replay.text
            assert "<title>Root</title>" in replay.text
        anonymous = requests.get(f"{origin}/admin/login/", timeout=10)
        assert anonymous.status_code == 200
        assert '"user": null' in anonymous.text
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page()
            page.goto(f"{origin}/admin/login/")
            page.locator("#id_username").fill("apitestadmin")
            page.locator("#id_password").fill("testpass123")
            page.locator('input[type="submit"]').click()
            page.wait_for_url(f"{origin}/admin/")
            page.goto(f"{origin}/admin/core/snapshot/")
            for _ in range(2):
                with page.expect_response(lambda response: "/progress.json" in response.url) as poll:
                    pass
                assert poll.value.status == 200
            assert page.evaluate("Sentry.getIsolationScope().getUser().id") == user_id
            assert page.evaluate("Sentry.flush(10000)") is True
            browser.close()
    finally:
        stop_archivebox_process(server)
    items = []
    spans = []
    for request, response in httpserver.log:
        assert response.status_code == 200
        data = request.data
        if request.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        if request.path.endswith("/otlp/v1/traces/"):
            batch = ExportTraceServiceRequest.FromString(data)
            for resource in batch.resource_spans:
                resource_attributes = {a.key: getattr(a.value, a.value.WhichOneof("value")) for a in resource.resource.attributes}
                assert resource_attributes["service.name"] == "archivebox"
                assert resource_attributes["deployment.environment.name"] == "plugin-test"
                for scope in resource.scope_spans:
                    for span in scope.spans:
                        spans.append(
                            {
                                "name": span.name,
                                "trace_id": span.trace_id.hex(),
                                "span_id": span.span_id.hex(),
                                "parent_span_id": span.parent_span_id.hex(),
                                "kind": span.kind,
                                "start_time_unix_nano": span.start_time_unix_nano,
                                "end_time_unix_nano": span.end_time_unix_nano,
                                "scope": scope.scope.name,
                                "resource": resource_attributes,
                                "attributes": {a.key: getattr(a.value, a.value.WhichOneof("value")) for a in span.attributes},
                            },
                        )
            continue
        envelope = BytesIO(data)
        json.loads(envelope.readline())
        while header := envelope.readline():
            metadata = json.loads(header)
            if "length" in metadata:
                payload = json.loads(envelope.read(metadata["length"]))
                envelope.readline()
            else:
                payload = json.loads(envelope.readline())
            items.append((metadata["type"], payload))
    events = [payload for kind, payload in items if kind == "event"]
    (initialized_archive / "sentry-envelopes.json").write_text(json.dumps(items))
    (initialized_archive / "sentry-otlp-spans.json").write_text(json.dumps(spans))
    # Compare exported identities with rows written by the real capture, not
    # just with other telemetry that could repeat the same incorrect identity.
    with sqlite3.connect(initialized_archive / "index.sqlite3") as database:
        database.row_factory = sqlite3.Row
        processes = {
            row["id"]: dict(row)
            for row in database.execute(
                "SELECT id, parent_id, process_type, worker_type, pid, status, started_at, ended_at, exit_code FROM machine_process",
            )
        }
        snapshot_rows = list(database.execute("SELECT id, crawl_id, url FROM core_snapshot"))
        snapshots = {row["id"]: row["crawl_id"] for row in snapshot_rows}
        snapshot_urls = {row["id"]: row["url"] for row in snapshot_rows}
    logged = next(event for event in events if event.get("logger") == "archivebox.sentry_test")
    hook_failures = [event for event in events if event.get("tags", {}).get("plugin.name") == "wget"]
    # A runner takeover can also terminate a real in-flight hook. Select the
    # invalid-arguments exit independently of the stderr assertion below.
    hook_failure = next(event for event in hook_failures if event["contexts"]["hook"]["exit_code"] == 1)
    assert hook_failure["level"] == "error"
    assert hook_failure["contexts"]["hook"]["exit_code"] != 0
    assert "invalid time period" in hook_failure["contexts"]["hook"]["stderr"].lower()
    assert logged["logentry"]["formatted"] == "Sentry logging acceptance"
    assert logged["environment"] == "plugin-test"
    assert logged["release"] == "plugin-test@1"
    assert any(crumb["message"] == "Sentry breadcrumb acceptance" for crumb in logged["breadcrumbs"]["values"])
    head_failure = next(event for event in events if event.get("logger") == "archivebox.core.templatetags.core_tags")
    assert head_failure["logentry"]["formatted"] == "Unable to render plugin page head: abx_plugins.plugins.sentry"
    assert head_failure["exception"]["values"][-1]["type"] == "TemplateSyntaxError"
    failure = next(event for event in events if "sentry_acceptance_invalid_tag" in str(event.get("exception", "")))
    assert failure["exception"]["values"][-1]["type"] == "TemplateSyntaxError"
    assert failure["request"]["url"].endswith("/admin/login/")
    assert failure["request"]["data"] == ""
    assert "sentry-private-request-body" not in json.dumps(items)
    assert "sentry-private-authorization" not in json.dumps(items)
    assert all("vars" not in frame for exc in failure["exception"]["values"] for frame in exc["stacktrace"]["frames"])
    logs = [item for kind, payload in items if kind == "log" for item in payload["items"]]
    assert any(item["body"] == "Sentry logging acceptance" for item in logs)
    head_log = next(item for item in logs if item["body"] == "Unable to render plugin page head: abx_plugins.plugins.sentry")
    assert head_log["trace_id"] == head_failure["contexts"]["trace"]["trace_id"]
    hook_logs = [item for item in logs if item["attributes"].get("plugin.name", {}).get("value") == "wget"]
    assert any(
        item["attributes"].get("process.stream", {}).get("value") == "stdout" and "wget download started" in item["body"]
        for item in hook_logs
    ), hook_logs
    assert any(
        item["attributes"].get("process.stream", {}).get("value") == "stderr" and "saving page with wget" in item["body"]
        for item in hook_logs
    )
    assert any(item["attributes"].get("process.exit_code", {}).get("value") == 0 for item in hook_logs)
    python_logs = [item for item in logs if item["attributes"].get("sentry.sdk.name", {}).get("value", "").startswith("sentry.python")]
    assert python_logs
    for item in python_logs:
        for key in ("process.pid", "process.parent_pid", "process.command"):
            assert item["attributes"].get(key, {}).get("value"), (key, item["body"])
    assert any(item["attributes"].get("supervisor.process.name", {}).get("value") for item in hook_logs)
    assert any(item["attributes"].get("supervisor.process.name", {}).get("value") == "worker_uvicorn" for item in logs)
    completions = [item for item in hook_logs if "process.exit_code" in item["attributes"]]
    assert completions
    for item in completions:
        assert item["attributes"]["hook.process.pid"]["value"] > 0
        assert item["attributes"]["hook.process.pid"]["value"] != item["attributes"]["process.pid"]["value"]
    assert spans
    assert not any(kind == "transaction" for kind, payload in items)
    assert not any(
        discarded["reason"] in {"queue_overflow", "buffer_overflow"}
        for kind, report in items
        if kind == "client_report"
        for discarded in report["discarded_events"]
    )
    install_trace = next(item for item in spans if item["name"] == "ArchiveBox_install.emit(InstallEvent)")
    assert install_trace["attributes"]["abxbus.event_type"] == "InstallEvent"
    assert install_trace["attributes"]["abxbus.event_bus.name"] == "ArchiveBox_install"
    assert any("BinaryRequestEvent" in span["name"] and span["trace_id"] == install_trace["trace_id"] for span in spans)
    crawl_traces = [item for item in spans if item["name"].endswith(".emit(CrawlEvent)")]
    assert crawl_traces
    crawl_trace_ids = {item["trace_id"] for item in crawl_traces}
    crawl_spans = [span for span in spans if span["trace_id"] in crawl_trace_ids]
    assert any(".emit(SnapshotEvent)" in span["name"] for span in crawl_spans)
    assert any(".emit(ProcessEvent)" in span["name"] for span in crawl_spans)
    assert any(item["trace_id"] in crawl_trace_ids for item in hook_logs)
    assert hook_failure["contexts"]["trace"]["trace_id"] in crawl_trace_ids
    server_requests = [item for item in spans if item["kind"] == 2 and "http.status_code" in item["attributes"]]
    assert any("admin/login" in item["name"] for item in server_requests)
    assert any(item["resource"]["service.version"] == installed_release for item in server_requests)
    assert any(item["resource"]["service.version"] == "plugin-test@1" for item in server_requests)
    for request_span in server_requests:
        attrs = request_span["attributes"]
        process = processes[UUID(attrs["process.id"]).hex]
        assert attrs["process.type"] == process["process_type"]
        assert request_span["resource"]["process.pid"] == process["pid"]
        assert process["worker_type"] == "worker_uvicorn"
        assert process["status"] == "exited"
        assert process["exit_code"] == 0
        assert (UUID(attrs["process.parent_id"]).hex if attrs["process.parent_id"] else None) == process["parent_id"]
        assert process["ended_at"] is not None
    replay_requests = [span for span in server_requests if span["attributes"].get("snapshot.id")]
    assert replay_requests
    assert all(UUID(span["attributes"]["snapshot.id"]).hex == replay_snapshot_id for span in replay_requests)
    assert all(UUID(span["attributes"]["crawl.id"]).hex == replay_crawl_id for span in replay_requests)
    assert all(span["attributes"]["snapshot.url"] == snapshot_urls[replay_snapshot_id] for span in replay_requests)
    request_trace_ids = {item["trace_id"] for item in server_requests}
    sql_spans = [span for span in spans if span["attributes"].get("db.system") == "sqlite"]
    assert sql_spans
    assert all(span["attributes"].get("db.statement") for span in sql_spans)
    assert all(span["resource"].get("process.command") for span in sql_spans)
    assert all(span["resource"].get("process.parent_pid") for span in sql_spans)
    # Queries must belong to the actual request, worker operation, or event
    # that issued them; standalone SQL traces cannot explain that workload.
    root_sql = [span for span in sql_spans if not span["parent_span_id"]]
    # SDK initialization and Process registration precede usable operation
    # scopes, and shutdown records run after them. Neither should excuse SQL
    # emitted without parents between a worker's first and last real operation.
    work_by_process = {}
    for span in spans:
        if span["scope"] == "archivebox" or span in server_requests:
            work_by_process.setdefault(span["resource"]["process.pid"], []).append(span)
    for sql in root_sql:
        work = work_by_process.get(sql["resource"]["process.pid"], [])
        if sql["attributes"].get("thread.name") == "archivebox-importers":
            # The importer reads its config once before entering its first poll.
            work = [span for span in work if span["name"] == "archivebox.importers.service._background_run"]
        if work:
            first = min(span["start_time_unix_nano"] for span in work)
            last = max(span["end_time_unix_nano"] for span in work)
            assert sql["end_time_unix_nano"] <= first or sql["start_time_unix_nano"] >= last, sql
    assert any("SELECT" in span["attributes"]["db.statement"] and span["trace_id"] in request_trace_ids for span in sql_spans)
    assert any(span["trace_id"] in crawl_trace_ids for span in sql_spans)
    spans_by_id = {span["span_id"]: span for span in spans}
    assert len(spans_by_id) == len(spans)
    for crawl_span in crawl_traces:
        operation = spans_by_id[crawl_span["parent_span_id"]]
        assert operation["name"] == "CrawlRunner.run"
        assert operation["trace_id"] == crawl_span["trace_id"]
        assert operation["attributes"]["crawl.id"] == crawl_span["attributes"]["crawl.id"]
    for operation_name in ("run_pending_crawls", "archivebox.importers.service._background_run"):
        operations = [span for span in spans if span["name"] == operation_name]
        assert operations, operation_name
        for operation in operations:
            attrs = operation["attributes"]
            process = processes[UUID(attrs["process.id"]).hex]
            assert attrs["process.type"] == process["process_type"]
            assert attrs["worker.type"] == process["worker_type"]
            assert UUID(attrs["process.parent_id"]).hex == process["parent_id"]
            assert operation["resource"]["process.pid"] == process["pid"]
        assert any(sql["parent_span_id"] in {operation["span_id"] for operation in operations} for sql in sql_spans)

    process_events = [span for span in crawl_spans if span["name"].endswith(".emit(ProcessEvent)")]
    assert len(process_events) >= 3
    process_spans = {}
    for span in process_events:
        attrs = span["attributes"]
        process_id = UUID(attrs["hook.process.id"]).hex
        process = processes[process_id]
        process_spans[process_id] = span
        assert attrs["plugin.name"] == "wget"
        assert attrs["hook.name"].startswith("on_Snapshot__")
        assert attrs["hook.process.type"] == process["process_type"] == "hook"
        assert attrs["hook.process.pid"] == process["pid"]
        assert UUID(attrs["hook.process.parent_id"]).hex == process["parent_id"]
        assert UUID(attrs["process.id"]).hex == process["parent_id"]
        assert UUID(attrs["crawl.id"]).hex == snapshots[UUID(attrs["snapshot.id"]).hex]
        assert attrs["snapshot.url"] == snapshot_urls[UUID(attrs["snapshot.id"]).hex]
        started_at = datetime.fromisoformat(process["started_at"]).replace(tzinfo=timezone.utc)
        ended_at = datetime.fromisoformat(process["ended_at"]).replace(tzinfo=timezone.utc)
        assert attrs["process.exit_code"] == process["exit_code"]
        assert attrs["process.duration"] == pytest.approx((ended_at - started_at).total_seconds() * 1000, abs=1)
        assert datetime.fromisoformat(attrs["process.started_at"]) == started_at
        assert datetime.fromisoformat(attrs["process.ended_at"]) == ended_at
        # A background process span must cover its actual execution, not end
        # when its launch handler returns and leaves the child running.
        assert span["start_time_unix_nano"] <= started_at.timestamp() * 1e9
        assert span["end_time_unix_nano"] + 1000 >= ended_at.timestamp() * 1e9

    completed_events = [span for span in crawl_spans if span["name"].endswith(".emit(ProcessCompletedEvent)")]
    completed_updates = {span["span_id"]: [] for span in completed_events}
    for sql in sql_spans:
        if not sql["attributes"]["db.statement"].startswith('UPDATE "machine_process"'):
            continue
        parent_id = sql["parent_span_id"]
        while parent_id in spans_by_id:
            if parent_id in completed_updates:
                completed_updates[parent_id].append(sql)
                break
            parent_id = spans_by_id[parent_id]["parent_span_id"]
    assert completed_events
    assert all(completed_updates.values()), completed_updates
    assert {UUID(span["attributes"]["hook.process.id"]).hex for span in completed_events} == set(process_spans)
    assert len({span["attributes"]["hook.process.parent_id"] for span in process_events}) < len(process_events)
    for item in hook_logs:
        attrs = {key: value["value"] for key, value in item["attributes"].items()}
        process_id = UUID(attrs["hook.process.id"]).hex
        process = processes[process_id]
        process_span = process_spans[process_id]
        assert item["trace_id"] == process_span["trace_id"]
        for key in (
            "hook.process.id",
            "hook.process.parent_id",
            "hook.process.type",
            "plugin.name",
            "hook.name",
            "snapshot.id",
            "snapshot.url",
            "crawl.id",
        ):
            assert attrs[key] == process_span["attributes"][key], (key, item["body"])
        assert UUID(attrs["process.id"]).hex == process["parent_id"]
        assert attrs["hook.process.pid"] == process["pid"]
        resource = spans_by_id[item["span_id"]]["resource"]
        for key in ("process.pid", "process.parent_pid", "process.command", "supervisor.process.name"):
            assert item["attributes"].get(key, {}).get("value") == resource.get(key), (key, item["body"])
    for hook_error in hook_failures:
        failure_attrs = hook_error["contexts"]["hook"]
        failed_process_id = UUID(failure_attrs["hook.process.id"]).hex
        assert processes[failed_process_id]["exit_code"] != 0
        assert hook_error["contexts"]["trace"]["trace_id"] == process_spans[failed_process_id]["trace_id"]
        for key in ("hook.process.id", "hook.process.parent_id", "plugin.name", "hook.name", "snapshot.id", "snapshot.url", "crawl.id"):
            assert hook_error["tags"][key] == process_spans[failed_process_id]["attributes"][key]
    access_logs = [item for item in logs if item["attributes"].get("logger.name", {}).get("value") == "uvicorn.access"]
    assert access_logs
    for item in access_logs:
        assert item.get("span_id") in spans_by_id, item
        request_span = spans_by_id[item["span_id"]]
        assert request_span in server_requests
        assert item["trace_id"] == request_span["trace_id"]
        for key in ("process.id", "user.id", "user.name", "snapshot.id", "crawl.id"):
            if key in request_span["attributes"]:
                assert item["attributes"].get(key, {}).get("value") == request_span["attributes"][key], (key, item)
    assert len({item["span_id"] for item in access_logs}) == len(access_logs)
    assert all(item["scope"] == "opentelemetry.instrumentation.asgi" for item in server_requests)
    assert not any(item["scope"] == "opentelemetry.instrumentation.django" for item in spans)
    assert not any(event.get("logger") == "opentelemetry.context" for event in events)
    assert head_log["span_id"] in spans_by_id
    assert head_failure["contexts"]["trace"]["span_id"] in spans_by_id
    operation_trace_ids = {span["trace_id"] for work in work_by_process.values() for span in work}
    for span in sql_spans:
        if span["trace_id"] in request_trace_ids | crawl_trace_ids | operation_trace_ids:
            assert span["parent_span_id"] in spans_by_id, span
            assert spans_by_id[span["parent_span_id"]]["trace_id"] == span["trace_id"]
    assert any(item["attributes"].get("user.id") == user_id for item in server_requests)
    assert any(item["attributes"].get("user.name") == "apitestadmin" for item in server_requests)
    assert any("admin/login" in item["name"] and "user.id" not in item["attributes"] for item in server_requests)
    browser_pages = [
        item
        for kind, payload in items
        if kind == "span"
        for item in payload["items"]
        if item["name"] == "/admin/core/snapshot/" and item["attributes"].get("sentry.op", {}).get("value") == "pageload"
    ]
    assert browser_pages
    assert all(item["end_timestamp"] - item["start_timestamp"] < 30 for item in browser_pages)
    assert all(item["attributes"]["user.id"]["value"] == user_id for item in browser_pages)
    browser_spans = {item["span_id"]: item for kind, payload in items if kind == "span" for item in payload["items"]}
    browser_requests = [span for span in server_requests if span["parent_span_id"] in browser_spans]
    assert browser_requests
    assert all(span["trace_id"] == browser_spans[span["parent_span_id"]]["trace_id"] for span in browser_requests)
    metrics = [item for kind, payload in items if kind == "trace_metric" for item in payload["items"]]
    assert any(item["name"] == "archivebox.spans" for item in metrics)
    assert any(item["name"] == "archivebox.span.duration" for item in metrics)
    for metric in metrics:
        if metric["name"] in {"archivebox.spans", "archivebox.span.duration"}:
            assert metric["span_id"] in spans_by_id, metric
            source_span = spans_by_id[metric["span_id"]]
            assert metric["trace_id"] == source_span["trace_id"]
            for key in ("process.id", "hook.process.id", "plugin.name", "hook.name", "crawl.id", "snapshot.id", "snapshot.url"):
                if key in source_span["attributes"]:
                    assert metric["attributes"].get(key, {}).get("value") == source_span["attributes"][key], (key, metric)
    profiles = [payload for kind, payload in items if kind == "profile_chunk"]
    assert profiles
    assert any(profile["profile"]["samples"] for profile in profiles)
    assert any("archivebox" in frame.get("module", "") for profile in profiles for frame in profile["profile"]["frames"])
    profiler_ids = {profile["profiler_id"] for profile in profiles}
    assert any(span["attributes"].get("sentry.profiler_id") in profiler_ids for span in server_requests)
    assert any(span["attributes"].get("sentry.profiler_id") in profiler_ids for span in crawl_spans)
