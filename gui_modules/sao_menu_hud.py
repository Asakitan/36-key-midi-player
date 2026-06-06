from __future__ import annotations

import datetime as _dt
import math
import os
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
try:
    import _sao_cy_skillfx as _CY_SKILLFX  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    _CY_SKILLFX = None  # type: ignore[assignment]


# v2.3.3 GIL-safety fix.
#
# PIL._imagingft (FreeType) is NOT internally re-entrant: when two
# overlay-compose worker threads concurrently call ImageDraw.text()
# / textbbox() / ImageFont.truetype(), the C-level FT_Library state
# corrupts and the main thread's tstate is NULLed at the next
# Tcl_DoOneEvent reacquire ("Fatal Python error: PyEval_RestoreThread:
# the function must be called with the GIL held, but the GIL is
# released (the current Python thread state is NULL)").
#
# The trigger that the user reports — clicking a floating menu bar
# button → menu re-layout (resize) → crash — is exactly this race:
# the click changes the menu HUD content_w/content_h, MenuHudOverlay
# enqueues a fresh render_pil() compose with the new size on its
# overlay-compose lane (rebuilds the static layer with FreeType-rendered
# 'SYS:MENU' / 'ACTIVE' labels + stamp text), AND the SAO menu bar
# painter on a different lane is mid-recompose for the fisheye animation
# (FreeType for icon glyphs).  Two lanes in PIL FreeType simultaneously
# corrupt FT state.
#
# Fix: a single module-level RLock serializes every renderer entry point
# that may rasterize text / build a draw context.  Held across entire
# render(), render_pil(), and MenuCircleButtonRenderer.render() calls
# so the FreeType native code never overlaps across threads.  The lock
# is held during GIL-released PIL ops; that's intentional — other Python
# threads can still acquire the GIL while we wait for FreeType, and the
# wait time is bounded by one compose (≈3-30 ms).
#
# RLock so that a renderer entry point can call its own helpers that
# also acquire the lock without deadlocking.
_PIL_DRAW_LOCK: threading.RLock = threading.RLock()

try:
    from render.gpu_renderer import gaussian_blur_rgba as _gpu_blur
    from render.gpu_renderer import render_shell_rgba as _gpu_shell
except Exception:
    _gpu_blur = None
    _gpu_shell = None

from utils.perf_probe import probe as _probe


