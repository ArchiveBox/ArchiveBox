from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.utils import timezone

from archivebox.config import views as config_views
from archivebox.core import views as core_views
from archivebox.machine.models import Binary


pytestmark = pytest.mark.django_db


def test_get_db_binaries_by_name_collapses_youtube_dl_aliases(monkeypatch):
    now = timezone.now()
    records = [
        SimpleNamespace(
            name="youtube-dl",
            version="",
            binprovider="",
            abspath="/usr/bin/youtube-dl",
            status=Binary.StatusChoices.INSTALLED,
            modified_at=now,
        ),
        SimpleNamespace(
            name="yt-dlp",
            version="2026.03.01",
            binprovider="pip",
            abspath="/usr/bin/yt-dlp",
            status=Binary.StatusChoices.INSTALLED,
            modified_at=now + timedelta(seconds=1),
        ),
    ]

    monkeypatch.setattr(config_views.Binary, "objects", SimpleNamespace(all=lambda: records))

    binaries = config_views.get_db_binaries_by_name()

    assert "yt-dlp" in binaries
    assert "youtube-dl" not in binaries
    assert binaries["yt-dlp"].version == "2026.03.01"


def test_binaries_list_view_uses_db_version_and_hides_youtube_dl_alias(monkeypatch):
    request = RequestFactory().get("/admin/environment/binaries/")
    request.user = SimpleNamespace(is_superuser=True)

    db_binary = SimpleNamespace(
        name="youtube-dl",
        version="2026.03.01",
        binprovider="pip",
        abspath="/usr/bin/yt-dlp",
        status=Binary.StatusChoices.INSTALLED,
        sha256="",
        modified_at=timezone.now(),
    )

    monkeypatch.setattr(config_views, "get_db_binaries_by_name", lambda: {"yt-dlp": db_binary})

    context = config_views.binaries_list_view.__wrapped__(request)

    assert len(context["table"]["Binary Name"]) == 1
    assert str(context["table"]["Binary Name"][0].link_item) == "yt-dlp"
    assert context["table"]["Found Version"][0] == "✅ 2026.03.01"
    assert context["table"]["Provided By"][0] == "pip"
    assert context["table"]["Found Abspath"][0] == "/usr/bin/yt-dlp"


def test_binaries_list_view_only_shows_persisted_records(monkeypatch):
    request = RequestFactory().get("/admin/environment/binaries/")
    request.user = SimpleNamespace(is_superuser=True)

    monkeypatch.setattr(config_views, "get_db_binaries_by_name", lambda: {})

    context = config_views.binaries_list_view.__wrapped__(request)

    assert context["table"]["Binary Name"] == []
    assert context["table"]["Found Version"] == []
    assert context["table"]["Provided By"] == []
    assert context["table"]["Found Abspath"] == []


def test_binary_detail_view_uses_canonical_db_record(monkeypatch):
    request = RequestFactory().get("/admin/environment/binaries/youtube-dl/")
    request.user = SimpleNamespace(is_superuser=True)

    db_binary = SimpleNamespace(
        id="019d14cc-6c40-7793-8ff1-0f8bb050e8a3",
        name="yt-dlp",
        version="2026.03.01",
        binprovider="pip",
        abspath="/usr/bin/yt-dlp",
        sha256="abc123",
        status=Binary.StatusChoices.INSTALLED,
        modified_at=timezone.now(),
    )

    monkeypatch.setattr(config_views, "get_db_binaries_by_name", lambda: {"yt-dlp": db_binary})

    context = config_views.binary_detail_view.__wrapped__(request, key="youtube-dl")
    section = context["data"][0]

    assert context["title"] == "yt-dlp"
    assert section["fields"]["name"] == "yt-dlp"
    assert section["fields"]["version"] == "2026.03.01"
    assert section["fields"]["binprovider"] == "pip"
    assert section["fields"]["abspath"] == "/usr/bin/yt-dlp"
    assert "/admin/machine/binary/019d14cc-6c40-7793-8ff1-0f8bb050e8a3/change/?_changelist_filters=q%3Dyt-dlp" in section["description"]


def test_binary_detail_view_marks_unrecorded_binary(monkeypatch):
    request = RequestFactory().get("/admin/environment/binaries/wget/")
    request.user = SimpleNamespace(is_superuser=True)

    monkeypatch.setattr(config_views, "get_db_binaries_by_name", lambda: {})

    context = config_views.binary_detail_view.__wrapped__(request, key="wget")
    section = context["data"][0]

    assert section["description"] == "No persisted Binary record found"
    assert section["fields"]["status"] == "unrecorded"
    assert section["fields"]["binprovider"] == "not recorded"


