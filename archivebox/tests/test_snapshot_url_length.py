"""Tests for very long Snapshot URLs.

ArchiveBox supports URLs up to MAX_URL_LENGTH chars. The url column is stored as a
variable-length TextField (so short URLs don't reserve the full max length) but stays fully
indexed, so exact, prefix, and substring lookups all keep working for long URLs.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from archivebox.misc.util import MAX_URL_LENGTH, validate_url, validate_url_length

pytestmark = pytest.mark.django_db


def _make_long_url(length: int, *, needle: str = "", prefix: str = "https://example.com/") -> str:
    """Build a valid http URL of exactly `length` chars, optionally embedding a needle near the end."""
    assert length >= len(prefix) + len(needle)
    filler = "a" * (length - len(prefix) - len(needle))
    url = prefix + filler + needle
    assert len(url) == length, (len(url), length)
    return url


def test_max_url_length_constant():
    assert MAX_URL_LENGTH == 65535


def test_validate_url_length_accepts_exactly_max():
    url = _make_long_url(MAX_URL_LENGTH)
    assert validate_url_length(url) == url
    # full validate_url (scheme + hostname checks) should also pass at the limit
    assert validate_url(url) == url


def test_validate_url_strips_outer_newlines_but_rejects_internal_newlines():
    assert validate_url("\nhttps://example.com\r\n") == "https://example.com"
    with pytest.raises(ValueError, match="single line"):
        validate_url("https://example.com\nhttps://example.org")


def test_validate_url_length_rejects_over_max():
    url = _make_long_url(MAX_URL_LENGTH + 1)
    with pytest.raises(ValueError, match="too long"):
        validate_url_length(url)


def test_snapshot_persists_full_long_url(crawl):
    from archivebox.core.models import Snapshot

    long_url = _make_long_url(MAX_URL_LENGTH, needle="ENDNEEDLE")
    snapshot = Snapshot.objects.create(url=long_url, crawl=crawl)

    # Round-trip through the DB to make sure nothing was truncated.
    reloaded = Snapshot.objects.get(pk=snapshot.pk)
    assert reloaded.url == long_url
    assert len(reloaded.url) == MAX_URL_LENGTH


def test_long_url_exact_prefix_and_substring_lookups(crawl):
    from archivebox.core.models import Snapshot

    long_url = _make_long_url(MAX_URL_LENGTH, needle="ENDNEEDLE")
    Snapshot.objects.create(url=long_url, crawl=crawl)

    # exact match
    assert Snapshot.objects.filter(url=long_url).count() == 1
    # prefix match (uses the index)
    assert Snapshot.objects.filter(url__startswith="https://example.com/").filter(url=long_url).exists()
    # substring search (the common case for URL search in admin/CLI/API)
    assert Snapshot.objects.filter(url__icontains="ENDNEEDLE").count() == 1
    assert Snapshot.objects.filter(url__contains="ENDNEEDLE").get().url == long_url


def test_snapshot_rejects_url_over_max(crawl):
    from archivebox.core.models import Snapshot

    too_long = _make_long_url(MAX_URL_LENGTH + 1)
    with pytest.raises(ValidationError):
        Snapshot.objects.create(url=too_long, crawl=crawl)


def test_long_url_uniqueness_still_enforced_per_crawl(crawl, admin_user):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    long_url = _make_long_url(MAX_URL_LENGTH, needle="DUP")
    Snapshot.objects.create(url=long_url, crawl=crawl)

    # Same long URL in the same crawl is rejected by the (url, crawl) unique constraint.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Snapshot.objects.create(url=long_url, crawl=crawl)

    # ...but the same long URL is allowed in a different crawl.
    other_crawl = Crawl.objects.create(urls=long_url, created_by=admin_user)
    other = Snapshot.objects.create(url=long_url, crawl=other_crawl)
    assert other.url == long_url
