"""Exercise optional monitoring through real collection commands and Django requests."""

import gzip
import json
import os
import re
import subprocess
import sys
import time
from io import BytesIO

import pytest
import requests
from playwright.sync_api import sync_playwright

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


@pytest.mark.parametrize("dsn", ["", "http://public@127.0.0.1:1/1"])
def test_sentry_disabled_never_imports_sdk(initialized_archive, dsn, free_tcp_port):
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import sys, asyncio; from django.apps import apps; from django.conf import settings; "
            "from archivebox.services.runner import create_bus; "
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


def test_sentry_sends_logging_and_django_errors(initialized_archive, httpserver, free_tcp_port, recursive_test_site, browser_runtime):
    httpserver.expect_request("/api/1/envelope/", method="POST").respond_with_json({}, headers={"Access-Control-Allow-Origin": "*"})
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
            "SENTRY_RELEASE=plugin-test@1",
            "SENTRY_ENABLE_LOGS=True",
            "SENTRY_ENABLE_METRICS=True",
            "SENTRY_TRACES_SAMPLE_RATE=1",
            "SENTRY_PROFILE_SESSION_SAMPLE_RATE=1",
            "SENTRY_PROFILE_LIFECYCLE=manual",
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
        # Continuous profiling publishes native 60-second chunks. Keep a real
        # request workload alive through that interval instead of altering SDK
        # internals or forcing a test-only profiler flush.
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            response = requests.get(f"http://127.0.0.1:{free_tcp_port}/admin/login/", headers={"Host": "localhost"}, timeout=10)
            assert response.status_code == 200
            time.sleep(1)
    finally:
        stop_archivebox_process(server)
    capture = run_archivebox_cmd(
        ["add", "--plugins=wget", recursive_test_site["root_url"]],
        cwd=initialized_archive,
        check=True,
        timeout=120,
    )
    (initialized_archive / "sentry-capture.log").write_text(capture.stdout + capture.stderr)
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
from archivebox.services.runner import CrawlRunner

user, _ = get_user_model().objects.get_or_create(username='sentry-acceptance')
for enabled, expected in [(False, 0), (True, 1)]:
    persona = Persona.objects.create(name=f'sentry-{enabled}', config={'SENTRY_ENABLED': enabled})
    crawl = Crawl.objects.create(urls='', created_by=user, persona=persona, config={'PLUGINS': 'wget'})
    runner = CrawlRunner(crawl, show_progress=False, wait_for_resources=False)
    asyncio.run(runner.run())
    assert len(runner.bus.middlewares) == expected, (enabled, runner.bus.middlewares)
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
    template.unlink()
    run_archivebox_cmd(
        ["config", "--set", "SENTRY_SEND_DEFAULT_PII=True"],
        cwd=initialized_archive,
        env={"SENTRY_ENABLED": "false"},
        check=True,
    )
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
            user_id = browser_config["user"]["id"]
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
    for request, response in httpserver.log:
        assert response.status_code == 200
        data = request.data
        if request.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
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
    logged = next(event for event in events if event.get("logger") == "archivebox.sentry_test")
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
    transactions = [payload for kind, payload in items if kind == "transaction"]
    install_trace = next(item for item in transactions if item["transaction"] == "ArchiveBox_install.emit(InstallEvent)")
    assert install_trace["contexts"]["otel"]["attributes"]["abxbus.event_type"] == "InstallEvent"
    assert install_trace["contexts"]["otel"]["attributes"]["abxbus.event_bus.name"] == "ArchiveBox_install"
    assert any("BinaryRequestEvent" in span["description"] for span in install_trace["spans"])
    server_requests = [item for item in transactions if item["contexts"]["trace"]["op"] == "http.server"]
    assert any("admin/login" in item["transaction"] for item in server_requests), sorted({item["transaction"] for item in transactions})
    assert any(span["op"] == "db" and "SELECT" in span["description"] for item in server_requests for span in item["spans"])
    assert any(item.get("user", {}).get("id") == user_id for item in server_requests)
    assert any(item.get("user", {}).get("username") == "apitestadmin" for item in server_requests)
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
    metrics = [item for kind, payload in items if kind == "trace_metric" for item in payload["items"]]
    assert any(item["name"] == "archivebox.spans" for item in metrics)
    assert any(item["name"] == "archivebox.span.duration" for item in metrics)
    profiles = [payload for kind, payload in items if kind == "profile_chunk"]
    assert profiles
    assert any(profile["profile"]["samples"] for profile in profiles)
    assert any("archivebox" in frame.get("module", "") for profile in profiles for frame in profile["profile"]["frames"])
