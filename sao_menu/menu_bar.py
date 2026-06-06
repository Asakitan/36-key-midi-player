# -*- coding: utf-8 -*-
"""SAOMenuBar (split from sao_theme.py — verbatim)."""
import tkinter as tk
import time
from typing import Any, Optional, List, Dict, Tuple
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from render.overlay_scheduler import get_scheduler as _get_scheduler
from utils.perf_probe import probe as _probe
try:
    # v2.3.0 Phase 3+: GPU-presented fisheye sidebar. Off-thread
    # composes the whole 8-button strip into one BGRA frame on a
    # GLFW-backed overlay window; SAOCircleButton stays as an
    # invisible hit-test rectangle when this is active.
    from gui_modules.sao_menu_bar_gpu import (
        MenuBarGpuPainter,
        BarColorFns,
        _ButtonSnapshot,
        gpu_menu_bar_enabled,
    )
except Exception as _menu_gpu_import_error:
    _MENU_GPU_IMPORT_ERROR = _menu_gpu_import_error
    MenuBarGpuPainter = None  # type: ignore[assignment]
    BarColorFns = None  # type: ignore[assignment]
    _ButtonSnapshot = None  # type: ignore[assignment]
    def gpu_menu_bar_enabled() -> bool:  # type: ignore[no-redef]
        raise RuntimeError('MenuBarGpuPainter GPU module is required') from _MENU_GPU_IMPORT_ERROR
from sao_menu.colors import SAOColors
from sao_menu.animator import Animator
from sao_menu.utils import lerp_color
from sao_menu.circle_button import SAOCircleButton

