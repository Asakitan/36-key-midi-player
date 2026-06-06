"""Synchronization utilities for render capture operations."""

from __future__ import annotations

import threading
from contextlib import contextmanager


_lock = threading.Lock()
_capture_depth = 0
_capture_active = threading.Event()
_capture_idle = threading.Event()
_capture_idle.set()


def begin_capture() -> None:
    global _capture_depth
    with _lock:
        _capture_depth += 1
        _capture_active.set()
        _capture_idle.clear()


def end_capture() -> None:
    global _capture_depth
    with _lock:
        if _capture_depth > 0:
            _capture_depth -= 1
        if _capture_depth <= 0:
            _capture_depth = 0
            _capture_active.clear()
            _capture_idle.set()


@contextmanager
def capture_section():
    begin_capture()
    try:
        yield
    finally:
        end_capture()


def capture_is_active() -> bool:
    return _capture_active.is_set()


def wait_until_capture_idle(timeout_s: float = 0.0) -> bool:
    if not _capture_active.is_set():
        return True
    try:
        timeout = max(0.0, float(timeout_s or 0.0))
    except Exception:
        timeout = 0.0
    return bool(_capture_idle.wait(timeout))