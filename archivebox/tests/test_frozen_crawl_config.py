import time
from types import SimpleNamespace

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


def test_snapshot_config_overlays_frozen_crawl_without_re_reading_persona(archivebox_db):
    from archivebox.config.common import get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    user = _user("frozen-config-snapshot-admin")
    persona = _persona(user, name="Frozen Snapshot Persona", user_agent="Crawl UA")
    crawl = Crawl.objects.create(urls="https://example.com/root", persona=persona, created_by=user, config={"TIMEOUT": 11})
    snapshot = Snapshot.objects.create(
        url="https://example.com/root",
        crawl=crawl,
        config={"TIMEOUT": 22, "ANTHROPIC_API_KEY": "snapshot-secret"},
    )

    persona.config["TIMEOUT"] = 99
    persona.save(update_fields=["config"])

    runtime_config = get_config(crawl=crawl, snapshot=snapshot)
    assert runtime_config.USER_AGENT == "Crawl UA"
    assert runtime_config.TIMEOUT == 22
    assert runtime_config.ANTHROPIC_API_KEY == "snapshot-secret"
    assert snapshot.config == {
        "TIMEOUT": 22,
        "ANTHROPIC_API_KEY": "snapshot-secret",
        "PERMISSIONS": "private",
    }


def test_config_scopes_are_derived_from_section_and_field_metadata():
    from archivebox.config.common import ArchiveBoxConfig

    assert ArchiveBoxConfig.scope_for_key("TIMEOUT") == "crawl_frozen"
    assert ArchiveBoxConfig.scope_for_key("DEBUG") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("DEFAULT_PERSONA") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("WGET_ENABLED") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("SEARCH_BACKEND_SQLITE_ENABLED") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("SEARCH_BACKEND_ENGINE") == "crawl_execution"
    assert ArchiveBoxConfig.scope_for_key("WGET_WARC_ENABLED") == "crawl_frozen"
    assert ArchiveBoxConfig.scope_for_key("SECRET_KEY") == "server"
    assert ArchiveBoxConfig.scope_for_key("DATABASE_NAME") == "server"


def test_search_backend_engine_derives_default_backend_enabled_without_entering_hook_env():
    from archivebox.config.common import ArchiveBoxConfig

    default_runtime_config = ArchiveBoxConfig().for_crawl_runtime(extra_context={"snapshot_id": "default-runtime-config"})
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


def test_plugin_selection_enabled_keys_are_derived_from_plugins_not_frozen_or_env_overridden(archivebox_db, monkeypatch):
    from archivebox.config.common import get_config
    from archivebox.crawls.models import Crawl
    from archivebox.plugins.discovery import get_plugin_special_config

    monkeypatch.setenv("ARCHIVEDOTORG_ENABLED", "False")
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
    env_default_config = get_config(crawl=env_default_crawl, include_machine=False)
    assert env_default_config.ARCHIVEDOTORG_ENABLED is False

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
    runtime_config = get_config(crawl=crawl, include_machine=False)
    assert runtime_config.ARCHIVEDOTORG_ENABLED is True
    assert runtime_config.WGET_ENABLED is False
    assert get_plugin_special_config("archivedotorg", runtime_config)["enabled"] is True
    assert get_plugin_special_config("wget", runtime_config)["enabled"] is False

    monkeypatch.delenv("ARCHIVEDOTORG_ENABLED")

    Crawl.objects.filter(id=crawl.id).update(
        config={
            **crawl.config,
            "ARCHIVEDOTORG_ENABLED": False,
            "YTDLP_ENABLED": True,
            "WGET_ENABLED": True,
        },
    )
    crawl.refresh_from_db()
    stale_runtime_config = get_config(crawl=crawl, include_machine=False)
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
        "for_crawl_frozen": lambda: config.for_crawl_frozen(persona=persona),
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
