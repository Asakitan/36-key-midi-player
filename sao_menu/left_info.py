# -*- coding: utf-8 -*-
"""SAOLeftInfo (split from sao_theme.py — verbatim)."""
import tkinter as tk
import math
from typing import Any, Optional, Tuple
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from utils.perf_probe import probe as _probe
from gui_modules.sao_menu_hud import MenuLeftInfoRenderer
try:
    # v2.3.0 Phase 3+: GPU-presented left info panel. Same pattern as
    # MenuBar: Tk Canvases stay invisible at chroma key, painter owns
    # one GLFW window covering the panel's bounding box.
    from gui_modules.sao_left_info_gpu import (
        LeftInfoGpuPainter,
        _LeftInfoSnapshot,
        gpu_left_info_enabled,
    )
except Exception as _left_gpu_import_error:
    _LEFT_GPU_IMPORT_ERROR = _left_gpu_import_error
    LeftInfoGpuPainter = None  # type: ignore[assignment]
    _LeftInfoSnapshot = None  # type: ignore[assignment]
    def gpu_left_info_enabled() -> bool:  # type: ignore[no-redef]
        raise RuntimeError('LeftInfoGpuPainter GPU module is required') from _LEFT_GPU_IMPORT_ERROR
from sao_menu.animator import Animator
from sao_menu.utils import ease_in_out

