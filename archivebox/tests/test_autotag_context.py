import asyncio
import json

import pytest
from asgiref.sync import async_to_sync

pytestmark = pytest.mark.django_db(transaction=True)


def test_runner_supplies_only_the_owners_existing_tags(admin_user):
    from django.contrib.auth.models import User
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import CrawlRunner

    other = User.objects.create_user(username="other-tag-owner")
    own = Tag.objects.create(name="Hacker News", created_by=admin_user)
    shared = Tag.objects.create(name="Programming", created_by=other)
    private = Tag.objects.create(name="Other user's private tag", created_by=other)
    crawl = Crawl.objects.create(
        urls="https://news.ycombinator.com/",
        created_by=admin_user,
        config={"PLUGINS": "autotag", "AUTOTAG_ENABLED": True, "AUTOTAG_EXISTING_TAGS": [private.name]},
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    snapshot.tags.add(shared)
    runner = CrawlRunner(crawl, config_overrides={"AUTOTAG_EXISTING_TAGS": [private.name]})
    try:
        runner.load_run_state()
        payload = async_to_sync(runner.load_snapshot_payload)(str(snapshot.pk), prepare=False)
        assert set(payload["config"]["AUTOTAG_EXISTING_TAGS"]) == {own.name, shared.name}
        from abx_dl.config import GlobalConfig, RuntimeConfig, get_plugin_env

        plugin_env = async_to_sync(get_plugin_env)(
            runner.bus,
            plugin=runner.catalog["autotag"],
            run_output_dir=snapshot.output_dir,
            config=RuntimeConfig(user=GlobalConfig(**payload["config"]), derived={}),
        ).to_env()
        assert set(json.loads(plugin_env["AUTOTAG_EXISTING_TAGS"])) == {own.name, shared.name}
        assert json.loads(payload["config"]["EXTRA_CONTEXT"]) == {"snapshot_id": str(snapshot.pk)}
        other_crawl = Crawl.objects.create(urls=crawl.urls, created_by=other, config={"PLUGINS": "autotag", "AUTOTAG_ENABLED": True})
        other_snapshot = Snapshot.objects.create(url=crawl.urls, crawl=other_crawl)
        other_payload = async_to_sync(runner.load_snapshot_payload)(str(other_snapshot.pk), prepare=False)
        assert set(other_payload["config"]["AUTOTAG_EXISTING_TAGS"]) == {shared.name, private.name}
        assert own.name not in other_payload["config"]["AUTOTAG_EXISTING_TAGS"]
    finally:
        asyncio.run(runner.bus.destroy(clear=False))


@pytest.mark.parametrize("prefix", ["Topic", "界" * 95])
def test_runner_bounds_existing_tag_count_and_environment_bytes(admin_user, prefix):
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import CrawlRunner

    Tag.objects.bulk_create([Tag(name=f"{prefix}{index:03}", created_by=admin_user) for index in range(150)])
    crawl = Crawl.objects.create(
        urls="https://news.ycombinator.com/",
        created_by=admin_user,
        config={"PLUGINS": "autotag", "AUTOTAG_ENABLED": True},
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    runner = CrawlRunner(crawl)
    try:
        runner.load_run_state()
        payload = async_to_sync(runner.load_snapshot_payload)(str(snapshot.pk), prepare=False)
        names = payload["config"]["AUTOTAG_EXISTING_TAGS"]
        assert 0 < len(names) <= 128
        assert len(json.dumps(names).encode()) <= 12_288
        if prefix == "Topic":
            assert len(names) == 128
        else:
            assert len(names) < 128
    finally:
        asyncio.run(runner.bus.destroy(clear=False))


def test_emitted_tags_belong_to_the_snapshot_owner(admin_user):
    from abx_dl.events import TagEvent
    from abx_dl.orchestrator import create_bus
    from django.contrib.auth.models import User
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.services.tag_service import TagService

    owner = User.objects.create_user(username="generated-tag-owner")
    other = User.objects.create_user(username="existing-tag-owner")
    reused = Tag.objects.create(name="Programming", created_by=other)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=owner)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    bus = create_bus(name="test_autotag_owner")
    TagService(bus)

    async def emit():
        try:
            for name in ("Hacker News", reused.name):
                event = bus.emit(TagEvent(name=name, snapshot_id=str(snapshot.pk)))
                await event.now()
                await event.wait()
                await event.event_results_list()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(emit())
    assert Tag.objects.get(name="Hacker News").created_by_id == owner.pk
    reused.refresh_from_db()
    assert reused.created_by_id == other.pk
    assert set(snapshot.tags.values_list("name", flat=True)) == {"Hacker News", reused.name}


def test_existing_tag_context_is_not_an_editable_plugin_setting():
    from django.http import QueryDict
    from archivebox.personas.forms import PersonaAdminForm

    data = QueryDict(mutable=True)
    data["plugin_config__autotag__AUTOTAG_EXISTING_TAGS"] = '["untrusted vocabulary"]'
    form = PersonaAdminForm(data=data)
    fields = [field for group in form.plugin_groups for plugin in group["plugins"] for field in plugin["config_fields"]]
    assert "AUTOTAG_EXISTING_TAGS" not in {field["key"] for field in fields}
    assert "AUTOTAG_EXISTING_TAGS" not in form.clean_plugin_config_overrides()
    from archivebox.config.common import redact_sensitive_config

    assert redact_sensitive_config({"AUTOTAG_EXISTING_TAGS": ["private vocabulary"]}) == {"AUTOTAG_EXISTING_TAGS": "********"}
