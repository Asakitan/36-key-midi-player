# -*- coding: utf-8 -*-
"""通用动画引擎 Animator (split from sao_theme.py — verbatim)."""
import tkinter as tk
import time
from typing import Optional, Callable, Dict
from sao_menu.utils import ease_out

# ──────────────────── 通用动画引擎 ────────────────────
class Animator:
    """用 after() 驱动的属性动画引擎"""

    def __init__(self, widget: tk.Widget):
        self.widget = widget
        self._jobs: Dict[str, str] = {}

    def animate(self, name: str, duration_ms: int, callback: Callable[[float], None],
                on_done: Optional[Callable] = None, easing=ease_out):
        if name in self._jobs:
            self.widget.after_cancel(self._jobs[name])
        # 时间驱动 (不累积误差, 消除撕裂)
        t0 = time.time()
        dur = max(0.001, duration_ms / 1000.0)

        def tick():
            if not self.widget.winfo_exists():
                return
            t = min(1.0, (time.time() - t0) / dur)
            callback(easing(t))
            if t < 1.0:
                try:
                    self._jobs[name] = self.widget.after(16, tick)
                except Exception:
                    self._jobs.pop(name, None)
            else:
                self._jobs.pop(name, None)
                if on_done:
                    on_done()

        tick()

    def cancel(self, name: str):
        if name in self._jobs:
            try:
                self.widget.after_cancel(self._jobs[name])
            except Exception:
                pass
            del self._jobs[name]

    def cancel_all(self):
        for name in list(self._jobs):
            self.cancel(name)


