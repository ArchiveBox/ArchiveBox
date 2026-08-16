import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from archivebox.config import views as config_views
from archivebox.plugins import views as plugin_views
from archivebox.core import views as core_views
from archivebox.config import CONSTANTS
from archivebox.machine.models import Machine
from archivebox.tests.conftest import install_real_binary


pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(
        username="configviewadmin",
        email="configviewadmin@test.com",
        password="testpassword",
    )


@pytest.fixture
def admin_request(admin_user):
    def request_for(path: str):
        request = RequestFactory().get(path)
        request.user = admin_user
        return request

    return request_for


@pytest.fixture
def machine():
    return Machine.current(refresh=True)


@pytest.mark.django_db(transaction=True)
def test_get_db_binaries_by_name_collapses_youtube_dl_aliases(machine):
    install_real_binary(
        "youtube-dl",
        machine=machine,
        binproviders="env,uv,brew",
        overrides={"uv": {"install_args": ["youtube_dl"]}},
    )
    ytdlp = install_real_binary(
        "yt-dlp",
        machine=machine,
        binproviders="env,uv,brew",
        overrides={"uv": {"install_args": ["yt-dlp[default]"]}},
    )

    binaries = config_views.get_db_binaries_by_name()

    assert "yt-dlp" in binaries
    assert "youtube-dl" not in binaries
    assert binaries["yt-dlp"].id == ytdlp.id
    assert binaries["yt-dlp"].version == ytdlp.version
    assert binaries["yt-dlp"].abspath == ytdlp.abspath


@pytest.mark.django_db(transaction=True)
def test_binaries_list_view_uses_db_version_and_hides_youtube_dl_alias(admin_request, machine):
    binary = install_real_binary(
        "youtube-dl",
        machine=machine,
        binproviders="env,uv,brew",
        overrides={"uv": {"install_args": ["youtube_dl"]}},
    )

    context = config_views.binaries_list_view.__wrapped__(admin_request("/admin/environment/binaries/"))

    assert len(context["table"]["Binary Name"]) == 1
    assert str(context["table"]["Binary Name"][0].link_item) == "yt-dlp"
    assert context["table"]["Found Version"][0] == f"✅ {binary.version}"
    assert context["table"]["Provided By"][0] == binary.binprovider
    assert context["table"]["Found Abspath"][0] == binary.abspath


def test_binaries_list_view_only_shows_persisted_records(admin_request):
    context = config_views.binaries_list_view.__wrapped__(admin_request("/admin/environment/binaries/"))

    assert context["table"]["Binary Name"] == []
    assert context["table"]["Found Version"] == []
    assert context["table"]["Provided By"] == []
    assert context["table"]["Found Abspath"] == []


@pytest.mark.django_db(transaction=True)
def test_binary_detail_view_uses_canonical_db_record(admin_request, machine):
    db_binary = install_real_binary(
        "yt-dlp",
        machine=machine,
        binproviders="env,uv,brew",
        overrides={"uv": {"install_args": ["yt-dlp[default]"]}},
    )

    context = config_views.binary_detail_view.__wrapped__(admin_request("/admin/environment/binaries/youtube-dl/"), key="youtube-dl")
    section = context["data"][0]

    assert context["title"] == "yt-dlp"
    assert section["fields"]["name"] == "yt-dlp"
    assert section["fields"]["version"] == db_binary.version
    assert section["fields"]["binprovider"] == db_binary.binprovider
    assert section["fields"]["abspath"] == db_binary.abspath
    assert f"/admin/machine/binary/{db_binary.id}/change/?_changelist_filters=q%3Dyt-dlp" in section["description"]


def test_binary_detail_view_marks_unrecorded_binary(admin_request):
    context = config_views.binary_detail_view.__wrapped__(admin_request("/admin/environment/binaries/wget/"), key="wget")
    section = context["data"][0]

    assert section["description"] == "No persisted Binary record found"
    assert section["fields"]["status"] == "unrecorded"
    assert section["fields"]["binprovider"] == "not recorded"


def test_plugin_detail_view_renders_shipped_plugin_config_in_dedicated_sections(admin_request, machine):
    context = plugin_views.plugin_detail_view.__wrapped__(admin_request("/admin/environment/plugins/builtin.wget/"), key="builtin.wget")

    assert context["title"] == "wget"
    assert len(context["data"]) == 5

    summary_section, hooks_section, metadata_section, config_section, properties_section = context["data"]

    assert summary_section["fields"] == {
        "id": "builtin.wget",
        "name": "wget",
        "source": "builtin",
    }
    assert "abx_plugins/plugins/wget" in summary_section["description"]
    assert "https://archivebox.github.io/abx-plugins/#wget" in summary_section["description"]

    assert hooks_section["name"] == "Hooks"
    assert hooks_section["fields"] == {}
    assert "on_Snapshot__35_wget.finite.bg.py" in hooks_section["description"]

    assert metadata_section["name"] == "Plugin Metadata"
    assert metadata_section["fields"] == {}
    assert "Archive pages and their requisites with wget" in metadata_section["description"]
    assert "WGET_BINARY" in metadata_section["description"]
    assert "text/html" in metadata_section["description"]
    assert "application/warc" in metadata_section["description"]

    assert config_section["name"] == "config.json"
    assert config_section["fields"] == {}
    assert "<pre style=" in config_section["description"]
    assert "WGET_ENABLED" in config_section["description"]
    assert '<span style="color: #0550ae;">"properties"</span>' in config_section["description"]

    assert properties_section["name"] == "Config Properties"
    assert properties_section["fields"] == {}
    assert f"/admin/machine/machine/{machine.id}/change/" in properties_section["description"]
    assert "/admin/machine/binary/" in properties_section["description"]
    assert "/admin/environment/binaries/" in properties_section["description"]
    assert "WGET_ENABLED" in properties_section["description"]
    assert "boolean" in properties_section["description"]
    assert "Enable wget archiving" in properties_section["description"]
    assert "/admin/environment/config/WGET_ENABLED/" in properties_section["description"]
    assert "/admin/environment/config/CHECK_SSL_VALIDITY/" in properties_section["description"]
    assert "/admin/environment/config/SAVE_WGET/" in properties_section["description"]
    assert "/admin/environment/binaries/wget/" in properties_section["description"]
    assert "WGET_BINARY" in properties_section["description"]


