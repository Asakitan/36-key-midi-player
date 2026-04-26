"""Lightweight render helpers for the 28midi SAO entity menu."""
from __future__ import annotations

import datetime as _dt
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk


_PIL_DRAW_LOCK = threading.RLock()
_KEY_RGBA = (1, 1, 1, 255)


def _hex_to_rgba(color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    raw = (color or '').strip().lstrip('#')
    if len(raw) == 8:
        raw = raw[:6]
    if len(raw) == 3:
        raw = ''.join(ch * 2 for ch in raw)
    try:
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)
    except Exception:
        return (255, 255, 255, alpha)


def _font(size: int, text: str = '') -> ImageFont.ImageFont:
    win_fonts = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    candidates = [
        os.path.join(win_fonts, 'seguisym.ttf'),
        os.path.join(win_fonts, 'seguiemj.ttf'),
        os.path.join(win_fonts, 'msyh.ttc'),
        os.path.join(win_fonts, 'simhei.ttf'),
        os.path.join(win_fonts, 'simsun.ttc'),
        os.path.join(win_fonts, 'arial.ttf'),
        'assets/fonts/ZhuZiAYuanJWD.ttf',
        'web/fonts/ZhuZiAYuanJWD.ttf',
        'assets/fonts/SAOUI.ttf',
        'web/fonts/SAOUI.ttf',
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, max(8, int(size)))
        except Exception:
            pass
    return ImageFont.load_default()