# ──────────────────── 左侧信息面板 (LeftInfo) ────────────────────
class SAOLeftInfo(tk.Frame):
    """
    SAO 风格左侧用户信息面板
    - 顶部: 白色背景, 用户名 + 插槽内容
    - 底部: 灰色背景, 描述文字
    - 右三角箭头指示器
    - 展开/关闭动画
    """

    def __init__(self, parent, username: str = 'Player',
                 description: str = 'Welcome to SAO world', **kw):
        super().__init__(parent, bg=parent.cget('bg'), highlightthickness=0, **kw)
        self.username = username
        self.description = description
        self._active = False
        self._anim = Animator(self)
        self._target_w = 240
        self._top_h = 200
        self._bottom_h = 80
        self._open_ms = 240
        self._close_ms = 160
        self._pulse_ms = 180
        self._renderer = MenuLeftInfoRenderer()
        self._top_image_id = None
        self._top_photo = None
        self._bottom_image_id = None
        self._bottom_photo = None
        self._sweep_phase = 0.0
        self._sweep_strength = 0.0
        # GPU-required painter for the left info panel. _redraw_top/
        # _redraw_bottom skip Tk PhotoImage uploads and dispatch a
        # snapshot to the painter instead. Tk Canvases stay in place at
        # chroma-key bg so the GPU layer underneath shows through.
        # GPU painter: when attached we set Tk canvases to FINAL size
        # once (so the parent layout settles correctly) and never
        # configure them again per animation frame. The painter
        # receives the animated sizes via snapshot.
        self._gpu_painter: Optional[Any] = None
        self._gpu_managed: bool = False
        self._gpu_tk_sized: bool = False
        self._cached_screen_xy: Optional[Tuple[int, int]] = None
        # Q11: cache the last-configured (width, height) tuple so the per-tick
        # _apply_panel_progresses path can skip 4 Tk.cget() calls during the
        # 240ms open / close / pulse animation (60Hz tick).
        self._top_current_size: Tuple[int, int] = (0, 0)
        self._bottom_current_size: Tuple[int, int] = (0, 0)

        self._build()
        self._setup_gpu_painter()

    def _setup_gpu_painter(self) -> None:
        if LeftInfoGpuPainter is None:
            raise RuntimeError('LeftInfoGpuPainter GPU module is required')
        gpu_left_info_enabled()
        try:
            self._gpu_painter = LeftInfoGpuPainter(self.winfo_toplevel())
            self._gpu_managed = True
        except Exception:
            self._gpu_painter = None
            self._gpu_managed = False
            raise

    def _on_destroy(self) -> None:
        if self._gpu_painter is not None:
            try:
                self._gpu_painter.destroy()
            except Exception:
                pass
            self._gpu_painter = None

    def _build(self):
        bg = self.cget('bg')
        self._top = tk.Canvas(self, width=0, height=0,
                              bg=bg, highlightthickness=0)
        self._top.pack(anchor='nw')

        self._bottom = tk.Canvas(self, width=0, height=0,
                                 bg=bg, highlightthickness=0)
        self._bottom.pack(anchor='nw')
        self.bind('<Destroy>', lambda e: self._on_destroy(), add='+')
        # v2.3.0 Phase A2: invalidate cached screen origin on layout
        # change. <Configure> fires only when geometry actually moves.
        self.bind('<Configure>',
                  lambda e: setattr(self, '_cached_screen_xy', None),
                  add='+')

    def set_active(self, active: bool):
        if active == self._active:
            return
        self._active = active
        if active:
            self._animate_open()
        else:
            self._animate_close()

    def _animate_open(self):
        self._anim.cancel('close')

        def phase(t):
            self._apply_panel_state(t, opening=True)

        self._anim.animate('panel_sync', self._open_ms, phase, easing=ease_in_out)

    def _animate_close(self):
        self._anim.cancel('panel_sync')

        def fade(t):
            self._apply_panel_state(t, opening=False)

        self._anim.animate('close', self._close_ms, fade, easing=ease_in_out)

    def sync_pulse(self):
        if not self._active:
            return
        self._anim.cancel('close')

        def pulse(t):
            shrink = math.sin(t * math.pi)
            top_t = 1.0 - 0.040 * shrink
            bottom_t = 1.0 - 0.058 * shrink
            self._apply_panel_progresses(
                top_t, bottom_t,
                sweep_phase=t,
                sweep_strength=shrink * 0.88,
            )

        self._anim.animate('panel_sync', self._pulse_ms, pulse, easing=ease_in_out)

    def _apply_panel_state(self, t: float, opening: bool):
        t = max(0.0, min(1.0, t))
        if opening:
            top_t = t
            bottom_t = max(0.0, min(1.0, (t - 0.12) / 0.88))
        else:
            inv = 1.0 - t
            top_t = inv
            bottom_t = max(0.0, min(1.0, (inv - 0.04) / 0.96))

        self._apply_panel_progresses(top_t, bottom_t)

    @_probe.decorate('ui.menu.left_panel_apply')
    def _apply_panel_progresses(self, top_t: float, bottom_t: float,
                                sweep_phase: float = 0.0, sweep_strength: float = 0.0):
        (top_t, bottom_t,
         self._sweep_phase, self._sweep_strength,
         top_w, top_h, bottom_w, bottom_h) = _CY_UI.left_panel_progress_dims(
            top_t, bottom_t,
            self._target_w, self._top_h, self._bottom_h,
            sweep_phase, sweep_strength,
        )

        if self._gpu_managed and self._gpu_painter is not None \
                and _LeftInfoSnapshot is not None:
            # GPU path: resize Tk canvases ONCE to final/full target so
            # layout managers see a stable bounding box, then leave
            # them alone. The animated sizes only feed the painter.
            if not self._gpu_tk_sized:
                try:
                    self._top.configure(width=self._target_w,
                                        height=self._top_h)
                    self._bottom.configure(width=self._target_w,
                                           height=self._bottom_h)
                    self._top_current_size = (self._target_w, self._top_h)
                    self._bottom_current_size = (self._target_w, self._bottom_h)
                    self._gpu_tk_sized = True
                    self._cached_screen_xy = None
                except Exception:
                    pass
            self._dispatch_gpu_paint(top_w, top_h, bottom_w, bottom_h)
        else:
            _new_top = (top_w, top_h)
            if self._top_current_size != _new_top:
                self._top.configure(width=top_w, height=top_h)
                self._top_current_size = _new_top
            _new_bot = (bottom_w, bottom_h)
            if self._bottom_current_size != _new_bot:
                self._bottom.configure(width=bottom_w, height=bottom_h)
                self._bottom_current_size = _new_bot
            self._redraw_top(top_w, top_h)
            self._redraw_bottom(bottom_w, bottom_h)

    def _dispatch_gpu_paint(self, top_w: int, top_h: int,
                            bottom_w: int, bottom_h: int) -> None:
        if not self.winfo_exists() or not self.winfo_ismapped():
            return
        cached = self._cached_screen_xy
        if cached is None:
            try:
                cached = (self.winfo_rootx(), self.winfo_rooty())
            except Exception:
                return
            self._cached_screen_xy = cached
        sx, sy = cached
        snap = _LeftInfoSnapshot(
            self.username, self.description,
            top_w, top_h, bottom_w, bottom_h,
            self._sweep_phase, self._sweep_strength,
        )
        try:
            self._gpu_painter.tick(sx, sy, snap)
        except Exception:
            pass

    def _redraw_top(self, w, h):
        if w < 20 or h < 20:
            if self._top_image_id is not None:
                self._top.delete('all')
                self._top_image_id = None
                self._top_photo = None
            return
        photo = self._renderer.render_top(
            self.username, w, h,
            sweep_phase=self._sweep_phase,
            sweep_strength=self._sweep_strength,
        )
        if self._top_image_id is None:
            self._top.delete('all')
            self._top_image_id = self._top.create_image(0, 0, image=photo, anchor='nw')
        elif photo is not self._top_photo:
            self._top.itemconfigure(self._top_image_id, image=photo)
        self._top_photo = photo

    def _redraw_bottom(self, w, h):
        if w < 20 or h < 15:
            if self._bottom_image_id is not None:
                self._bottom.delete('all')
                self._bottom_image_id = None
                self._bottom_photo = None
            return
        photo = self._renderer.render_bottom(
            self.description, w, h,
            sweep_phase=self._sweep_phase,
            sweep_strength=self._sweep_strength,
        )
        if self._bottom_image_id is None:
            self._bottom.delete('all')
            self._bottom_image_id = self._bottom.create_image(0, 0, image=photo, anchor='nw')
        elif photo is not self._bottom_photo:
            self._bottom.itemconfigure(self._bottom_image_id, image=photo)
        self._bottom_photo = photo


