from itertools import islice

import pytest

from archivebox.core.models import Snapshot
from archivebox.search.views import iter_meta_search_ids, iter_url_search_prefixes

pytestmark = pytest.mark.django_db(transaction=True)


def test_bare_domain_prefers_real_host_and_www_before_lexical_lookalikes(crawl):
    snapshots = Snapshot.objects.bulk_create(
        [Snapshot(url=f"https://example.com-news.test/{i:03}", crawl=crawl, timestamp=str(1900000000 + i)) for i in range(60)]
        + [
            Snapshot(url=f"https://{host}/{i:03}", crawl=crawl, timestamp=str(1900000100 + i))
            for i, host in enumerate(["example.com", "www.example.com"])
        ],
    )
    direct = {str(item.pk).replace("-", "") for item in snapshots[-2:]}
    queryset = Snapshot.objects.filter(pk__in=[item.pk for item in snapshots])
    result = list(iter_meta_search_ids("example.com", queryset))
    normalized = [str(pk).replace("-", "") for pk in result]
    assert set(normalized[:2]) == direct
    assert len(normalized) == len(snapshots)
    assert set(normalized) == {str(item.pk).replace("-", "") for item in snapshots}
    # Membership intersection still excludes a higher-priority unauthorized row.
    scoped = queryset.exclude(pk=snapshots[-1].pk)
    first = list(islice(iter_meta_search_ids("example.com", scoped), 50))
    assert str(snapshots[-1].pk).replace("-", "") not in {str(pk).replace("-", "") for pk in first}
    assert list(islice(iter_meta_search_ids("example.com", scoped), 50)) == first


def test_non_domain_queries_keep_existing_prefix_order():
    assert list(iter_url_search_prefixes("two words")) == []
    assert list(iter_url_search_prefixes("https://example.com/path")) == [
        "https://example.com/path",
        "https://www.example.com/path",
    ]
    assert list(iter_url_search_prefixes("title")) == [
        "title",
        "https://title",
        "https://www.title",
        "http://title",
        "http://www.title",
    ]
