# -*- coding: utf-8 -*-
"""v2.3.0 Phase 3+ — GPU-presented SAOMenuBar fisheye row.

The vertical menu sidebar (``SAOMenuBar``) lives inside the chroma-key
``SAOPopUpMenu`` Toplevel. Each ``SAOCircleButton`` is a ``tk.Canvas``
that paints a per-button PIL sprite + ``ImageTk.PhotoImage`` upload +
``itemconfigure`` on the **Tk main thread** every fisheye tick. With 8
buttons that's measurably the dominant cost of ``ui.menu.fisheye_tick``
(~16 ms p99 on the user's box).

This module replaces that visual layer with:

- A single **GPU overlay window** (GLFW + ``moderngl``) sized to the
  menubar rect, sitting **on top of** the chroma-key popup. Because
  the popup's bg is ``#010101`` chroma-keyed and the SAOCircleButton
  Canvases also inherit that bg, the area occupied by the menubar is
  fully see-through, letting the GPU layer show through.
- An **off-thread compose** path that snapshots all 8 button visual
  states each tick and composites the entire strip into one BGRA frame
  on the heavy ``AsyncFrameWorker`` lane.
- The ``SAOCircleButton`` widgets remain in place as **invisible
  hit-test rectangles** — their ``_draw`` is no-op'd when the painter
  is attached, so no per-button PIL/PhotoImage work runs on the main
  thread. Click/Enter/Leave bindings still fire because the widget
  area exists.

Entity menu bar rendering is GPU-required; do not fall back to Tk/ULW.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from typing import Any, Callable, List, Optional, Tuple

from PIL import Image

from render.overlay_render_worker import AsyncFrameWorker, FrameBuffer
from utils.perf_probe import phase as _phase_trace, probe as _probe
from gui_modules.entity_gpu_policy import require_entity_gpu
from gui_modules.sao_menu_hud import MenuCircleButtonRenderer
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]

try:
    from render import gpu_overlay_window as _gow
except Exception:  # pragma: no cover - optional dep
    _gow = None  # type: ignore[assignment]


def gpu_menu_bar_enabled() -> bool:
    """Menu bar requires the shared Entity GPU backend."""
    return require_entity_gpu('MenuBarGpuPainter', _gow)


class _ButtonSnapshot:
    """Plain data carrier for a single button's visual state. Built
    on the main thread under the Tk lock and consumed on the worker —
    it must not touch any Tk widget."""

    __slots__ = ('size', 'hover_t', 'active', 'icon')

    def __init__(self, size: float, hover_t: float, active: bool, icon: str):
        self.size = float(size)
        self.hover_t = float(hover_t)
        self.active = bool(active)
        self.icon = str(icon or '●')


class MenuBarGpuPainter:
    """Owns one ``GpuOverlayWindow`` + ``AsyncFrameWorker`` for the
    SAOMenuBar fisheye strip. Composes all buttons into one BGRA
    frame per tick on the worker lane and presents via moderngl.

    The painter is a **passive** consumer of state: SAOMenuBar's
    ``_tick_float`` snapshots its buttons after updating sizes and
    feeds the snapshot in via :meth:`tick`. The painter handles its
    own no-op deduping based on the snapshot signature.
    """

    def __init__(self, root: tk.Tk, slot_px: int, max_size: int,
                 hover_cb: Optional[Callable[[int], None]] = None,
                 leave_cb: Optional[Callable[[], None]] = None,
                 click_cb: Optional[Callable[[int], None]] = None,
                 scroll_cb: Optional[Callable[[float], None]] = None):
        self._root = root
        self._slot = int(slot_px)
        self._max_size = int(max_size)
        self._hover_cb = hover_cb
        self._leave_cb = leave_cb
        self._click_cb = click_cb
        self._scroll_cb = scroll_cb
        self._render_worker = AsyncFrameWorker(prefer_isolation=True)
        self._renderer = MenuCircleButtonRenderer()
        self._gpu_window: Optional[Any] = None
        self._presenter: Optional[Any] = None
        self._destroyed = False
        # Re-entrancy guard for GLFW mouse callbacks. The click_cb may
        # invoke menu commands that destroy this very GPU window
        # (panel toggles, switch UI, exit), and running them inline
        # inside glfw.poll_events tears down the window we're still
        # dispatching from → crash. Defer via after_idle and gate
        # rapid clicks. See popup_glfw_callback_reentrancy memory.
        self._click_pending = False
        # Latest signature of the snapshot we already submitted; stops
        # us from re-rendering 60 Hz of identical frames once the bar
        # settles back to rest size.
        self._last_sig: Optional[tuple] = None
        # Cached strip dims so we only call set_geometry on real moves.
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        # Latest requested onscreen geometry. We must track this
        # independently from the last presented framebuffer geometry
        # because the menu content itself animates during open; using
        # fb.x/fb.y can lag one or more frames behind the live Tk rect.
        self._target_geom: Optional[Tuple[int, int, int, int]] = None
        self._button_count = 0
        self._hover_idx: Optional[int] = None
        # Lock protects the small caches above; tick() is main-thread
        # only so this is mainly defensive against future async usage.
        self._lock = threading.Lock()

    # ──────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────

    def _ensure_window(self, w: int, h: int, x: int, y: int) -> bool:
        if self._gpu_window is not None:
            return True
        require_entity_gpu('MenuBarGpuPainter', _gow)
        try:
            pump = _gow.get_glfw_pump(self._root)
            self._presenter = _gow.BgraPresenter()
            interactive = any(
                cb is not None
                for cb in (self._hover_cb, self._leave_cb,
                           self._click_cb, self._scroll_cb)
            )
            self._gpu_window = _gow.GpuOverlayWindow(
                pump,
                w=max(1, int(w)), h=max(1, int(h)),
                x=int(x), y=int(y),
                render_fn=self._presenter.render,
                click_through=not interactive,
                title='sao_menu_bar_gpu',
            )
            if interactive:
                self._gpu_window.set_input_callbacks(
                    cursor_pos_fn=self._handle_cursor_pos,
                    cursor_leave_fn=self._handle_cursor_leave,
                    mouse_button_fn=self._handle_mouse_button,
                    scroll_fn=self._handle_scroll,
                )
            self._gpu_window.show()
            return True
        except Exception as exc:
            self._presenter = None
            self._gpu_window = None
            raise RuntimeError('MenuBarGpuPainter requires GPU window support') from exc

    def _slot_index(self, x: float, y: float) -> Optional[int]:
        return _CY_UI.menu_bar_slot_index(
            x, y, self._max_size, self._slot, self._button_count)

    def _handle_cursor_pos(self, x: float, y: float) -> None:
        idx = self._slot_index(x, y)
        if idx is None:
            self._handle_cursor_leave()
            return
        if idx == self._hover_idx:
            return
        self._hover_idx = idx
        if self._hover_cb is not None:
            self._hover_cb(idx)

    def _handle_cursor_leave(self) -> None:
        if self._hover_idx is None:
            return
        self._hover_idx = None
        if self._leave_cb is not None:
            self._leave_cb()

    def _handle_mouse_button(self, button: int, action: int,
                             _mods: int, x: float, y: float) -> None:
        if button != 0 or action != 1:
            return
        idx = self._slot_index(x, y)
        if idx is None:
            return
        self._hover_idx = idx
        if self._hover_cb is not None:
            self._hover_cb(idx)
        if self._click_cb is None:
            return
        if self._click_pending:
            return
        self._click_pending = True
        _phase_trace('menu.bar.click.schedule', f'idx={idx}')
        try:
            self._root.after_idle(self._fire_click, idx)
        except Exception:
            self._click_pending = False
            try:
                self._click_cb(idx)
            except Exception:
                pass

    def _fire_click(self, idx: int) -> None:
        cb = self._click_cb
        if cb is None:
            self._click_pending = False
            return
        _phase_trace('menu.bar.click.begin', f'idx={idx}')
        # WGC pyo3 callback race avoidance: the click cb's transitive
        # work (Tk update_idletasks reentry → pump _tick → glfw
        # make_context_current/swap_buffers, plus possible new GPU
        # window _create()) opens many GIL-released ctypes windows on
        # the main thread. windows_capture's pyo3 callback firing in
        # any of those windows triggers the assume_gil_acquired() bug
        # → corrupts _PyThreadState_Current → next Tcl
        # Py_BEGIN_ALLOW_THREADS aborts with NULL tstate. Pause WGC
        # for the WHOLE cb. Reference-counted so nested _create()
        # pauses still nest correctly. See gpu_capture.pause_capture.
        try:
            from render.gpu_capture import pause_capture as _wgc_pause
            from render.gpu_capture import resume_capture as _wgc_resume
        except Exception:
            _wgc_pause = None
            _wgc_resume = None
        if _wgc_pause is not None:
            try:
                _wgc_pause()
            except Exception:
                _wgc_resume = None  # don't try to resume what didn't pause
        try:
            try:
                _phase_trace('menu.bar.click.cb', f'idx={idx}')
                cb(idx)
            except Exception:
                pass
        finally:
            if _wgc_resume is not None:
                try:
                    _wgc_resume()
                except Exception:
                    pass
        _phase_trace('menu.bar.click.end', f'idx={idx}')
        # Hold the guard for a short cooldown so a fast second click
        # cannot queue another after_idle while sao_sound daemon threads
        # spawned by this cb are still warming up. Without the cooldown
        # rapid clicks pile up concurrent C-extension work and trigger
        # PyEval_RestoreThread NULL-tstate crashes (popup_glfw_callback
        # _reentrancy memory). 120 ms ≈ 2 frames at 60 Hz.
        try:
            self._root.after(120, self._clear_click_pending)
        except Exception:
            self._click_pending = False

    def _clear_click_pending(self) -> None:
        _phase_trace('menu.bar.click.cooldown_clear')
        self._click_pending = False

    def _handle_scroll(self, _xoff: float, yoff: float) -> None:
        if self._scroll_cb is None or abs(yoff) <= 1e-6:
            return
        self._scroll_cb(yoff)

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._handle_cursor_leave()
        try:
            self._render_worker.stop()
        except Exception:
            pass
        if self._presenter is not None:
            try:
                self._presenter.release()
            except Exception:
                pass
            self._presenter = None
        if self._gpu_window is not None:
            try:
                self._gpu_window.destroy()
            except Exception:
                pass
            self._gpu_window = None
        self._target_geom = None

    # ──────────────────────────────────────────
    #  Per-tick entry (main thread)
    # ──────────────────────────────────────────

    @_probe.decorate('ui.menu.bar_gpu_tick')
    def tick(self,
             screen_x: int, screen_y: int,
             strip_w: int, strip_h: int,
             snapshots: List[_ButtonSnapshot],
             color_fns: 'BarColorFns') -> None:
        """Drain the previous frame and (if state changed) submit a
        new compose. Cheap to call every tick — does no PIL work and
        early-outs when the snapshot signature is unchanged.
        """
        if self._destroyed or not snapshots:
            return
        # Defer window creation until Tk has reported a real screen
        # origin. On the very first tick after a popup opens, Tk can
        # report (0, 0) for winfo_rootx/y before the popup is fully
        # mapped — creating the GLFW window with that placeholder
        # geometry leaves it stuck at the monitor top-left until the
        # next compose result lands.
        if self._gpu_window is None and (screen_x <= 0 and screen_y <= 0):
            return
        if not self._ensure_window(strip_w, strip_h, screen_x, screen_y):
            return
        self._button_count = len(snapshots)
        self._target_geom = (
            int(screen_x), int(screen_y), int(strip_w), int(strip_h))

        # 1) Drain previous frame and present it.
        fb = self._render_worker.take_result(allow_during_capture=True)
        if fb is not None and self._gpu_window is not None and self._presenter is not None:
            try:
                geom = self._target_geom or (fb.x, fb.y, fb.width, fb.height)
                if geom != self._last_geom:
                    self._gpu_window.set_geometry(*geom)
                    self._last_geom = geom
                self._presenter.set_frame(fb.bgra_bytes, fb.width, fb.height)
                self._gpu_window.request_redraw()
            except Exception:
                pass

        # 2) Build dedup signature. Quantize size to 1/4 px and hover_t
        #    to 1/20 (matches SAOCircleButton._draw quantization so we
        #    submit one frame per visually-distinct state).
        sig = _CY_UI.menu_bar_snapshot_sig(strip_w, strip_h, snapshots)
        with self._lock:
            if sig == self._last_sig:
                # Position can still drift even when visuals are static
                # (popup breathing). Reposition the existing GLFW window
                # without resubmitting a new compose. The previous
                # `pass` branch was a no-op so the window stayed at the
                # last presented (sx, sy) until something else triggered
                # a recompose — visible as the menu strip lagging when
                # the popup itself moves.
                if self._gpu_window is not None and self._target_geom is not None:
                    if self._target_geom != self._last_geom:
                        try:
                            self._gpu_window.set_geometry(*self._target_geom)
                            self._last_geom = self._target_geom
                        except Exception:
                            pass
                return
            self._last_sig = sig

        # 3) Submit a new compose. Capture state by value into the
        #    closure — never touch Tk on the worker.
        states = list(snapshots)
        slot = self._slot
        max_sz = self._max_size
        renderer = self._renderer
        cf = color_fns

        def compose(_now: float) -> Image.Image:
            img = Image.new('RGBA', (int(strip_w), int(strip_h)), (0, 0, 0, 0))
            for i, b in enumerate(states):
                size = max(1, int(round(b.size)))
                t = max(0.0, min(1.0, b.hover_t))
                if b.active:
                    border_color = cf.active_border
                    inner_fill = cf.active_bg
                    icon_color = cf.active_icon
                else:
                    border_color = cf.lerp(cf.border, cf.active_border, t)
                    inner_fill = cf.lerp(cf.bg, cf.hover_bg, t)
                    icon_color = cf.lerp(cf.icon, cf.hover_icon, t)
                sprite = renderer.render(
                    size, b.icon or '●',
                    border_color, inner_fill, icon_color, '#010101',
                )
                # Vertical strip: each button centered in its slot rect.
                slot_top = i * slot
                cx = (max_sz - size) // 2
                cy = slot_top + (slot - size) // 2
                img.alpha_composite(sprite, (cx, cy))
            return img

        try:
            self._render_worker.submit(
                compose, time.perf_counter(),
                0, int(screen_x), int(screen_y),
            )
        except Exception:
            pass


class BarColorFns:
    """Frozen color helpers + palette shared with SAOCircleButton.
    Captured once per painter so the worker closure doesn't need to
    import sao_theme (avoids circular import + Tk-touch surface)."""

    __slots__ = (
        'border', 'bg', 'icon',
        'active_border', 'active_bg', 'active_icon',
        'hover_bg', 'hover_icon',
        'lerp',
    )

    def __init__(self, palette: dict, lerp_fn: Callable[[str, str, float], str]):
        self.border = palette['border']
        self.bg = palette['bg']
        self.icon = palette['icon']
        self.active_border = palette['active_border']
        self.active_bg = palette['active_bg']
        self.active_icon = palette['active_icon']
        self.hover_bg = palette['hover_bg']
        self.hover_icon = palette['hover_icon']
        self.lerp = lerp_fn
