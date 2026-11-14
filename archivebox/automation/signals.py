"""Record genuine library changes; rule-generated changes cannot recurse."""

from django.db.models.signals import m2m_changed, pre_save, post_save
from django.dispatch import receiver

from archivebox.core.models import Snapshot, Tag
from archivebox.core.signals import snapshot_folders_changed, snapshot_tags_changed
from .service import record_event


@receiver(m2m_changed, sender=Snapshot.tags.through)
def tags_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "pre_clear":
        instance._automation_cleared_tags = (
            list(instance.snapshot_set.values_list("pk", flat=True)) if reverse else list(instance.tags.values_list("name", flat=True))
        )
        return
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    kind = "tag_added" if action == "post_add" else "tag_removed"
    if reverse:
        snapshot_ids = getattr(instance, "_automation_cleared_tags", []) if action == "post_clear" else (pk_set or [])
        for snapshot in Snapshot.objects.filter(pk__in=snapshot_ids):
            record_event(snapshot, kind, {"tags": [instance.name]})
    else:
        tags = (
            getattr(instance, "_automation_cleared_tags", [])
            if action == "post_clear"
            else list(Tag.objects.filter(pk__in=pk_set or []).values_list("name", flat=True))
        )
        if tags:
            record_event(instance, kind, {"tags": tags})


@receiver(pre_save, sender=Snapshot)
def track_folder(sender, instance, update_fields=None, **kwargs):
    instance._automation_track_folder = False
    if instance._state.adding or "folder_id" not in instance.__dict__:
        return
    if update_fields is not None and not {"folder", "folder_id"}.intersection(update_fields):
        return
    instance._automation_previous_folder = Snapshot.objects.filter(pk=instance.pk).values_list("folder_id", flat=True).first()
    instance._automation_track_folder = True


@receiver(post_save, sender=Snapshot)
def folder_changed(sender, instance, created, **kwargs):
    tracked = getattr(instance, "_automation_track_folder", False)
    instance._automation_track_folder = False
    if not tracked:
        return
    before = getattr(instance, "_automation_previous_folder", instance.folder_id)
    if not created and before != instance.folder_id:
        record_event(
            instance,
            "folder_moved",
            {"before": str(before) if before else None, "after": str(instance.folder_id) if instance.folder_id else None},
        )


@receiver(snapshot_folders_changed)
def folders_changed(sender, changes, **kwargs):
    from .models import Rule, RuleEvent
    from .service import _suppress_events
    if _suppress_events.get() or not Rule.objects.filter(enabled=True, trigger='folder_moved').exists():
        return
    RuleEvent.objects.bulk_create([
        RuleEvent(snapshot_id=change['snapshot_id'], kind='folder_moved',
                  details={key: str(change[key]) if change[key] else None for key in ('before', 'after')})
        for change in changes
    ], batch_size=500)



@receiver(snapshot_tags_changed)
def snapshot_tags_updated(sender, changes, **kwargs):
    for change in changes:
        record_event(change["snapshot_id"], change["kind"], {"tags": change["tags"]})
