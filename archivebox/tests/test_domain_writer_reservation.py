"""Domain creation reserves its writer before model/config snapshot reads."""

import sqlite3

import pytest
from django.db import connection

from archivebox.domains.forms import DomainCrawlForm
from archivebox.tests.test_domains import clone_data

pytestmark = pytest.mark.django_db(transaction=True)


def test_domain_save_reserves_writer_before_model_reads(admin_user):
    assert connection.vendor == "sqlite"
    connection.ensure_connection()
    with connection.cursor() as cursor:
        assert cursor.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    form = DomainCrawlForm(clone_data(schedule="daily"))
    assert form.is_valid(), form.errors
    previous_mode = connection.transaction_mode
    competing_writer_results = []
    other = sqlite3.connect(connection.settings_dict["NAME"], timeout=0, isolation_level=None)

    def concurrent_commit_after_read(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if not competing_writer_results and sql.lstrip().upper().startswith("SELECT") and connection.in_atomic_block:
            # Real second SQLite connection attempts a daemon-like write after
            # the form has established its read snapshot, before its INSERT.
            try:
                other.execute("UPDATE auth_user SET last_name='concurrent writer' WHERE id=?", (admin_user.pk,))
            except sqlite3.OperationalError as error:
                assert error.sqlite_errorcode == sqlite3.SQLITE_BUSY
                competing_writer_results.append("reserved")
            else:
                competing_writer_results.append("committed")
        return result

    try:
        with connection.execute_wrapper(concurrent_commit_after_read):
            crawl = form.save(admin_user)
        assert competing_writer_results == ["reserved"]
        assert crawl.pk and crawl.crawlschedule_set.count() == 1
        assert connection.transaction_mode == previous_mode
        other.execute("UPDATE auth_user SET last_name='concurrent writer' WHERE id=?", (admin_user.pk,))
    finally:
        other.close()


def test_domain_save_restores_mode_after_database_failure(admin_user):
    from django.db import DataError

    from archivebox.crawls.models import Crawl, CrawlSchedule

    form = DomainCrawlForm(clone_data(schedule="daily"))
    assert form.is_valid(), form.errors
    previous_mode = connection.transaction_mode
    # Exceed the actual SQLite integer range when persisting the Crawl,
    # exercising a real database failure rather than mocking the save path.
    admin_user.pk = 2**100
    with pytest.raises((OverflowError, DataError)):
        form.save(admin_user)
    assert not Crawl.objects.exists()
    assert not CrawlSchedule.objects.exists()
    assert connection.transaction_mode == previous_mode