_BASE = (
    getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    if getattr(sys, 'frozen', False)
    # Round 61 of sao_gui split refactor: this file moved from the project
    # root into gui_modules/, so __file__ now lives one level deeper. Use
    # dirname twice to keep the dev-mode fallback pointing at sao_auto/.
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
# v2.1.2-f: 优先使用 config 的 lifted-out 路径解析器, 兼容
# build_release.bat 把 assets/ 提升到 EXE 顶层的模块化布局.
try:
    from config import FONTS_DIR as _CFG_FONTS_DIR
    _FONTS_DIR = _CFG_FONTS_DIR
except Exception:
    _FONTS_DIR = os.path.join(_BASE, 'assets', 'fonts')
_FONT_SAO = os.path.join(_FONTS_DIR, 'SAOUI.ttf')
_FONT_CJK = os.path.join(_FONTS_DIR, 'ZhuZiAYuanJWD.ttf')


def _hex_to_rgb_tuple(color: str, fallback: Tuple[int, int, int] = (1, 1, 1)) -> Tuple[int, int, int]:
    if not isinstance(color, str):
        return fallback
    raw = color.strip().lstrip('#')
    if len(raw) == 8:
        raw = raw[:6]
    if len(raw) == 3:
        raw = ''.join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return fallback
    try:
        return tuple(int(raw[idx:idx + 2], 16) for idx in (0, 2, 4))
    except Exception:
        return fallback


def _rgba_to_hex(color: Tuple[int, int, int, int]) -> str:
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    return f'#{r:02x}{g:02x}{b:02x}'


def _tk_font_spec(kind: str, size: int) -> Tuple:
    """Return a Tk font spec, preferring the installed SAO UI/CJK face so
    the Canvas stamp looks identical to the PIL-rendered version. Falls
    back to a system font if sao_sound.get_sao_font is unavailable."""
    try:
        if kind == 'sao':
            from utils.sao_sound import get_sao_font as _gs
            return _gs(max(6, int(size)))
        from utils.sao_sound import get_cjk_font as _gc
        return _gc(max(6, int(size)))
    except Exception:
        family = 'Segoe UI' if kind == 'sao' else 'Microsoft YaHei UI'
        return (family, max(6, int(size)))


@dataclass
class MenuHudFrame:
    """Lightweight per-frame descriptor for the menu HUD.

    Instead of a single composited PhotoImage, this splits the HUD into
    a static background photo + a handful of dynamic primitives that the
    caller renders via Canvas-native items (lines, images, text). This
    keeps the per-frame cost at a few coords()/itemconfigure() calls."""

    static_photo: ImageTk.PhotoImage
    static_size: Tuple[int, int]
    cx1: int
    cy1: int
    cx2: int
    cy2: int
    rail_x_l: int
    rail_x_r: int
    scan_y: int
    trail_ys: Tuple[int, int]
    scan_color: str
    trail_colors: Tuple[str, str]
    dot_y_l: int
    dot_y_r: int
    dot_color_l: str
    dot_color_r: str
    dot_photo_l: ImageTk.PhotoImage
    dot_photo_r: ImageTk.PhotoImage
    dot_radius: int
    dot_glow_size: int
    stamp_text: str
    stamp_pos: Tuple[int, int]
    stamp_color: str
    stamp_font: Tuple
    canvas_sig: Tuple[int, ...]


class MenuHudSpriteRenderer:
    _PLATE_PAD = 16
    _HUD_MARGIN = 6
    _BRACKET_LEN = 16
    _RAIL_OFFSET = 4
    _DOT_RADIUS = 2
    _CYAN = (94, 184, 202, 255)
    _GOLD = (243, 175, 18, 255)
    _DIM_CYAN = (94, 184, 202, 180)
    _DIM_GOLD = (200, 145, 14, 180)
    _SCAN_TRAIL = ((58, 106, 120, 255), (42, 80, 96, 255))
    _SHELL_SHADOW = (76, 122, 138, 24)

    def __init__(self) -> None:
        self._static_key: Optional[Tuple[int, int, int, int]] = None
        self._static_img: Optional[Image.Image] = None
        self._static_photo: Optional[ImageTk.PhotoImage] = None
        self._static_photo_size: Optional[Tuple[int, int]] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._photo_size: Optional[Tuple[int, int]] = None
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._dot_cache: Dict[Tuple[Tuple[int, int, int, int], int], Image.Image] = {}
        self._dot_photo_cache: Dict[Tuple[Tuple[int, int, int, int], int], ImageTk.PhotoImage] = {}
        self._stamp_second: Optional[int] = None
        self._stamp_text: str = ''
        # Per-frame dedup: if nothing visible would change, return the
        # cached PhotoImage without copying the static layer or repainting.
        self._frame_sig: Optional[Tuple[int, ...]] = None
        # v2.2.25: reusable scratch buffer for render_pil. Avoids a
        # ~840 KB Image alloc + memcpy per frame at 60 Hz; we re-blit
        # the cached static into it via the C-implemented Image.paste.
        self._scratch: Optional[Image.Image] = None
        self._scratch_size: Optional[Tuple[int, int]] = None
        # v2.2.25: pre-rendered stamp sprite (text only), invalidated when
        # the second changes. Avoids font rasterization every frame.
        self._stamp_sprite: Optional[Image.Image] = None
        self._stamp_sprite_text: Optional[str] = None
        self._stamp_sprite_size: Tuple[int, int] = (0, 0)
        self._canvas_frame: Optional[MenuHudFrame] = None
        self._pil_frame_sig: Optional[Tuple[int, ...]] = None
        self._pil_frame_cache: Optional[Image.Image] = None
        self._pil_frame_off: Tuple[int, int] = (0, 0)
        self._scan_color_hex = _rgba_to_hex(self._CYAN)
        self._trail_colors_hex = (
            _rgba_to_hex(self._SCAN_TRAIL[0]),
            _rgba_to_hex(self._SCAN_TRAIL[1]),
        )
        self._dot_color_l_hex = _rgba_to_hex(self._CYAN)
        self._dot_color_r_hex = _rgba_to_hex(self._GOLD)
        self._stamp_color_hex = _rgba_to_hex(self._DIM_GOLD)
        self._stamp_font_spec = _tk_font_spec('sao', 10)

    def reset(self) -> None:
        self._static_key = None
        self._static_img = None
        self._static_photo = None
        self._static_photo_size = None
        self._photo = None
        self._photo_size = None
        self._stamp_second = None
        self._stamp_text = ''
        self._frame_sig = None
        self._scratch = None
        self._scratch_size = None
        self._stamp_sprite = None
        self._stamp_sprite_text = None
        self._stamp_sprite_size = (0, 0)
        self._canvas_frame = None
        self._pil_frame_sig = None
        self._pil_frame_cache = None
        self._pil_frame_off = (0, 0)

    @_probe.decorate('ui.menu.render_canvas')
    def render(self, content_w: int, content_h: int,
               screen_w: int, screen_h: int,
               phase: float) -> 'MenuHudFrame':
        """Return a lightweight frame descriptor that can be drawn with
        Canvas-native primitives (lines, images, text).

        The previous implementation composited the full HUD into a single
        PhotoImage every tick, which required `static.copy()` + PIL draw
        ops + `PhotoImage.paste()` (~2.7 ms/frame at 60 Hz). By splitting
        the static background from the dynamic scan/dot/clock elements
        and letting Tk's Canvas animate them natively, we keep the exact
        visual output while cutting the per-frame cost ~>25x.

        Held under :data:`_PIL_DRAW_LOCK`: this entry point can be
        reached from the Tk main thread (Canvas fallback) while another
        worker is mid-render_pil — without the lock the two collide in
        FreeType.
        """
        with _PIL_DRAW_LOCK:
            return self._render_locked(content_w, content_h, screen_w, screen_h, phase)

    def _render_locked(self, content_w: int, content_h: int,
                       screen_w: int, screen_h: int,
                       phase: float) -> 'MenuHudFrame':
        content_w = max(260, int(content_w))
        content_h = max(180, int(content_h))
        screen_w = max(1, int(screen_w))
        screen_h = max(1, int(screen_h))

        cx1, cy1, cx2, cy2, scan_y, dot_y_l, dot_y_r = _CY_UI.popup_hud_dynamic(
            content_w, content_h, phase, self._PLATE_PAD,
            self._HUD_MARGIN, self._BRACKET_LEN)
        now = _dt.datetime.now()
        now_second = int(now.timestamp())
        frame_sig = (
            content_w, content_h, screen_w, screen_h,
            cx1, cy1, cx2, cy2, scan_y, dot_y_l, dot_y_r,
            now_second,
        )
        if frame_sig == self._frame_sig and self._canvas_frame is not None:
            return self._canvas_frame

        static_photo = self._get_static_photo(content_w, content_h,
                                              screen_w, screen_h)
        dot_photo_l = self._dot_photo(self._CYAN, 10)
        dot_photo_r = self._dot_photo(self._GOLD, 10)

        if self._stamp_second != now_second:
            self._stamp_second = now_second
            self._stamp_text = now.strftime('%H:%M:%S')

        frame = MenuHudFrame(
            static_photo=static_photo,
            static_size=self._static_photo_size or (0, 0),
            cx1=cx1, cy1=cy1, cx2=cx2, cy2=cy2,
            rail_x_l=cx1 - self._RAIL_OFFSET,
            rail_x_r=cx2 + self._RAIL_OFFSET,
            scan_y=scan_y,
            trail_ys=(scan_y - 2, scan_y - 4),
            trail_colors=self._trail_colors_hex,
            scan_color=self._scan_color_hex,
            dot_y_l=dot_y_l, dot_y_r=dot_y_r,
            dot_color_l=self._dot_color_l_hex,
            dot_color_r=self._dot_color_r_hex,
            dot_photo_l=dot_photo_l,
            dot_photo_r=dot_photo_r,
            dot_radius=self._DOT_RADIUS,
            dot_glow_size=dot_photo_l.width() if dot_photo_l else 30,
            stamp_text=self._stamp_text,
            stamp_pos=(cx2 - 2, cy2 + 2),   # Tk text anchor='ne'
            stamp_color=self._stamp_color_hex,
            stamp_font=self._stamp_font_spec,
            canvas_sig=(cx1, cy1, cx2, cy2, scan_y,
                        dot_y_l, dot_y_r, now_second),
        )
        self._frame_sig = frame_sig
        self._canvas_frame = frame
        return frame

    @_probe.decorate('ui.menu.render_pil')
    def render_pil(self, content_w: int, content_h: int,
                   screen_w: int, screen_h: int,
                   phase: float) -> Tuple[Image.Image, Tuple[int, int]]:
        """v2.2.12: compose the entire HUD into a single RGBA PIL.Image.

        Used by ``MenuHudOverlay`` (sao_gui_menu_hud) to drive a layered
        per-pixel-alpha window from a worker thread instead of the
        ``Toplevel(-transparentcolor) + Canvas`` chroma-key path. Touches
        no Tk objects so it is safe to call off the main thread.

        Returns ``(image, sprite_origin_offset)`` where the offset is the
        sprite's top-left relative to the content frame's top-left
        (``-PLATE_PAD, -PLATE_PAD``). The caller adds it to the desired
        on-screen position before submitting via ``ulw_commit``.

        Held under :data:`_PIL_DRAW_LOCK` — see module docstring.
        """
        with _PIL_DRAW_LOCK:
            return self._render_pil_locked(content_w, content_h, screen_w, screen_h, phase)

    def _render_pil_locked(self, content_w: int, content_h: int,
                           screen_w: int, screen_h: int,
                           phase: float) -> Tuple[Image.Image, Tuple[int, int]]:
        content_w = max(260, int(content_w))
        content_h = max(180, int(content_h))
        screen_w = max(1, int(screen_w))
        screen_h = max(1, int(screen_h))

        static = self._get_static_layer(
            content_w, content_h, screen_w, screen_h)
        # v2.2.25: reuse a single scratch RGBA image across frames. The
        # previous `static.copy()` allocated a fresh PIL Image (~840 KB
        # for a typical 480×440 menu HUD) every tick; at 60 Hz that's
        # 50 MB/s of pure allocation churn for the menu alone, on top of
        # the actual memcpy. We now keep one scratch buffer and re-blit
        # the cached static into it via the C-implemented Image.paste,
        # which is a straight memcpy with no Python-level allocation.
        sw_size = static.size
        if self._scratch is None or self._scratch_size != sw_size:
            self._scratch = Image.new('RGBA', sw_size, (0, 0, 0, 0))
            self._scratch_size = sw_size
        scratch = self._scratch
        scratch.paste(static, (0, 0))
        frame = scratch

        cx1, cy1, cx2, cy2, scan_y, dot_y_l, dot_y_r = _CY_UI.popup_hud_dynamic(
            content_w, content_h, phase, self._PLATE_PAD,
            self._HUD_MARGIN, self._BRACKET_LEN)

        now = _dt.datetime.now()
        now_second = int(now.timestamp())
        frame_sig = (
            content_w, content_h, screen_w, screen_h,
            cx1, cy1, cx2, cy2, scan_y, dot_y_l, dot_y_r,
            now_second,
        )
        if frame_sig == self._pil_frame_sig and self._pil_frame_cache is not None:
            return self._pil_frame_cache, self._pil_frame_off
        if self._stamp_second != now_second:
            self._stamp_second = now_second
            self._stamp_text = now.strftime('%H:%M:%S')

        self._draw_dynamic(frame, cx1, cy1, cx2, cy2,
                           scan_y, dot_y_l, dot_y_r,
                           self._stamp_text)
        self._pil_frame_sig = frame_sig
        self._pil_frame_cache = frame
        self._pil_frame_off = (-self._PLATE_PAD, -self._PLATE_PAD)
        return frame, self._pil_frame_off

    def _get_static_photo(self, content_w: int, content_h: int,
                          screen_w: int, screen_h: int) -> ImageTk.PhotoImage:
        key = (content_w, content_h, screen_w, screen_h)
        static = self._get_static_layer(content_w, content_h,
                                        screen_w, screen_h)
        if self._static_key == key and self._static_photo is not None:
            return self._static_photo
        self._static_photo = ImageTk.PhotoImage(static)
        self._static_photo_size = static.size
        return self._static_photo

    def _dot_photo(self, color: Tuple[int, int, int, int],
                   size: int) -> ImageTk.PhotoImage:
        key = (color, size)
        cached = self._dot_photo_cache.get(key)
        if cached is not None:
            return cached
        sprite = self._dot_sprite(color, size)
        photo = ImageTk.PhotoImage(sprite)
        self._dot_photo_cache[key] = photo
        return photo

    def sprite_origin(self, left: int, top: int) -> Tuple[int, int]:
        return int(left) - self._PLATE_PAD, int(top) - self._PLATE_PAD

    def _get_static_layer(self, content_w: int, content_h: int,
                          screen_w: int, screen_h: int) -> Image.Image:
        key = (content_w, content_h, screen_w, screen_h)
        if self._static_key == key and self._static_img is not None:
            return self._static_img

        img_w = content_w + self._PLATE_PAD * 2
        img_h = content_h + self._PLATE_PAD * 2
        # Keep the menu HUD transparent-only on Windows transparentcolor
        # overlays. A dark translucent plate behind the content produces a
        # visible black fringe around the floating menu and child options.
        layer = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))

        draw = ImageDraw.Draw(layer)
        cx1 = self._PLATE_PAD - self._HUD_MARGIN
        cy1 = self._PLATE_PAD - self._HUD_MARGIN
        cx2 = self._PLATE_PAD + content_w + self._HUD_MARGIN
        cy2 = self._PLATE_PAD + content_h + self._HUD_MARGIN
        self._draw_brackets(draw, cx1, cy1, cx2, cy2)
        self._draw_rails(draw, cx1, cy1, cx2, cy2)
        self._draw_static_labels(draw, cx1, cy1, cx2, cy2, screen_w, screen_h)

        self._static_key = key
        self._static_img = layer
        return layer

    def _draw_dynamic(self, frame: Image.Image,
                      cx1: int, cy1: int, cx2: int, cy2: int,
                      scan_y: int, dot_y_l: int, dot_y_r: int,
                      stamp: str) -> None:
        draw = ImageDraw.Draw(frame)
        draw.line((cx1, scan_y, cx2, scan_y), fill=self._CYAN, width=1)
        for idx, color in enumerate(self._SCAN_TRAIL):
            trail_y = scan_y - 3 - idx * 3
            draw.line((cx1, trail_y, cx2, trail_y), fill=color, width=1)

        rail_x_l = cx1 - self._RAIL_OFFSET
        rail_x_r = cx2 + self._RAIL_OFFSET
        self._alpha_dot(frame, rail_x_l, dot_y_l, self._CYAN)
        self._alpha_dot(frame, rail_x_r, dot_y_r, self._GOLD)

        # v2.2.25: stamp text changes only once per second. Cache it as
        # a tiny sprite and paste it each frame, avoiding the FreeType
        # rasterization + textbbox + ImageDraw.text path on every tick.
        sprite = self._get_stamp_sprite(stamp)
        if sprite is not None:
            sx = cx2 - 4 - self._stamp_sprite_size[0]
            sy = cy2 + 4
            frame.alpha_composite(sprite, dest=(sx, sy))

    def _get_stamp_sprite(self, stamp: str) -> Optional[Image.Image]:
        if not stamp:
            return None
        if (self._stamp_sprite is not None
                and self._stamp_sprite_text == stamp):
            return self._stamp_sprite
        font = self._font('sao', 10)
        # Use a throwaway image to measure first.
        probe = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        bbox = self._text_bbox(ImageDraw.Draw(probe), stamp, font)
        w = max(1, bbox[2] - bbox[0])
        h = max(1, bbox[3] - bbox[1])
        sprite = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sprite).text(
            (-bbox[0], -bbox[1]), stamp, font=font, fill=self._DIM_GOLD)
        self._stamp_sprite = sprite
        self._stamp_sprite_text = stamp
        self._stamp_sprite_size = (w, h)
        return sprite

    def _build_shell(self, img_w: int, img_h: int) -> Image.Image:
        if _gpu_shell is not None:
            shell = _gpu_shell(
                img_w,
                img_h,
                body_pad=self._PLATE_PAD,
                radius=44.0,
                color_a=(10, 16, 24, 180),
                color_b=(14, 20, 30, 140),
                edge=(110, 210, 240, 60),
                inner=(160, 230, 255, 36),
                scan=(0, 0, 0, 0),
                shadow=self._SHELL_SHADOW,
                shadow_dx=4.0,
                shadow_dy=6.0,
                shadow_sigma=7.0,
                shadow_radius=30.0,
            )
            if shell is not None:
                shell.alpha_composite(self._build_gloss(img_w, img_h))
                return shell

        layer = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        shadow = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle(
            (self._PLATE_PAD + 6, self._PLATE_PAD + 8,
             img_w - self._PLATE_PAD + 6, img_h - self._PLATE_PAD + 8),
            radius=34,
            fill=self._SHELL_SHADOW,
        )
        shadow = self._blur(shadow, 7)
        layer.alpha_composite(shadow)

        draw = ImageDraw.Draw(layer)
        outer = (self._PLATE_PAD, self._PLATE_PAD,
                 img_w - self._PLATE_PAD, img_h - self._PLATE_PAD)
        inner = (self._PLATE_PAD + 10, self._PLATE_PAD + 10,
                 img_w - self._PLATE_PAD - 10, img_h - self._PLATE_PAD - 10)
        draw.rounded_rectangle(
            outer,
            radius=34,
            fill=(10, 16, 24, 180),
            outline=(110, 210, 240, 60),
            width=1,
        )
        draw.rounded_rectangle(
            inner,
            radius=28,
            fill=(14, 20, 30, 140),
            outline=(160, 230, 255, 36),
            width=1,
        )
        layer.alpha_composite(self._build_gloss(img_w, img_h))
        return layer

    def _build_gloss(self, img_w: int, img_h: int) -> Image.Image:
        gloss = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(gloss)
        draw.rounded_rectangle(
            (self._PLATE_PAD + 10, self._PLATE_PAD + 8,
             img_w - self._PLATE_PAD - 12,
             int(self._PLATE_PAD + (img_h - self._PLATE_PAD * 2) * 0.40)),
            radius=24,
            fill=(200, 240, 255, 18),
        )
        return self._blur(gloss, 10)

    def _draw_brackets(self, draw: ImageDraw.ImageDraw,
                       cx1: int, cy1: int, cx2: int, cy2: int) -> None:
        spec = (
            (cx1, cy1, self._BRACKET_LEN, 0, 0, self._BRACKET_LEN, self._CYAN),
            (cx2, cy1, -self._BRACKET_LEN, 0, 0, self._BRACKET_LEN, self._GOLD),
            (cx1, cy2, self._BRACKET_LEN, 0, 0, -self._BRACKET_LEN, self._CYAN),
            (cx2, cy2, -self._BRACKET_LEN, 0, 0, -self._BRACKET_LEN, self._GOLD),
        )
        for x, y, dx1, dy1, dx2, dy2, color in spec:
            draw.line((x, y, x + dx1, y + dy1), fill=color, width=1)
            draw.line((x, y, x + dx2, y + dy2), fill=color, width=1)

    def _draw_rails(self, draw: ImageDraw.ImageDraw,
                    cx1: int, cy1: int, cx2: int, cy2: int) -> None:
        rail_x_l = cx1 - self._RAIL_OFFSET
        rail_x_r = cx2 + self._RAIL_OFFSET
        draw.line((rail_x_l, cy1 + self._BRACKET_LEN,
                   rail_x_l, cy2 - self._BRACKET_LEN), fill=self._CYAN, width=1)
        draw.line((rail_x_r, cy1 + self._BRACKET_LEN,
                   rail_x_r, cy2 - self._BRACKET_LEN), fill=self._GOLD, width=1)

    def _draw_static_labels(self, draw: ImageDraw.ImageDraw,
                            cx1: int, cy1: int, cx2: int, cy2: int,
                            screen_w: int, screen_h: int) -> None:
        font = self._font('sao', 10)
        draw.text((cx1 + 4, cy1 - 12), 'SYS:MENU', font=font, fill=self._DIM_CYAN)
        res_text = f'RES:{screen_w}x{screen_h}'
        bbox = self._text_bbox(draw, res_text, font)
        draw.text((cx2 - 4 - (bbox[2] - bbox[0]), cy1 - 12),
                  res_text, font=font, fill=self._DIM_GOLD)
        draw.text((cx1 + 4, cy2 + 2), 'ACTIVE', font=font, fill=self._DIM_CYAN)

    def _alpha_dot(self, frame: Image.Image, cx: int, cy: int,
                   color: Tuple[int, int, int, int]) -> None:
        glow = self._dot_sprite(color, 10)
        gx = int(cx - glow.width / 2)
        gy = int(cy - glow.height / 2)
        frame.alpha_composite(glow, dest=(gx, gy))
        draw = ImageDraw.Draw(frame)
        r = self._DOT_RADIUS
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    def _dot_sprite(self, color: Tuple[int, int, int, int], size: int) -> Image.Image:
        key = (color, size)
        cached = self._dot_cache.get(key)
        if cached is not None:
            return cached
        pad = 6
        sprite = Image.new('RGBA', (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)
        draw.ellipse((pad, pad, pad + size, pad + size),
                 fill=(color[0], color[1], color[2], 56))
        sprite = self._blur(sprite, 3)
        self._dot_cache[key] = sprite
        return sprite

    def _blur(self, img: Image.Image, radius: float) -> Image.Image:
        if _gpu_blur is not None:
            try:
                return _gpu_blur(img, radius)
            except Exception:
                pass
        return img.filter(ImageFilter.GaussianBlur(radius))

    def _to_photo(self, img: Image.Image) -> ImageTk.PhotoImage:
        size = img.size
        if self._photo is not None and self._photo_size == size:
            try:
                self._photo.paste(img)
                return self._photo
            except Exception:
                self._photo = None
                self._photo_size = None
        self._photo = ImageTk.PhotoImage(img)
        self._photo_size = size
        return self._photo

    def _font(self, kind: str, size: int):
        font_path = _FONT_SAO if kind == 'sao' else _FONT_CJK
        key = (font_path, size)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(font_path, size=size)
        except Exception:
            font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    @staticmethod
    def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int, int, int]:
        if hasattr(draw, 'textbbox'):
            return draw.textbbox((0, 0), text, font=font)
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)


