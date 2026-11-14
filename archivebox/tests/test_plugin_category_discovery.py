"""Discover installed plugin categories through real settings pages and submissions."""

import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

from abx_plugins import get_plugins_dir
from archivebox.plugins.forms import PLUGIN_GROUPS

from .conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
)
from .test_ui_add_view import ADD_FORM_DEFAULTS
from .test_ui_add_view_runtime import _login_to_add_view


class SettingsControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.category = ""
        self.in_category = False
        self.tabs = {}
        self.panels = []
        self.switches = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "div" and attrs.get("class") == "plugin-settings-category":
            self.in_category = True
        if tag == "button" and attrs.get("role") == "tab":
            self.tabs[attrs["data-plugin"]] = self.category
        if "data-plugin-name" in attrs:
            self.panels.append(attrs["data-plugin-name"])
        if tag == "input" and "plugin-section-toggle" in attrs.get("class", "").split():
            self.switches.append(attrs)

    def handle_data(self, data):
        if self.in_category:
            self.category = data.strip()

    def handle_endtag(self, tag):
        if tag == "div":
            self.in_category = False


def test_installed_plugins_in_new_categories_are_editable_and_selectable(initialized_archive):
    root = initialized_archive
    # Install genuine plugin packages as collection overrides, changing only
    # presentation metadata; the source package and hook code stay untouched.
    for plugin, category in (("screenshot", "visual_review"), ("pdf", "visual_review"), ("title", "catalog_checks")):
        installed = root / "custom_plugins" / plugin
        shutil.copytree(Path(get_plugins_dir()) / plugin, installed)
        config_path = installed / "config.json"
        config = json.loads(config_path.read_text())
        config["category"] = category
        config_path.write_text(json.dumps(config))
    create_admin_and_token(root)
    port = get_free_port()
    server = start_archivebox_server(root, env=cli_env(port=port, server=True), port=port, log_name="category-server.log")
    try:
        session, add_page, csrf = _login_to_add_view(port)
        host = f"admin.archivebox.localhost:{port}"
        controls = SettingsControls(add_page.text)
        assert controls.tabs["screenshot"] == controls.tabs["pdf"] == "Visual review"
        assert controls.tabs["title"] == "Catalog checks"
        assert controls.tabs["wget"] == "Main"
        categories = list(dict.fromkeys(controls.tabs.values()))
        known_categories = [title for _category, _field, title in PLUGIN_GROUPS if title in categories]
        assert categories[: len(known_categories)] == known_categories
        assert categories.index("Catalog checks") < categories.index("Visual review")
        assert len(controls.panels) == len(set(controls.panels))
        switches = {item["value"]: item for item in controls.switches}
        for plugin in ("screenshot", "pdf", "title"):
            assert switches[plugin]["name"] == "other_plugins"
        ids = [item["id"] for item in controls.switches]
        assert len(ids) == len(set(ids))
        assert "importer_rss" not in controls.tabs
        assert 'name="plugin_config__screenshot__SCREENSHOT_TIMEOUT"' in add_page.text

        listing = session.get(f"http://127.0.0.1:{port}/admin/personas/persona/", headers={"Host": host}, timeout=10)
        assert listing.status_code == 200
        persona_link = re.search(r'href="(/admin/personas/persona/[^/]+/change/)">Default</a>', listing.text)
        assert persona_link, listing.text
        persona_page = session.get(f"http://127.0.0.1:{port}" + persona_link.group(1), headers={"Host": host}, timeout=10)
        assert persona_page.status_code == 200
        persona_controls = SettingsControls(persona_page.text)
        assert persona_controls.tabs["screenshot"] == persona_controls.tabs["pdf"] == "Visual review"
        assert persona_controls.tabs["title"] == "Catalog checks"
        assert persona_controls.tabs["importer_rss"] == "Importers"
        assert not persona_controls.switches
        assert len(persona_controls.panels) == len(set(persona_controls.panels))

        saved = session.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": host, "Referer": f"http://{host}/add/"},
            data={
                **ADD_FORM_DEFAULTS,
                "csrfmiddlewaretoken": csrf,
                "url": "https://example.com/category-discovery",
                "other_plugins": ["screenshot", "pdf", "title"],
                "plugin_config__screenshot__SCREENSHOT_TIMEOUT": "77",
                "start_paused": "on",
            },
            timeout=30,
            allow_redirects=False,
        )
        assert saved.status_code == 302, saved.text
        result = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                "import json; from archivebox.crawls.models import Crawl; c = Crawl.objects.latest('created_at'); "
                "print(json.dumps({'plugins': c.config.get('PLUGINS'), 'status': c.status, 'timeout': c.config.get('SCREENSHOT_TIMEOUT')}))",
            ],
            cwd=root,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        record = json.loads(result.stdout.strip().splitlines()[-1])
        assert set(record["plugins"].split(",")) == {"screenshot", "pdf", "title"}
        assert record["status"] == "paused"
        assert record["timeout"] == 77
    finally:
        stop_archivebox_process(server)
