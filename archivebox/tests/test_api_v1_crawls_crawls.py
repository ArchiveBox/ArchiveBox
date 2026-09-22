from django.test import RequestFactory

import pytest


pytestmark = pytest.mark.django_db(transaction=True)


def test_create_crawl_api_queues_crawl_without_spawning_runner():
    from django.contrib.auth import get_user_model

    from archivebox.api.v1_crawls import CrawlCreateSchema, create_crawl

    user = get_user_model().objects.create_superuser(
        username="runner-api-admin",
        email="runner-api-admin@example.com",
        password="testpassword",
    )
    request = RequestFactory().post("/api/v1/crawls")
    request.user = user

    crawl = create_crawl(
        request,
        CrawlCreateSchema(
            urls=["https://example.com"],
            max_depth=0,
            tags=[],
            tags_str="",
            label="",
            notes="",
            config={},
        ),
    )

    assert str(crawl.id)
    assert crawl.status == "queued"
    assert crawl.retry_at is not None
    assert crawl.snapshot_set.count() == 0
