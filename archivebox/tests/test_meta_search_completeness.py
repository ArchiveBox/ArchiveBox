import pytest
from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.search.views import iter_meta_search_ids

pytestmark = pytest.mark.django_db(transaction=True)


def test_meta_retains_crawl_only_and_config_only_matches(crawl):
    query = "needlecompleteness"
    direct = Snapshot.objects.create(url="https://direct.example/", title=query, crawl=crawl)
    metadata_crawl = Crawl.objects.create(urls="https://metadata.example/", label=query, created_by=crawl.created_by)
    metadata = Snapshot.objects.create(url="https://metadata.example/", crawl=metadata_crawl)
    config_crawl = Crawl.objects.create(urls="https://config.example/", config={"USER_AGENT": query}, created_by=crawl.created_by)
    config = Snapshot.objects.create(url="https://config.example/", crawl=config_crawl)
    both = Snapshot.objects.create(url="https://both.example/", title=query, crawl=metadata_crawl)
    expected = {direct.pk, metadata.pk, config.pk, both.pk}
    ids = list(iter_meta_search_ids(query, Snapshot.objects.filter(pk__in=expected)))
    assert set(ids) == expected
    assert len(ids) == len(expected)
    assert ids.index(direct.pk) < ids.index(metadata.pk) < ids.index(config.pk)


def test_meta_tag_wave_matches_case_insensitively_inside_the_scope(crawl):
    matching_tag = Tag.objects.create(name="Library_Tag%")
    other_tag = Tag.objects.create(name="LibraryXTagElse")
    earlier = Snapshot.objects.create(url="https://www.python.org/about/", title="Library_Tag%", crawl=crawl)
    tagged = Snapshot.objects.create(url="https://www.python.org/downloads/", crawl=crawl)
    outside = Snapshot.objects.create(url="https://www.python.org/doc/", crawl=crawl)
    decoy = Snapshot.objects.create(url="https://www.python.org/community/", crawl=crawl)
    for snapshot in (earlier, tagged, outside):
        snapshot.tags.add(matching_tag)
    decoy.tags.add(other_tag)

    scope = Snapshot.objects.filter(pk__in=[earlier.pk, tagged.pk, decoy.pk]).order_by("-pk")

    assert list(iter_meta_search_ids("lIBRARY_tAG%", scope)) == [earlier.pk, tagged.pk]