def test_plugin_detail_view_renders_config_in_dedicated_sections(monkeypatch):
    request = RequestFactory().get("/admin/environment/plugins/builtin.example/")
    request.user = SimpleNamespace(is_superuser=True)

    plugin_config = {
        "title": "Example Plugin",
        "description": "Example config used to verify plugin metadata rendering.",
        "type": "object",
        "required_plugins": ["chrome"],
        "required_binaries": ["example-cli"],
        "output_mimetypes": ["text/plain", "application/json"],
        "properties": {
            "EXAMPLE_ENABLED": {
                "type": "boolean",
                "description": "Enable the example plugin.",
                "x-fallback": "CHECK_SSL_VALIDITY",
            },
            "EXAMPLE_BINARY": {
                "type": "string",
                "default": "gallery-dl",
                "description": "Filesystem path for example output.",
                "x-aliases": ["USE_EXAMPLE_BINARY"],
            },
        },
    }

    monkeypatch.setattr(
        config_views,
        "get_filesystem_plugins",
        lambda: {
            "builtin.example": {
                "id": "builtin.example",
                "name": "example",
                "source": "builtin",
                "path": "/plugins/example",
                "hooks": ["on_Snapshot__01_example.py"],
                "config": plugin_config,
            },
        },
    )
    monkeypatch.setattr(config_views, "get_machine_admin_url", lambda: "/admin/machine/machine/test-machine/change/")

    context = config_views.plugin_detail_view.__wrapped__(request, key="builtin.example")

    assert context["title"] == "example"
    assert len(context["data"]) == 5

    summary_section, hooks_section, metadata_section, config_section, properties_section = context["data"]

    assert summary_section["fields"] == {
        "id": "builtin.example",
        "name": "example",
        "source": "builtin",
    }
    assert "/plugins/example" in summary_section["description"]
    assert "https://archivebox.github.io/abx-plugins/#example" in summary_section["description"]

    assert hooks_section["name"] == "Hooks"
    assert hooks_section["fields"] == {}
    assert (
        "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/example/on_Snapshot__01_example.py"
        in hooks_section["description"]
    )
    assert "on_Snapshot__01_example.py" in hooks_section["description"]

    assert metadata_section["name"] == "Plugin Metadata"
    assert metadata_section["fields"] == {}
    assert "Example Plugin" in metadata_section["description"]
    assert "Example config used to verify plugin metadata rendering." in metadata_section["description"]
    assert "https://archivebox.github.io/abx-plugins/#chrome" in metadata_section["description"]
    assert "/admin/environment/binaries/example-cli/" in metadata_section["description"]
    assert "text/plain" in metadata_section["description"]
    assert "application/json" in metadata_section["description"]

    assert config_section["name"] == "config.json"
    assert config_section["fields"] == {}
    assert "<pre style=" in config_section["description"]
    assert "EXAMPLE_ENABLED" in config_section["description"]
    assert '<span style="color: #0550ae;">"properties"</span>' in config_section["description"]

    assert properties_section["name"] == "Config Properties"
    assert properties_section["fields"] == {}
    assert "/admin/machine/machine/test-machine/change/" in properties_section["description"]
    assert "/admin/machine/binary/" in properties_section["description"]
    assert "/admin/environment/binaries/" in properties_section["description"]
    assert "EXAMPLE_ENABLED" in properties_section["description"]
    assert "boolean" in properties_section["description"]
    assert "Enable the example plugin." in properties_section["description"]
    assert "/admin/environment/config/EXAMPLE_ENABLED/" in properties_section["description"]
    assert "/admin/environment/config/CHECK_SSL_VALIDITY/" in properties_section["description"]
    assert "/admin/environment/config/USE_EXAMPLE_BINARY/" in properties_section["description"]
    assert "/admin/environment/binaries/gallery-dl/" in properties_section["description"]
    assert "EXAMPLE_BINARY" in properties_section["description"]


def test_get_config_definition_link_keeps_core_config_search_link(monkeypatch):
    monkeypatch.setattr(core_views, "find_plugin_for_config_key", lambda key: None)

    url, label = core_views.get_config_definition_link("CHECK_SSL_VALIDITY")

    assert "github.com/search" in url
    assert "CHECK_SSL_VALIDITY" in url
    assert label == "archivebox/config"


def test_get_config_definition_link_uses_plugin_config_json_for_plugin_options(monkeypatch):
    plugin_dir = core_views.BUILTIN_PLUGINS_DIR / "parse_dom_outlinks"

    monkeypatch.setattr(core_views, "find_plugin_for_config_key", lambda key: "parse_dom_outlinks")
    monkeypatch.setattr(core_views, "iter_plugin_dirs", lambda: [plugin_dir])

    url, label = core_views.get_config_definition_link("PARSE_DOM_OUTLINKS_ENABLED")

    assert url == "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/parse_dom_outlinks/config.json"
    assert label == "abx_plugins/plugins/parse_dom_outlinks/config.json"


