"""ArchiveBox lifecycle signals delivered through the existing webhook handler."""

from contextvars import ContextVar
from contextlib import contextmanager
import os

from django.db import transaction
from django.db.models import Q
from signal_webhooks.handlers import default_hook_handler
from signal_webhooks.settings import webhook_settings
from signal_webhooks.typing import SignalChoices
from signal_webhooks.utils import model_from_reference, get_webhook_model, reference_for_model


# A sequence may save models and its Process logs. Those writes must not start
# the same subscription recursively (including callbacks scheduled on commit).
executing_webhook = ContextVar("executing_webhook", default=False)
active_relationship: ContextVar[str] = ContextVar("webhook_relationship", default="")
RELATIONSHIP_EVENTS = {"M2M_ADD", "M2M_REMOVE", "M2M_CLEAR"}
TAG_EVENTS = {"TAGGED", "UNTAGGED"}


def relationship_fields(model):
    # A forward field identifies the actual relation of the object initiating
    # the operation. Existing generic subscriptions also receive reverse events.
    return model._meta.many_to_many


@contextmanager
def relationship_context(name):
    token = active_relationship.set(name)
    try:
        yield
    finally:
        active_relationship.reset(token)


def emit_relationship_event(instance, signal, relationship):
    from signal_webhooks.handlers import webhook_handler

    with relationship_context(relationship):
        webhook_handler(instance=instance, method=signal)


def dispatch_relationship_signal(sender, instance, reverse, model, **kwargs):
    from signal_webhooks.handlers import webhook_m2m_handler

    names = (
        [
            field.name
            for field in relationship_fields(type(instance))
            if field.remote_field.through is sender and field.related_model is model
        ]
        if not reverse
        else []
    )
    with relationship_context(names[0] if len(names) == 1 else ""):
        webhook_m2m_handler(sender, instance=instance, reverse=reverse, model=model, **kwargs)


def snapshot_tag_rules(signal, tag_ids=None):
    from archivebox.core.models import Snapshot

    rules = get_webhook_model().objects.filter(ref=reference_for_model(Snapshot), signal=signal, enabled=True)
    if tag_ids is not None:
        rules = rules.filter(Q(tag_id__in=tag_ids) | Q(any_tag=True))
    return rules


def emit_snapshot_tag_events(snapshot, signal, tag_ids):
    """Emit one event for each changed tag link."""
    from archivebox.core.models import Tag

    if not tag_ids or action_in_progress():
        return
    scopes = set(snapshot_tag_rules(signal, tag_ids).values_list("tag_id", flat=True))
    if not scopes:
        return
    tags = list(Tag.objects.filter(pk__in=tag_ids if None in scopes else scopes).order_by("pk").values_list("pk", "name"))
    for tag_id, tag_name in tags:
        emit_event(snapshot, signal, tag_id=tag_id, tag_name=tag_name)


