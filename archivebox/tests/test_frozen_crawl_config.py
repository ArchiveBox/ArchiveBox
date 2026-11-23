import time
from types import SimpleNamespace

from asgiref.sync import async_to_sync

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)


SENSITIVE_SECRET = "raw-twocaptcha-secret-for-frozen-crawl-test"
UPDATED_SECRET = "updated-secret-that-must-not-affect-old-crawl"


@pytest.fixture
def archivebox_db(initialized_archive):
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(initialized_archive):
        yield initialized_archive


def _user(username="frozen-config-admin"):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="testpassword",
    )


def _persona(user, *, name="Frozen Persona", secret=SENSITIVE_SECRET, user_agent="Frozen UA"):
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(
        name=name,
        created_by=user,
        config={
            "PERMISSIONS": "private",
            "USER_AGENT": user_agent,
            "TWOCAPTCHA_API_KEY": secret,
            "DELETE_AFTER": "2h",
        },
    )
    persona.ensure_dirs()
    return persona


def test_crawl_save_freezes_full_raw_persona_config_and_redacts_public_serialization(archivebox_db):
    from archivebox.config.common import SENSITIVE_CONFIG_VALUE_REDACTED, get_config
    from archivebox.crawls.models import Crawl

    user = _user()
    persona = _persona(user)

    crawl = Crawl.objects.create(
        urls="https://example.com/frozen",
        persona=persona,
        created_by=user,
        config={"CRAWL_MAX_CONCURRENT_SNAPSHOTS": 3},
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )

    assert "TIMEOUT" in crawl.config
    assert "CHECK_SSL_VALIDITY" in crawl.config
    assert crawl.config["USER_AGENT"] == "Frozen UA"
    assert "TWOCAPTCHA_API_KEY" not in crawl.config
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 3
    assert "ACTIVE_PERSONA" not in crawl.config
    assert "DEFAULT_PERSONA" not in crawl.config
    assert "CRAWL_DIR" not in crawl.config
    assert "SNAP_DIR" not in crawl.config
    assert "DEBUG" not in crawl.config
    assert "SECRET_KEY" not in crawl.config
    assert "PUBLIC_ADD_VIEW" not in crawl.config
    assert "DATABASE_NAME" not in crawl.config

    persona.config["USER_AGENT"] = "Mutated UA"
    persona.config["TWOCAPTCHA_API_KEY"] = UPDATED_SECRET
    persona.save(update_fields=["config"])

    runtime_config = get_config(crawl=crawl)
    assert runtime_config.USER_AGENT == "Frozen UA"
    assert runtime_config.TWOCAPTCHA_API_KEY == UPDATED_SECRET
    redacted_runtime_config = get_config(crawl=crawl, redact_sensitive=True)
    assert redacted_runtime_config.USER_AGENT == "Frozen UA"
    assert redacted_runtime_config.TWOCAPTCHA_API_KEY == SENSITIVE_CONFIG_VALUE_REDACTED
    execution_config = runtime_config.for_crawl()
    assert execution_config["DEBUG"] is False
    assert "CRAWL_DIR" not in execution_config
    assert "SNAP_DIR" not in execution_config
    assert "SECRET_KEY" not in execution_config
    assert "PUBLIC_ADD_VIEW" not in execution_config
    assert "DATABASE_NAME" not in execution_config

    public_json = crawl.to_json()
    assert "TWOCAPTCHA_API_KEY" not in public_json["config"]
    assert SENSITIVE_SECRET not in str(public_json)


def test_snapshot_config_overlays_frozen_crawl_but_uses_live_persona_credentials(archivebox_db):
    from archivebox.config.common import SENSITIVE_CONFIG_VALUE_REDACTED, get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    user = _user("frozen-config-snapshot-admin")
    persona = _persona(user, name="Frozen Snapshot Persona", user_agent="Crawl UA")
    persona.config["ANTHROPIC_API_KEY"] = "synthetic-original-persona-key"
    persona.save(update_fields=["config"])
    crawl = Crawl.objects.create(urls="https://example.com/root", persona=persona, created_by=user, config={"TIMEOUT": 11})
    snapshot = Snapshot.objects.create(
        url="https://example.com/root",
        crawl=crawl,
        config={"TIMEOUT": 22, "ANTHROPIC_API_KEY": "synthetic-ignored-snapshot-key"},
    )

    assert "ANTHROPIC_API_KEY" not in crawl.config
    persona.config.update(TIMEOUT=99, USER_AGENT="Changed Persona UA", ANTHROPIC_API_KEY="synthetic-rotated-persona-key")
    persona.save(update_fields=["config"])

    runtime_config = get_config(crawl=crawl, snapshot=snapshot)
    assert runtime_config.USER_AGENT == "Crawl UA"
    assert runtime_config.TIMEOUT == 22
    assert runtime_config.ANTHROPIC_API_KEY == "synthetic-rotated-persona-key"
    assert get_config(crawl=crawl, snapshot=snapshot, redact_sensitive=True).ANTHROPIC_API_KEY == SENSITIVE_CONFIG_VALUE_REDACTED
    snapshot.refresh_from_db()
    assert snapshot.config["TIMEOUT"] == 22
    assert snapshot.config["PERMISSIONS"] == "private"


