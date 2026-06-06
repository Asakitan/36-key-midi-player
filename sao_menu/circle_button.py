# -*- coding: utf-8 -*-
"""SAOCircleButton (split from sao_theme.py — verbatim)."""
import tkinter as tk
from typing import Optional, Callable
from PIL import Image, ImageTk
from render.overlay_subpixel import subpixel_alpha_composite
from gui_modules.sao_menu_hud import MenuCircleButtonRenderer
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from sao_menu.colors import SAOColors
from sao_menu.animator import Animator
from sao_menu.utils import lerp

# ──────────────────── 圆形图标按钮 ────────────────────
class SAOCircleButton(tk.Canvas):
    """
    SAO 风格圆形图标按钮 (54px)
    - 边框 2px solid rgba(201,198,198,0.6)
    - 内圆白底 + 图标
    - 激活: 金色边框 + 金色填充
    - 悬停: 金色高亮
    """
    RADIUS = 27
    SIZE = 54
    # Canvas stays at this fixed size through the whole entry + fisheye
    # animation. The sprite inside is re-centered at the current _size to
    # produce the visual growth without paying for Tk geometry changes or
    # reallocating a new PhotoImage on every animation frame.
    MAX_SIZE = 70

    def __init__(self, parent, icon_text: str = '●', name: str = '',
                 can_activate: bool = True, command: Optional[Callable] = None, **kw):
        super().__init__(parent, width=self.MAX_SIZE, height=self.MAX_SIZE,
                         highlightthickness=0, bd=0, bg=parent.cget('bg'), **kw)
        self.icon_text = icon_text
        self.name = name
        self.can_activate = can_activate
        self.command = command
        self._active = False
        self._hovering = False
        self._hover_t = 0.0  # 0=normal, 1=hover/active (用于平滑过渡)
        self._size = float(self.SIZE)  # 实例级尺寸, 鱼眼缩放时动态修改
        self._anim = Animator(self)
        self._renderer = MenuCircleButtonRenderer()
        self._bg_item = None
        self._bg_photo = None
        # Reusable max-size canvas used to center each frame's sprite without
        # reallocating a Pillow image every tick.
        self._bg_canvas_image = Image.new(
            'RGBA', (self.MAX_SIZE, self.MAX_SIZE), (0, 0, 0, 0))
        self._visual_sig = None
        self._last_pasted_size: Optional[int] = None
        # v2.3.0 Phase 3+: when True, _draw becomes a no-op; the
        # painting is delegated to MenuBarGpuPainter on a GPU overlay
        # underneath. The Canvas widget remains for hit-testing only.
        self._gpu_managed: bool = False

        self._draw()
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, v):
        self._active = v
        self._draw()

    def _draw(self):
        # v2.3.0 Phase 3+: when a MenuBarGpuPainter owns this button's
        # visual layer, skip ALL Tk-side paint work. The Canvas remains
        # at chroma-key bg so the GPU layer underneath shows through,
        # and hit-test geometry is unchanged so click/Enter/Leave
        # bindings continue to fire.
        if self._gpu_managed:
            return
        # v2.2.10: subpixel fisheye. Render the sprite at the next-larger
        # integer size (so the renderer cache can still hit on each int
        # bucket) but composite it onto the canvas using the fractional
        # `_size` so smooth fisheye scaling no longer snaps to whole-pixel
        # parity flips (the visual "half-pixel tear" the user reported).
        size_f, size, size_q, off_pre, ioff_pre, snap_pre = _CY_UI.menu_circle_visual_metrics(
            float(self._size), float(self.MAX_SIZE))
        t = self._hover_t

        border_color, inner_fill, icon_color = _CY_UI.menu_circle_palette(
            bool(self._active), t,
            SAOColors.CIRCLE_BORDER, SAOColors.ACTIVE_BORDER,
            SAOColors.CIRCLE_BG, SAOColors.HOVER_BG,
            SAOColors.CIRCLE_ICON, SAOColors.HOVER_ICON,
            SAOColors.ACTIVE_BG, SAOColors.ACTIVE_ICON,
        )

        bg_key = self.cget('bg') or '#010101'
        # Quantize the floating size to 1/4 px so we still skip duplicate
        # paints when the animation has settled but redraw smoothly while
        # it's in motion.
        # v2.2.27: dedup by integer-snapped offset bucket as well, since
        # the renderer cache is keyed on int-size and the v2.2.26+ snap
        # path produces identical pixel output for any size_f within ±0.25
        # of the same integer offset. Without this, fisheye redrew every
        # frame because size_q kept ticking while the actual composite
        # was identical.
        sig_pos = (size, ioff_pre, True) if snap_pre else (size_q, off_pre, False)
        sig = (sig_pos, self.icon_text, border_color, inner_fill, icon_color, bg_key)
        if sig == self._visual_sig and self._bg_item is not None:
            return

        image = self._renderer.render(
            size,
            self.icon_text or '●',
            border_color,
            inner_fill,
            icon_color,
            bg_key,
        )

        # Full-clear is cheap on a 70x70 canvas; required because the
        # subpixel composite samples neighbouring pixels.
        canvas_img = self._bg_canvas_image
        canvas_img.paste((0, 0, 0, 0), (0, 0, self.MAX_SIZE, self.MAX_SIZE))
        # Center the (possibly oversized by ≤1 px) sprite at the float
        # _size so motion is continuous instead of stepping by 1 px.
        off = (self.MAX_SIZE - size_f) / 2.0
        # v2.2.26: use the cheap integer-composite path whenever the
        # fractional offset is within 0.10 px of an integer. On a 70 px
        # sprite that's a sub-perceptual shift but it skips PIL's BILINEAR
        # AFFINE transform (~0.17 ms → ~0.03 ms per button × 8 buttons).
        # Without this, the size_q quantization to 1/4 px still routed
        # 3 of every 4 frames through the slow subpixel path during
        # fisheye hover.
        # v2.2.27: bumped to 0.25 px. On a 70 px button at 60 fps, a
        # quarter-pixel snap is invisible (well below the 1 minute-of-arc
        # vernier acuity threshold at typical viewing distance), but it
        # catches ~50% of fisheye frames vs ~20% with the 0.10 threshold,
        # cutting per-tick wall from ~1.25 ms → ~0.6 ms per button (×8
        # buttons = ~5 ms saved per tick on Tk main thread).
        if snap_pre:
            canvas_img.alpha_composite(image, (int(ioff_pre), int(ioff_pre)))
        else:
            subpixel_alpha_composite(canvas_img, image, off_pre, off_pre)
        self._last_pasted_size = size

        if self._bg_photo is None:
            self._bg_photo = ImageTk.PhotoImage(canvas_img)
        else:
            try:
                self._bg_photo.paste(canvas_img)
            except Exception:
                self._bg_photo = ImageTk.PhotoImage(canvas_img)

        if self._bg_item is None:
            self.delete('all')
            self._bg_item = self.create_image(0, 0, image=self._bg_photo, anchor='nw')
        else:
            self.itemconfigure(self._bg_item, image=self._bg_photo)
        self._visual_sig = sig

    def _on_enter(self, e=None):
        self._hovering = True
        self._anim.animate('hover', 200,
                           lambda t: self._set_hover_t(t))

    def _on_leave(self, e=None):
        self._hovering = False
        start = self._hover_t

        def fade(t):
            self._set_hover_t(lerp(start, 0, t))

        self._anim.animate('hover', 200, fade)

    def _set_hover_t(self, t):
        t = max(0.0, min(1.0, t))
        # Quantize to ~20 buckets so the renderer's image cache actually
        # hits during smooth hover fades instead of missing every frame.
        tq = round(t * 20.0) / 20.0
        if abs(tq - self._hover_t) < 1e-4:
            return
        self._hover_t = tq
        self._draw()

    def _on_click(self, e=None):
        if self.can_activate:
            self._active = not self._active
        if self.command:
            self.command()
        self._draw()


