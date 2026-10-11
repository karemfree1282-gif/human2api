"""Cooperative cancellation and bounded retries for non-mutating UI checks.

Retries are deliberately forbidden for clicks, typing, downloads, taps and
navigation: automatic repetition of a write may duplicate real-world effects.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .models import WorkflowError
from playwright.sync_api import Error as PlaywrightError

READ_RETRY_ACTIONS = frozenset({"wait", "assert_text", "extract_text", "assert_image"})


class RunCancelled(WorkflowError):
    """The current user explicitly cancelled a running workflow."""


def check_cancelled(event: threading.Event | None) -> None:
    if event is not None and event.is_set():
        raise RunCancelled("execution cancelled by user")


def interruptible_wait(ms: int, event: threading.Event | None) -> None:
    check_cancelled(event)
    if event is not None:
        if event.wait(ms / 1000):
            raise RunCancelled("execution cancelled by user")
    else:
        time.sleep(ms / 1000)


def run_step_with_retry(step: dict[str, Any], operation: Callable[[], Any], *, cancel_event: threading.Event | None = None) -> Any:
    retries = step.get("retries", 0)
    for attempt in range(retries + 1):
        check_cancelled(cancel_event)
        try:
            return operation()
        except RunCancelled:
            raise
        except (WorkflowError, PlaywrightError, AssertionError, OSError, ValueError, TimeoutError):
            if attempt == retries:
                raise
            interruptible_wait(step.get("retryDelayMs", 500), cancel_event)
    raise AssertionError("retry loop terminated unexpectedly")
