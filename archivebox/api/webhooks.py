__package__ = "archivebox.api"

from typing import Any
from collections.abc import Callable
import logging

from django.db import transaction
from django.db.models.signals import pre_delete
from asgiref.sync import async_to_sync
from signal_webhooks.handlers import build_client_kwargs_by_hook_id, default_hook_handler, fire_webhooks
from signal_webhooks.utils import get_webhook_model


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
    def run_webhook() -> None:
        try:
            if hook is default_hook_handler:
                # The library's asyncio.run() cannot return to an enclosing
                # sync_to_async worker to persist delivery results. Use the
                # matching asgiref bridge, with the DB reads materialized first.
                hooks = get_webhook_model().objects.get_for_model(kwargs["instance"], method=kwargs["method"])
                if hooks:
                    client_kwargs = build_client_kwargs_by_hook_id(hooks)
                    async_to_sync(fire_webhooks)(hooks, kwargs["data"], client_kwargs)
            else:
                hook(**kwargs)
        except Exception:
            logger.warning("Outbound webhook failed after transaction commit.", exc_info=True)

    try:
        transaction.on_commit(run_webhook)
    except Exception:
        logger.warning("Could not schedule outbound webhook after transaction commit.", exc_info=True)