# ──────────────────── 菜单栏 (MenuBar) ────────────────────
class SAOMenuBar(tk.Frame):
    """
    SAO 风格垂直菜单栏
    - 最多显示 9 个圆形按钮 (v3: +插件分类)
    - 下落动画 (from top:-500 to top:0)
    - 滚轮滚动
    - 点击激活 → 触发 LeftInfo + ChildBar
    """

    _MAX_VISIBLE = 9

    def __init__(self, parent, icon_arr: List[Dict], on_activate=None, **kw):
        super().__init__(parent, bg='', highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self.icon_arr = list(icon_arr)
        self.on_activate = on_activate
        self._buttons: List[SAOCircleButton] = []
        self._slots:   List[tk.Frame] = []
        self._active_item = None
        self._hover_idx: Optional[int] = None
        self._float_registered = False
        self._float_sched_ident = f'sao_menu_bar_{id(self)}'
        self._enter_active = False
        self._enter_t0 = 0.0
        self._enter_delay_s = 0.08
        self._enter_duration_s = 0.28
        self._float_phases: List[float] = []
        self._anim = Animator(self)
        # GPU-required painter for the fisheye strip. Built lazily in
        # _build() once the slot/button geometry is known; torn down in
        # _stop_float on widget destroy.
        self._gpu_painter: Optional[Any] = None
        self._gpu_color_fns: Optional[Any] = None
        # v2.3.0 Phase A3: cache screen origin so _dispatch_gpu_paint
        # doesn't pay 0.1-0.5ms of OS window queries per frame. Tk
        # <Configure> on self fires only when geometry changes.
        self._cached_screen_xy: Optional[Tuple[int, int]] = None
        self.bind('<Configure>',
                  lambda e: setattr(self, '_cached_screen_xy', None),
                  add='+')
        self.bind('<Destroy>', lambda e: self._on_destroy())
        self._build()

    _SLOT = 70  # 按钮槽尺寸(px) — 大于 SIZE=54 以容纳鱼眼放大后的按钮

    def _build(self):
        self._stop_float()
        for w in self.winfo_children():
            w.destroy()
        self._buttons.clear()
        self._slots.clear()
        bg = self.cget('bg')
        for idx, item in enumerate(self.icon_arr[:self._MAX_VISIBLE]):
            slot = tk.Frame(self, width=self._SLOT, height=self._SLOT, bg=bg)
            slot.pack_propagate(False)
            slot.pack(side='top')
            btn = SAOCircleButton(
                slot,
                icon_text=item.get('icon', '●'),
                name=item.get('name', ''),
                can_activate=item.get('can_active', True),
                command=lambda it=item: self._on_item_click(it)
            )
            # Canvas is MAX_SIZE (==_SLOT); place once and never reposition.
            # The sprite inside is re-centered at _size each frame so we
            # avoid Tk geometry changes during fisheye / entry animation.
            btn.place(x=0, y=0)
            self._buttons.append(btn)
            self._slots.append(slot)
            btn._cursor_ready = True
            # 鱼眼: hover 时通知 MenuBar 更新所有按钮尺寸
            btn.bind('<Enter>', lambda e, i=idx: self._on_fisheye(i), add='+')
            btn.bind('<Leave>', lambda e: self._off_fisheye(),         add='+')
        self.bind_all_recursive('<MouseWheel>', self._on_scroll)
        self._float_phases = [i * 1.57 for i in range(len(self._buttons))]
        # v2.3.0 Phase 3+: bring up the GPU painter if available.
        # Done after buttons exist so we can flip _gpu_managed and
        # clear the per-button Canvas paint state.
        self._setup_gpu_painter()

    def _setup_gpu_painter(self) -> None:
        # Tear down any prior painter (e.g. on _build re-entry from scroll).
        if self._gpu_painter is not None:
            try:
                self._gpu_painter.destroy()
            except Exception:
                pass
            self._gpu_painter = None
        if MenuBarGpuPainter is None:
            raise RuntimeError('MenuBarGpuPainter GPU module is required')
        gpu_menu_bar_enabled()
        if not self._buttons:
            return
        try:
            palette = {
                'border': SAOColors.CIRCLE_BORDER,
                'bg': SAOColors.CIRCLE_BG,
                'icon': SAOColors.CIRCLE_ICON,
                'active_border': SAOColors.ACTIVE_BORDER,
                'active_bg': SAOColors.ACTIVE_BG,
                'active_icon': SAOColors.ACTIVE_ICON,
                'hover_bg': SAOColors.HOVER_BG,
                'hover_icon': SAOColors.HOVER_ICON,
            }
            self._gpu_color_fns = BarColorFns(palette, lerp_color)
            self._gpu_painter = MenuBarGpuPainter(
                self.winfo_toplevel(),
                slot_px=self._SLOT,
                max_size=SAOCircleButton.MAX_SIZE,
                hover_cb=self.dispatch_gpu_hover,
                leave_cb=self.dispatch_gpu_leave,
                click_cb=self.dispatch_gpu_click,
                scroll_cb=self.dispatch_gpu_scroll,
            )
            for btn in self._buttons:
                btn._gpu_managed = True
                # Drop any pre-existing PhotoImage so the Canvas is
                # pure chroma-keyed bg (invisible) under the GPU layer.
                if btn._bg_item is not None:
                    try:
                        btn.delete(btn._bg_item)
                    except Exception:
                        pass
                    btn._bg_item = None
                btn._bg_photo = None
                btn._visual_sig = None
        except Exception:
            self._gpu_painter = None
            self._gpu_color_fns = None
            for btn in self._buttons:
                btn._gpu_managed = False
            raise
        # Force Tk to lay out the menu bar before the first dispatch
        # fires from `_tick_float`. Without this the painter's first
        # tick can race the popup mapping and read rootx/rooty == 0,
        # leaving the GPU window stuck at the monitor top-left until
        # something else triggers a recompose.
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            self.after_idle(self._dispatch_gpu_paint)
        except Exception:
            pass

    def bind_all_recursive(self, event, handler):
        self.bind(event, handler)
        for slot in self._slots:
            slot.bind(event, handler)
        for btn in self._buttons:
            btn.bind(event, handler)

    def _on_item_click(self, item):
        if not item.get('can_active', True):
            return
        try:
            from utils.sao_sound import play_sound as _ps
            _ps('click', volume=0.5)
        except Exception:
            pass
        if self._active_item and self._active_item.get('name') == item.get('name'):
            self._active_item = None
            for btn in self._buttons:
                btn.active = False
            if self.on_activate:
                self.on_activate(None)
            return
        self._active_item = item
        for btn in self._buttons:
            btn.active = (btn.name == item.get('name'))
        if self.on_activate:
            self.on_activate(item)

    def _root_hit_test_item(self, x_root: int, y_root: int):
        """Return the visible menu item under a root-level click.

        In GPU mode the button canvases are intentionally visually empty
        under a transparent-color popup, so Windows can deliver the click
        straight to the root window instead of the Tk canvas. Hit-testing
        the fixed 70x70 slot rect restores the original interaction model.
        """
        if not self._buttons or not self.winfo_exists() or not self.winfo_ismapped():
            return None
        visible_items = self.icon_arr[:len(self._buttons)]
        for idx, (btn, item) in enumerate(zip(self._buttons, visible_items)):
            try:
                bx = int(btn.winfo_rootx())
                by = int(btn.winfo_rooty())
                bw = int(btn.winfo_width() or btn.winfo_reqwidth() or self._SLOT)
                bh = int(btn.winfo_height() or btn.winfo_reqheight() or self._SLOT)
            except Exception:
                continue
            if bx <= x_root <= (bx + bw) and by <= y_root <= (by + bh):
                return idx, item
        return None

    def dispatch_root_click(self, x_root: int, y_root: int) -> bool:
        hit = self._root_hit_test_item(int(x_root), int(y_root))
        if hit is None:
            return False
        idx, item = hit
        self._on_fisheye(idx)
        self._on_item_click(item)
        return True

    def dispatch_gpu_hover(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._buttons):
            return
        self._on_fisheye(int(idx))

    def dispatch_gpu_leave(self) -> None:
        self._off_fisheye()

    def dispatch_gpu_click(self, idx: int) -> None:
        visible_items = self.icon_arr[:len(self._buttons)]
        if idx < 0 or idx >= len(visible_items):
            return
        self._on_fisheye(int(idx))
        self._on_item_click(visible_items[idx])

    def _scroll_by_delta(self, delta: float) -> None:
        if not self.icon_arr or len(self.icon_arr) <= self._MAX_VISIBLE:
            return
        if delta > 0:
            self.icon_arr.insert(0, self.icon_arr.pop())
        elif delta < 0:
            self.icon_arr.append(self.icon_arr.pop(0))
        else:
            return
        self._active_item = None
        if self.on_activate:
            self.on_activate(None)
        self._build()

    def dispatch_gpu_scroll(self, delta_y: float) -> None:
        if delta_y > 0:
            self._scroll_by_delta(120)
        elif delta_y < 0:
            self._scroll_by_delta(-120)

    def _on_scroll(self, e):
        self._scroll_by_delta(getattr(e, 'delta', 0))

    def play_enter_animation(self):
        """下落入场: 单时间轴动画，避免 5 路 after 同时抢帧。"""
        self._stop_float()
        self._enter_active = True
        self._enter_t0 = time.time()
        for btn in self._buttons:
            btn.configure(cursor='')
            btn._size = 1.0
            btn._draw()
            btn._float_prev_s = 1
            btn._cursor_ready = False
        self._start_float()


    # ── 浮动 + 鱼眼循环 ──────────────────────────────────────────

    def _start_float(self):
        if self._float_registered or not self.winfo_exists():
            return
        try:
            _get_scheduler().register(
                self._float_sched_ident,
                self._tick_float,
                self._float_animating,
            )
            self._float_registered = True
        except Exception:
            self._float_registered = False
        self._tick_float(time.time())

    def _stop_float(self):
        if self._float_registered:
            try:
                _get_scheduler().unregister(self._float_sched_ident)
            except Exception:
                pass
            self._float_registered = False
        # NOTE: GPU painter teardown lives in _on_destroy, not here.
        # _stop_float fires every time the fisheye settles; the painter
        # must persist across rest ↔ hover transitions.

    def _on_destroy(self) -> None:
        """Bound to <Destroy>; releases the float scheduler AND any
        long-lived resources (the GPU painter)."""
        self._stop_float()
        if self._gpu_painter is not None:
            try:
                self._gpu_painter.destroy()
            except Exception:
                pass
            self._gpu_painter = None

    def _float_animating(self) -> bool:
        if not self.winfo_exists() or not self._buttons:
            return False
        if self._enter_active:
            return True
        if self._hover_idx is not None:
            return True
        for btn in self._buttons:
            if abs(float(btn._size) - float(SAOCircleButton.SIZE)) > 0.18:
                return True
        return False

    @_probe.decorate('ui.menu.fisheye_tick')
    def _tick_float(self, _now: float):
        if not self.winfo_exists() or not self._buttons:
            return
        keep_animating, ready_indices = _CY_UI.menu_bar_advance_buttons(
            self._buttons, _now,
            self._enter_active, self._enter_t0,
            self._enter_delay_s, self._enter_duration_s,
            self._hover_idx, float(SAOCircleButton.SIZE),
            0.18, 0.28,
        )
        ready_set = set(ready_indices)
        for i, btn in enumerate(self._buttons):
            if i in ready_set and getattr(btn, '_cursor_ready', False) is not True:
                btn.configure(cursor='hand2')
                btn._cursor_ready = True
            s = max(1, int(round(btn._size)))
            # v2.1.17: trigger redraw on 1/4 px changes for subpixel-smooth
            # fisheye motion (the actual paint dedup happens via _visual_sig).
            sq = round(float(btn._size) * 4.0) / 4.0
            prev_q = getattr(btn, '_float_prev_q', None)
            if prev_q != sq:
                btn._draw()
                btn._float_prev_q = sq
                btn._float_prev_s = s
        # v2.3.0 Phase 3+: feed the GPU painter once per tick after all
        # button states have settled. The painter snapshots state by
        # value and dedupes internally so calling every tick is cheap.
        if self._gpu_painter is not None and self._gpu_color_fns is not None:
            try:
                self._dispatch_gpu_paint()
            except Exception:
                pass
        if self._enter_active and not keep_animating:
            self._enter_active = False
        if not keep_animating and self._hover_idx is None:
            self._stop_float()

    def _dispatch_gpu_paint(self) -> None:
        """Snapshot all button visual states and feed them to the GPU
        painter. Runs on the Tk main thread; reads winfo for screen
        position. The painter's worker does the PIL composite."""
        if not self._buttons or _ButtonSnapshot is None:
            return
        if not self.winfo_exists() or not self.winfo_ismapped():
            return
        # Defer the dispatch until Tk has actually laid out the menu
        # bar. Without this the very first tick after a popup opens
        # can fire before geometry is realised, returning rootx=0/
        # rooty=0 (or a 1-px wide frame) — the GPU window then lands
        # at the monitor top-left and the buttons appear missing /
        # misaligned until the user moves the mouse over them.
        if self.winfo_width() <= 1 or self.winfo_height() <= 1:
            return
        try:
            sx, sy = self.winfo_rootx(), self.winfo_rooty()
        except Exception:
            return
        if sx <= 0 and sy <= 0:
            # Tk has not yet positioned the popup; try again next tick.
            return
        max_sz = SAOCircleButton.MAX_SIZE
        slot = self._SLOT
        n = len(self._buttons)
        strip_w = max_sz
        strip_h = slot * n
        snaps = [
            _ButtonSnapshot(b._size, b._hover_t, b._active, b.icon_text)
            for b in self._buttons
        ]
        self._gpu_painter.tick(sx, sy, strip_w, strip_h, snaps,
                               self._gpu_color_fns)

    def _on_fisheye(self, idx: int):
        self._hover_idx = idx
        self._start_float()

    def _off_fisheye(self):
        self._hover_idx = None
        self._start_float()


