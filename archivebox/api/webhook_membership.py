"""Folder entry/exit is a difference of the existing snapshot queries, not state."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import m2m_changed, pre_save, post_save, pre_delete, post_delete

_active = ContextVar("folder_membership_change", default=False)


class MembershipChange:
    def __init__(self, snapshot_ids=None, *, deleted=None):
        from archivebox.api.webhook_events import executing_webhook

        if executing_webhook.get():
            self.folder_ids = []
            return
        from archivebox.api.models import OutboundWebhook
        from archivebox.core.models import Snapshot
        from archivebox.core.smart_folders import RuleQuery

        self.folder_ids = list(
            OutboundWebhook.objects.filter(
                enabled=True,
                ref="archivebox.core.models.Snapshot",
                signal__in=["FOLDER_ENTERED", "FOLDER_LEFT"],
                folder_id__isnull=False,
            )
            .order_by()
            .values_list("folder_id", flat=True)
            .distinct(),
        )
        self.deleted = deleted or {}
        self.before = {}
        if not self.folder_ids:
            return
        self.ids = None if snapshot_ids is None else set(snapshot_ids() if callable(snapshot_ids) else snapshot_ids)
        self.compiler = RuleQuery(freeze_limits=True)
        self.queries = {folder_id: self.compiler.folder(folder_id) for folder_id in self.folder_ids}
        candidates = self.ids
        for folder_id, query in self.queries.items():
            matches = Snapshot.objects.filter(query)
            if candidates is not None:
                matches = matches.filter(pk__in=candidates)
            self.before[folder_id] = set(matches.values_list("pk", flat=True))
        # Only a limited folder can change an untouched row's membership when
        # snapshot data changes. Follow the compiler's cache to include limits in
        # nested/referenced folders without inventing a second dependency walker.
        self.has_limits = any((self.compiler.folders[key].rules or {}).get("limit") for key in self.compiler.cache)

    def finish(self):
        if not self.folder_ids:
            return
        from archivebox.core.models import Snapshot
        from archivebox.core.smart_folders import RuleQuery
        from archivebox.api.webhook_events import emit_event

        after_compiler = RuleQuery(freeze_limits=True)
        after_queries = {folder_id: after_compiler.folder(folder_id) for folder_id in self.folder_ids}
        events = []
        for folder_id, query in after_queries.items():
            matches = Snapshot.objects.filter(query)
            if self.ids is not None:
                matches = matches.filter(pk__in=self.ids)
            after = set(matches.values_list("pk", flat=True))
            before = self.before[folder_id]
            left, entered = before - after, after - before
            if self.ids is not None and self.has_limits:
                # Compare frozen ordered windows in SQL for unchanged snapshots.
                # This finds evictions/refills without materializing a million-row
                # playlist or putting its IDs into a giant SQL IN expression.
                untouched = Snapshot.objects.exclude(pk__in=self.ids)
                old_query = self.queries[folder_id]
                left.update(untouched.filter(old_query).exclude(query).values_list("pk", flat=True))
                entered.update(untouched.filter(query).exclude(old_query).values_list("pk", flat=True))
            for signal, ids in (("FOLDER_LEFT", left), ("FOLDER_ENTERED", entered)):
                # Finish all SELECTs before dispatch: webhook actions can perform
                # subprocess/network work and must not retain a database cursor.
                instances = {snapshot.pk: snapshot for snapshot in Snapshot.objects.filter(pk__in=ids)}
                for pk in sorted(ids):
                    instance = instances.get(pk) or self.deleted.get(pk)
                    if instance is not None:
                        events.append((instance, signal, str(folder_id)))
        # An action may itself edit tags/folders. Capture the complete transition
        # first, so earlier subscriptions cannot alter later membership deltas.
        for instance, signal, folder_id in events:
            emit_event(instance, signal, folder_id=folder_id)


@contextmanager
def track_membership(snapshot_ids=None, *, deleted=None):
    if _active.get():
        yield
        return
    token = _active.set(True)
    try:
        change = MembershipChange(snapshot_ids, deleted=deleted)
        yield
    except BaseException:
        raise
    else:
        change.finish()
    finally:
        _active.reset(token)


def related_snapshot_ids(instance):
    """Use the same model relationships the folder predicate compiler exposes."""
    from archivebox.core.models import Snapshot

    label = instance._meta.label_lower
    if label == "core.snapshot":
        return [instance.pk]
    if label in {"core.archiveresult", "core.snapshottag"}:
        return [instance.snapshot_id]
    paths = {"core.tag": "tags", "crawls.crawl": "crawl", "auth.user": "crawl__created_by", "personas.persona": "crawl__persona"}
    if path := paths.get(label):
        return Snapshot.objects.filter(**{path: instance.pk}).values_list("pk", flat=True)
    return None


def before_related_change(sender, instance, raw=False, **kwargs):
    if raw or _active.get():
        return
    if instance._meta.label_lower not in {
        "core.archiveresult",
        "core.snapshottag",
        "core.tag",
        "crawls.crawl",
        "auth.user",
        "personas.persona",
    }:
        return
    instance._folder_membership_change = MembershipChange(lambda: related_snapshot_ids(instance))


def after_related_change(sender, instance, **kwargs):
    change = instance.__dict__.pop("_folder_membership_change", None)
    if change:
        change.finish()


def before_delete(sender, instance, origin=None, **kwargs):
    # Django sends per-row signals around one collector operation. Track its
    # initiating queryset once; through-row cascades must not duplicate leaves.
    if _active.get():
        return
    origin = origin if origin is not None else instance
    model = getattr(origin, "model", type(origin))
    if model is not sender or hasattr(origin, "_folder_membership_delete"):
        return
    label = sender._meta.label_lower
    supported = {
        "core.folder",
        "core.snapshot",
        "core.archiveresult",
        "core.snapshottag",
        "core.tag",
        "crawls.crawl",
        "auth.user",
        "personas.persona",
    }
    if label not in supported:
        return
    deleted = {}
    if hasattr(origin, "model"):
        from archivebox.core.models import Snapshot

        if label == "core.folder":
            ids = None
        elif label == "core.snapshot":
            deleted = {snapshot.pk: snapshot for snapshot in origin}
            ids = list(deleted)
        elif label in {"core.archiveresult", "core.snapshottag"}:
            ids = lambda: origin.values_list("snapshot_id", flat=True)
        else:
            paths = {"core.tag": "tags", "crawls.crawl": "crawl", "auth.user": "crawl__created_by", "personas.persona": "crawl__persona"}
            ids = lambda: Snapshot.objects.filter(**{paths[label] + "__in": origin}).values_list("pk", flat=True)
    else:
        ids = None if label == "core.folder" else lambda: related_snapshot_ids(instance)
        if label == "core.snapshot":
            deleted = {instance.pk: instance}
    origin._folder_membership_delete = MembershipChange(ids, deleted=deleted)


def after_delete(sender, instance, origin=None, **kwargs):
    origin = origin if origin is not None else instance
    if getattr(origin, "model", type(origin)) is not sender:
        return
    change = origin.__dict__.pop("_folder_membership_delete", None)
    if change:
        change.finish()


def tags_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if _active.get():
        return
    if action == "pre_add":

        def affected():
            ids = set(related_snapshot_ids(instance))
            if reverse:
                ids.update(pk_set or ())
            return ids

        instance._folder_membership_m2m = MembershipChange(affected)
    elif action == "post_add":
        change = instance.__dict__.pop("_folder_membership_m2m", None)
        if change:
            change.finish()


def register_membership_signals():
    from archivebox.core.models import Snapshot

    for signal, receiver in (
        (pre_save, before_related_change),
        (post_save, after_related_change),
        (pre_delete, before_delete),
        (post_delete, after_delete),
    ):
        signal.connect(receiver, weak=False, dispatch_uid=f"archivebox.folder_membership.{receiver.__name__}")
    m2m_changed.connect(tags_changed, sender=Snapshot.tags.through, weak=False, dispatch_uid="archivebox.folder_membership.tags")
