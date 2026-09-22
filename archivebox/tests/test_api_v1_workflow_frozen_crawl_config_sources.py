from django.test import RequestFactory

import pytest


pytestmark = pytest.mark.django_db(transaction=True)


SENSITIVE_SECRET = "raw-twocaptcha-secret-for-frozen-crawl-test"


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
