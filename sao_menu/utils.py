# -*- coding: utf-8 -*-
"""缓动 / 数学 / 图像工具函数 (split from sao_theme.py — verbatim)."""
import tkinter as tk
from typing import Tuple
from PIL import Image, ImageDraw, ImageTk
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]

def _aa_circle_icon(kind: str, outer: str, inner: str, size: int = 40, scale: int = 4) -> ImageTk.PhotoImage:
    """Render an anti-aliased circular SAO action icon as a PhotoImage."""
    sw = size * scale
    img = Image.new('RGBA', (sw, sw), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def S(v):
        return int(round(v * scale))

    draw.ellipse((S(2), S(2), S(size - 2), S(size - 2)), outline=_hex_to_rgba(outer), width=max(1, S(3)))
    if kind == 'ok':
        draw.ellipse((S(9), S(9), S(31), S(31)), fill=_hex_to_rgba('#ffffff'))
        draw.ellipse((S(12), S(12), S(28), S(28)), fill=_hex_to_rgba(inner))
    else:
        draw.ellipse((S(9), S(9), S(31), S(31)), fill=_hex_to_rgba(inner))
        draw.line((S(14), S(14), S(26), S(26)), fill=_hex_to_rgba('#ffffff'), width=max(1, S(3)))
        draw.line((S(14), S(26), S(26), S(14)), fill=_hex_to_rgba('#ffffff'), width=max(1, S(3)))

    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def _make_aa_icon_button(parent, kind: str, command, outer: str, inner: str, bg: str = '#ffffff'):
    """Create a reusable anti-aliased popup icon button."""
    lbl = tk.Label(parent, bg=bg, cursor='hand2', bd=0, highlightthickness=0)
    normal = _aa_circle_icon(kind, outer, inner)
    hover_inner = '#ffffff' if kind == 'ok' else '#ff6b7b'
    hover = _aa_circle_icon(kind, outer, hover_inner if kind == 'close' else inner)
    lbl.configure(image=normal)
    lbl.image = normal
    lbl._img_normal = normal
    lbl._img_hover = hover
    lbl.bind('<Enter>', lambda e: lbl.configure(image=lbl._img_hover))
    lbl.bind('<Leave>', lambda e: lbl.configure(image=lbl._img_normal))
    lbl.bind('<Button-1>', lambda e: command())
    return lbl


def _hex_to_rgba(hex_color: str, alpha: int = 255):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(ch * 2 for ch in hex_color)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)


# ──────────────────── 动画工具 ────────────────────
def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3

def ease_in(t: float) -> float:
    return t ** 3

def ease_in_out(t: float) -> float:
    return 3 * t ** 2 - 2 * t ** 3

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip('#')
    if len(h) == 8:
        h = h[:6]
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f'#{r:02x}{g:02x}{b:02x}'

def _strip_alpha(c: str) -> str:
    """Strip 8-digit RGBA hex to 6-digit RGB (tkinter doesn't support alpha).

    Retained for backward compatibility with any external callers; new hot
    paths should call lerp_color directly (the cython kernel normalizes).
    """
    c = c.strip()
    if c.startswith('#') and len(c) == 9:
        return c[:7]
    return c


lerp_color = _CY_UI.lerp_hex_color  # cython kernel already strips alpha + normalizes


