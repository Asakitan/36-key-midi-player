"""Small sub-pixel compositing helpers for SAO Tk overlays."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PIL import Image


_EPS = 1.0 / 512.0


def subpixel_alpha_composite(dst: Image.Image, src: Image.Image,
                             x: float, y: float,
                             eps: float = _EPS) -> None:
    """Alpha-composite ``src`` onto ``dst`` at fractional coordinates."""
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy
    if (fx < eps or fx > 1.0 - eps) and (fy < eps or fy > 1.0 - eps):
        if fx > 0.5:
            ix += 1
        if fy > 0.5:
            iy += 1
        dst.alpha_composite(src, (ix, iy))
        return

    w, h = src.size
    if w <= 0 or h <= 0:
        return
    padded = Image.new('RGBA', (w + 2, h + 2), (0, 0, 0, 0))
    padded.alpha_composite(src, (1, 1))
    shifted = padded.transform(
        (w + 2, h + 2),
        Image.AFFINE,
        (1, 0, -fx, 0, 1, -fy),
        resample=Image.BILINEAR,
        fillcolor=(0, 0, 0, 0),
    )
    dst.alpha_composite(shifted, (ix - 1, iy - 1))


def subpixel_bar_width(bar_img: Image.Image,
                       frac_w: float) -> Optional[Image.Image]:
    """Crop a bar to fractional width by fading the trailing column."""
    if frac_w <= 0.0:
        return None
    fw_int = int(math.ceil(frac_w))
    frac = frac_w - math.floor(frac_w)
    if fw_int > bar_img.width:
        fw_int = bar_img.width
        frac = 0.0
    cropped = bar_img.crop((0, 0, fw_int, bar_img.height))
    if frac < _EPS or frac > (1.0 - _EPS):
        return cropped
    arr = np.array(cropped)
    arr[:, fw_int - 1, 3] = np.clip(
        arr[:, fw_int - 1, 3].astype(np.float32) * frac, 0, 255
    ).astype(np.uint8)
    return Image.fromarray(arr, 'RGBA')
