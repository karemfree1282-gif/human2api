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

READ_RETRY_ACTIONS = frozenset({"wait", "assert_text", "extract_text", "assert_image", "ui_assert_text", "ui_extract_text"})


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
    if type(retries) is not int or not 0 <= retries <= 3 or (retries and step.get("action") not in READ_RETRY_ACTIONS):
        raise WorkflowError("bounded retries are allowed only for read-only verification")
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


# All HTTP/MCP/CLI calls in this process share the same native desktop/device.
# Browser contexts are independent; native writers must not compete for focus.
from contextlib import contextmanager

_NATIVE_LOCKS = {"desktop": threading.Lock(), "android": threading.Lock()}


@contextmanager
def target_lease(target: str):
    lock = _NATIVE_LOCKS.get(target)
    if lock is not None and not lock.acquire(blocking=False):
        raise WorkflowError(f"{target} device is busy; no actions were executed")
    try:
        if lock is None:
            yield
        else:
            from .leases import device_lease
            with device_lease(target):
                yield
    finally:
        if lock is not None:
            lock.release()
