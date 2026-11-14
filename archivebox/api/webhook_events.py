"""ArchiveBox lifecycle signals delivered through the existing webhook handler."""

from contextvars import ContextVar
from contextlib import contextmanager
import os

from django.db import transaction
from signal_webhooks.handlers import default_hook_handler
from signal_webhooks.settings import webhook_settings
from signal_webhooks.typing import SignalChoices
from signal_webhooks.utils import model_from_reference, get_webhook_model, reference_for_model


# A sequence may save models and its Process logs. Those writes must not start
# the same subscription recursively (including callbacks scheduled on commit).
executing_webhook = ContextVar("executing_webhook", default=False)


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
    "FOLDER_ENTERED": dict(label="Enters a folder", icon="folder", color="#9d618f", membership=True),
    "FOLDER_LEFT": dict(label="Leaves a folder", icon="leave", color="#9d618f", membership=True),
    "STARTED": dict(label="Started", icon="play", color="#597bab"),
    "COMPLETED": dict(label="Completed", icon="complete", color="#377b5b"),
    "EXITED": dict(label="Exited", icon="complete", color="#377b5b"),
    "M2M_ADD": dict(label="Relationship added", icon="plus", color="#377b5b"),
    "M2M_REMOVE": dict(label="Relationship removed", icon="leave", color="#9d618f"),
    "M2M_CLEAR": dict(label="Relationships cleared", icon="leave", color="#9d618f"),
    "UPDATE": dict(label="Updated", icon="update", color="#547caa", section=True),
    "DELETE": dict(label="Deleted", icon="delete", color="#b3495a"),
}
LIFECYCLE = {
    "core.Snapshot": ("BEFORE_QUEUE", "BEFORE_CAPTURE", "CAPTURE_COMPLETED", "FOLDER_ENTERED", "FOLDER_LEFT"),
    "crawls.Crawl": ("BEFORE_QUEUE", "STARTED", "COMPLETED"),
    "core.ArchiveResult": ("CAPTURE_COMPLETED",),
    "machine.Process": ("STARTED", "EXITED"),
}
STATUS_EVENTS = {
    "crawls.Crawl": {"started": "STARTED", "sealed": "COMPLETED"},
    "machine.Process": {"running": "STARTED", "exited": "EXITED"},
    "core.ArchiveResult": dict.fromkeys(("succeeded", "failed", "skipped", "noresults"), "CAPTURE_COMPLETED"),
}
SIGNAL_CHOICES = list(SignalChoices.choices) + [(key, value["label"]) for key, value in EVENTS.items() if key not in SignalChoices.values]


def event_catalog():
    """One registry for model validation and the editor; labels are presentation."""
    result = []
    for ref in webhook_settings.HOOKS:
        model = model_from_reference(ref, check_hooks=False)
        keys = ["CREATE", *LIFECYCLE.get(model._meta.label, ())]
        if model._meta.many_to_many:
            keys.extend(("M2M_ADD", "M2M_REMOVE", "M2M_CLEAR"))
        keys.extend(("UPDATE", "DELETE"))
        result.append(dict(ref=ref, name=model.__name__, emoji=model.emoji, events=[dict(key=key, **EVENTS[key]) for key in keys]))
    return result


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
    events = STATUS_EVENTS.get(queryset.model._meta.label, {})
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

    if not get_webhook_model().objects.filter(ref=reference_for_model(type(instance)), signal=signal, enabled=True).exists():
        return
    data = webhook_settings.SERIALIZER(instance)
    if EVENTS[signal].get("blocking"):
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

    def before_save(sender, instance, raw=False, **kwargs):
        if raw or action_in_progress() or sender._meta.label not in {"crawls.Crawl", "core.ArchiveResult", "machine.Process"}:
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
        signal = STATUS_EVENTS[sender._meta.label].get(status)
        if signal:
            emit_event(instance, signal)

    pre_save.connect(before_save, weak=False, dispatch_uid="archivebox.webhook.lifecycle.before")
    post_save.connect(after_save, weak=False, dispatch_uid="archivebox.webhook.lifecycle.after")