def test_get_config_definition_link_keeps_core_config_search_link():
    url, label = core_views.get_config_definition_link("CHECK_SSL_VALIDITY")

    assert "github.com/search" in url
    assert "CHECK_SSL_VALIDITY" in url
    assert label == "archivebox/config"


def test_get_config_definition_link_uses_plugin_config_json_for_plugin_options():
    url, label = core_views.get_config_definition_link("PARSE_DOM_OUTLINKS_ENABLED")

    assert url == "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/parse_dom_outlinks/config.json"
    assert label == "abx_plugins/plugins/parse_dom_outlinks/config.json"


def test_live_config_value_view_renames_source_field_and_uses_plugin_definition_link(admin_request):
    context = core_views.live_config_value_view.__wrapped__(
        admin_request("/admin/environment/config/PARSE_DOM_OUTLINKS_ENABLED/"),
        key="PARSE_DOM_OUTLINKS_ENABLED",
    )
    section = context["data"][0]

    assert "Currently read from" in section["fields"]
    assert "Source" not in section["fields"]
    assert section["fields"]["Currently read from"] == "Plugin Default"
    assert "abx_plugins/plugins/parse_dom_outlinks/config.json" in section["help_texts"]["Type"]


def test_live_config_list_view_escapes_machine_config_values(admin_request, machine):
    payload = '</code><script id="config-list-xss">window.__archivebox_config_list_xss__=1</script>'
    machine.config = {"USER_AGENT": payload}
    machine.save(update_fields=["config"])

    context = core_views.live_config_list_view.__wrapped__(admin_request("/admin/environment/config/"))

    keys = [str(item.link_item) for item in context["table"]["Key"]]
    value_cell = str(context["table"]["Value"][keys.index("USER_AGENT")])
    assert '<script id="config-list-xss">' not in value_cell
    assert "&lt;/code&gt;&lt;script id=&quot;config-list-xss&quot;&gt;" in value_cell


def test_live_config_value_view_escapes_machine_config_source_values(admin_request, machine):
    payload = '</code><script id="config-value-xss">window.__archivebox_config_value_xss__=1</script>'
    machine.config = {"USER_AGENT": payload}
    machine.save(update_fields=["config"])

    context = core_views.live_config_value_view.__wrapped__(
        admin_request("/admin/environment/config/USER_AGENT/"),
        key="USER_AGENT",
    )
    section = context["data"][0]

    assert section["fields"]["Currently read from"] == "Machine"
    assert section["fields"]["Value"] == payload
    help_text = str(section["help_texts"]["Value"])
    assert '<script id="config-value-xss">' not in help_text
    assert "&lt;/code&gt;&lt;script id=&quot;config-value-xss&quot;&gt;" in help_text


def test_find_config_source_prefers_machine_over_file(machine):
    machine.config = {"CHECK_SSL_VALIDITY": "true"}
    machine.save(update_fields=["config"])
    CONSTANTS.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONSTANTS.CONFIG_FILE.write_text("[SERVER_CONFIG]\nCHECK_SSL_VALIDITY = true\n")

    assert core_views.find_config_source("CHECK_SSL_VALIDITY", {"CHECK_SSL_VALIDITY": False}) == "Machine"


def test_live_config_value_view_priority_text_matches_runtime_precedence(admin_request, machine):
    machine.config = {"CHECK_SSL_VALIDITY": "true"}
    machine.save(update_fields=["config"])
    CONSTANTS.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONSTANTS.CONFIG_FILE.write_text("[SERVER_CONFIG]\nCHECK_SSL_VALIDITY = true\n")
    context = core_views.live_config_value_view.__wrapped__(
        admin_request("/admin/environment/config/CHECK_SSL_VALIDITY/"),
        key="CHECK_SSL_VALIDITY",
    )
    section = context["data"][0]

    assert section["fields"]["Currently read from"] == "Machine"
    assert section["fields"]["Value"] is True
    help_text = section["help_texts"]["Currently read from"]
    assert help_text.index("Machine") < help_text.index("Environment") < help_text.index("File") < help_text.index("Default")
    assert "Configuration Sources (highest priority first):" in section["help_texts"]["Value"]
