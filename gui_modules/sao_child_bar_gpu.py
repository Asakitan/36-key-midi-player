# -*- coding: utf-8 -*-
"""
sao_child_bar_gpu.py — GPU-presented child bar (popup submenu) for
SAOChildBar in `sao_theme.py`.

Phase 3+++ of the v2.3.0 overlay perf pass. Mirrors the same pattern
as `sao_menu_bar_gpu` and `sao_left_info_gpu`:

  * Tk widgets (the line/arrow Canvases, the row tk.Frames + Labels)
    stay alive for hit-testing (Enter/Leave/click bindings still
    fire). Their backgrounds are forced to chroma-key `#010101` so
    Tk paints nothing visible.
  * One GLFW transparent click-through window covers the full
    child-bar bounding box and presents the row strip via
    `BgraPresenter`.
  * The painter computes its own bbox from the snapshot (line column +
    arrow column + max row width) and walks the GpuOverlayWindow
    geometry on every dispatch so it tracks open/switch animations.

The compose closure uses pure PIL + ImageDraw (no Tk) and runs on the
shared `AsyncFrameWorker` lane. A signature dedup skips redundant
uploads when nothing visible changed.

Public API:

    gpu_child_bar_enabled() -> bool
    ChildBarGpuPainter(root)
        .tick(sx, sy, snap)        — dispatch one paint
        .clear()                   — present an empty frame
        .destroy()
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, List, Optional, Tuple

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont

try:
    from render import gpu_overlay_window as _gow
except Exception:
    _gow = None  # type: ignore[assignment]

import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from render.overlay_render_worker import AsyncFrameWorker
from utils.perf_probe import probe as _probe
from gui_modules.entity_gpu_policy import require_entity_gpu
from gui_modules.sao_menu_hud import _PIL_DRAW_LOCK


# ═══════════════════════════════════════════════
#  Public env gate
# ═══════════════════════════════════════════════

def gpu_child_bar_enabled() -> bool:
    """Child bar requires the shared Entity GPU backend."""
    return require_entity_gpu('ChildBarGpuPainter', _gow)


# ═══════════════════════════════════════════════
#  Snapshots (worker-safe, no Tk)
# ═══════════════════════════════════════════════

class _RowSnapshot:
    __slots__ = ('icon', 'label', 'hover_t', 'row_w')

    def __init__(self, icon: str, label: str, hover_t: float, row_w: int):
        self.icon = icon
        self.label = label
        self.hover_t = max(0.0, min(1.0, float(hover_t)))
        self.row_w = max(1, int(row_w))


class _ChildBarSnapshot:
    __slots__ = ('line_w', 'line_h', 'arrow_w', 'fade_t', 'rows',
                 'bg_hex', 'colors')

    def __init__(self, line_w: int, line_h: int, arrow_w: int,
                 fade_t: float, rows: List[_RowSnapshot],
                 bg_hex: str, colors: 'BarColors'):
        self.line_w = max(1, int(line_w))
        self.line_h = max(1, int(line_h))
        self.arrow_w = max(1, int(arrow_w))
        self.fade_t = max(0.0, min(1.0, float(fade_t)))
        self.rows = rows
        self.bg_hex = bg_hex
        self.colors = colors


class BarColors:
    """Captures palette + lerp helper as plain values so the worker
    closure has no Tk/sao_theme dependency."""
    __slots__ = ('child_bg', 'child_hover', 'child_text', 'child_hover_fg',
                 'child_icon', 'active_border', 'lerp')

    def __init__(self, child_bg: str, child_hover: str, child_text: str,
                 child_hover_fg: str, child_icon: str, active_border: str,
                 lerp_color):
        self.child_bg = child_bg
        self.child_hover = child_hover
        self.child_text = child_text
        self.child_hover_fg = child_hover_fg
        self.child_icon = child_icon
        self.active_border = active_border
        self.lerp = lerp_color


# Layout constants — must match _create_item / _rebuild
ROW_H = 44
ROW_STRIDE = 47
ROW_X_INDICATOR_W = 2
ROW_X_PAD_L = 8
ROW_X_ICON_GAP = 5
ROW_X_PAD_R = 8
LINE_COL_W = 10
LINE_COL_PAD_R = 3
ARROW_COL_W = 12
ARROW_COL_PAD_R = 2
LINE_TOP_PAD = 5
ARROW_TOP_PAD = 5
ICON_FONT_SIZE = 12
LABEL_FONT_SIZE = 10
LIST_X = LINE_COL_W + LINE_COL_PAD_R + ARROW_COL_W + ARROW_COL_PAD_R  # 27


_font_tls = threading.local()
_FONT_PATH_CACHE: dict = {}
_MISSING_GLYPH_PROBES = ('\u0378', '\u0380', '\ufdd0', '\U000f0000')


def _resolve_font_path(filename: str) -> Optional[str]:
    """Resolve a font filename to an absolute path under FONTS_DIR or
    a Windows system font path. Returns None if not found."""
    cached = _FONT_PATH_CACHE.get(filename)
    if cached is not None:
        return cached if cached else None
    # Try project FONTS_DIR first
    try:
        from config import FONTS_DIR as _fonts_dir
        path = os.path.join(_fonts_dir, filename)
        if os.path.exists(path):
            _FONT_PATH_CACHE[filename] = path
            return path
    except Exception:
        pass
    # Try Windows system fonts
    try:
        win_dir = os.environ.get('WINDIR', r'C:\Windows')
        path = os.path.join(win_dir, 'Fonts', filename)
        if os.path.exists(path):
            _FONT_PATH_CACHE[filename] = path
            return path
    except Exception:
        pass
    # Last-ditch: hand the filename to PIL and let it resolve via OS
    try:
        ImageFont.truetype(filename, size=10)
        _FONT_PATH_CACHE[filename] = filename
        return filename
    except Exception:
        _FONT_PATH_CACHE[filename] = ''
        return None


# Fallback chains: primary → progressively wider coverage → bitmap.
# Both icon and label chains include the CJK font (ZhuZiAYuanJWD) and
# Microsoft YaHei so codepoints missing from SAOUI render correctly.
_ICON_FALLBACK_FILES = (
    'SAOUI.ttf', 'ZhuZiAYuanJWD.ttf',
    'msyh.ttc', 'msyhbd.ttc', 'simhei.ttf',
    'seguisym.ttf', 'seguiemj.ttf', 'segoeui.ttf', 'arial.ttf',
)
_LABEL_FALLBACK_FILES = (
    'ZhuZiAYuanJWD.ttf', 'msyh.ttc', 'msyhbd.ttc', 'simhei.ttf',
    'seguisym.ttf', 'seguiemj.ttf', 'SAOUI.ttf', 'segoeui.ttf', 'arial.ttf',
)


def _build_font_chain(size: int, filenames) -> list:
    fonts = []
    for fn in filenames:
        path = _resolve_font_path(fn)
        if not path:
            continue
        try:
            fonts.append(ImageFont.truetype(path, size=size))
        except Exception:
            continue
    if not fonts:
        try:
            fonts.append(ImageFont.load_default())
        except Exception:
            pass
    return fonts


def _icon_font_chain(size: int) -> list:
    cache = getattr(_font_tls, 'icon_chain', None)
    if cache is None:
        cache = {}
        _font_tls.icon_chain = cache
    chain = cache.get(size)
    if chain is None:
        chain = _build_font_chain(size, _ICON_FALLBACK_FILES)
        cache[size] = chain
    return chain


def _label_font_chain(size: int) -> list:
    cache = getattr(_font_tls, 'label_chain', None)
    if cache is None:
        cache = {}
        _font_tls.label_chain = cache
    chain = cache.get(size)
    if chain is None:
        chain = _build_font_chain(size, _LABEL_FALLBACK_FILES)
        cache[size] = chain
    return chain


def _icon_font_cached(size: int) -> ImageFont.FreeTypeFont:
    chain = _icon_font_chain(size)
    return chain[0]


def _label_font_cached(size: int) -> ImageFont.FreeTypeFont:
    chain = _label_font_chain(size)
    return chain[0]


def _glyph_signature(font: ImageFont.FreeTypeFont, ch: str):
    mask = font.getmask(ch)
    return (mask.size, bytes(mask))


def _missing_glyph_signatures(font: ImageFont.FreeTypeFont) -> set:
    cache = getattr(_font_tls, 'missing_sig', None)
    if cache is None:
        cache = {}
        _font_tls.missing_sig = cache
    key = (id(font), getattr(font, 'size', 0))
    sigs = cache.get(key)
    if sigs is None:
        sigs = set()
        for probe in _MISSING_GLYPH_PROBES:
            try:
                sigs.add(_glyph_signature(font, probe))
            except Exception:
                pass
        cache[key] = sigs
    return sigs


def _glyph_supported(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    """Return True if the font has a real glyph for `ch` (not tofu)."""
    if not ch or ch.isspace():
        return True
    try:
        mask = font.getmask(ch)
        bbox = mask.getbbox()
        if bbox is None or (bbox[2] - bbox[0]) <= 0 or (bbox[3] - bbox[1]) <= 0:
            return False
        return (mask.size, bytes(mask)) not in _missing_glyph_signatures(font)
    except Exception:
        return False


def _draw_text_with_fallback(draw: ImageDraw.ImageDraw, xy, text: str,
                             chain: list, fill) -> int:
    """Draw `text` left-to-right; per character pick the first font in
    `chain` that has a glyph. Whitespace is always allowed via the
    primary font. Returns the advanced x offset from the starting xy."""
    if not text or not chain:
        return 0
    primary = chain[0]
    x, y = xy
    x0 = x
    for ch in text:
        chosen = primary
        if ch != ' ' and not _glyph_supported(primary, ch):
            for fb in chain[1:]:
                if _glyph_supported(fb, ch):
                    chosen = fb
                    break
        try:
            draw.text((x, y), ch, fill=fill, font=chosen)
        except Exception:
            pass
        try:
            x += int(draw.textlength(ch, font=chosen))
        except Exception:
            x += chosen.size if hasattr(chosen, 'size') else 8
    return x - x0


# ═══════════════════════════════════════════════
#  Compose helper (worker-safe)
# ═══════════════════════════════════════════════

def _compose_child_bar(snap: _ChildBarSnapshot, total_w: int, total_h: int) -> Image.Image:
    # Shares the same menu overlay worker race as sao_menu_hud.py:
    # first fast submenu-open and every second submenu switch can
    # schedule child-bar GPU compose concurrently with the HUD/menu-bar
    # workers. Serialize the entire child-bar PIL/FreeType entry point
    # under the existing process-wide RLock so Image.new/ImageDraw/
    # getmask/truetype never overlap across threads.
    with _PIL_DRAW_LOCK:
        img = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        colors = snap.colors
        bg = snap.bg_hex
        fade_t = snap.fade_t

        # Line column
        line_h = snap.line_h
        line_w = max(1, snap.line_w)
        if line_w > 1 and line_h > 5:
            glow_color = colors.lerp('#d4d0d0', bg, fade_t)
            main_color = colors.lerp('#9c9999', bg, fade_t)
            dot_color = colors.lerp('#b0b0b0', bg, fade_t)
            cx = LINE_COL_W // 2
            ly = LINE_TOP_PAD
            draw.line((cx, ly + 5, cx, ly + line_h - 5), fill=glow_color, width=4)
            draw.line((cx, ly + 5, cx, ly + line_h - 5), fill=main_color, width=2)
            draw.ellipse((cx - 2, ly + 3, cx + 2, ly + 7), fill=dot_color)
            draw.ellipse((cx - 2, ly + line_h - 7, cx + 2, ly + line_h - 3),
                         fill=dot_color)

        # Arrow column
        arrow_x = LINE_COL_W + LINE_COL_PAD_R
        arrow_w = max(1, snap.arrow_w)
        if arrow_w > 1 and line_h > 5:
            ay = ARROW_TOP_PAD
            cx = 6
            cy = ay + line_h // 2
            for gr in range(6, 0, -2):
                ga = int(15 * (1 - gr / 6))
                base_hex = '#%02x%02x%02x' % (
                    int(ga * 3.5) & 0xFF,
                    int(ga * 2.2) & 0xFF,
                    int(ga * 0.3) & 0xFF,
                )
                faded = colors.lerp(base_hex, bg, fade_t)
                draw.ellipse((arrow_x + cx - gr, cy - gr,
                              arrow_x + cx + gr, cy + gr),
                             fill=faded)
            core_fill = colors.lerp('#c9b896', bg, fade_t)
            core_outline = colors.lerp('#d4c8a8', bg, fade_t)
            draw.ellipse((arrow_x + 4, cy - 2, arrow_x + 9, cy + 3),
                         fill=core_fill, outline=core_outline)

        # Rows
        icon_chain = _icon_font_chain(ICON_FONT_SIZE)
        label_chain = _label_font_chain(LABEL_FONT_SIZE)

        for idx, row in enumerate(snap.rows):
            row_y = idx * ROW_STRIDE
            ht = row.hover_t
            rw = row.row_w
            if rw <= 1:
                continue
            bg_now = colors.lerp(colors.child_bg, colors.child_hover, ht)
            fg_now = colors.lerp(colors.child_text, colors.child_hover_fg, ht)
            icon_now = colors.lerp(colors.child_icon, colors.child_hover_fg, ht)
            ind_now = colors.lerp(colors.child_bg, colors.active_border, ht)
            bg_blend = colors.lerp(bg_now, bg, fade_t)
            fg_blend = colors.lerp(fg_now, bg, fade_t)
            icon_blend = colors.lerp(icon_now, bg, fade_t)
            ind_blend = colors.lerp(ind_now, bg, fade_t)

            draw.rectangle((LIST_X, row_y, LIST_X + rw, row_y + ROW_H),
                           fill=bg_blend)
            draw.rectangle((LIST_X, row_y, LIST_X + ROW_X_INDICATOR_W, row_y + ROW_H),
                           fill=ind_blend)

            ic_x = LIST_X + ROW_X_INDICATOR_W + ROW_X_PAD_L
            ic_y = row_y + (ROW_H - ICON_FONT_SIZE) // 2 - 2
            ic_w = 0
            if row.icon:
                ic_w = _draw_text_with_fallback(
                    draw, (ic_x, ic_y), row.icon, icon_chain, icon_blend,
                )
            if ic_w <= 0:
                ic_w = ICON_FONT_SIZE
            lbl_x = ic_x + ic_w + ROW_X_ICON_GAP
            lbl_y = row_y + (ROW_H - LABEL_FONT_SIZE) // 2 - 2
            max_lbl_w = max(0, LIST_X + rw - lbl_x - ROW_X_PAD_R - 6)
            if row.label and max_lbl_w > 4:
                _draw_text_with_fallback(
                    draw, (lbl_x, lbl_y), row.label, label_chain, fg_blend,
                )
            if ht > 0.05:
                arr_x = LIST_X + rw - ROW_X_PAD_R - 6
                arr_y = row_y + (ROW_H - 14) // 2 - 1
                arr_color = colors.lerp(colors.child_bg, colors.child_hover_fg, ht)
                arr_blend = colors.lerp(arr_color, bg, fade_t)
                _draw_text_with_fallback(
                    draw, (arr_x, arr_y), '\u203a', label_chain, arr_blend,
                )

        return img


# ═══════════════════════════════════════════════
#  Painter
# ═══════════════════════════════════════════════

class ChildBarGpuPainter:
    """Owns one GpuOverlayWindow + AsyncFrameWorker for the child bar."""

    def __init__(self, root: tk.Misc, click_cb=None, hover_cb=None,
                 leave_cb=None):
        self._root = root
        self._render_worker = AsyncFrameWorker(prefer_isolation=True)
        self._gpu_window: Optional[Any] = None
        self._presenter: Optional[Any] = None
        self._destroyed = False
        self._last_sig: Optional[tuple] = None
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        self._lock = threading.Lock()
        # Interactive input: the child bar can't rely on click-through + the Tk
        # overlay catching passed-through clicks (in this app's window z-order
        # those clicks miss the Tk rows entirely → submenu items never fire).
        # When given callbacks we make the GPU window interactive and dispatch
        # row click/hover ourselves via window-local hit-testing.
        self._click_cb = click_cb
        self._hover_cb = hover_cb
        self._leave_cb = leave_cb
        self._row_count = 0
        self._hover_idx: Optional[int] = None

    def _ensure_window(self, w: int, h: int, x: int, y: int) -> bool:
        if self._gpu_window is not None:
            return True
        require_entity_gpu('ChildBarGpuPainter', _gow)
        try:
            pump = _gow.get_glfw_pump(self._root)
            self._presenter = _gow.BgraPresenter()
            interactive = any(cb is not None for cb in
                              (self._click_cb, self._hover_cb, self._leave_cb))
            self._gpu_window = _gow.GpuOverlayWindow(
                pump,
                w=max(1, int(w)), h=max(1, int(h)),
                x=int(x), y=int(y),
                render_fn=self._presenter.render,
                click_through=not interactive,
                title='sao_child_bar_gpu',
            )
            if interactive:
                self._gpu_window.set_input_callbacks(
                    cursor_pos_fn=self._handle_cursor_pos,
                    cursor_leave_fn=self._handle_cursor_leave,
                    mouse_button_fn=self._handle_mouse_button,
                )
            self._gpu_window.show()
            return True
        except Exception as exc:
            self._presenter = None
            self._gpu_window = None
            raise RuntimeError('ChildBarGpuPainter requires GPU window support') from exc

    # ── window-local hit-testing (rows are drawn at y = idx*ROW_STRIDE) ──
    def _row_at(self, x: float, y: float) -> Optional[int]:
        if self._row_count <= 0 or y < 0:
            return None
        idx = int(y // ROW_STRIDE)
        if idx < 0 or idx >= self._row_count:
            return None
        if (y - idx * ROW_STRIDE) > ROW_H:   # in the gap between rows
            return None
        return idx

    def _handle_mouse_button(self, button: int, action: int,
                             _mods: int, x: float, y: float) -> None:
        if button != 0 or action != 1:   # left button press only
            return
        idx = self._row_at(x, y)
        if idx is not None and self._click_cb is not None:
            try:
                self._click_cb(idx)
            except Exception:
                pass

    def _handle_cursor_pos(self, x: float, y: float) -> None:
        idx = self._row_at(x, y)
        if idx is None:
            self._handle_cursor_leave()
            return
        if idx == self._hover_idx:
            return
        self._hover_idx = idx
        if self._hover_cb is not None:
            try:
                self._hover_cb(idx)
            except Exception:
                pass

    def _handle_cursor_leave(self) -> None:
        if self._hover_idx is None:
            return
        self._hover_idx = None
        if self._leave_cb is not None:
            try:
                self._leave_cb()
            except Exception:
                pass

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
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

    def clear(self) -> None:
        if self._destroyed:
            return
        self._last_sig = None
        if self._presenter is not None:
            try:
                self._presenter.clear()
            except Exception:
                pass
        if self._gpu_window is not None:
            try:
                self._gpu_window.request_redraw()
            except Exception:
                pass

    @_probe.decorate('ui.menu.child_bar_gpu_tick')
    def tick(self, screen_x: int, screen_y: int,
             snap: _ChildBarSnapshot) -> None:
        if self._destroyed:
            return
        if not snap.rows:
            self._row_count = 0
            self.clear()
            return

        self._row_count = len(snap.rows)   # for window-local click/hover hit-test
        max_row_w = max(r.row_w for r in snap.rows)
        out_w = max(1, LIST_X + max_row_w)
        rows_h = len(snap.rows) * ROW_STRIDE - 3
        line_h_pad = LINE_TOP_PAD + snap.line_h
        out_h = max(rows_h, line_h_pad)
        if out_w < 4 or out_h < 4:
            return
        if not self._ensure_window(out_w, out_h, screen_x, screen_y):
            return

        # 1) Drain previous result and present.
        fb = self._render_worker.take_result(allow_during_capture=True)
        if fb is not None:
            self._last_fb_size = (fb.width, fb.height)
        # Keep the window at the CURRENT live origin (screen_x/screen_y) EVERY
        # tick — independent of whether a new bitmap arrived. The child bar
        # re-aligns to the clicked circle on a category switch; gating the move
        # on `fb is not None` froze the submenu at the previous category's spot
        # (or top-left from an early frame) whenever the async worker had nothing
        # ready during the switch animation. Size tracks the last rendered buffer
        # (the bitmap is position-independent).
        win_w, win_h = getattr(self, '_last_fb_size', None) or (out_w, out_h)
        if self._gpu_window is not None:
            geom = (screen_x, screen_y, win_w, win_h)
            if geom != self._last_geom:
                try:
                    self._gpu_window.set_geometry(*geom)
                    self._last_geom = geom
                except Exception:
                    pass
        if fb is not None and self._gpu_window is not None and self._presenter is not None:
            try:
                self._presenter.set_frame(fb.bgra_bytes, fb.width, fb.height)
                self._gpu_window.request_redraw()
            except Exception:
                pass

        # 2) Build dedup signature.
        sig = _CY_UI.popup_child_snapshot_sig(
            out_w, out_h,
            snap.line_w, snap.line_h, snap.arrow_w,
            snap.fade_t, snap.bg_hex, snap.rows,
        )
        with self._lock:
            if sig == self._last_sig:
                return
            self._last_sig = sig

        # 3) Submit compose. Capture state by value.
        s = snap
        out_w_local = out_w
        out_h_local = out_h

        def compose(_now: float) -> Image.Image:
            return _compose_child_bar(s, out_w_local, out_h_local)

        try:
            self._render_worker.submit(
                compose, time.perf_counter(),
                0, int(screen_x), int(screen_y),
            )
        except Exception:
            pass