def test_live_config_value_view_renames_source_field_and_uses_plugin_definition_link(monkeypatch):
    request = RequestFactory().get("/admin/environment/config/PARSE_DOM_OUTLINKS_ENABLED/")
    request.user = SimpleNamespace(is_superuser=True)

    monkeypatch.setattr(core_views, "get_all_configs", lambda: {})
    monkeypatch.setattr(core_views, "get_flat_config", lambda: {})
    monkeypatch.setattr(core_views, "get_config", lambda: {"PARSE_DOM_OUTLINKS_ENABLED": True})
    monkeypatch.setattr(core_views, "find_config_default", lambda key: "True")
    monkeypatch.setattr(core_views, "find_config_type", lambda key: "bool")
    monkeypatch.setattr(core_views, "find_config_source", lambda key, merged: "Default")
    monkeypatch.setattr(core_views, "key_is_safe", lambda key: True)
    monkeypatch.setattr(core_views.CONSTANTS, "CONFIG_FILE", SimpleNamespace(exists=lambda: False))

    from archivebox.machine.models import Machine
    from archivebox.config.configset import BaseConfigSet

    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: SimpleNamespace(id="machine-id", config={})))
    monkeypatch.setattr(BaseConfigSet, "load_from_file", classmethod(lambda cls, path: {}))
    monkeypatch.setattr(
        core_views,
        "get_config_definition_link",
        lambda key: (
            "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/parse_dom_outlinks/config.json",
            "abx_plugins/plugins/parse_dom_outlinks/config.json",
        ),
    )

    context = core_views.live_config_value_view.__wrapped__(request, key="PARSE_DOM_OUTLINKS_ENABLED")
    section = context["data"][0]

    assert "Currently read from" in section["fields"]
    assert "Source" not in section["fields"]
    assert section["fields"]["Currently read from"] == "Default"
    assert "abx_plugins/plugins/parse_dom_outlinks/config.json" in section["help_texts"]["Type"]


def test_find_config_source_prefers_environment_over_machine_and_file(monkeypatch):
    monkeypatch.setenv("CHECK_SSL_VALIDITY", "false")

    from archivebox.machine.models import Machine
    from archivebox.config.configset import BaseConfigSet

    monkeypatch.setattr(
        Machine,
        "current",
        classmethod(lambda cls: SimpleNamespace(id="machine-id", config={"CHECK_SSL_VALIDITY": "true"})),
    )
    monkeypatch.setattr(
        BaseConfigSet,
        "load_from_file",
        classmethod(lambda cls, path: {"CHECK_SSL_VALIDITY": "true"}),
    )

    assert core_views.find_config_source("CHECK_SSL_VALIDITY", {"CHECK_SSL_VALIDITY": False}) == "Environment"


def test_live_config_value_view_priority_text_matches_runtime_precedence(monkeypatch):
    request = RequestFactory().get("/admin/environment/config/CHECK_SSL_VALIDITY/")
    request.user = SimpleNamespace(is_superuser=True)

    monkeypatch.setattr(core_views, "get_all_configs", lambda: {})
    monkeypatch.setattr(core_views, "get_flat_config", lambda: {"CHECK_SSL_VALIDITY": True})
    monkeypatch.setattr(core_views, "get_config", lambda: {"CHECK_SSL_VALIDITY": False})
    monkeypatch.setattr(core_views, "find_config_default", lambda key: "True")
    monkeypatch.setattr(core_views, "find_config_type", lambda key: "bool")
    monkeypatch.setattr(core_views, "key_is_safe", lambda key: True)

    from archivebox.machine.models import Machine
    from archivebox.config.configset import BaseConfigSet

    monkeypatch.setattr(
        Machine,
        "current",
        classmethod(lambda cls: SimpleNamespace(id="machine-id", config={"CHECK_SSL_VALIDITY": "true"})),
    )
    monkeypatch.setattr(
        BaseConfigSet,
        "load_from_file",
        classmethod(lambda cls, path: {"CHECK_SSL_VALIDITY": "true"}),
    )
    monkeypatch.setattr(core_views.CONSTANTS, "CONFIG_FILE", SimpleNamespace(exists=lambda: True))
    monkeypatch.setenv("CHECK_SSL_VALIDITY", "false")

    context = core_views.live_config_value_view.__wrapped__(request, key="CHECK_SSL_VALIDITY")
    section = context["data"][0]

    assert section["fields"]["Currently read from"] == "Environment"
    help_text = section["help_texts"]["Currently read from"]
    assert help_text.index("Environment") < help_text.index("Machine") < help_text.index("Config File") < help_text.index("Default")
    assert "Configuration Sources (highest priority first):" in section["help_texts"]["Value"]