class MenuCircleButtonRenderer:
    def __init__(self) -> None:
        self._image_cache: Dict[Tuple[int, str, str, str, str, str], Image.Image] = {}
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

    def render(self, size: int, icon_text: str,
               border_hex: str, fill_hex: str, icon_hex: str,
               bg_hex: str) -> Image.Image:
        # Held under module-level :data:`_PIL_DRAW_LOCK` so the icon's
        # FreeType rasterization (draw.text inside the !cache-miss
        # branch) doesn't race the menu HUD overlay-compose worker also
        # in FreeType. Cache hits skip the lock cost (single attr read).
        with _PIL_DRAW_LOCK:
            return self._render_locked(size, icon_text, border_hex, fill_hex, icon_hex, bg_hex)

    def _render_locked(self, size: int, icon_text: str,
                       border_hex: str, fill_hex: str, icon_hex: str,
                       bg_hex: str) -> Image.Image:
        size = max(1, int(size))
        bg_hex = bg_hex or '#010101'
        key = (size, icon_text, border_hex, fill_hex, icon_hex, bg_hex)
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached

        if size <= 6:
            final = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            self._image_cache[key] = final
            return final

        scale = 4 if size <= 20 else 3
        canvas = size * scale
        image = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        border_rgb = _hex_to_rgb_tuple(border_hex, (201, 198, 198))
        fill_rgb = _hex_to_rgb_tuple(fill_hex, (255, 255, 255))
        icon_rgb = _hex_to_rgb_tuple(icon_hex, (185, 183, 183))
        inset = max(2 * scale, 2)
        ring_w = max(scale + 1, 2)
        # Guard: at very small sizes the inner insets can collapse and PIL's
        # ellipse raises "x1 must be >= x0". Fall back to a simple filled
        # dot so the growth animation never throws.
        if canvas - 2 * inset < 4:
            final = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(final)
            sdraw.ellipse((0, 0, size - 1, size - 1),
                          fill=fill_rgb + (255,),
                          outline=border_rgb + (255,))
            self._image_cache[key] = final
            return final
        draw.ellipse(
            (inset, inset, canvas - inset - 1, canvas - inset - 1),
            outline=border_rgb + (255,),
            width=ring_w,
        )

        inner_inset = inset + max(scale * 2, 2)
        if canvas - 2 * inner_inset < 2:
            # Ring-only at small sizes; skip inner fill + icon.
            resized = image.resize((size, size), Image.LANCZOS)
            alpha = resized.getchannel('A').point(lambda a: 0 if a < 24 else a)
            resized.putalpha(alpha)
            self._image_cache[key] = resized
            return resized
        draw.ellipse(
            (inner_inset, inner_inset,
             canvas - inner_inset - 1, canvas - inner_inset - 1),
            fill=fill_rgb + (255,),
        )

        if not self._draw_builtin_icon(draw, icon_text, canvas, icon_rgb + (255,), scale):
            font_size = max(9, int(size * 0.42 * scale))
            font = self._icon_font(font_size)
            bbox = self._text_bbox(draw, icon_text, font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = int((canvas - text_w) * 0.5)
            text_y = int((canvas - text_h) * 0.5 - scale * 0.35)
            draw.text((text_x, text_y), icon_text, font=font, fill=icon_rgb + (255,))

        resized = image.resize((size, size), Image.LANCZOS)
        # Clamp only the very low-alpha fringe so the icon stays smooth while
        # the transparent corners do not pick up a dark halo on the menu
        # overlay's transparent-color keyed background.
        alpha = resized.getchannel('A').point(lambda a: 0 if a < 24 else a)
        resized.putalpha(alpha)
        final = resized
        self._image_cache[key] = final
        return final

    def _draw_builtin_icon(self, draw: ImageDraw.ImageDraw, icon_text: str,
                           canvas: int, color: Tuple[int, int, int, int],
                           scale: int) -> bool:
        cx = canvas * 0.5
        cy = canvas * 0.5
        stroke = max(scale + 1, 2)
        if icon_text == '⚡':
            pts = [
                (cx - canvas * 0.10, cy - canvas * 0.26),
                (cx + canvas * 0.02, cy - canvas * 0.26),
                (cx - canvas * 0.05, cy - canvas * 0.02),
                (cx + canvas * 0.12, cy - canvas * 0.02),
                (cx - canvas * 0.03, cy + canvas * 0.27),
                (cx + canvas * 0.00, cy + canvas * 0.06),
                (cx - canvas * 0.14, cy + canvas * 0.06),
            ]
            draw.polygon(pts, fill=color)
            return True
        if icon_text == '◆':
            pts = [
                (cx, cy - canvas * 0.18),
                (cx + canvas * 0.18, cy),
                (cx, cy + canvas * 0.18),
                (cx - canvas * 0.18, cy),
            ]
            draw.polygon(pts, fill=color)
            return True
        if icon_text == 'ℹ':
            dot_r = max(scale + 1, 2)
            stem_w = max(scale + 1, 2)
            draw.ellipse(
                (cx - dot_r, cy - canvas * 0.22 - dot_r,
                 cx + dot_r, cy - canvas * 0.22 + dot_r),
                fill=color,
            )
            draw.rounded_rectangle(
                (cx - stem_w * 0.5, cy - canvas * 0.06,
                 cx + stem_w * 0.5, cy + canvas * 0.20),
                radius=stem_w * 0.5,
                fill=color,
            )
            return True
        if icon_text == '⚙':
            ring_r = canvas * 0.15
            outer_r = canvas * 0.24
            tooth_r = max(scale * 1.25, 2.0)
            for idx in range(8):
                ang = (math.pi * 2.0 * idx) / 8.0
                tx = cx + math.cos(ang) * outer_r
                ty = cy + math.sin(ang) * outer_r
                draw.ellipse((tx - tooth_r, ty - tooth_r, tx + tooth_r, ty + tooth_r), fill=color)
            draw.ellipse((cx - outer_r + scale, cy - outer_r + scale,
                          cx + outer_r - scale, cy + outer_r - scale),
                         outline=color, width=stroke)
            draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), fill=color)
            draw.ellipse((cx - ring_r * 0.48, cy - ring_r * 0.48,
                          cx + ring_r * 0.48, cy + ring_r * 0.48),
                         fill=(255, 255, 255, 0))
            return True
        if icon_text == '⚔':
            blade = max(scale + 1, 2)
            draw.line((cx - canvas * 0.18, cy + canvas * 0.16,
                       cx + canvas * 0.18, cy - canvas * 0.16),
                      fill=color, width=blade)
            draw.line((cx - canvas * 0.18, cy - canvas * 0.16,
                       cx + canvas * 0.18, cy + canvas * 0.16),
                      fill=color, width=blade)
            guard = max(scale, 2)
            draw.line((cx - canvas * 0.10, cy + canvas * 0.08,
                       cx - canvas * 0.02, cy + canvas * 0.15),
                      fill=color, width=guard)
            draw.line((cx + canvas * 0.10, cy + canvas * 0.08,
                       cx + canvas * 0.02, cy + canvas * 0.15),
                      fill=color, width=guard)
            draw.line((cx - canvas * 0.10, cy - canvas * 0.08,
                       cx - canvas * 0.02, cy - canvas * 0.15),
                      fill=color, width=guard)
            draw.line((cx + canvas * 0.10, cy - canvas * 0.08,
                       cx + canvas * 0.02, cy - canvas * 0.15),
                      fill=color, width=guard)
            return True
        # Palette / theme icon: ellipse body with thumb hole + 3 dots
        if icon_text == 'P':
            r = canvas * 0.20
            # Main palette body (offset slightly left-up)
            px = cx - canvas * 0.01
            py = cy + canvas * 0.01
            draw.ellipse((px - r, py - r, px + r, py + r), fill=color)
            # Thumb hole
            hr = r * 0.32
            draw.ellipse((px - hr, py + r * 0.25 - hr,
                          px + hr, py + r * 0.25 + hr),
                         fill=(0, 0, 0, 0))
            # Color dots
            dr = max(scale * 1.1, 2)
            draw.ellipse((cx - r * 0.50 - dr, cy - r * 0.55 - dr,
                          cx - r * 0.50 + dr, cy - r * 0.55 + dr),
                         fill=(255, 255, 255, 0))  # negative space
            draw.ellipse((cx - r * 0.50 - dr, cy - r * 0.55 - dr,
                          cx - r * 0.50 + dr, cy - r * 0.55 + dr),
                         outline=color, width=max(scale, 1))
            draw.ellipse((cx + r * 0.20 - dr, cy - r * 0.65 - dr,
                          cx + r * 0.20 + dr, cy - r * 0.65 + dr),
                         outline=color, width=max(scale, 1))
            draw.ellipse((cx + r * 0.45 - dr, cy + r * 0.10 - dr,
                          cx + r * 0.45 + dr, cy + r * 0.10 + dr),
                         outline=color, width=max(scale, 1))
            return True
        # Plugin / module icon: a filled hexagon (nut/module) with a hollow
        # center, distinct from the ◆ diamond. SAOUI.ttf lacks ⬢ (U+2B22) so it
        # MUST be drawn here — the circle-button font path has no glyph fallback.
        if icon_text == '⬢':
            r = canvas * 0.22
            pts = []
            for idx in range(6):
                ang = math.pi / 6.0 + idx * (math.pi / 3.0)  # flat-top hexagon
                pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
            draw.polygon(pts, fill=color)
            hr = r * 0.40
            draw.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), fill=(255, 255, 255, 0))
            return True
        return False

    def _icon_font(self, size: int):
        for font_path in (_FONT_SAO, 'seguisym.ttf', 'segoeui.ttf', 'arial.ttf'):
            key = (font_path, size)
            cached = self._font_cache.get(key)
            if cached is not None:
                return cached
            try:
                font = ImageFont.truetype(font_path, size=size)
                self._font_cache[key] = font
                return font
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int, int, int]:
        if hasattr(draw, 'textbbox'):
            return draw.textbbox((0, 0), text, font=font)
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)


