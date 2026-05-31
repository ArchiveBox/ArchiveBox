import pytest
from django.test import RequestFactory
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
    assert crawl.config["TWOCAPTCHA_API_KEY"] == SENSITIVE_SECRET
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 3
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
    assert runtime_config.TWOCAPTCHA_API_KEY == SENSITIVE_SECRET
    execution_config = runtime_config.for_crawl()
    assert execution_config["DEBUG"] is False
    assert execution_config["CRAWL_DIR"] == str(crawl.output_dir)
    assert "SECRET_KEY" not in execution_config
    assert "PUBLIC_ADD_VIEW" not in execution_config
    assert "DATABASE_NAME" not in execution_config

    public_json = crawl.to_json()
    assert public_json["config"]["TWOCAPTCHA_API_KEY"] == SENSITIVE_CONFIG_VALUE_REDACTED
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
    assert snapshot.config == {"TIMEOUT": 22, "ANTHROPIC_API_KEY": "snapshot-secret"}


def test_config_scopes_are_derived_from_section_and_field_metadata():
    from archivebox.config.common import ArchiveBoxConfig

    assert ArchiveBoxConfig.scope_for_key("TIMEOUT") == "crawl"
    assert ArchiveBoxConfig.scope_for_key("DEBUG") == "runtime"
    assert ArchiveBoxConfig.scope_for_key("CRAWL_DIR") == "runtime"
    assert ArchiveBoxConfig.scope_for_key("SECRET_KEY") == "system"
    assert ArchiveBoxConfig.scope_for_key("DATABASE_NAME") == "system"


def test_api_create_and_cli_add_store_full_frozen_config(archivebox_db):
    from archivebox.api.v1_crawls import CrawlCreateSchema, CrawlSchema, create_crawl
    from archivebox.cli.archivebox_add import add
    from archivebox.config.common import SENSITIVE_CONFIG_VALUE_REDACTED

    user = _user("frozen-config-api-admin")
    request = RequestFactory().post("/api/v1/crawls")
    request.user = user

    api_crawl = create_crawl(
        request,
        CrawlCreateSchema(
            urls=["https://example.com/api"],
            max_depth=0,
            tags=[],
            tags_str="",
            label="API frozen config",
            notes="",
            config={"TWOCAPTCHA_API_KEY": SENSITIVE_SECRET, "TIMEOUT": 33, "SECRET_KEY": "must-not-freeze", "PUBLIC_ADD_VIEW": True},
        ),
    )
    assert "CHECK_SSL_VALIDITY" in api_crawl.config
    assert api_crawl.config["TIMEOUT"] == 33
    assert api_crawl.config["TWOCAPTCHA_API_KEY"] == SENSITIVE_SECRET
    assert "SECRET_KEY" not in api_crawl.config
    assert "PUBLIC_ADD_VIEW" not in api_crawl.config
    assert CrawlSchema.resolve_config(api_crawl)["TWOCAPTCHA_API_KEY"] == SENSITIVE_CONFIG_VALUE_REDACTED

    cli_crawl, _snapshots = add(
        "https://example.com/cli",
        bg=True,
        created_by_id=user.pk,
        config={"TWOCAPTCHA_API_KEY": SENSITIVE_SECRET, "TIMEOUT": 44},
    )
    assert "CHECK_SSL_VALIDITY" in cli_crawl.config
    assert cli_crawl.config["TIMEOUT"] == 44
    assert cli_crawl.config["TWOCAPTCHA_API_KEY"] == SENSITIVE_SECRET


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
    schedule = CrawlSchedule.objects.create(template=template, schedule="daily", created_by=user)

    persona.config["USER_AGENT"] = "Current schedule UA"
    persona.config["TWOCAPTCHA_API_KEY"] = UPDATED_SECRET
    persona.save(update_fields=["config"])

    child = schedule.enqueue()
    assert child.config["TIMEOUT"] == 55
    assert child.config["USER_AGENT"] == "Current schedule UA"
    assert child.config["TWOCAPTCHA_API_KEY"] == UPDATED_SECRET
    assert "SECRET_KEY" not in child.config
    assert "PUBLIC_ADD_VIEW" not in child.config
    assert template.config["USER_AGENT"] == "Initial schedule UA"
    assert template.config["TWOCAPTCHA_API_KEY"] == SENSITIVE_SECRET
