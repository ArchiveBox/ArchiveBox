__package__ = "archivebox.api"

from typing import Any
from collections.abc import Callable
import logging

from django.db import transaction
from signal_webhooks.handlers import sync_task_handler


logger = logging.getLogger(__name__)


def warning_error_handler(hook: Any, error: Exception | None) -> None:
    if error is not None:
        logger.warning("Outbound webhook %r failed: %s", hook.name, error)
        return

    logger.warning("Outbound webhook %r returned a non-success response.", hook.name)


def transaction_on_commit_task_handler(hook: Callable[..., None], **kwargs: Any) -> None:
    def run_webhook() -> None:
        try:
            sync_task_handler(hook, **kwargs)
        except Exception:
            logger.warning("Outbound webhook failed after transaction commit.", exc_info=True)

    try:
        transaction.on_commit(run_webhook)
    except Exception:
        logger.warning("Could not schedule outbound webhook after transaction commit.", exc_info=True)