def _keyed_image(img: Image.Image) -> Image.Image:
    """Composite RGBA artwork onto the popup chroma-key background.

    Tk's PhotoImage alpha can expose rectangular bounds inside a
    transparent-color Toplevel on some Windows/Tk builds. Feeding Tk an
    opaque image whose empty pixels are the exact transparent key keeps the
    window shape stable and leaves Windows to cut the key color out.
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    out = Image.new('RGBA', img.size, _KEY_RGBA)
    out.alpha_composite(img)
    if img.getchannel('A').getextrema()[0] == 0:
        alpha = img.getchannel('A')
        key_mask = alpha.point(lambda a: 255 if a < 12 else 0)
        key_layer = Image.new('RGBA', img.size, _KEY_RGBA)
        out.paste(key_layer, mask=key_mask)
    return out


class MenuCircleButtonRenderer:
    def __init__(self) -> None:
        self._cache: Dict[Tuple, Image.Image] = {}

    def render(self, size: int, icon_text: str, border_color: str,
               inner_fill: str, icon_color: str, bg_key: str) -> Image.Image:
        size = max(1, min(96, int(size)))
        key = (size, icon_text, border_color, inner_fill, icon_color, bg_key)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if len(self._cache) > 180:
            self._cache.clear()
        if size < 8:
            out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            self._cache[key] = out
            return out
        base_size = 70
        if size != base_size:
            base = self.render(base_size, icon_text, border_color, inner_fill, icon_color, bg_key)
            out = base.resize((size, size), Image.LANCZOS)
            out.putalpha(Image.eval(out.getchannel('A'), lambda a: 0 if a < 10 else a))
            self._cache[key] = out
            return out
        with _PIL_DRAW_LOCK:
            scale = 4
            ss = size * scale
            img = Image.new('RGBA', (ss, ss), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            outer_pad = max(1, int(round(size * 0.06))) * scale
            inner_pad = max(2, int(round(size * 0.13))) * scale
            draw.ellipse(
                (outer_pad, outer_pad, ss - outer_pad, ss - outer_pad),
                outline=_hex_to_rgba(border_color),
                width=max(1, 2 * scale),
            )
            draw.ellipse(
                (inner_pad, inner_pad, ss - inner_pad, ss - inner_pad),
                fill=_hex_to_rgba(inner_fill),
            )
            small = img.resize((size, size), Image.LANCZOS)
            out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            out.alpha_composite(small)
            out.putalpha(Image.eval(out.getchannel('A'), lambda a: 0 if a < 10 else a))

            d = ImageDraw.Draw(out)
            text = icon_text or '*'
            font = _font(max(12, int(size * 0.32)), text)
            try:
                box = d.textbbox((0, 0), text, font=font)
                tw, th = box[2] - box[0], box[3] - box[1]
                tx = (size - tw) / 2 - box[0]
                ty = (size - th) / 2 - box[1] - 1
                d.text((tx, ty), text, font=font, fill=_hex_to_rgba(icon_color))
            except Exception:
                pass
        self._cache[key] = out
        return out


@dataclass
class MenuHudFrame:
    static_photo: ImageTk.PhotoImage
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


class MenuHudSpriteRenderer:
    _PAD = 20
    _MARGIN = 12
    _BRACKET = 20

    def __init__(self) -> None:
        self._static_key = None
        self._static_photo = None
        self._dot_cache: Dict[str, ImageTk.PhotoImage] = {}

    def reset(self) -> None:
        self._static_key = None
        self._static_photo = None
        self._dot_cache.clear()

    def sprite_origin(self, left: int, top: int) -> Tuple[int, int]:
        return int(left - self._PAD - self._MARGIN), int(top - self._PAD - self._MARGIN)

    def _dot_photo(self, color: str) -> ImageTk.PhotoImage:
        photo = self._dot_cache.get(color)
        if photo is not None:
            return photo
        img = Image.new('RGBA', (18, 18), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        rgba = _hex_to_rgba(color, 170)
        for r, a in ((8, 28), (6, 52), (3, 210)):
            c = (rgba[0], rgba[1], rgba[2], a)
            d.ellipse((9 - r, 9 - r, 9 + r, 9 + r), fill=c)
        photo = ImageTk.PhotoImage(_keyed_image(img))
        self._dot_cache[color] = photo
        return photo

    def render(self, content_w: int, content_h: int,
               screen_w: int, screen_h: int, phase: float) -> MenuHudFrame:
        content_w = max(120, int(content_w))
        content_h = max(120, int(content_h))
        key = (content_w, content_h, screen_w, screen_h)
        cx1 = self._PAD + self._MARGIN
        cy1 = self._PAD + self._MARGIN
        cx2 = cx1 + content_w + self._MARGIN * 2
        cy2 = cy1 + content_h + self._MARGIN * 2
        w = cx2 + self._PAD
        h = cy2 + self._PAD

        if key != self._static_key or self._static_photo is None:
            with _PIL_DRAW_LOCK:
                img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                cyan = _hex_to_rgba('#5eb8ca')
                gold = _hex_to_rgba('#f3af12')
                dim_cyan = _hex_to_rgba('#5eb8ca', 180)
                dim_gold = _hex_to_rgba('#c8910e', 180)
                for x, y, dx1, dy1, dx2, dy2, col in (
                    (cx1, cy1, self._BRACKET, 0, 0, self._BRACKET, cyan),
                    (cx2, cy1, -self._BRACKET, 0, 0, self._BRACKET, gold),
                    (cx1, cy2, self._BRACKET, 0, 0, -self._BRACKET, cyan),
                    (cx2, cy2, -self._BRACKET, 0, 0, -self._BRACKET, gold),
                ):
                    d.line((x, y, x + dx1, y + dy1), fill=col, width=1)
                    d.line((x, y, x + dx2, y + dy2), fill=col, width=1)
                rail_l = cx1 - 8
                rail_r = cx2 + 8
                d.line((rail_l, cy1 + self._BRACKET, rail_l, cy2 - self._BRACKET), fill=cyan, width=1)
                d.line((rail_r, cy1 + self._BRACKET, rail_r, cy2 - self._BRACKET), fill=gold, width=1)
                f = _font(9)
                d.text((cx1 + 4, cy1 - 14), 'SYS:MENU', fill=dim_cyan, font=f)
                res = f'RES:{int(screen_w)}x{int(screen_h)}'
                try:
                    rb = d.textbbox((0, 0), res, font=f)
                    d.text((cx2 - (rb[2] - rb[0]) - 4, cy1 - 14), res, fill=dim_gold, font=f)
                    d.text((cx1 + 4, cy2 + 4), 'ACTIVE', fill=dim_cyan, font=f)
                except Exception:
                    pass
                self._static_photo = ImageTk.PhotoImage(_keyed_image(img))
                self._static_key = key

        scan_y = int(cy1 + (cy2 - cy1) * ((phase % 6.0) / 6.0))
        travel = max(1, cy2 - cy1 - self._BRACKET * 2)
        dot_l = cy1 + self._BRACKET + int(travel * ((phase * 0.8) % 1.0))
        dot_r = cy1 + self._BRACKET + int(travel * (1.0 - ((phase * 0.8) % 1.0)))
        stamp = _dt.datetime.now().strftime('%H:%M:%S')
        return MenuHudFrame(
            static_photo=self._static_photo,
            cx1=cx1, cy1=cy1, cx2=cx2, cy2=cy2,
            rail_x_l=cx1 - 8, rail_x_r=cx2 + 8,
            scan_y=scan_y,
            trail_ys=(scan_y - 3, scan_y - 6),
            scan_color='#5eb8ca',
            trail_colors=('#3a6a78', '#2a5060'),
            dot_y_l=dot_l, dot_y_r=dot_r,
            dot_color_l='#5eb8ca', dot_color_r='#f3af12',
            dot_photo_l=self._dot_photo('#5eb8ca'),
            dot_photo_r=self._dot_photo('#f3af12'),
            dot_radius=3, dot_glow_size=18,
            stamp_text=stamp,
            stamp_pos=(cx2 - 4, cy2 + 4),
            stamp_color='#c8910e',
            stamp_font=('Consolas', 7),
        )


class MenuLeftInfoRenderer:
    def reset(self) -> None:
        pass
