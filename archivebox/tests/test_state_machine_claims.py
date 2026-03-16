import threading
import time

import pytest
from django.db import close_old_connections
from django.utils import timezone

from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary, Machine
from archivebox.workers.worker import BinaryWorker


def get_fresh_machine() -> Machine:
    import archivebox.machine.models as machine_models

    machine_models._CURRENT_MACHINE = None
    machine_models._CURRENT_BINARIES.clear()
    return Machine.current()


@pytest.mark.django_db
def test_claim_processing_lock_does_not_steal_future_retry_at():
    """
    retry_at is both the schedule and the ownership lock.

    Once one process claims a due row and moves retry_at into the future, a
    fresh reader must not be able to "re-claim" that future timestamp and run
    the same side effects a second time.
    """
    machine = get_fresh_machine()
    binary = Binary.objects.create(
        machine=machine,
        name='claim-test',
        binproviders='env',
        status=Binary.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )

    owner = Binary.objects.get(pk=binary.pk)
    contender = Binary.objects.get(pk=binary.pk)

    assert owner.claim_processing_lock(lock_seconds=30) is True

    contender.refresh_from_db()
    assert contender.retry_at > timezone.now()
    assert contender.claim_processing_lock(lock_seconds=30) is False


@pytest.mark.django_db
def test_binary_worker_skips_binary_claimed_by_other_owner(monkeypatch):
    """
    BinaryWorker must never run install side effects for a Binary whose retry_at
    lock has already been claimed by another process.
    """
    machine = get_fresh_machine()
    binary = Binary.objects.create(
        machine=machine,
        name='claimed-binary',
        binproviders='env',
        status=Binary.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )

    owner = Binary.objects.get(pk=binary.pk)
    assert owner.claim_processing_lock(lock_seconds=30) is True

    calls: list[str] = []

    def fake_run(self):
        calls.append(self.name)
        self.status = self.StatusChoices.INSTALLED
        self.abspath = '/tmp/fake-binary'
        self.version = '1.0'
        self.save(update_fields=['status', 'abspath', 'version', 'modified_at'])

    monkeypatch.setattr(Binary, 'run', fake_run)

    worker = BinaryWorker(binary_id=str(binary.id))
    worker._process_single_binary()

    assert calls == []


@pytest.mark.django_db(transaction=True)
def test_crawl_install_declared_binaries_waits_for_existing_owner(monkeypatch):
    """
    Crawl.install_declared_binaries should wait for the current owner of a Binary
    to finish instead of launching a duplicate install against shared provider
    state such as the npm tree.
    """
    machine = get_fresh_machine()
    crawl = Crawl.objects.create(
        urls='https://example.com',
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )
    binary = Binary.objects.create(
        machine=machine,
        name='puppeteer',
        binproviders='npm',
        status=Binary.StatusChoices.QUEUED,
        retry_at=timezone.now(),
    )

    owner = Binary.objects.get(pk=binary.pk)
    assert owner.claim_processing_lock(lock_seconds=30) is True

    calls: list[str] = []

    def fake_run(self):
        calls.append(self.name)
        self.status = self.StatusChoices.INSTALLED
        self.abspath = '/tmp/should-not-run'
        self.version = '1.0'
        self.save(update_fields=['status', 'abspath', 'version', 'modified_at'])

    monkeypatch.setattr(Binary, 'run', fake_run)

    def finish_existing_install():
        close_old_connections()
        try:
            time.sleep(0.3)
            Binary.objects.filter(pk=binary.pk).update(
                status=Binary.StatusChoices.INSTALLED,
                retry_at=None,
                abspath='/tmp/finished-by-owner',
                version='1.0',
                modified_at=timezone.now(),
            )
        finally:
            close_old_connections()

    thread = threading.Thread(target=finish_existing_install, daemon=True)
    thread.start()
    crawl.install_declared_binaries({'puppeteer'}, machine=machine)
    thread.join(timeout=5)

    binary.refresh_from_db()
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.abspath == '/tmp/finished-by-owner'
    assert calls == []
