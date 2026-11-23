import pytest
from django.contrib.auth import get_user_model

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.services.cache_candidates import cache_candidates


@pytest.mark.django_db(transaction=True)
def test_cache_candidates_isolate_owner_persona_and_find_siblings(admin_user):
    origin = "https://example.test"
    url = origin + "/owner/repo/blob/a"
    persona = Persona.objects.create(name="cache", created_by=admin_user)
    isolated = []
    for who in (admin_user, get_user_model().objects.create_user(username="elsewhere")):
        for profile in (None, persona):
            crawl = Crawl.objects.create(created_by=who, persona=profile, urls=url)
            Snapshot.objects.create(crawl=crawl, url=url, status="sealed")
            if who == admin_user and profile == persona:
                current = crawl
            else:
                isolated.append(crawl)
    for path in ("/owner/repo/issues/1", "/owner/repo", "/", "/owner/repository/foo"):
        Snapshot.objects.create(crawl=current, url=origin + path, status="sealed")
    prior = [
        Snapshot.objects.create(crawl=Crawl.objects.create(created_by=admin_user, persona=persona, urls=url), url=url, status="sealed")
        for _ in range(21)
    ]
    snap = Snapshot.objects.create(crawl=Crawl.objects.create(created_by=admin_user, persona=persona, urls=url), url=url)
    hints = cache_candidates(snap)
    assert [hint["snapdir"].split("/")[-1] for hint in hints[:20]] == [s.pk.hex for s in reversed(prior[-20:])]
    assert {hint["url"] for hint in hints[20:]} >= {origin + "/owner/repo", origin + "/", origin + "/owner/repo/issues/1"}
    for crawl in isolated:
        snap = Snapshot.objects.create(crawl=Crawl.objects.create(created_by=crawl.created_by, persona=crawl.persona, urls=url), url=url)
        assert len(cache_candidates(snap)) == 1


@pytest.mark.django_db(transaction=True)
def test_snapshot_payload_includes_candidate_hints(admin_user):
    import asyncio
    import json
    from asgiref.sync import async_to_sync
    from archivebox.config.constants import CONSTANTS
    from archivebox.services.runner import CrawlRunner

    origin = "https://example.test"
    crawl = Crawl.objects.create(created_by=admin_user, urls=origin)
    sibling = Snapshot.objects.create(crawl=crawl, url=origin + "/files/first", status="sealed")
    snap = Snapshot.objects.create(crawl=crawl, url=origin + "/files/next")
    runner = CrawlRunner(crawl)
    try:
        runner.load_run_state()
        payload = async_to_sync(runner.load_snapshot_payload)(str(snap.id))
        hints = json.loads(payload["config"]["CACHE_CANDIDATES"])
        assert [(hint["url"], CONSTANTS.DATA_DIR / hint["snapdir"]) for hint in hints] == [(sibling.url, sibling.output_dir)]
    finally:
        asyncio.run(runner.bus.destroy(clear=False))