def test_server_config_stays_available_without_entering_crawl_or_snapshot_runtime(archivebox_db):
    from archivebox.config.common import get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine
    from archivebox.workers.runner import CrawlRunner
    import asyncio

    user = _user("config-boundaries-admin")
    server_config = {
        "BIND_ADDR": "127.0.0.1:9292",
        "CSRF_TRUSTED_ORIGINS": "https://admin.archive.example",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    retained = {"BASE_URL": "https://archive.example", "SONIC_DIR": "/tmp/sonic", "OPENCODE_STATE_DIR": "/tmp/opencode"}
    machine = Machine.current()
    machine.config = {**machine.config, **server_config, **retained}
    machine.save(update_fields=["config"])
    persona = _persona(user)
    crawl = Crawl.objects.create(urls="https://example.com", persona=persona, created_by=user, config={"TIMEOUT": 11})
    assert all(get_config()[key] == value for key, value in server_config.items())
    assert not retained.keys() & crawl.config.keys()
    assert not server_config.keys() & crawl.config.keys()
    assert all(get_config(crawl=crawl)[key] == value for key, value in server_config.items())
    crawl.config.update({**server_config, "FAVICON_PROVIDER": "https://example.com/explicit.ico", "CUSTOM_PLUGIN_OPTION": "preserve"})
    crawl.save(update_fields=["config"])
    crawl.refresh_from_db()
    assert not server_config.keys() & crawl.config.keys()
    assert crawl.config["FAVICON_PROVIDER"] == "https://example.com/explicit.ico"
    assert crawl.config["CUSTOM_PLUGIN_OPTION"] == "preserve"

    # Self-archive protection follows the current server, not old crawl metadata.
    from django.core.exceptions import ValidationError

    machine.config = {**machine.config, "BIND_ADDR": "127.0.0.1:9393"}
    machine.save(update_fields=["config"])
    with pytest.raises(ValidationError, match="cannot archive its own"):
        Snapshot.objects.create(url="http://127.0.0.1:9393/admin/", crawl=crawl)
    assert crawl.create_discovered_snapshots(None, [{"url": "http://127.0.0.1:9393/admin/"}], depth=0) == []
    machine.config.update(server_config)
    machine.save(update_fields=["config"])

    # Legacy rows and explicit overrides must pass through the same projection.
    Crawl.objects.filter(pk=crawl.pk).update(config={**crawl.config, **server_config})
    snapshot = Snapshot.objects.create(url="https://example.com", crawl=crawl, config={**server_config, "TIMEOUT": 22})
    runner = CrawlRunner(crawl)
    try:
        runner.load_run_state()
        runtime = async_to_sync(runner.load_snapshot_payload)(str(snapshot.id))["config"]
        assert runtime["TIMEOUT"] == 22
        assert {key: runtime[key] for key in retained} == retained
        assert not server_config.keys() & runtime.keys()
        assert (
            not server_config.keys() & get_config(crawl=crawl, snapshot=snapshot).for_crawl_runtime(runtime_overrides=server_config).keys()
        )
        assert all(get_config()[key] == value for key, value in server_config.items())
    finally:
        asyncio.run(runner.bus.destroy(clear=False))


def test_config_scopes_are_derived_from_section_and_field_metadata():
    from archivebox.config.common import ArchiveBoxConfig

    assert ArchiveBoxConfig.scope_for_key("TIMEOUT") == "crawl_frozen"
    assert ArchiveBoxConfig.scope_for_key("DEBUG") == "server"
    assert ArchiveBoxConfig.scope_for_key("DEFAULT_PERSONA") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("WGET_ENABLED") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("SEARCH_BACKEND_SQLITE_ENABLED") == "server"
    assert ArchiveBoxConfig.scope_for_key("SEARCH_BACKEND_ENGINE") == "server"
    assert ArchiveBoxConfig.scope_for_key("WGET_WARC_ENABLED") == "crawl_frozen"
    assert ArchiveBoxConfig.scope_for_key("SECRET_KEY") == "server"
    assert ArchiveBoxConfig.scope_for_key("DATABASE_NAME") == "server"


def test_search_backend_engine_derives_default_backend_enabled_without_entering_hook_env():
    from archivebox.config.common import ArchiveBoxConfig

    default_config = ArchiveBoxConfig()
    assert default_config.SEARCH_BACKEND_ENGINE == "sonic"

    default_runtime_config = default_config.for_crawl_runtime(extra_context={"snapshot_id": "default-runtime-config"})
    assert default_runtime_config["SEARCH_BACKEND_RIPGREP_ENABLED"] is True
    assert default_runtime_config["SEARCH_BACKEND_SQLITE_ENABLED"] is False
    assert default_runtime_config["SEARCH_BACKEND_SONIC_ENABLED"] is True

    sqlite_runtime_config = ArchiveBoxConfig(SEARCH_BACKEND_ENGINE="sqlite").for_crawl_runtime(
        extra_context={"snapshot_id": "sqlite-runtime-config"},
    )
    assert sqlite_runtime_config["SEARCH_BACKEND_SQLITE_ENABLED"] is True

    config = ArchiveBoxConfig(
        SEARCH_BACKEND_ENGINE="ripgrep",
        SEARCH_BACKEND_SQLITE_ENABLED=False,
        SEARCH_BACKEND_SONIC_ENABLED=True,
        SECRET_KEY="server-secret",
        DATABASE_NAME="server-db.sqlite3",
    )

    runtime_config = config.for_crawl_runtime(extra_context={"snapshot_id": "runtime-config"})

    assert "SEARCH_BACKEND_ENGINE" not in runtime_config
    assert runtime_config["SEARCH_BACKEND_RIPGREP_ENABLED"] is True
    assert runtime_config["SEARCH_BACKEND_SQLITE_ENABLED"] is False
    assert runtime_config["SEARCH_BACKEND_SONIC_ENABLED"] is True
    assert "SECRET_KEY" not in runtime_config
    assert "DATABASE_NAME" not in runtime_config


def test_plugin_selection_enabled_keys_are_derived_from_plugins_not_frozen_or_base_config_overridden(archivebox_db):
    from archivebox.config.common import ArchiveBoxConfig, get_config
    from archivebox.crawls.models import Crawl
    from archivebox.plugins.discovery import get_plugin_special_config

    process_defaults = ArchiveBoxConfig(ARCHIVEDOTORG_ENABLED=False)
    user = _user("frozen-config-enabled-admin")
    persona = _persona(user, name="Enabled Persona")

    env_default_crawl = Crawl(
        urls="https://example.com/env-enabled",
        persona=persona,
        created_by=user,
        config={},
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )
    env_default_crawl.save()
    base_default_config = get_config(crawl=env_default_crawl, include_machine=False, base_config=process_defaults)
    assert base_default_config.ARCHIVEDOTORG_ENABLED is False

    crawl = Crawl(
        urls="https://example.com/enabled",
        persona=persona,
        created_by=user,
        config={"PLUGINS": "archivedotorg", "ARCHIVEDOTORG_ENABLED": True, "DEFAULT_PERSONA": "Other"},
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )
    crawl.save()

    assert crawl.config["PLUGINS"] == "archivedotorg"
    assert "ARCHIVEDOTORG_ENABLED" not in crawl.config
    assert "DEFAULT_PERSONA" not in crawl.config
    runtime_config = get_config(crawl=crawl, include_machine=False, base_config=process_defaults)
    assert runtime_config.ARCHIVEDOTORG_ENABLED is True
    assert runtime_config.WGET_ENABLED is False
    assert get_plugin_special_config("archivedotorg", runtime_config)["enabled"] is True
    assert get_plugin_special_config("wget", runtime_config)["enabled"] is False

    Crawl.objects.filter(id=crawl.id).update(
        config={
            **crawl.config,
            "ARCHIVEDOTORG_ENABLED": False,
            "YTDLP_ENABLED": True,
            "WGET_ENABLED": True,
        },
    )
    crawl.refresh_from_db()
    stale_runtime_config = get_config(crawl=crawl, include_machine=False, base_config=process_defaults)
    assert stale_runtime_config.ARCHIVEDOTORG_ENABLED is True
    assert stale_runtime_config.YTDLP_ENABLED is False
    assert stale_runtime_config.WGET_ENABLED is False


def test_crawl_config_projections_stay_under_hot_path_budget():
    from archivebox.config.common import ArchiveBoxConfig

    config = ArchiveBoxConfig(TIMEOUT=12, USER_AGENT="Perf UA", CHROME_BINARY="perf-chrome")
    persona = SimpleNamespace(
        config={"USER_AGENT": "Persona UA"},
        get_derived_config=lambda: {
            "ACTIVE_PERSONA": "Perf Persona",
            "USER_AGENT": "Persona UA",
            "CHROME_USER_DATA_DIR": "/tmp/persona/chrome",
        },
    )
    crawl = SimpleNamespace(config={"TIMEOUT": 13, "CHROME_BINARY": "crawl-chrome"})
    snapshot = SimpleNamespace(config={"TIMEOUT": 14, "CHROME_BINARY": "snapshot-chrome"})
    runtime_kwargs = {
        "crawl": crawl,
        "snapshot": snapshot,
        "persona": persona,
        "crawl_output_dir": "/tmp/archivebox/crawls/perf",
        "snapshot_output_dir": "/tmp/archivebox/crawls/perf/snapshots/example",
        "extra_context": {"snapshot_id": "perf"},
    }

    methods = {
        "for_crawl": config.for_crawl,
        "for_crawl_frozen": config.for_crawl_frozen,
        "for_crawl_runtime": lambda: config.for_crawl_runtime(**runtime_kwargs),
    }
    iterations = 250
    max_average_seconds = 0.020

    for name, method in methods.items():
        method()
        started_at = time.perf_counter()
        for _ in range(iterations):
            method()
        average_seconds = (time.perf_counter() - started_at) / iterations
        assert average_seconds < max_average_seconds, f"{name} averaged {average_seconds * 1000:.3f}ms"


def test_schedule_enqueue_refreezes_using_current_template_persona_defaults(archivebox_db):
    from archivebox.crawls.models import Crawl, CrawlSchedule

    user = _user("frozen-config-schedule-admin")
    persona = _persona(user, name="Frozen Schedule Persona", user_agent="Initial schedule UA")
    template = Crawl.objects.create(
        urls="https://example.com/scheduled",
        persona=persona,
        created_by=user,
        config={"TIMEOUT": 55, "SECRET_KEY": "template-secret-must-not-freeze", "PUBLIC_ADD_VIEW": True},
        status=Crawl.StatusChoices.PAUSED,
    )
    schedule = CrawlSchedule.objects.create(
        template=template,
        schedule="daily",
        created_by=user,
        config={"TIMEOUT": 55, "SECRET_KEY": "schedule-secret-must-not-freeze", "PUBLIC_ADD_VIEW": True},
    )

    assert schedule.config["TIMEOUT"] == 55
    assert "SECRET_KEY" in schedule.config

    persona.config["USER_AGENT"] = "Current schedule UA"
    persona.config["TWOCAPTCHA_API_KEY"] = UPDATED_SECRET
    persona.save(update_fields=["config"])

    child = schedule.enqueue()
    assert child.config["TIMEOUT"] == 55
    assert child.config["USER_AGENT"] == "Current schedule UA"
    assert "TWOCAPTCHA_API_KEY" not in child.config
    assert "SECRET_KEY" not in child.config
    assert "PUBLIC_ADD_VIEW" not in child.config
    assert template.config["USER_AGENT"] == "Initial schedule UA"
    assert "TWOCAPTCHA_API_KEY" not in template.config


def test_crawl_config_backfill_migration_uses_frozen_config_helper(archivebox_db):
    import importlib

    from django.apps import apps
    from django.db import connection

    from archivebox.crawls.models import Crawl

    migration = importlib.import_module("archivebox.crawls.migrations.0018_freeze_crawl_config_snapshots")
    user = _user("frozen-config-migration-admin")
    persona = _persona(user, name="Migration Persona", user_agent="Migration UA")
    crawl = Crawl(
        urls="https://example.com/migration",
        persona=persona,
        created_by=user,
        config={"TIMEOUT": 44, "CHROME_BINARY": "migration-chrome"},
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )
    crawl.save()

    Crawl.objects.filter(id=crawl.id).update(config={"TIMEOUT": 44, "CHROME_BINARY": "migration-chrome"})
    migration.freeze_existing_crawl_configs(apps, SimpleNamespace(connection=connection))

    crawl.refresh_from_db()
    assert crawl.config["TIMEOUT"] == 44
    assert "CHROME_BINARY" not in crawl.config
    assert crawl.config["USER_AGENT"] == "Migration UA"
    assert "TWOCAPTCHA_API_KEY" not in crawl.config
    assert "ACTIVE_PERSONA" not in crawl.config
    assert "DEFAULT_PERSONA" not in crawl.config
    assert "CRAWL_DIR" not in crawl.config
    assert "SNAP_DIR" not in crawl.config
    assert "SECRET_KEY" not in crawl.config


def test_host_config_does_not_follow_persona_crawl_or_snapshot(archivebox_db):
    import json
    import sys
    from django.test import Client

    from abx_dl.config import dump_to_dotenv_format
    from abx_dl.models import PluginEnv
    from archivebox.config.common import filter_crawl_env, get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine

    admin = _user("settings-scope-admin")
    machine = Machine.current()
    machine_keys = {"BASE_URL": "https://machine.example", "DEBUG": True, "USE_COLOR": True, "SHOW_PROGRESS": True}
    stale_values = {
        "BASE_URL": "https://old-crawl.example",
        "DEBUG": False,
        "USE_COLOR": False,
        "SHOW_PROGRESS": False,
        "IS_TTY": not sys.stdout.isatty(),
        "IN_DOCKER": True,
        "IN_QEMU": True,
        "ANSI": {"reset": "legacy"},
    }
    machine.config = {**machine.config, **machine_keys, **{k: stale_values[k] for k in ("IS_TTY", "ANSI")}}
    machine.save(update_fields=["config"])
    persona = _persona(admin)
    persona.config.update(stale_values)
    persona.save(update_fields=["config"])
    crawl = Crawl.objects.create(
        urls="https://example.com/settings-scope",
        persona=persona,
        created_by=admin,
        config={"TIMEOUT": 11, **stale_values},
    )
    assert not stale_values.keys() & crawl.config.keys()

    # Re-create a legacy row without invoking normal config snapshot logic.
    old_crawl_config = {**crawl.config, **stale_values}
    Crawl.objects.filter(pk=crawl.pk).update(config=old_crawl_config)
    crawl.refresh_from_db()
    crawl.save(update_fields=["label"])
    crawl.refresh_from_db()
    assert crawl.config == old_crawl_config
    snapshot = Snapshot.objects.create(url="https://example.com/settings-scope", crawl=crawl, config={"TIMEOUT": 22, **stale_values})
    current = get_config(machine=machine)
    assert current.IS_TTY is sys.stdout.isatty()
    assert current.ANSI != stale_values["ANSI"]

    effective = get_config(crawl=crawl, snapshot=snapshot, machine=machine)
    assert effective.TIMEOUT == 22 and effective.USER_AGENT == "Frozen UA"
    hook = effective.for_crawl_runtime(crawl=crawl, snapshot=snapshot, persona=persona, runtime_overrides=stale_values)
    assert {key: hook[key] for key in stale_values} == {key: current[key] for key in stale_values}
    assert {key: hook[key] for key in machine_keys} == machine_keys
    wire_env = filter_crawl_env(PluginEnv.from_config(hook, run_output_dir=snapshot.output_dir).to_env())
    assert {key: wire_env[key] for key in stale_values} == {key: dump_to_dotenv_format(current[key]) for key in stale_values}

    from archivebox.machine.forms import MachineAdminForm

    machine_form = MachineAdminForm(instance=machine)
    groups = {
        card["name"]: card["config_fields"] for group in machine_form.plugin_groups for card in group["plugins"] if card.get("is_core")
    }
    for key in machine_keys:
        assert key not in {field["key"] for field in groups["crawl_defaults"]}
        assert key in {field["key"] for field in groups["server"]}
    for key in set(stale_values) - machine_keys.keys():
        assert key not in {field["key"] for field in groups["server"]}

    client = Client(HTTP_HOST="machine.example")
    client.force_login(admin)
    for path in (f"/admin/personas/persona/{persona.pk}/change/", f"/admin/crawls/crawl/{crawl.pk}/change/"):
        response = client.get(path)
        assert response.status_code == 200
        html = response.content.decode()
        for key in stale_values:
            assert f'value="{key}"' not in html
            assert f'plugin_config__archivebox__{key}"' not in html

    changed = client.post(
        f"/admin/personas/persona/{persona.pk}/change/",
        {
            "name": persona.name,
            "created_by": str(admin.pk),
            "permissions": "private",
            "config": json.dumps({"BASE_URL": "https://forged.example", "TIMEOUT": 41}),
            "import_mode": "none",
            "_save": "Save",
        },
    )
    assert changed.status_code == 302
    persona.refresh_from_db()
    assert persona.config["TIMEOUT"] == 41
    assert {key: persona.config[key] for key in stale_values} == stale_values

    details = client.get("/admin/environment/config/ANSI/")
    assert details.status_code == 200
    assert "read-only, calculated at runtime" in details.content.decode()
    assert "Edit <code>ANSI</code> in Machine.config" not in details.content.decode()


def test_open_code_and_search_are_system_settings_without_removing_base_capture_fields(archivebox_db):
    from archivebox.config.common import ArchiveBoxConfig, get_config, host_config_keys
    from archivebox.crawls.models import Crawl
    from archivebox.machine.forms import MachineAdminForm
    from archivebox.machine.models import Machine
    from archivebox.personas.forms import PersonaAdminForm

    admin = _user("service-settings-admin")
    machine = Machine.current()
    settings = {
        "OPENCODE_ENABLED": True,
        "OPENCODE_PORT": 4503,
        "OPENCODE_STATE_DIR": "/tmp/opencode-service",
        "SEARCH_BACKEND_ENGINE": "sqlite",
        "SEARCH_BACKEND_SQLITE_ENABLED": True,
        "SEARCH_BACKEND_SONIC_ENABLED": False,
        "SEARCH_BACKEND_RIPGREP_ENABLED": False,
        "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.2",
    }
    machine.config = {**machine.config, **settings}
    machine.save(update_fields=["config"])
    persona = _persona(admin, name="Service scope persona")
    legacy = {
        "OPENCODE_ENABLED": False,
        "OPENCODE_PORT": 4502,
        "OPENCODE_STATE_DIR": "/tmp/legacy-persona",
        "SEARCH_BACKEND_ENGINE": "ripgrep",
        "SEARCH_BACKEND_SQLITE_ENABLED": False,
        "SEARCH_BACKEND_SONIC_ENABLED": True,
        "SEARCH_BACKEND_RIPGREP_ENABLED": True,
        "SONIC_HOST": "legacy.example",
    }
    persona.config.update(legacy)
    persona.save(update_fields=["config"])
    crawl = Crawl.objects.create(
        urls="https://example.com/service-settings",
        persona=persona,
        config={**legacy, "PLUGINS": "title", "TIMEOUT": 61},
    )
    assert not legacy.keys() & crawl.config.keys()
    Crawl.objects.filter(pk=crawl.pk).update(config={**crawl.config, **legacy})
    crawl.refresh_from_db()
    effective = get_config(crawl=crawl)
    assert effective.TIMEOUT == 61
    assert {key: effective[key] for key in settings} == settings
    wire = effective.for_crawl_runtime(crawl=crawl, runtime_overrides=legacy)
    assert "SEARCH_BACKEND_ENGINE" not in wire
    assert {key: wire[key] for key in set(settings) - {"SEARCH_BACKEND_ENGINE"}} == {
        key: value for key, value in settings.items() if key != "SEARCH_BACKEND_ENGINE"
    }
    assert ArchiveBoxConfig.scope_for_key("NODE_BINARY") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("GIT_BINARY") == "crawl_execution"
    assert "NODE_V8_COVERAGE" not in host_config_keys()

    def fields(form):
        return {card["name"]: card["config_fields"] for group in form.plugin_groups for card in group["plugins"] if card["config_fields"]}

    persona_cards = fields(PersonaAdminForm(instance=persona))
    machine_cards = fields(MachineAdminForm(instance=machine))
    names = {"opencode", "search_backend_sqlite", "search_backend_sonic", "search_backend_ripgrep"}
    assert not names & persona_cards.keys()
    assert names <= machine_cards.keys()
    assert {field["key"] for field in persona_cards["base"]} >= {"TIMEOUT", "MEMORY_LIMIT", "MEMORY_MIN_FREE", "USER_AGENT"}
    for groups in (persona_cards, machine_cards):
        assert next(field for field in groups["base"] if field["key"] == "NODE_V8_COVERAGE")["advanced"]
