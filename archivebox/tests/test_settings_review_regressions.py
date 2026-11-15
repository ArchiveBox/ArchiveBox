import json

from playwright.sync_api import expect, sync_playwright

from archivebox.tests.conftest import (
    cli_env,
    get_free_port,
    run_archivebox_cmd,
    run_python_cwd,
    start_archivebox_server,
    stop_archivebox_process,
)


def test_shared_templates_use_schema_step_and_existing_help(initialized_archive):
    _, stderr, code = run_python_cwd(
        """
import django
django.setup()
from html.parser import HTMLParser
from django.template.loader import render_to_string
from archivebox.config.common import config_field_metadata, get_config
from archivebox.machine.forms import MachineAdminForm
from archivebox.machine.models import Machine
from archivebox.plugins.discovery import discover_plugin_configs

class Controls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.controls = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        if tag in ('input', 'textarea'):
            self.controls.append(dict(attrs))

form = MachineAdminForm(instance=Machine.current())
runtime = get_config()
field = form._build_plugin_config_field('chrome_screencast', 'CHROME_SCREENCAST_SCALE', discover_plugin_configs()['chrome_screencast']['properties']['CHROME_SCREENCAST_SCALE'], runtime)
controls = Controls(render_to_string('plugins/config_range.html', {'field': field})).controls
assert [control['step'] for control in controls] == ['any', 'any'], controls
controls = Controls(render_to_string('plugins/config_range.html', {'field': field, 'step': '0.1'})).controls
assert [control['step'] for control in controls] == ['0.1', 'any'], controls
field = form._build_plugin_config_field('archivebox', 'URL_ALLOWLIST', config_field_metadata()['URL_ALLOWLIST']['schema'], runtime)
assert not field['description']
controls = Controls(render_to_string('plugins/config_editor.html', {'field': field})).controls
assert 'aria-describedby' not in controls[0], controls
field = form._build_plugin_config_field('archivebox', 'DELETE_AFTER', config_field_metadata()['DELETE_AFTER']['schema'], runtime)
controls = Controls(render_to_string('plugins/config_editor.html', {'field': field})).controls
assert controls[0]['aria-describedby'] == 'help_' + field['input_name']
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


def test_retention_aliases_and_timeout_slider_in_real_settings(initialized_archive, browser_runtime):
    root = initialized_archive
    aliases = (
        ["1hr"]
        + [
            f"2 {unit.upper()}"
            for unit in (
                "h",
                "hr",
                "hrs",
                "hour",
                "hours",
                "d",
                "day",
                "days",
                "w",
                "week",
                "weeks",
                "mo",
                "month",
                "months",
                "y",
                "yr",
                "yrs",
                "year",
                "years",
            )
        ]
        + ["0", "NONE", "False", "no", "OFF", "0hours", ""]
    )
    stdout, stderr, code = run_python_cwd(
        """
import json
import django
django.setup()
from archivebox.config.common import parse_delete_after
from archivebox.personas.models import Persona
records = []
for index, value in enumerate(ALIASES):
    persona = Persona.objects.create(name=f'Retention Review {index}', config={'DELETE_AFTER': value, 'PERMISSIONS': 'private'})
    duration = parse_delete_after(value)
    records.append({'id': str(persona.pk), 'value': value, 'seconds': duration.total_seconds() if duration else 0})
Persona.objects.create(name='Short Timeout', config={'TIMEOUT': 10, 'PERMISSIONS': 'private'})
print(json.dumps(records))
""".replace("ALIASES", repr(aliases)),
        cwd=root,
    )
    assert code == 0, stderr
    records = json.loads(stdout.splitlines()[-1])
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="quantity-review",
        DJANGO_SUPERUSER_PASSWORD="quantity-review-local-password",
        DJANGO_SUPERUSER_EMAIL="quantity-review@example.com",
    )
    result = run_archivebox_cmd(["manage", "createsuperuser", "--noinput"], cwd=root, env=env)
    assert result.returncode == 0, result.stderr
    server = start_archivebox_server(root, port=port, env=env, log_name="review-server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator(".navbar-username")).to_have_text(env["DJANGO_SUPERUSER_USERNAME"])
            for record in records:
                page.goto(base + f"/admin/personas/persona/{record['id']}/change/")
                page.get_by_role("searchbox", name="Search plugin settings").fill("DELETE_AFTER")
                canonical = page.locator('[name="plugin_config__archivebox__DELETE_AFTER"]')
                wrapper = canonical.locator("..")
                amount = wrapper.locator(".config-quantity-value")
                units = wrapper.locator(".config-quantity-unit")
                assert amount.evaluate("input => input.checkValidity()"), record
                original = canonical.input_value()
                if record["seconds"]:
                    expect(amount).to_be_visible()
                    units.select_option("h")
                    expect(amount).to_have_value(str(record["seconds"] / 3600).removesuffix(".0"))
                else:
                    expect(amount).to_be_visible()
                    expect(amount).to_have_value("")
                    expect(amount).to_have_attribute("placeholder", "Keep forever")
                    units.select_option("h")
                expect(canonical).to_have_value(original)
                assert amount.evaluate("input => input.checkValidity()"), record
                if record["value"] in {"1hr", "OFF"}:
                    page.locator('button[name="_continue"]').click()
                    expect(page.locator(".success")).to_be_visible()

            page.goto(base + "/add/")
            url_limit = page.locator(".crawl-limit-field").filter(has=page.locator('[name="max_urls"]'))
            expect(url_limit.locator("input[type=range]")).to_be_visible()
            expect(url_limit.locator("input[type=range]")).to_have_attribute("max", "1000000")
            url_limit.locator("input[type=range]").press("End")
            expect(url_limit.locator('[name="max_urls"]')).to_have_value("1000000")
            url_limit.locator(".config-zero-value").fill("")
            expect(url_limit.locator('[name="max_urls"]')).to_have_value("0")
            expect(url_limit.locator(".config-zero-value")).to_have_attribute("placeholder", "No limit")
            page.locator('[name="persona"]').select_option("Short Timeout")
            short_timeout = page.locator('[name="timeout"]')
            expect(short_timeout).to_have_value("10")
            short_wrapper = short_timeout.locator("..")
            assert not short_wrapper.locator(".config-quantity-value").evaluate("input => input.checkValidity()")
            short_wrapper.locator(".config-quantity-unit").select_option("min")
            assert not short_wrapper.locator(".config-quantity-value").evaluate("input => input.checkValidity()")
            for name in ("crawl_timeout", "timeout"):
                canonical = page.locator(f'[name="{name}"]')
                wrapper = canonical.locator("..")
                slider = wrapper.locator(".config-quantity-slider")
                amount = wrapper.locator(".config-quantity-value")
                expect(slider).to_be_visible()
                wrapper.locator(".config-quantity-unit").select_option("s")
                if name == "timeout":
                    slider.press("Home")
                    expect(canonical).to_have_value("0")
                    slider.press("ArrowRight")
                else:
                    amount.fill("11")
                expect(canonical).to_have_value("11")
                expect(slider).to_have_value("11")
                assert amount.evaluate("input => input.checkValidity()")
                slider.press("ArrowLeft")
                expect(canonical).to_have_value("0")
                expect(slider).to_have_value("0")
                if name == "crawl_timeout":
                    expect(slider).to_be_visible()
                    expect(amount).to_have_value("")
                    amount.fill("11")
                amount.fill("5")
                assert not amount.evaluate("input => input.checkValidity()")
                if name == "crawl_timeout":
                    slider.press("ArrowLeft")
                    expect(canonical).to_have_value("0")
                    expect(slider).to_be_visible()
                    continue
                slider.press("ArrowRight")
                expect(canonical).to_have_value("11")
                assert amount.evaluate("input => input.checkValidity()")
            browser.close()
    finally:
        stop_archivebox_process(server)

    _, stderr, code = run_python_cwd(
        """
import django
django.setup()
from archivebox.personas.models import Persona
for record in RECORDS:
    assert Persona.objects.get(pk=record['id']).config['DELETE_AFTER'] == record['value'], record
""".replace("RECORDS", repr(records)),
        cwd=root,
    )
    assert code == 0, stderr