class MenuLeftInfoRenderer:
    _TOP_BG = (251, 251, 251, 255)
    _BOTTOM_BG = (236, 235, 234, 255)
    _TEXT_MAIN = (100, 99, 100, 255)
    _TEXT_SUB = (140, 135, 138, 255)

    def __init__(self) -> None:
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._top_photo: Optional[ImageTk.PhotoImage] = None
        self._top_size: Optional[Tuple[int, int]] = None
        self._bottom_photo: Optional[ImageTk.PhotoImage] = None
        self._bottom_size: Optional[Tuple[int, int]] = None
        # v2.2.26: static plate cache (no sweep). Open/close + sync_pulse
        # animations vary the panel size every frame; without caching the
        # body, every frame re-runs ImageDraw.rectangle/lines/text/triangle
        # plus a fresh PIL alloc. Now we keep one body per (username,w,h)
        # and a separate sig-keyed scratch for sweep composites so steady
        # frames return the cached PhotoImage immediately.
        self._top_body_cache: Dict[Tuple[str, int, int], Image.Image] = {}
        self._bottom_body_cache: Dict[Tuple[str, int, int], Image.Image] = {}
        self._top_sig: Optional[Tuple] = None
        self._bottom_sig: Optional[Tuple] = None
        self._top_pil_sig: Optional[Tuple] = None
        self._bottom_pil_sig: Optional[Tuple] = None
        self._top_pil_frame: Optional[Image.Image] = None
        self._bottom_pil_frame: Optional[Image.Image] = None

    def reset(self) -> None:
        self._top_photo = None
        self._top_size = None
        self._bottom_photo = None
        self._bottom_size = None
        self._top_body_cache.clear()
        self._bottom_body_cache.clear()
        self._top_sig = None
        self._bottom_sig = None
        self._top_pil_sig = None
        self._bottom_pil_sig = None
        self._top_pil_frame = None
        self._bottom_pil_frame = None

    @_probe.decorate('ui.menu.plate_top')
    def render_top(self, username: str, width: int, height: int,
                   sweep_phase: float = 0.0, sweep_strength: float = 0.0) -> ImageTk.PhotoImage:
        with _PIL_DRAW_LOCK:
            return self._render_top_locked(username, width, height,
                                            sweep_phase, sweep_strength)

    def _render_top_locked(self, username: str, width: int, height: int,
                           sweep_phase: float, sweep_strength: float) -> ImageTk.PhotoImage:
        width = max(1, int(width))
        height = max(1, int(height))
        # v2.2.26: quantize sweep params so steady frames + several frames
        # near the apex of the sin pulse hit the cache. Without this, even
        # static (sweep_strength=0) ticks rebuilt the entire plate.
        sp_q, ss_q = _CY_UI.menu_plate_sweep_quantized(
            sweep_phase, sweep_strength, 1.0)
        sig = (username, width, height, sp_q, ss_q)
        if sig == self._top_sig and self._top_photo is not None:
            return self._top_photo

        image = self._compose_top_image(username, width, height, sp_q, ss_q)
        self._top_sig = sig
        return self._to_photo(image, slot='top')

    def render_top_pil(self, username: str, width: int, height: int,
                       sweep_phase: float = 0.0,
                       sweep_strength: float = 0.0) -> Image.Image:
        """Worker-safe variant of :meth:`render_top` returning a raw
        PIL Image. Does not touch Tk — safe to call from any thread.
        Bypasses the Tk PhotoImage cache; the GPU path keeps its own
        signature dedup."""
        with _PIL_DRAW_LOCK:
            return self._render_top_pil_locked(username, width, height,
                                                sweep_phase, sweep_strength)

    def _render_top_pil_locked(self, username: str, width: int, height: int,
                               sweep_phase: float, sweep_strength: float) -> Image.Image:
        width = max(1, int(width))
        height = max(1, int(height))
        sp_q, ss_q = _CY_UI.menu_plate_sweep_quantized(
            sweep_phase, sweep_strength, 1.0)
        sig = (username, width, height, sp_q, ss_q)
        if sig == self._top_pil_sig and self._top_pil_frame is not None:
            return self._top_pil_frame
        image = self._compose_top_image(username, width, height, sp_q, ss_q)
        self._top_pil_sig = sig
        self._top_pil_frame = image
        return image

    def _compose_top_image(self, username: str, width: int, height: int,
                           sp_q: float, ss_q: float) -> Image.Image:
        body = self._get_top_body(username, width, height)
        if ss_q <= 0.005:
            return body
        image = body.copy()
        self._apply_sweep(
            image, width, height,
            sweep_phase=sp_q,
            sweep_strength=ss_q,
            tint=(220, 246, 255),
            alpha_scale=48,
            blur_radius=max(5, width * 0.030),
            slant=0.34,
        )
        return image

    def _get_top_body(self, username: str, width: int, height: int) -> Image.Image:
        key = (username, width, height)
        cached = self._top_body_cache.get(key)
        if cached is not None:
            return cached
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        if width >= 20 and height >= 20:
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, width - 1, height - 1), fill=self._TOP_BG)
            for idx in range(6):
                shade = int(20 * (1.0 - idx / 6.0))
                y = max(0, height - 1 - idx)
                draw.line((3, y, max(3, width - 4), y), fill=(shade, shade, shade, 255), width=1)

            mid_y = int(height * 0.77)
            tri_w = min(16, max(7, width // 12))
            tri_h = min(16, max(7, height // 10))
            draw.polygon(
                ((width - 1, mid_y),
                 (max(0, width - tri_w), min(height - 1, mid_y + tri_h // 2)),
                 (width - 1, min(height - 1, mid_y + tri_h))),
                fill=self._TOP_BG,
            )

            font = self._font(_FONT_CJK, 13)
            bbox = self._text_bbox(draw, username, font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = max(8, int((width - text_w) * 0.5))
            text_y = max(6, int(30 - text_h * 0.5))
            draw.text((text_x, text_y), username, font=font, fill=self._TEXT_MAIN)

            if height > 50:
                for idx in range(3):
                    level = int(170 + idx * 25)
                    y = 49 + idx
                    draw.line(
                        (10 + idx * 2, y, max(10 + idx * 2, width - 10 - idx * 2), y),
                        fill=(level, level, level, 255),
                        width=1,
                    )
        # Cap cache: open/sync animations sweep through ~16 distinct sizes;
        # bound at 64 to defend against unexpected size storms.
        if len(self._top_body_cache) > 64:
            self._top_body_cache.clear()
        self._top_body_cache[key] = image
        return image

    @_probe.decorate('ui.menu.plate_bottom')
    def render_bottom(self, description: str, width: int, height: int,
                      sweep_phase: float = 0.0, sweep_strength: float = 0.0) -> ImageTk.PhotoImage:
        with _PIL_DRAW_LOCK:
            return self._render_bottom_locked(description, width, height,
                                               sweep_phase, sweep_strength)

    def _render_bottom_locked(self, description: str, width: int, height: int,
                              sweep_phase: float, sweep_strength: float) -> ImageTk.PhotoImage:
        width = max(1, int(width))
        height = max(1, int(height))
        sp_q, ss_q = _CY_UI.menu_plate_sweep_quantized(
            sweep_phase, sweep_strength, 0.82)
        sig = (description, width, height, sp_q, ss_q)
        if sig == self._bottom_sig and self._bottom_photo is not None:
            return self._bottom_photo

        image = self._compose_bottom_image(description, width, height, sp_q, ss_q)
        self._bottom_sig = sig
        return self._to_photo(image, slot='bottom')

    def render_bottom_pil(self, description: str, width: int, height: int,
                          sweep_phase: float = 0.0,
                          sweep_strength: float = 0.0) -> Image.Image:
        """Worker-safe variant of :meth:`render_bottom`. See
        :meth:`render_top_pil`."""
        with _PIL_DRAW_LOCK:
            return self._render_bottom_pil_locked(description, width, height,
                                                   sweep_phase, sweep_strength)

    def _render_bottom_pil_locked(self, description: str, width: int, height: int,
                                  sweep_phase: float, sweep_strength: float) -> Image.Image:
        width = max(1, int(width))
        height = max(1, int(height))
        sp_q, ss_q = _CY_UI.menu_plate_sweep_quantized(
            sweep_phase, sweep_strength, 0.82)
        sig = (description, width, height, sp_q, ss_q)
        if sig == self._bottom_pil_sig and self._bottom_pil_frame is not None:
            return self._bottom_pil_frame
        image = self._compose_bottom_image(description, width, height, sp_q, ss_q)
        self._bottom_pil_sig = sig
        self._bottom_pil_frame = image
        return image

    def _compose_bottom_image(self, description: str, width: int, height: int,
                              sp_q: float, ss_q: float) -> Image.Image:
        body = self._get_bottom_body(description, width, height)
        if ss_q <= 0.005:
            return body
        image = body.copy()
        self._apply_sweep(
            image, width, height,
            sweep_phase=sp_q,
            sweep_strength=ss_q,
            tint=(255, 236, 196),
            alpha_scale=32,
            blur_radius=max(4, width * 0.024),
            slant=0.26,
        )
        return image

    def _get_bottom_body(self, description: str, width: int, height: int) -> Image.Image:
        key = (description, width, height)
        cached = self._bottom_body_cache.get(key)
        if cached is not None:
            return cached
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        if width >= 20 and height >= 15:
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, width - 1, height - 1), fill=self._BOTTOM_BG)

            tri_left = min(max(10, width // 8), max(10, width - 20))
            tri_w = min(15, max(9, width // 16))
            tri_h = min(8, max(5, height // 10))
            draw.polygon(
                ((tri_left, 0),
                 (tri_left + tri_w // 2, min(height - 1, tri_h)),
                 (tri_left + tri_w, 0)),
                fill=self._BOTTOM_BG,
            )

            font = self._font(_FONT_CJK, 9)
            lines = self._wrap_text(draw, description or '', font, max(8, width - 20))
            draw.multiline_text((10, 15), '\n'.join(lines), font=font,
                                fill=self._TEXT_SUB, spacing=2)
        if len(self._bottom_body_cache) > 64:
            self._bottom_body_cache.clear()
        self._bottom_body_cache[key] = image
        return image

    def _apply_sweep(self, image: Image.Image, width: int, height: int,
                     sweep_phase: float, sweep_strength: float,
                     tint: Tuple[int, int, int], alpha_scale: int,
                     blur_radius: float, slant: float) -> None:
        sweep_strength = max(0.0, min(1.0, float(sweep_strength)))
        if sweep_strength <= 0.004 or width < 18 or height < 12:
            return
        sweep_phase = max(0.0, min(1.0, float(sweep_phase)))
        center = int((-0.24 + 1.30 * sweep_phase) * width)
        half_w = max(14, int(width * 0.16))
        skew = int(max(4, height * slant))
        alpha = max(6, int(alpha_scale * sweep_strength))
        # D2: cython polygon raster + 3-pass box blur replaces
        # Image.new + ImageDraw.polygon + ImageFilter.GaussianBlur. Returns
        # straight-alpha RGBA bytes — alpha_composite path unchanged.
        if _CY_SKILLFX is not None:
            sweep_bytes = _CY_SKILLFX.sweep_overlay_rgba_bytes(
                width, height,
                center - half_w,
                center + int(half_w * 0.28),
                center + half_w + skew,
                center - int(half_w * 0.55) + skew,
                alpha, int(tint[0]), int(tint[1]), int(tint[2]),
                float(blur_radius),
            )
            overlay = Image.frombytes('RGBA', (width, height), sweep_bytes)
            image.alpha_composite(overlay)
            return
        # Fallback: legacy PIL path.
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.polygon(
            (
                (center - half_w, 0),
                (center + int(half_w * 0.28), 0),
                (center + half_w + skew, height),
                (center - int(half_w * 0.55) + skew, height),
            ),
            fill=(tint[0], tint[1], tint[2], alpha),
        )
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        image.alpha_composite(overlay)

    def _to_photo(self, image: Image.Image, slot: str) -> ImageTk.PhotoImage:
        size = image.size
        if slot == 'top':
            if self._top_photo is not None and self._top_size == size:
                try:
                    self._top_photo.paste(image)
                    return self._top_photo
                except Exception:
                    self._top_photo = None
                    self._top_size = None
            self._top_photo = ImageTk.PhotoImage(image)
            self._top_size = size
            return self._top_photo

        if self._bottom_photo is not None and self._bottom_size == size:
            try:
                self._bottom_photo.paste(image)
                return self._bottom_photo
            except Exception:
                self._bottom_photo = None
                self._bottom_size = None
        self._bottom_photo = ImageTk.PhotoImage(image)
        self._bottom_size = size
        return self._bottom_photo

    def _font(self, font_path: str, size: int):
        key = (font_path, size)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(font_path, size=size)
        except Exception:
            font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    def _wrap_text(self, draw: ImageDraw.ImageDraw, text: str,
                   font, max_width: int) -> list[str]:
        if not text:
            return ['']
        lines: list[str] = []
        for paragraph in text.splitlines() or ['']:
            current = ''
            for ch in paragraph:
                candidate = current + ch
                bbox = self._text_bbox(draw, candidate, font)
                if current and (bbox[2] - bbox[0]) > max_width:
                    lines.append(current)
                    current = ch
                else:
                    current = candidate
            lines.append(current)
        return lines or ['']

    @staticmethod
    def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int, int, int]:
        if hasattr(draw, 'textbbox'):
            return draw.textbbox((0, 0), text, font=font)
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)


# ══════════════════════════════════════════════════════════════════════
#  PlayerPanelRenderer — PIL paint mirroring sao_gui.SAOPlayerPanel
# ══════════════════════════════════════════════════════════════════════
class PlayerPanelRenderer:
    """PIL renderer for ``sao_gui.SAOPlayerPanel`` used by the GPU
    painter ``sao_player_panel_gpu.PlayerPanelGpuPainter``.

    Mirrors the Tk Canvas paint code in ``SAOPlayerPanel._redraw_top``
    and ``_redraw_bottom`` so the GPU compose looks identical to the
    legacy CPU path. Thread-safe; never touches Tk.
    """

    _GOLD = (243, 175, 18, 255)
    _GOLD_HI = (245, 198, 68, 255)
    _CYAN = (134, 223, 255, 255)
    _DIM = (200, 200, 200, 255)
    _LABEL = (170, 170, 170, 255)
    _TITLE_FG = (100, 99, 100, 255)
    _TOP_BG = (255, 255, 255, 255)
    _BOTTOM_BG = (229, 227, 227, 255)
    _SEP = (170, 170, 170, 255)
    _XP_TRACK = (232, 232, 232, 255)
    _XP_BORDER = (216, 216, 216, 255)
    _SCAN_GRAY = (232, 232, 232, 255)
    _VAL_GRAY = (119, 119, 119, 255)
    _VAL_GRAY_LIGHT = (153, 153, 153, 255)
    _STATUS_GRAY = (176, 176, 176, 255)
    _SYS_GRAY = (200, 200, 200, 255)

    def __init__(self) -> None:
        self._font_cache: Dict[Tuple[str, int, bool], ImageFont.FreeTypeFont] = {}
        self._top_body_cache: Dict[Tuple, Image.Image] = {}
        self._bottom_body_cache: Dict[Tuple, Image.Image] = {}
        self._top_sig: Optional[Tuple] = None
        self._top_frame_cache: Optional[Image.Image] = None

    def reset(self) -> None:
        self._top_body_cache.clear()
        self._bottom_body_cache.clear()
        self._top_sig = None
        self._top_frame_cache = None

    # ── top plate ────────────────────────────────────────────────
    @_probe.decorate('ui.menu.player_panel_top')
    def render_top_pil(self, username: str, level: int, level_extra: int,
                       season_exp: int,
                       hp: Tuple[int, int], sta: Tuple[int, int],
                       width: int, height: int,
                       scan_phase: float = 0.0) -> Image.Image:
        with _PIL_DRAW_LOCK:
            return self._render_top_locked(
                username, level, level_extra, season_exp,
                hp, sta, width, height, scan_phase,
            )

    def _render_top_locked(self, username, level, level_extra, season_exp,
                           hp, sta, width, height, scan_phase):
        width = max(1, int(width))
        height = max(1, int(height))
        body = self._get_top_body(
            username, int(level), int(level_extra), int(season_exp),
            (int(hp[0]), int(hp[1])), (int(sta[0]), int(sta[1])),
            width, height,
        )
        if height <= 185:
            return body
        scan_q = round(max(0.0, min(1.0, float(scan_phase))) * 32.0) / 32.0
        sig = (
            username, int(level), int(level_extra), int(season_exp),
            (int(hp[0]), int(hp[1])), (int(sta[0]), int(sta[1])),
            width, height, scan_q,
        )
        if sig == self._top_sig and self._top_frame_cache is not None:
            return self._top_frame_cache
        # Animated bottom scan dot overlaid on cached body.
        image = body.copy()
        draw = ImageDraw.Draw(image)
        scan_y = height - 16
        scan_x = 10 + int((width - 20) * scan_q)
        draw.rectangle((scan_x - 12, scan_y - 1, scan_x + 12, scan_y + 1),
                       fill=self._CYAN)
        self._top_sig = sig
        self._top_frame_cache = image
        return image

    def _get_top_body(self, username, level, level_extra, season_exp,
                      hp, sta, width, height):
        key = (username, level, level_extra, season_exp, hp, sta, width, height)
        cached = self._top_body_cache.get(key)
        if cached is not None:
            return cached
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        if width >= 40 and height >= 40:
            self._compose_top(image, username, level, level_extra,
                              season_exp, hp, sta, width, height)
        if len(self._top_body_cache) > 96:
            self._top_body_cache.clear()
        self._top_body_cache[key] = image
        return image

    def _compose_top(self, image, username, level, level_extra,
                     season_exp, hp, sta, w, h):
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, w - 1, h - 1), fill=self._TOP_BG)

        # HUD brackets (4 corners)
        bk = 14
        draw.line((2, 2, 2 + bk, 2), fill=self._CYAN, width=1)
        draw.line((2, 2, 2, 2 + bk), fill=self._CYAN, width=1)
        draw.line((w - 2 - bk, 2, w - 2, 2), fill=self._GOLD, width=1)
        draw.line((w - 2, 2, w - 2, 2 + bk), fill=self._GOLD, width=1)
        draw.line((2, h - 2, 2 + bk, h - 2), fill=self._CYAN, width=1)
        draw.line((2, h - 2 - bk, 2, h - 2), fill=self._CYAN, width=1)
        draw.line((w - 2 - bk, h - 2, w - 2, h - 2), fill=self._GOLD, width=1)
        draw.line((w - 2, h - 2 - bk, w - 2, h - 2), fill=self._GOLD, width=1)

        # SYS:PLAYER (Tk anchor='e' at (w-8, 12))
        font_tiny = self._font(_FONT_SAO, 6)
        bbox = self._text_bbox(draw, 'SYS:PLAYER', font_tiny)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        draw.text((w - 8 - tw, 12 - th // 2), 'SYS:PLAYER',
                  font=font_tiny, fill=self._DIM)

        # Username (Tk anchor='center' at (w/2, 26))
        title_y = 26
        display_name = username or ''
        if len(display_name) > 18:
            display_name = display_name[:16] + '…'
        font_name = self._font(_FONT_CJK, 13, bold=True)
        bbox = self._text_bbox(draw, display_name, font_name)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, title_y - th // 2), display_name,
                  font=font_name, fill=self._TITLE_FG)

        # Separator + scan dots
        sep_y = 44
        draw.line((10, sep_y, w - 10, sep_y), fill=self._SEP, width=2)
        for i in range(5):
            dot_x = 14 + i * 8
            draw.rectangle((dot_x, sep_y - 1, dot_x + 3, sep_y),
                           fill=self._CYAN)

        if h < 60:
            return

        # LEVEL label (Tk anchor='w' at (20, 62))
        font_label = self._font(_FONT_SAO, 7)
        bbox = self._text_bbox(draw, 'LEVEL', font_label)
        th = bbox[3] - bbox[1]
        draw.text((20, 62 - th // 2), 'LEVEL', font=font_label, fill=self._LABEL)

        # Level value (Tk anchor='center' at (w/2, 84))
        level_text = f'Lv. {level}'
        level_font_size = 20
        if level_extra > 0:
            level_text = f'Lv. {level}(+{level_extra})'
            level_font_size = 16 if level_extra < 100 else 14
        font_lvl = self._font(_FONT_SAO, level_font_size, bold=True)
        bbox = self._text_bbox(draw, level_text, font_lvl)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, 84 - th // 2), level_text,
                  font=font_lvl, fill=self._GOLD)

        if h < 120:
            return

        # EXP label (Tk anchor='w' at (20, 108))
        bbox = self._text_bbox(draw, 'EXP', font_label)
        th = bbox[3] - bbox[1]
        draw.text((20, 108 - th // 2), 'EXP', font=font_label, fill=self._LABEL)

        # EXP value (Tk anchor='e' at (w-20, 108))
        exp_text = f'{season_exp:,}' if season_exp > 0 else '—'
        font_exp = self._font(_FONT_SAO, 8)
        bbox = self._text_bbox(draw, exp_text, font_exp)
        tw_e = bbox[2] - bbox[0]; th_e = bbox[3] - bbox[1]
        draw.text((w - 20 - tw_e, 108 - th_e // 2), exp_text,
                  font=font_exp, fill=self._VAL_GRAY_LIGHT)

        # EXP bar
        if h > 124:
            xp_y = 122; xp_x = 20; xp_w = w - 40; xp_h = 6
            draw.rectangle((xp_x, xp_y, xp_x + xp_w, xp_y + xp_h),
                           fill=self._XP_TRACK, outline=self._XP_BORDER)
            if season_exp > 0:
                draw.rectangle((xp_x + 1, xp_y + 1,
                                xp_x + 10, xp_y + xp_h - 1),
                               fill=self._GOLD)
                draw.rectangle((xp_x + 1, xp_y + 1,
                                xp_x + 10, xp_y + 3),
                               fill=self._GOLD_HI)

        # HP row
        if h > 150:
            info_y = 140
            font_lab_b = self._font(_FONT_SAO, 7, bold=True)
            font_val = self._font(_FONT_SAO, 8)
            hp_c, hp_m = hp
            bbox = self._text_bbox(draw, 'HP', font_lab_b)
            th = bbox[3] - bbox[1]
            draw.text((20, info_y - th // 2), 'HP',
                      font=font_lab_b, fill=self._CYAN)
            hp_text = f'{hp_c}/{hp_m}' if hp_m > 0 else '—'
            bbox = self._text_bbox(draw, hp_text, font_val)
            tw_h = bbox[2] - bbox[0]; th_h = bbox[3] - bbox[1]
            draw.text((w - 20 - tw_h, info_y - th_h // 2), hp_text,
                      font=font_val, fill=self._VAL_GRAY)

        # STA row
        if h > 170:
            info_y2 = 158
            font_lab_b = self._font(_FONT_SAO, 7, bold=True)
            font_val = self._font(_FONT_SAO, 8)
            sta_c, sta_m = sta
            bbox = self._text_bbox(draw, 'STA', font_lab_b)
            th = bbox[3] - bbox[1]
            draw.text((20, info_y2 - th // 2), 'STA',
                      font=font_lab_b, fill=self._GOLD)
            sta_text = f'{sta_c}/{sta_m}' if sta_m > 0 else '—'
            bbox = self._text_bbox(draw, sta_text, font_val)
            tw_s = bbox[2] - bbox[0]; th_s = bbox[3] - bbox[1]
            draw.text((w - 20 - tw_s, info_y2 - th_s // 2), sta_text,
                      font=font_val, fill=self._VAL_GRAY)

        # Bottom scan rail (static; the moving cyan dot is overlaid in
        # _render_top_locked because it depends on time)
        if h > 185:
            scan_y = h - 16
            draw.line((10, scan_y, w - 10, scan_y),
                      fill=self._SCAN_GRAY, width=1)

    # ── bottom plate ─────────────────────────────────────────────
    @_probe.decorate('ui.menu.player_panel_bottom')
    def render_bottom_pil(self, shift_mode: str,
                          width: int, height: int) -> Image.Image:
        with _PIL_DRAW_LOCK:
            return self._render_bottom_locked(shift_mode, width, height)

    def _render_bottom_locked(self, shift_mode, width, height):
        width = max(1, int(width)); height = max(1, int(height))
        key = (shift_mode or '', width, height)
        cached = self._bottom_body_cache.get(key)
        if cached is not None:
            return cached
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        if width >= 40 and height >= 15:
            self._compose_bottom(image, shift_mode or '', width, height)
        if len(self._bottom_body_cache) > 32:
            self._bottom_body_cache.clear()
        self._bottom_body_cache[key] = image
        return image

    def _compose_bottom(self, image, shift_mode, w, h):
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, w - 1, h - 1), fill=self._BOTTOM_BG)

        # top gradient lines
        for i in range(3):
            av = int(220 + i * 8)
            draw.line((0, i, w, i), fill=(av, av, av, 255), width=1)

        # corner brackets
        draw.line((3, 3, 12, 3), fill=self._CYAN, width=1)
        draw.line((3, 3, 3, 12), fill=self._CYAN, width=1)
        draw.line((w - 12, h - 3, w - 3, h - 3), fill=self._GOLD, width=1)
        draw.line((w - 3, h - 12, w - 3, h - 3), fill=self._GOLD, width=1)

        # STATUS label (Tk anchor='w' at (12, 12))
        font_tiny = self._font(_FONT_SAO, 6)
        bbox = self._text_bbox(draw, 'STATUS', font_tiny)
        th = bbox[3] - bbox[1]
        draw.text((12, 12 - th // 2), 'STATUS',
                  font=font_tiny, fill=self._STATUS_GRAY)

        # shift_mode (Tk anchor='w' at (15, h//2 - 2))
        sm = shift_mode if shift_mode else '普通模式'
        if sm == '普通模式':
            sm_color = (33, 150, 243, 255)
        elif 'CTRL' in sm:
            sm_color = (230, 81, 0, 255)
        else:
            sm_color = (21, 101, 192, 255)
        font_sm = self._font(_FONT_CJK, 9, bold=True)
        bbox = self._text_bbox(draw, sm, font_sm)
        th = bbox[3] - bbox[1]
        draw.text((15, h // 2 - 2 - th // 2), sm,
                  font=font_sm, fill=sm_color)

        # SAO://SYSTEM (Tk anchor='e' at (w-8, h-10))
        if h > 50:
            font_sys = self._font(_FONT_SAO, 5)
            bbox = self._text_bbox(draw, 'SAO://SYSTEM', font_sys)
            tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
            draw.text((w - 8 - tw, h - 10 - th // 2), 'SAO://SYSTEM',
                      font=font_sys, fill=self._SYS_GRAY)

    # ── helpers ──────────────────────────────────────────────────
    def _font(self, font_path: str, size: int, bold: bool = False):
        # ZhuZiAYuanJWD/SAOUI ship single-weight TTFs; the bold flag is
        # accepted for caller symmetry but resolves to the same file.
        key = (font_path, size, bool(bold))
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(font_path, size=size)
        except Exception:
            font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    @staticmethod
    def _text_bbox(draw, text, font):
        if hasattr(draw, 'textbbox'):
            return draw.textbbox((0, 0), text, font=font)
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)
