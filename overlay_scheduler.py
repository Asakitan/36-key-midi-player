"""Shared Tk frame scheduler used by lightweight SAO entity UI animations."""
from __future__ import annotations

import ctypes
import os
import time
from typing import Callable, Dict, Optional


TickFn = Callable[[float], None]
AnimatingFn = Callable[[], bool]


class _WinTimerResolution:
    def __init__(self) -> None:
        self._engaged = False
        self._winmm = None
        if os.name == 'nt':
            try:
                self._winmm = ctypes.windll.winmm
            except Exception:
                self._winmm = None

    def acquire(self) -> None:
        if self._engaged or self._winmm is None:
            return
        try:
            if self._winmm.timeBeginPeriod(1) == 0:
                self._engaged = True
        except Exception:
            pass

    def release(self) -> None:
        if not self._engaged or self._winmm is None:
            return
        try:
            self._winmm.timeEndPeriod(1)
        except Exception:
            pass
        self._engaged = False


class OverlayScheduler:
    def __init__(self, root=None, hz: int = 60) -> None:
        self.root = root
        self.hz = max(30, min(240, int(hz or 60)))
        self.interval_ms = max(1, int(round(1000.0 / self.hz)))
        self._items: Dict[str, tuple[TickFn, Optional[AnimatingFn]]] = {}
        self._job = None
        self._timer = _WinTimerResolution()

    def configure_root(self, root) -> None:
        if root is None:
            return
        if self.root is None:
            self.root = root
            return
        changed = False
        try:
            if not self.root.winfo_exists():
                self.root = root
                changed = True
        except Exception:
            self.root = root
            changed = True
        if changed:
            self._job = None

    def register(self, ident: str, tick_fn: TickFn,
                 animating_fn: Optional[AnimatingFn] = None) -> None:
        self._items[str(ident)] = (tick_fn, animating_fn)
        self._ensure_running()

    def unregister(self, ident: str) -> None:
        self._items.pop(str(ident), None)
        if not self._items:
            self._stop()

    def _ensure_running(self) -> None:
        if self._job is not None or self.root is None:
            return
        self._timer.acquire()
        self._schedule(0)

    def _schedule(self, delay_ms: int) -> None:
        if self.root is None:
            return
        try:
            self._job = self.root.after(delay_ms, self._tick)
        except Exception:
            self._job = None

    def _tick(self) -> None:
        self._job = None
        if not self._items or self.root is None:
            self._stop()
            return
        now = time.time()
        for ident, (tick_fn, animating_fn) in list(self._items.items()):
            try:
                tick_fn(now)
            except Exception:
                self._items.pop(ident, None)
                continue
            try:
                if animating_fn is not None and not animating_fn():
                    self._items.pop(ident, None)
            except Exception:
                pass
        if self._items:
            self._schedule(self.interval_ms)
        else:
            self._stop()

    def _stop(self) -> None:
        if self._job is not None and self.root is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
        self._job = None
        self._timer.release()


_SCHEDULER: Optional[OverlayScheduler] = None


def get_scheduler(root=None) -> OverlayScheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = OverlayScheduler(root)
    elif root is not None:
        _SCHEDULER.configure_root(root)
    return _SCHEDULER