def snapshot_tags_added(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "post_add" or not pk_set or action_in_progress():
        return
    if reverse:
        if snapshot_tag_rules("TAGGED", [instance.pk]).exists():
            from archivebox.core.models import Snapshot

            for snapshot in list(Snapshot.objects.filter(pk__in=pk_set)):
                emit_event(snapshot, "TAGGED", tag_id=instance.pk, tag_name=instance.name)
    else:
        emit_snapshot_tag_events(instance, "TAGGED", pk_set)


def snapshot_tag_deleted(sender, instance, origin, **kwargs):
    # Related-manager remove/clear deletes through rows via the collector.
    # Cascades from a deleted Tag or Snapshot have their own handlers.
    if getattr(origin, "model", type(origin)) is not sender or action_in_progress():
        return
    if snapshot_tag_rules("UNTAGGED", [instance.tag_id]).exists():
        emit_event(instance.snapshot, "UNTAGGED", tag_id=instance.tag_id, tag_name=instance.tag.name)


def before_tag_delete(sender, instance, **kwargs):
    # Specific subscriptions are deleted with their tag. Capture the links
    # once for wildcard subscriptions while the tag and its name still exist.
    instance.__dict__.pop("_untagged_snapshots", None)
    if not action_in_progress() and snapshot_tag_rules("UNTAGGED").filter(any_tag=True).exists():
        instance._untagged_snapshots = list(instance.snapshot_set.values_list("pk", flat=True))


def after_tag_delete(sender, instance, **kwargs):
    from archivebox.core.models import Snapshot

    if snapshot_ids := instance.__dict__.pop("_untagged_snapshots", None):
        for snapshot in Snapshot.objects.in_bulk(snapshot_ids).values():
            emit_event(snapshot, "UNTAGGED", tag_id=instance.pk, tag_name=instance.name)


def register_relationship_signals():
    from django.db.models.signals import m2m_changed, post_delete, pre_delete
    from archivebox.core.models import SnapshotTag, Tag

    # The library otherwise discards the sender before its task handler runs.
    # Delegate once to the same library receiver with context attached.
    m2m_changed.disconnect(dispatch_uid=webhook_settings.DISPATCH_UID_M2M_CHANGED)
    m2m_changed.connect(dispatch_relationship_signal, weak=False, dispatch_uid="archivebox.webhook_relationship")
    m2m_changed.connect(snapshot_tags_added, sender=SnapshotTag, weak=False, dispatch_uid="archivebox.webhook_tags_added")
    post_delete.connect(snapshot_tag_deleted, sender=SnapshotTag, weak=False, dispatch_uid="archivebox.webhook_tag_deleted")
    pre_delete.connect(before_tag_delete, sender=Tag, weak=False, dispatch_uid="archivebox.webhook_before_tag_delete")
    post_delete.connect(after_tag_delete, sender=Tag, weak=False, dispatch_uid="archivebox.webhook_after_tag_delete")


def action_in_progress():
    # Process.launch passes provenance to child Python/shell environments too.
    return executing_webhook.get() or bool(os.environ.get("ARCHIVEBOX_WEBHOOK_ID"))


class WebhookActionMiddleware:
    """Preserve the same recursion boundary for authenticated self-API actions."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.core import signing

        token = None
        if signature := request.headers.get("X-ArchiveBox-Webhook"):
            try:
                # Ordinary API authentication still runs. Only a server-signed
                # marker can suppress action-generated events; an arbitrary
                # request header must never disable subscriptions.
                signing.loads(signature, salt="archivebox.webhook-action", max_age=120)
                token = executing_webhook.set(True)
            except signing.BadSignature:
                pass
        try:
            return self.get_response(request)
        finally:
            if token is not None:
                executing_webhook.reset(token)


EVENTS = {
    "CREATE": dict(label="Created", icon="plus", color="#377b5b"),
    "BEFORE_QUEUE": dict(label="Before queuing", icon="queue", color="#967338", section=True, blocking=True),
    "BEFORE_CAPTURE": dict(label="Before capture", icon="capture", color="#597bab", blocking=True),
    "CAPTURE_COMPLETED": dict(label="Capture completed", icon="complete", color="#377b5b"),
    "TAGGED": dict(label="Tagged", icon="plus", color="#377b5b", tag=True),
    "UNTAGGED": dict(label="Untagged", icon="leave", color="#9d618f", tag=True),
    "FOLDER_ENTERED": dict(label="Added to folder", icon="folder", color="#9d618f", membership=True),
    "FOLDER_LEFT": dict(label="Removed from folder", icon="leave", color="#9d618f", membership=True),
    "STARTED": dict(label="Started", icon="play", color="#597bab"),
    "COMPLETED": dict(label="Completed", icon="complete", color="#377b5b"),
    "EXITED": dict(label="Exited", icon="complete", color="#377b5b"),
    "M2M_ADD": dict(label="Relationship added", icon="plus", color="#377b5b", relationship=True),
    "M2M_REMOVE": dict(label="Relationship removed", icon="leave", color="#9d618f", relationship=True),
    "M2M_CLEAR": dict(label="Relationships cleared", icon="leave", color="#9d618f", relationship=True),
    "UPDATE": dict(label="Updated", icon="update", color="#547caa", section=True),
    "DELETE": dict(label="Deleted", icon="delete", color="#b3495a"),
}


def event_options(model, event):
    return {
        "label": event.replace("_", " ").capitalize(),
        "icon": "bolt",
        "color": "#597bab",
        **EVENTS.get(event, {}),
        **getattr(model, "webhook_events", {}).get(event, {}),
    }


def event_catalog():
    """Read native registrations when used, including apps loaded after API.ready()."""
    result = []
    for ref, handlers in webhook_settings.HOOKS.items():
        if handlers is None:
            continue
        model = model_from_reference(ref, check_hooks=False)
        keys = ["CREATE", *getattr(model, "webhook_events", {})]
        relationships = relationship_fields(model)
        if relationships:
            keys.extend(("M2M_ADD", "M2M_REMOVE", "M2M_CLEAR"))
        keys.extend(("UPDATE", "DELETE"))
        result.append(
            dict(
                ref=ref,
                name=model.__name__,
                emoji=getattr(model, "emoji", "📄"),
                relationships=[{"id": field.name, "name": str(field.verbose_name).capitalize()} for field in relationships],
                events=[dict(key=key, **event_options(model, key)) for key in dict.fromkeys(keys)],
            ),
        )
    return result


def signal_choices():
    # A frozen choices list misses plugins whose ready() follows the API app.
    choices = dict(SignalChoices.choices)
    for model in event_catalog():
        for event in model["events"]:
            choices.setdefault(event["key"], event["label"])
    return list(choices.items())


def event_payload(instance, signal, *, data=None, **metadata):
    # Reuse signal_webhooks' serializer, including model.webhook_data overrides.
    # Django's serializer returns {model, pk, fields}; scripts receive the fields
    # directly. Metadata wins over colliding model fields, as it describes dispatch.
    data = data if data is not None else webhook_settings.SERIALIZER(instance)
    fields = data.get("fields", data)
    if instance._meta.label == "core.Snapshot" and signal != "DELETE" and instance.pk:
        # Django omits explicit-through M2M fields. Actions need the same tag
        # names exposed by Snapshot's existing JSON representation, without a
        # fresh ORM lookup in each script. Legacy HTTP data stays unchanged.
        fields = {**fields, "tags": sorted(instance.tags.values_list("name", flat=True))}
    # Django clears instance.pk after post_delete; commit callbacks must use the
    # identity captured by the serializer while the row still existed.
    object_id = data.get("pk", data.get("id", instance.pk))
    return {**fields, "id": str(object_id), "object_type": instance._meta.label, "event": signal, **metadata}


@contextmanager
def track_lifecycle_update(queryset, fields):
    """Preserve lifecycle events on existing queryset status projections."""
    events = getattr(queryset.model, "webhook_status_events", {})
    previous = {}
    if (
        "status" in fields
        and not action_in_progress()
        and get_webhook_model()
        .objects.filter(
            ref=reference_for_model(queryset.model),
            signal__in=set(events.values()),
            enabled=True,
        )
        .exists()
    ):
        previous = dict(queryset.values_list("pk", "status"))
    yield
    # Finish the read before callbacks can start HTTP requests or subprocesses.
    for instance in list(queryset.model.objects.filter(pk__in=previous)) if previous else ():
        if instance.status != previous[instance.pk] and (signal := events.get(instance.status)):
            emit_event(instance, signal)


def emit_event(instance, signal, **metadata):
    if action_in_progress():
        return
    from archivebox.api.webhooks import deliver_webhooks, transaction_on_commit_task_handler

    ref = reference_for_model(type(instance))
    if webhook_settings.HOOKS.get(ref) is None:
        return
    if not get_webhook_model().objects.filter(ref=ref, signal=signal, enabled=True).exists():
        return
    data = webhook_settings.SERIALIZER(instance)
    if event_options(type(instance), signal).get("blocking"):
        # Preparation is called by the runner, outside any write transaction,
        # before it resolves native config or hands the object to the event bus.
        if transaction.get_connection().in_atomic_block:
            raise RuntimeError("Blocking webhooks must run outside a database transaction")
        if not deliver_webhooks(instance, data, signal, metadata=metadata):
            raise RuntimeError(f"{signal} webhook failed; see the Process logs")
    else:
        transaction_on_commit_task_handler(default_hook_handler, instance=instance, data=data, method=signal, metadata=metadata)


def register_lifecycle_signals():
    from django.db.models.signals import pre_save, post_save
    from abx_plugins.plugins.base.django import webhook_event

    def explicit_event(sender, instance, event, signal, **metadata):
        emit_event(instance, event, **metadata)

    webhook_event.connect(explicit_event, weak=False, dispatch_uid="archivebox.webhook.explicit")

    def before_save(sender, instance, raw=False, **kwargs):
        if raw or action_in_progress() or not getattr(sender, "webhook_status_events", {}):
            return
        instance._webhook_previous_status = (
            None if instance._state.adding else sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        )

    def after_save(sender, instance, raw=False, **kwargs):
        if raw or action_in_progress() or not hasattr(instance, "_webhook_previous_status"):
            return
        previous = instance._webhook_previous_status
        del instance._webhook_previous_status
        status = instance.status
        if status == previous:
            return
        signal = sender.webhook_status_events.get(status)
        if signal:
            emit_event(instance, signal)

    pre_save.connect(before_save, weak=False, dispatch_uid="archivebox.webhook.lifecycle.before")
    post_save.connect(after_save, weak=False, dispatch_uid="archivebox.webhook.lifecycle.after")


@contextmanager
def track_model_update(queryset, fields):
    """Deliver UPDATE for changed rows in native conditional queryset writes."""
    previous = {}
    if (
        not action_in_progress()
        and get_webhook_model()
        .objects.filter(
            ref=reference_for_model(queryset.model),
            signal="UPDATE",
            enabled=True,
        )
        .exists()
    ):
        previous = {obj.pk: obj for obj in queryset}
    yield
    for instance in list(queryset.model.objects.filter(pk__in=previous)) if previous else ():
        before = previous[instance.pk]
        names = [queryset.model._meta.get_field(name).attname for name in fields]
        if any(getattr(before, name) != getattr(instance, name) for name in names):
            emit_event(instance, "UPDATE")
