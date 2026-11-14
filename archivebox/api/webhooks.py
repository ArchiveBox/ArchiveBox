__package__ = "archivebox.api"

from typing import Any
from collections.abc import Callable
import logging

from django.db import transaction
from django.db.models.signals import pre_delete
from asgiref.sync import async_to_sync
from signal_webhooks.handlers import build_client_kwargs_by_hook_id, default_hook_handler, fire_webhooks
from signal_webhooks.utils import get_webhook_model
from signal_webhooks.typing import METHOD_SIGNALS
from signal_webhooks.utils import reference_for_model
from archivebox.api.webhook_events import EVENTS, executing_webhook, action_in_progress, event_payload


logger = logging.getLogger(__name__)


def load_deferred_fields_for_delete_webhook(sender, instance, using, **kwargs) -> None:
    """Materialize deferred fields while DELETE webhook rows still exist.

    Admin lists defer large fields, but signal_webhooks serializes all concrete
    fields in post_delete. Loading one then would query an already-deleted row
    and drop the event. Hydrate only deferred fields on webhook-enabled models
    here, preserving the normal list-query optimization.
    """
    from signal_webhooks.handlers import find_hook_handler
    from signal_webhooks.utils import reference_for_model

    ref = reference_for_model(type(instance))
    deferred_fields = instance.get_deferred_fields()
    if not deferred_fields or find_hook_handler(ref, "DELETE") is None:
        return

    instance.refresh_from_db(using=using, fields=deferred_fields)


def register_delete_webhook_field_loader() -> None:
    pre_delete.connect(
        load_deferred_fields_for_delete_webhook,
        dispatch_uid="archivebox.load_deferred_fields_for_delete_webhook",
        weak=False,
    )


def warning_error_handler(hook: Any, error: Exception | None) -> None:
    if error is not None:
        logger.warning("Outbound webhook %r failed: %s", hook.name, error)
        return

    logger.warning("Outbound webhook %r returned a non-success response.", hook.name)


def transaction_on_commit_task_handler(hook: Callable[..., None], **kwargs: Any) -> None:
    if action_in_progress():
        return
    # Freeze normal event inputs at the transition. CREATE must wait for the
    # model's initialization transaction (including Snapshot tag defaults).
    payload = (
        None
        if kwargs["method"] == "CREATE"
        else event_payload(
            kwargs["instance"],
            kwargs["method"],
            data=kwargs["data"],
            **kwargs.get("metadata", {}),
        )
    )

    def run_webhook() -> None:
        try:
            if hook is default_hook_handler:
                # The library's asyncio.run() cannot return to an enclosing
                # sync_to_async worker to persist delivery results. Use the
                # matching asgiref bridge, with the DB reads materialized first.
                deliver_webhooks(kwargs["instance"], kwargs["data"], kwargs["method"], metadata=kwargs.get("metadata", {}), payload=payload)
            else:
                hook(**kwargs)
        except Exception:
            logger.warning("Outbound webhook failed after transaction commit.", exc_info=True)

    try:
        transaction.on_commit(run_webhook)
    except Exception:
        logger.warning("Could not schedule outbound webhook after transaction commit.", exc_info=True)


def deliver_webhooks(instance, data, method, *, metadata=None, subscriptions=None, payload=None):
    from archivebox.api.webhook_actions import execute_actions
    from archivebox.crawls.locks import after_lifecycle_locks

    metadata = metadata or {}
    # The package's lookup table knows CRUD/M2M aliases. Additional lifecycle
    # events use their exact signal name, on the same OutboundWebhook model.
    if subscriptions is None:
        hooks = get_webhook_model().objects.filter(
            ref=reference_for_model(type(instance)),
            signal__in=(*METHOD_SIGNALS.get(method, ()), method),
            enabled=True,
        )
        if method in {"FOLDER_ENTERED", "FOLDER_LEFT"}:
            hooks = hooks.filter(folder_id=metadata["folder_id"])
        hooks = list(hooks)
    else:
        hooks = subscriptions
    if not hooks:
        return True
    token = executing_webhook.set(True)
    succeeded = True
    try:
        payload = payload if payload is not None else event_payload(instance, method, data=data, **metadata)
        for index, subscription in enumerate(hooks):
            external = not subscription.actions or any(
                action["type"] in {"http_request", "python", "shell"} for action in subscription.actions
            )
            if external and not EVENTS.get(method, {}).get("blocking"):
                # A post-save callback can still be inside the crawl's lifecycle
                # lock even after DB commit. Its HTTP/subprocess work may need
                # that same lock. Preserve ordering/stop_processing by deferring
                # this subscription AND the remaining subscriptions together.
                remaining = hooks[index:]

                def after_release():
                    try:
                        if method != "DELETE" and instance.pk:
                            try:
                                instance.refresh_from_db()
                            except type(instance).DoesNotExist:
                                pass  # HTTP/script payload still describes the committed event.
                        deliver_webhooks(instance, data, method, metadata=metadata, subscriptions=remaining, payload=payload)
                    except Exception:
                        logger.warning("Outbound webhook failed after lifecycle lock release.", exc_info=True)

                if after_lifecycle_locks(after_release):
                    return succeeded
            if subscription.actions:
                success = execute_actions(subscription, instance, method, payload)
            else:
                # Preserve the original payload, HTTP client settings and delivery
                # status semantics for already configured endpoint-only webhooks.
                client_kwargs = build_client_kwargs_by_hook_id([subscription])
                async_to_sync(fire_webhooks)([subscription], data, client_kwargs)
                success = not subscription.last_failure or bool(
                    subscription.last_success and subscription.last_success > subscription.last_failure,
                )
            succeeded = succeeded and success
            if success and subscription.stop_processing:
                break
    finally:
        executing_webhook.reset(token)
    return succeeded
