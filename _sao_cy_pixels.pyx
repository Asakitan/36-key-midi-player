# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
"""Small Cython pixel kernels for SAO GUI hot paths.

The module intentionally keeps a tiny surface area. Large GUI modules stay
as Python because their dynamic Tk/PIL code does not benefit from whole-file
Cython compilation and is easier to keep correct in Python.
"""

import numpy as _np


cpdef bytes premultiply_bgra_ndarray(object rgba):
    """RGBA ndarray-like object -> premultiplied BGRA bytes.

    Matches overlay_render_worker's historical rounding:
    channel = (channel * alpha + 127) // 255
    """
    cdef const unsigned char[:, :, :] arr = rgba
    cdef Py_ssize_t h = arr.shape[0]
    cdef Py_ssize_t w = arr.shape[1]
    cdef Py_ssize_t y
    cdef Py_ssize_t x
    cdef Py_ssize_t i = 0
    cdef unsigned int a
    cdef bytearray out
    cdef unsigned char[:] dst

    if arr.shape[2] < 4:
        raise ValueError('expected RGBA input with at least 4 channels')

    out = bytearray(h * w * 4)
    dst = out
    with nogil:
        for y in range(h):
            for x in range(w):
                a = arr[y, x, 3]
                dst[i] = <unsigned char>((<unsigned int>arr[y, x, 2] * a + 127) // 255)
                dst[i + 1] = <unsigned char>((<unsigned int>arr[y, x, 1] * a + 127) // 255)
                dst[i + 2] = <unsigned char>((<unsigned int>arr[y, x, 0] * a + 127) // 255)
                dst[i + 3] = <unsigned char>a
                i += 4
    return bytes(out)


cpdef bytes premultiply_bgra_bytes_floor(
        object data, Py_ssize_t height, Py_ssize_t width,
        double master_alpha=1.0):
    """RGBA bytes -> premultiplied BGRA bytes.

    Matches ui_gpu.composer's floor semantics:
    - master alpha uses int(master_alpha * 255) only when master_alpha < 0.999
    - premultiply uses channel * alpha // 255
    """
    cdef const unsigned char[:] src = data
    cdef Py_ssize_t expected
    cdef Py_ssize_t y
    cdef Py_ssize_t x
    cdef Py_ssize_t si = 0
    cdef Py_ssize_t di = 0
    cdef unsigned int a
    cdef unsigned int mul = 255
    cdef bint apply_master = False
    cdef bytearray out
    cdef unsigned char[:] dst

    if height < 0 or width < 0:
        raise ValueError('height and width must be non-negative')
    expected = height * width * 4
    if src.shape[0] != expected:
        raise ValueError('RGBA byte length does not match height * width * 4')

    if master_alpha < 0.999:
        apply_master = True
        if master_alpha <= 0.0:
            mul = 0
        elif master_alpha >= 1.0:
            mul = 255
        else:
            mul = <unsigned int>(master_alpha * 255.0)

    out = bytearray(expected)
    dst = out
    with nogil:
        for y in range(height):
            for x in range(width):
                a = src[si + 3]
                if apply_master:
                    a = (a * mul) // 255
                dst[di] = <unsigned char>((<unsigned int>src[si + 2] * a) // 255)
                dst[di + 1] = <unsigned char>((<unsigned int>src[si + 1] * a) // 255)
                dst[di + 2] = <unsigned char>((<unsigned int>src[si] * a) // 255)
                dst[di + 3] = <unsigned char>a
                si += 4
                di += 4
    return bytes(out)


cpdef bytes multiply_alpha_rgba_ndarray_floor(object rgba, double alpha):
    """RGBA ndarray-like object -> RGBA bytes with alpha multiplied.

    Matches the HP/BossHP/DPS final fade:
    alpha_channel = alpha_channel * int(alpha * 255) // 255
    """
    cdef const unsigned char[:, :, :] arr = rgba
    cdef Py_ssize_t h = arr.shape[0]
    cdef Py_ssize_t w = arr.shape[1]
    cdef Py_ssize_t y
    cdef Py_ssize_t x
    cdef Py_ssize_t i = 0
    cdef unsigned int mul = 255
    cdef bytearray out
    cdef unsigned char[:] dst

    if arr.shape[2] < 4:
        raise ValueError('expected RGBA input with at least 4 channels')

    if alpha < 0.999:
        if alpha <= 0.0:
            mul = 0
        elif alpha >= 1.0:
            mul = 255
        else:
            mul = <unsigned int>(alpha * 255.0)

    out = bytearray(h * w * 4)
    dst = out
    with nogil:
        for y in range(h):
            for x in range(w):
                dst[i] = arr[y, x, 0]
                dst[i + 1] = arr[y, x, 1]
                dst[i + 2] = arr[y, x, 2]
                dst[i + 3] = <unsigned char>((<unsigned int>arr[y, x, 3] * mul) // 255)
                i += 4
    return bytes(out)


cpdef bytes multiply_alpha_mask_rgba_ndarray_floor(object rgba, object mask):
    """RGBA ndarray-like object -> RGBA bytes clipped by an L mask.

    Matches HP/BossHP _clip_alpha:
    alpha_channel = alpha_channel * mask // 255
    """
    cdef const unsigned char[:, :, :] arr = rgba
    cdef const unsigned char[:, :] m = mask
    cdef Py_ssize_t h = arr.shape[0]
    cdef Py_ssize_t w = arr.shape[1]
    cdef Py_ssize_t y
    cdef Py_ssize_t x
    cdef Py_ssize_t i = 0
    cdef unsigned int ma
    cdef bytearray out
    cdef unsigned char[:] dst

    if arr.shape[2] < 4:
        raise ValueError('expected RGBA input with at least 4 channels')
    if m.shape[0] != h or m.shape[1] != w:
        raise ValueError('mask shape must match RGBA height and width')

    out = bytearray(h * w * 4)
    dst = out
    with nogil:
        for y in range(h):
            for x in range(w):
                ma = m[y, x]
                dst[i] = arr[y, x, 0]
                dst[i + 1] = arr[y, x, 1]
                dst[i + 2] = arr[y, x, 2]
                dst[i + 3] = <unsigned char>((<unsigned int>arr[y, x, 3] * ma) // 255)
                i += 4
    return bytes(out)


cpdef bytes multiply_alpha_regions_rgba_bytes(object rgba, object rects, double alpha):
    """RGBA ndarray-like object -> RGBA bytes with alpha multiplied in rects.

    Mirrors ``sao_gui_hp._multiply_alpha_regions`` without numpy slice
    allocation/casts. RGB is copied unchanged; only alpha inside the
    clamped rectangles is multiplied by ``int(alpha * 255) // 255``.
    """
    cdef const unsigned char[:, :, :] arr = rgba
    cdef Py_ssize_t h = arr.shape[0]
    cdef Py_ssize_t w = arr.shape[1]
    cdef Py_ssize_t y, x, i = 0
    cdef unsigned int mul = 255
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef object rect
    cdef Py_ssize_t rx0, ry0, rx1, ry1
    cdef Py_ssize_t yy, xx, pos

    if arr.shape[2] < 4:
        raise ValueError('expected RGBA input with at least 4 channels')

    if alpha < 0.999:
        if alpha <= 0.0:
            mul = 0
        elif alpha >= 1.0:
            mul = 255
        else:
            mul = <unsigned int>(alpha * 255.0)

    out = bytearray(h * w * 4)
    dst = out
    with nogil:
        for y in range(h):
            for x in range(w):
                dst[i] = arr[y, x, 0]
                dst[i + 1] = arr[y, x, 1]
                dst[i + 2] = arr[y, x, 2]
                dst[i + 3] = arr[y, x, 3]
                i += 4

    for rect in (rects or ()):
        try:
            rx0 = <long>int(rect[0])
            ry0 = <long>int(rect[1])
            rx1 = <long>int(rect[2])
            ry1 = <long>int(rect[3])
        except Exception:
            continue
        if rx0 < 0:
            rx0 = 0
        elif rx0 > w:
            rx0 = w
        if ry0 < 0:
            ry0 = 0
        elif ry0 > h:
            ry0 = h
        if rx1 < rx0:
            rx1 = rx0
        elif rx1 > w:
            rx1 = w
        if ry1 < ry0:
            ry1 = ry0
        elif ry1 > h:
            ry1 = h
        if rx1 <= rx0 or ry1 <= ry0:
            continue
        with nogil:
            for yy in range(ry0, ry1):
                pos = (yy * w + rx0) * 4 + 3
                for xx in range(rx0, rx1):
                    dst[pos] = <unsigned char>((<unsigned int>dst[pos] * mul) // 255)
                    pos += 4
    return bytes(out)


cpdef bytes scanline_texture_rgba_bytes(Py_ssize_t width, Py_ssize_t height,
                                        unsigned int alpha=10):
    """Return RGBA bytes for the HP scanline texture."""
    cdef Py_ssize_t expected = width * height * 4
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x, pos
    cdef unsigned char a = <unsigned char>(255 if alpha > 255 else alpha)
    if width <= 0 or height <= 0:
        return bytes(4)
    out = bytearray(expected)
    dst = out
    with nogil:
        for y in range(height):
            if y % 3 != 2:
                continue
            pos = y * width * 4
            for x in range(width):
                dst[pos] = 255
                dst[pos + 1] = 255
                dst[pos + 2] = 255
                dst[pos + 3] = a
                pos += 4
    return bytes(out)


cpdef bytes hgrad_bar_rgba_bytes(Py_ssize_t width, Py_ssize_t height,
                                 object ca, object cb):
    """Return RGBA bytes for HP/STA horizontal gradient bars."""
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x, pos = 0
    cdef double tx, shade
    cdef int ar, ag, ab, aa, br, bg, bb, ba
    cdef int rr, gg, bl, al
    if width <= 0 or height <= 0:
        return bytes(4)
    ar = <int>int(ca[0]); ag = <int>int(ca[1]); ab = <int>int(ca[2]); aa = <int>int(ca[3])
    br = <int>int(cb[0]); bg = <int>int(cb[1]); bb = <int>int(cb[2]); ba = <int>int(cb[3])
    out = bytearray(width * height * 4)
    dst = out
    with nogil:
        for y in range(height):
            if height > 1:
                shade = 1.02 + (0.88 - 1.02) * (<double>y / <double>(height - 1))
            else:
                shade = 1.02
            for x in range(width):
                tx = (<double>x / <double>(width - 1)) if width > 1 else 0.0
                rr = <int>((<double>ar + (<double>(br - ar)) * tx) * shade)
                gg = <int>((<double>ag + (<double>(bg - ag)) * tx) * shade)
                bl = <int>((<double>ab + (<double>(bb - ab)) * tx) * shade)
                al = <int>((<double>aa + (<double>(ba - aa)) * tx))
                if rr < 0: rr = 0
                elif rr > 255: rr = 255
                if gg < 0: gg = 0
                elif gg > 255: gg = 255
                if bl < 0: bl = 0
                elif bl > 255: bl = 255
                if al < 0: al = 0
                elif al > 255: al = 255
                dst[pos] = <unsigned char>rr
                dst[pos + 1] = <unsigned char>gg
                dst[pos + 2] = <unsigned char>bl
                dst[pos + 3] = <unsigned char>al
                pos += 4
    return bytes(out)


cpdef bytes hgrad_bar_flat_rgba_bytes(Py_ssize_t width, Py_ssize_t height,
                                      object ca, object cb):
    """C2 fix: HP/BossHP horizontal-gradient bar WITHOUT the 1.02→0.88 vertical
    shade. Identical to hgrad_bar_rgba_bytes except shade is fixed at 1.0,
    preserving the previous per-column flat fill for the BossHP per-unit HP
    bar (6 px tall — the y-shade would visibly darken the bottom row ~12%)."""
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x, pos = 0
    cdef double tx
    cdef int ar, ag, ab, aa, br, bg, bb, ba
    cdef int rr, gg, bl, al
    if width <= 0 or height <= 0:
        return bytes(4)
    ar = <int>int(ca[0]); ag = <int>int(ca[1]); ab = <int>int(ca[2]); aa = <int>int(ca[3])
    br = <int>int(cb[0]); bg = <int>int(cb[1]); bb = <int>int(cb[2]); ba = <int>int(cb[3])
    out = bytearray(width * height * 4)
    dst = out
    with nogil:
        for y in range(height):
            for x in range(width):
                tx = (<double>x / <double>(width - 1)) if width > 1 else 0.0
                rr = <int>(<double>ar + (<double>(br - ar)) * tx)
                gg = <int>(<double>ag + (<double>(bg - ag)) * tx)
                bl = <int>(<double>ab + (<double>(bb - ab)) * tx)
                al = <int>(<double>aa + (<double>(ba - aa)) * tx)
                if rr < 0: rr = 0
                elif rr > 255: rr = 255
                if gg < 0: gg = 0
                elif gg > 255: gg = 255
                if bl < 0: bl = 0
                elif bl > 255: bl = 255
                if al < 0: al = 0
                elif al > 255: al = 255
                dst[pos] = <unsigned char>rr
                dst[pos + 1] = <unsigned char>gg
                dst[pos + 2] = <unsigned char>bl
                dst[pos + 3] = <unsigned char>al
                pos += 4
    return bytes(out)


cpdef bytes hgrad_bar_fade_rgba_bytes(Py_ssize_t width, Py_ssize_t height,
                                      Py_ssize_t fw, double frac,
                                      object ca, object cb):
    """HP/BossHP horizontal-gradient bar with sub-pixel trailing-column fade.

    H2: fuses what was previously _make_gradient_bar + PIL crop + numpy
    clip+fromarray for the subpixel_bar_width(fw + frac) case. Returns the
    raw RGBA bytes of a (fw, height) image where the last column's alpha is
    scaled by ``frac`` (matching the floor `alpha*frac255//255` semantics of
    multiply_alpha_*). Caller wraps via Image.frombytes('RGBA', (fw, h)).
    """
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x, pos = 0
    cdef double tx, shade
    cdef int ar, ag, ab, aa, br, bg, bb, ba
    cdef int rr, gg, bl, al, ra
    cdef int frac255
    cdef Py_ssize_t denom
    if width <= 0 or height <= 0 or fw <= 0:
        return bytes(4)
    if fw > width:
        fw = width
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0
    # C4 fix: truncation, NOT rounding — matches multiply_alpha_*_floor and
    # the PIL fallback (np.float32 * frac → astype(uint8) truncates).
    frac255 = <int>(frac * 255.0)
    if frac255 < 0:
        frac255 = 0
    elif frac255 > 255:
        frac255 = 255
    ar = <int>int(ca[0]); ag = <int>int(ca[1]); ab = <int>int(ca[2]); aa = <int>int(ca[3])
    br = <int>int(cb[0]); bg = <int>int(cb[1]); bb = <int>int(cb[2]); ba = <int>int(cb[3])
    out = bytearray(fw * height * 4)
    dst = out
    denom = (width - 1) if width > 1 else 1
    with nogil:
        for y in range(height):
            if height > 1:
                shade = 1.02 + (0.88 - 1.02) * (<double>y / <double>(height - 1))
            else:
                shade = 1.02
            for x in range(fw):
                tx = (<double>x / <double>denom) if width > 1 else 0.0
                rr = <int>((<double>ar + (<double>(br - ar)) * tx) * shade)
                gg = <int>((<double>ag + (<double>(bg - ag)) * tx) * shade)
                bl = <int>((<double>ab + (<double>(bb - ab)) * tx) * shade)
                al = <int>((<double>aa + (<double>(ba - aa)) * tx))
                if rr < 0: rr = 0
                elif rr > 255: rr = 255
                if gg < 0: gg = 0
                elif gg > 255: gg = 255
                if bl < 0: bl = 0
                elif bl > 255: bl = 255
                if al < 0: al = 0
                elif al > 255: al = 255
                if x == fw - 1 and frac255 < 255:
                    ra = (al * frac255) // 255
                    al = ra
                dst[pos] = <unsigned char>rr
                dst[pos + 1] = <unsigned char>gg
                dst[pos + 2] = <unsigned char>bl
                dst[pos + 3] = <unsigned char>al
                pos += 4
    return bytes(out)


cpdef bytes subpixel_shift_rgba_bytes(object rgba_bytes,
                                      Py_ssize_t width,
                                      Py_ssize_t height,
                                      double fx, double fy):
    """D1/E1: bilinear sub-pixel shift of an RGBA buffer by (fx, fy) in [0,1).

    Replaces the overlay_subpixel.subpixel_alpha_composite hot path that
    previously did:
      Image.new('RGBA', (w+2, h+2)) + alpha_composite + transform(AFFINE,
                                                                  BILINEAR)

    Outputs a (width, height) buffer; the caller composites at the
    integer base offset (ix, iy). Out-of-bounds source pixels are treated
    as transparent (matching the PIL fillcolor=(0,0,0,0) + 1px pad trick).

    Floor RGB blending matches PIL's BILINEAR; alpha uses the same
    (alpha*weight + alpha*weight)//256 rounding so a sub-pixel shifted
    sprite's leading edge fades the same as the previous AFFINE path.
    """
    cdef const unsigned char[:] src = rgba_bytes
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x
    cdef Py_ssize_t dst_pos, p00, p10, p01, p11
    cdef double wx0, wx1, wy0, wy1
    cdef double r, g, b, a
    cdef int sx, sy
    cdef int ww00, ww10, ww01, ww11
    cdef Py_ssize_t stride = width * 4
    cdef bint use_x0, use_x1, use_y0, use_y1
    if width <= 0 or height <= 0:
        return bytes(4)
    if fx < 0.0:
        fx = 0.0
    elif fx >= 1.0:
        fx = 0.999999
    if fy < 0.0:
        fy = 0.0
    elif fy >= 1.0:
        fy = 0.999999
    wx1 = fx
    wx0 = 1.0 - fx
    wy1 = fy
    wy0 = 1.0 - fy
    # Pre-quantise weights to int (0..256) for fast multiply-shift inside the
    # nogil block. PIL BILINEAR uses similar fixed-point with 8-bit precision.
    cdef int qx1 = <int>(wx1 * 256.0 + 0.5)
    cdef int qx0 = 256 - qx1
    cdef int qy1 = <int>(wy1 * 256.0 + 0.5)
    cdef int qy0 = 256 - qy1
    cdef int w00 = (qx0 * qy0) >> 8
    cdef int w10 = (qx1 * qy0) >> 8
    cdef int w01 = (qx0 * qy1) >> 8
    cdef int w11 = (qx1 * qy1) >> 8
    out = bytearray(width * height * 4)
    dst = out
    with nogil:
        for y in range(height):
            for x in range(width):
                dst_pos = (y * width + x) * 4
                # Source sample positions: shifting OUTPUT by (+fx,+fy) means
                # sampling SOURCE at (x - fx, y - fy). The integer base is
                # (x - 1, y - 1) and (x, y); past the edges sample as zero.
                sx = x - 1
                sy = y - 1
                use_x0 = (sx >= 0)
                use_x1 = (sx + 1 < width)
                use_y0 = (sy >= 0)
                use_y1 = (sy + 1 < height)
                ww00 = w00 if (use_x0 and use_y0) else 0
                ww10 = w10 if (use_x1 and use_y0) else 0
                ww01 = w01 if (use_x0 and use_y1) else 0
                ww11 = w11 if (use_x1 and use_y1) else 0
                p00 = (sy * width + sx) * 4 if (use_x0 and use_y0) else 0
                p10 = (sy * width + (sx + 1)) * 4 if (use_x1 and use_y0) else 0
                p01 = ((sy + 1) * width + sx) * 4 if (use_x0 and use_y1) else 0
                p11 = ((sy + 1) * width + (sx + 1)) * 4 if (use_x1 and use_y1) else 0
                r = 0.0
                g = 0.0
                b = 0.0
                a = 0.0
                if ww00 > 0:
                    r += (<int>src[p00]) * ww00
                    g += (<int>src[p00 + 1]) * ww00
                    b += (<int>src[p00 + 2]) * ww00
                    a += (<int>src[p00 + 3]) * ww00
                if ww10 > 0:
                    r += (<int>src[p10]) * ww10
                    g += (<int>src[p10 + 1]) * ww10
                    b += (<int>src[p10 + 2]) * ww10
                    a += (<int>src[p10 + 3]) * ww10
                if ww01 > 0:
                    r += (<int>src[p01]) * ww01
                    g += (<int>src[p01 + 1]) * ww01
                    b += (<int>src[p01 + 2]) * ww01
                    a += (<int>src[p01 + 3]) * ww01
                if ww11 > 0:
                    r += (<int>src[p11]) * ww11
                    g += (<int>src[p11 + 1]) * ww11
                    b += (<int>src[p11 + 2]) * ww11
                    a += (<int>src[p11 + 3]) * ww11
                dst[dst_pos] = <unsigned char>((<int>(r + 128.0)) >> 8)
                dst[dst_pos + 1] = <unsigned char>((<int>(g + 128.0)) >> 8)
                dst[dst_pos + 2] = <unsigned char>((<int>(b + 128.0)) >> 8)
                dst[dst_pos + 3] = <unsigned char>((<int>(a + 128.0)) >> 8)
    return bytes(out)


cpdef bytes fade_last_column_alpha_rgba_bytes(object rgba_bytes,
                                              Py_ssize_t width,
                                              Py_ssize_t height,
                                              double frac):
    """Apply a sub-pixel alpha multiplier to the LAST column of an RGBA buffer.

    H2: extracted from overlay_subpixel.subpixel_bar_width when the call site
    has already built a PIL cropped image and only needs the trailing-column
    fade. Floor semantics match multiply_alpha_*: alpha = (alpha*frac255)//255.
    Returns a new bytes (caller wraps via Image.frombytes).
    """
    cdef const unsigned char[:] src = rgba_bytes
    cdef bytearray out
    cdef unsigned char[:] dst
    cdef Py_ssize_t y, x, pos
    cdef Py_ssize_t last_col
    cdef int frac255
    cdef int al, ra
    if width <= 0 or height <= 0:
        return bytes(4)
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0
    # C4 fix: truncation, NOT rounding — matches multiply_alpha_*_floor and
    # the PIL fallback (np.float32 * frac → astype(uint8) truncates).
    frac255 = <int>(frac * 255.0)
    if frac255 < 0:
        frac255 = 0
    elif frac255 > 255:
        frac255 = 255
    out = bytearray(rgba_bytes)
    dst = out
    if frac255 >= 255 or width < 1:
        return bytes(out)
    last_col = width - 1
    with nogil:
        for y in range(height):
            pos = (y * width + last_col) * 4 + 3
            al = <int>dst[pos]
            ra = (al * frac255) // 255
            dst[pos] = <unsigned char>ra
    return bytes(out)


# ───────────────────────────────────────────────
#  STA / bar detection kernels (recognition.py)
# ───────────────────────────────────────────────
#
# v3.1.3: `recognition._detect_stamina_pct` previously did:
#
#   pixels = img.astype(np.float32)           # H*W*3*4 byte allocation
#   diff = pixels - target_bgr[None, None, :] # another allocation
#   dist = np.sqrt((diff * diff).sum(axis=2)) # sqrt over every pixel
#   match = dist <= threshold                 # bool mask
#   col_fill = match.mean(axis=0)             # (W,) per-column ratio
#   overall_match = float(match.mean())       # scalar
#
# All five intermediates can be replaced by one nogil pass that counts
# per-column matches into a single uint32 buffer using the squared
# distance test (no sqrt needed). The Python-side post-processing
# (threshold scanning, near-full extension, confidence math) is left
# alone — only the per-pixel scan is moved to Cython.


cpdef tuple bgr_color_match_column_ratio(object bgr_img,
                                         int target_b,
                                         int target_g,
                                         int target_r,
                                         double dist_threshold):
    """Per-column match ratio against a target BGR colour.

    `bgr_img` is a contiguous ``(H, W, 3)`` ``uint8`` numpy array in BGR
    order (the format ``recognition.py`` already produces). The kernel
    returns ``(col_fill, overall_ratio)`` where:

      * ``col_fill`` is a length-W ``float32`` ndarray giving the
        fraction of rows in each column whose euclidean BGR distance to
        the target is <= ``dist_threshold``.
      * ``overall_ratio`` is the same fraction taken across the whole
        image.

    Uses the squared-distance test internally so no sqrt is needed; the
    threshold is squared once at entry and the rest of the loop is pure
    integer arithmetic over a typed memoryview.
    """
    cdef const unsigned char[:, :, :] src = bgr_img
    cdef Py_ssize_t h = src.shape[0]
    cdef Py_ssize_t w = src.shape[1]
    cdef Py_ssize_t c = src.shape[2]
    cdef Py_ssize_t y, x
    cdef int db, dg, dr
    cdef long long dist_sq
    cdef long long threshold_sq
    cdef unsigned long long total_match = 0
    cdef unsigned long long total_pixels = (<unsigned long long>h) * (<unsigned long long>w)

    if c < 3 or h == 0 or w == 0:
        return (_np.zeros((max(w, 0),), dtype=_np.float32), 0.0)
    if target_b < 0 or target_b > 255 or target_g < 0 or target_g > 255 \
            or target_r < 0 or target_r > 255:
        raise ValueError('target BGR channels must be in [0, 255]')
    if dist_threshold < 0:
        dist_threshold = 0
    threshold_sq = <long long>(dist_threshold * dist_threshold)

    col_counts_np = _np.zeros((w,), dtype=_np.uint32)
    cdef unsigned int[:] col_counts = col_counts_np

    with nogil:
        for y in range(h):
            for x in range(w):
                db = <int>src[y, x, 0] - target_b
                dg = <int>src[y, x, 1] - target_g
                dr = <int>src[y, x, 2] - target_r
                dist_sq = (<long long>db) * db + (<long long>dg) * dg + (<long long>dr) * dr
                if dist_sq <= threshold_sq:
                    col_counts[x] += 1
                    total_match += 1

    cdef double inv_h = 1.0 / <double>h
    col_fill = col_counts_np.astype(_np.float32) * inv_h
    cdef double overall
    if total_pixels == 0:
        overall = 0.0
    else:
        overall = <double>total_match / <double>total_pixels
    return (col_fill, overall)


# ───────────────────────────────────────────────
#  Per-row fill % median (recognition._row_independent_pct)
# ───────────────────────────────────────────────
#
# v3.1.3 round 4: outlier-resistant per-row fill detection. Replaces:
#
#   for r in range(n_rows):
#       rv = val[r, :].astype(np.float32)
#       rs = sat[r, :].astype(np.float32)
#       rh_cov = hue_mask[r, :].astype(np.float32)
#       row_score = 0.78 * (rv / 255.0) + 0.22 * (rs / 255.0)
#       row_score = np.where(rh_cov >= 0.5, row_score, row_score * 0.80)
#       row_score = np.convolve(row_score, [1/3, 1/3, 1/3], mode="same")
#       filled = row_score >= threshold
#       if np.any(filled):
#           last_idx = int(np.max(np.where(filled)[0]))
#           pct = _subpixel_threshold_crossing(row_score, threshold, last_idx) / eff_w
#           row_pcts.append(clip(pct, 0, 1))
#   median(row_pcts)
#
# This was a Python-level ``for`` loop with three astype copies and a
# convolve allocation per row. The cython kernel reuses two reusable
# float64 scratch buffers and walks each row inside a single nogil
# block (with sub-pixel crossing inlined). Median is computed via a
# small in-place quickselect on the per-row pct buffer.


cdef inline double _row_subpixel_crossing(const double[::1] score,
                                           Py_ssize_t eff_w,
                                           double threshold,
                                           Py_ssize_t last_filled_idx) nogil:
    """Inlined nogil clone of ``_subpixel_threshold_crossing``."""
    cdef double s0, s1, frac
    cdef Py_ssize_t nxt
    if last_filled_idx >= eff_w - 1:
        return <double>(last_filled_idx + 1)
    nxt = last_filled_idx + 1
    if nxt > eff_w - 1:
        nxt = eff_w - 1
    s0 = score[last_filled_idx]
    s1 = score[nxt]
    if s0 > threshold and s1 <= threshold and s0 != s1:
        frac = (s0 - threshold) / (s0 - s1)
        return <double>last_filled_idx + frac
    return <double>(last_filled_idx + 1)


cdef void _quickselect_median(double[::1] arr, Py_ssize_t count, double *out) nogil:
    """Median of arr[:count] via standard quickselect (partial sort).

    Sorts in place. ``out`` receives the median. Caller must ensure count > 0.
    """
    cdef Py_ssize_t left = 0
    cdef Py_ssize_t right = count - 1
    cdef Py_ssize_t lo, hi, mid_target_lo, mid_target_hi
    cdef Py_ssize_t i, j
    cdef double pivot, tmp
    # For even count, median = mean of the two middle items; for odd count,
    # the middle element. We expose both targets and reuse one quickselect
    # pass to land both at the right positions (median of medium-sized arrays
    # is rare-call so even O(n) average is fine).
    if count == 1:
        out[0] = arr[0]
        return
    mid_target_lo = (count - 1) // 2
    mid_target_hi = count // 2
    lo = left
    hi = right
    while lo < hi:
        pivot = arr[(lo + hi) // 2]
        i = lo
        j = hi
        while i <= j:
            while arr[i] < pivot:
                i += 1
            while arr[j] > pivot:
                j -= 1
            if i <= j:
                tmp = arr[i]
                arr[i] = arr[j]
                arr[j] = tmp
                i += 1
                j -= 1
        if j >= mid_target_lo and i <= mid_target_hi:
            break
        if i <= mid_target_lo:
            lo = i
        elif j >= mid_target_hi:
            hi = j
        else:
            break
    # arr is now partitioned so arr[mid_target_lo] and arr[mid_target_hi] hold
    # the proper order-statistics in expectation. Run a tiny insertion sort
    # over the middle window to guarantee correctness on small arrays where
    # the partition can leave 2–4 stragglers.
    cdef Py_ssize_t window_lo = max(0, mid_target_lo - 2)
    cdef Py_ssize_t window_hi = min(count - 1, mid_target_hi + 2)
    for i in range(window_lo + 1, window_hi + 1):
        tmp = arr[i]
        j = i - 1
        while j >= window_lo and arr[j] > tmp:
            arr[j + 1] = arr[j]
            j -= 1
        arr[j + 1] = tmp
    if (count & 1) == 1:
        out[0] = arr[mid_target_lo]
    else:
        out[0] = 0.5 * (arr[mid_target_lo] + arr[mid_target_hi])


cpdef object row_independent_fill_pct(object val, object sat,
                                       object hue_mask,
                                       double threshold):
    """Per-row fill % median — outlier-resistant version of `_row_independent_pct`.

    ``val`` and ``sat`` are ``(H, W) float32`` HSV channels (val=V, sat=S).
    ``hue_mask`` is an ``(H, W) bool`` array describing whether each pixel
    matched the hue/saturation window in the caller.

    Returns the median of per-row fill ratios as a Python ``float``, or
    ``None`` if fewer than two rows produced a fill (matching the original
    contract used by ``recognition._detect_bar_pct``).
    """
    cdef Py_ssize_t h, w, r, x, last_idx, kept = 0
    cdef bint has_filled
    cdef double s, crossing, pct, inv_w, median_out
    cdef double third = 1.0 / 3.0
    cdef const float[:, :] val_v
    cdef const float[:, :] sat_v
    cdef const unsigned char[:, :] mask_v
    cdef double[::1] row_score
    cdef double[::1] smoothed
    cdef double[::1] pcts

    # Bool ndarrays are 1 byte per element in numpy, but their buffer format
    # string is '?' rather than 'B' so cython's `unsigned char` memoryview
    # won't accept them directly. Reinterpret as uint8 view (no copy) when
    # possible; otherwise force a contiguous uint8 copy.
    if hasattr(hue_mask, 'dtype') and hue_mask.dtype == _np.bool_:
        mask_obj = hue_mask.view(_np.uint8)
    else:
        mask_obj = _np.ascontiguousarray(hue_mask, dtype=_np.uint8)

    val_v = val
    sat_v = sat
    mask_v = mask_obj
    h = val_v.shape[0]
    w = val_v.shape[1]

    if h < 2 or w <= 4:
        return None
    if not (val_v.shape[0] == sat_v.shape[0] == mask_v.shape[0]
            and val_v.shape[1] == sat_v.shape[1] == mask_v.shape[1]):
        raise ValueError('val, sat, hue_mask must share shape (H, W)')

    row_score_np = _np.empty(w, dtype=_np.float64)
    smoothed_np = _np.empty(w, dtype=_np.float64)
    pcts_np = _np.empty(h, dtype=_np.float64)
    row_score = row_score_np
    smoothed = smoothed_np
    pcts = pcts_np

    inv_w = 1.0 / <double>w

    with nogil:
        for r in range(h):
            # Build per-row score with hue-mask scaling.
            for x in range(w):
                s = 0.78 * (<double>val_v[r, x] / 255.0) + 0.22 * (<double>sat_v[r, x] / 255.0)
                if mask_v[r, x] != 0:
                    row_score[x] = s
                else:
                    row_score[x] = s * 0.80

            # 3-wide moving-average smoothing (np.convolve [1/3,1/3,1/3], mode='same').
            #   smoothed[0]    = (row[0] + row[1]) / 3
            #   smoothed[w-1]  = (row[w-2] + row[w-1]) / 3
            #   smoothed[i]    = (row[i-1] + row[i] + row[i+1]) / 3
            if w == 1:
                smoothed[0] = row_score[0] * third
            else:
                smoothed[0] = (row_score[0] + row_score[1]) * third
                smoothed[w - 1] = (row_score[w - 2] + row_score[w - 1]) * third
                for x in range(1, w - 1):
                    smoothed[x] = (row_score[x - 1] + row_score[x] + row_score[x + 1]) * third

            # Walk right-to-left to find last filled index.
            has_filled = False
            last_idx = -1
            for x in range(w - 1, -1, -1):
                if smoothed[x] >= threshold:
                    last_idx = x
                    has_filled = True
                    break

            if not has_filled:
                continue

            crossing = _row_subpixel_crossing(smoothed, w, threshold, last_idx)
            pct = crossing * inv_w
            if pct < 0.0:
                pct = 0.0
            elif pct > 1.0:
                pct = 1.0
            pcts[kept] = pct
            kept += 1

    if kept < 2:
        return None

    # Median over kept rows.
    with nogil:
        _quickselect_median(pcts, kept, &median_out)
    return float(median_out)


# ───────────────────────────────────────────────
#  Gradient-based edge detection (recognition._gradient_edge_pct)
# ───────────────────────────────────────────────
#
# v3.1.3 round 5: the per-bar fill detector calls ``_gradient_edge_pct``
# once per tick to locate the fill->empty boundary via the sharpest
# negative gradient. The pure-numpy version allocates three arrays
# (np.diff, np.convolve, slice) and calls np.argmin per tick. The
# cython kernel does one nogil pass: derivative + 7-wide smoothing +
# argmin in the search window + sub-pixel mid-score crossing.


cpdef object gradient_edge_pct(object smooth_score, Py_ssize_t eff_w,
                                double dynamic_range):
    """Find the fill->empty boundary via the sharpest negative gradient.

    Returns a sub-pixel ``pct in [0, 1]`` as a Python float, or ``None``
    when no edge stands out enough relative to the dynamic range. This
    mirrors ``recognition._gradient_edge_pct`` semantics byte-for-byte
    except for the float64-everywhere precision (the original mixed
    float32 inputs with float64 intermediates).
    """
    cdef const double[::1] ss = smooth_score
    cdef Py_ssize_t n = ss.shape[0]
    cdef Py_ssize_t i, j, s_start, s_end
    cdef double grad_threshold
    cdef double min_val
    cdef Py_ssize_t min_idx
    cdef double seventh = 1.0 / 7.0
    cdef double s0, s1, frac, mid_score, candidate
    cdef double r0, r1, r2, r3, r4, r5, r6  # 7-wide window

    if eff_w <= 6 or n != eff_w:
        # The caller passes eff_w explicitly; n should match smooth_score
        # length. If they disagree, prefer the conservative empty result.
        if n != eff_w:
            return None
        return None
    # The numpy gradient has length eff_w - 1
    cdef Py_ssize_t gn = eff_w - 1
    if gn < 5:
        return None

    grad_np = _np.empty(gn, dtype=_np.float64)
    smooth_grad_np = _np.empty(gn, dtype=_np.float64)
    cdef double[::1] grad = grad_np
    cdef double[::1] smooth_grad = smooth_grad_np

    # Search window — match the original semantics:
    #   s_start = max(2, int(eff_w * 0.03))
    #   s_end   = max(s_start + 4, eff_w - 1 - max(3, int(eff_w * 0.02)))
    s_start = <Py_ssize_t>(eff_w * 0.03)
    if s_start < 2:
        s_start = 2
    cdef Py_ssize_t margin_right = <Py_ssize_t>(eff_w * 0.02)
    if margin_right < 3:
        margin_right = 3
    s_end = (eff_w - 1) - margin_right
    if s_end < s_start + 4:
        s_end = s_start + 4
    # `region = smooth_grad[s_start:s_end]` — empty when s_start >= s_end
    if s_start >= s_end:
        return None
    # Also cap s_end to the smooth_grad length so the argmin window stays valid.
    if s_end > gn:
        s_end = gn
    if s_start >= s_end:
        return None

    with nogil:
        # np.diff(smooth_score) — grad[i] = ss[i+1] - ss[i] for i in [0, gn)
        for i in range(gn):
            grad[i] = ss[i + 1] - ss[i]

        # np.convolve(grad, ones(7)/7, mode='same')
        #   smooth_grad[i] = (grad[i-3] + .. + grad[i+3]) * (1/7),
        #   with out-of-range slots treated as 0.
        for i in range(gn):
            r0 = grad[i - 3] if i - 3 >= 0 else 0.0
            r1 = grad[i - 2] if i - 2 >= 0 else 0.0
            r2 = grad[i - 1] if i - 1 >= 0 else 0.0
            r3 = grad[i]
            r4 = grad[i + 1] if i + 1 < gn else 0.0
            r5 = grad[i + 2] if i + 2 < gn else 0.0
            r6 = grad[i + 3] if i + 3 < gn else 0.0
            smooth_grad[i] = (r0 + r1 + r2 + r3 + r4 + r5 + r6) * seventh

        # argmin over smooth_grad[s_start:s_end]
        min_idx = s_start
        min_val = smooth_grad[s_start]
        for i in range(s_start + 1, s_end):
            if smooth_grad[i] < min_val:
                min_val = smooth_grad[i]
                min_idx = i

    # grad_threshold = -max(0.008, dynamic_range * 0.08)
    grad_threshold = dynamic_range * 0.08
    if grad_threshold < 0.008:
        grad_threshold = 0.008
    grad_threshold = -grad_threshold

    if min_val >= grad_threshold:
        return None

    # mid_score = (ss[min_idx] + ss[min(min_idx+1, eff_w-1)]) / 2
    cdef Py_ssize_t nxt = min_idx + 1
    if nxt > eff_w - 1:
        nxt = eff_w - 1
    mid_score = (ss[min_idx] + ss[nxt]) * 0.5

    # Search a narrow window around min_idx for the mid-score crossing.
    cdef Py_ssize_t j_lo = min_idx - 2
    cdef Py_ssize_t j_hi = min_idx + 4
    if j_lo < 0:
        j_lo = 0
    if j_hi > eff_w - 1:
        j_hi = eff_w - 1
    for j in range(j_lo, j_hi):
        s0 = ss[j]
        s1 = ss[j + 1] if j + 1 < eff_w else ss[eff_w - 1]
        if s0 >= mid_score and mid_score > s1 and s0 != s1:
            frac = (s0 - mid_score) / (s0 - s1)
            candidate = (<double>j + frac + 0.5) / <double>eff_w
            if candidate < 0.0:
                candidate = 0.0
            elif candidate > 1.0:
                candidate = 1.0
            return float(candidate)

    candidate = <double>(min_idx + 1) / <double>eff_w
    if candidate < 0.0:
        candidate = 0.0
    elif candidate > 1.0:
        candidate = 1.0
    return float(candidate)


# ───────────────────────────────────────────────
#  Per-column HSV means + hue mask (recognition._detect_bar_pct)
# ───────────────────────────────────────────────
#
# v3.1.4 round 6: ``_detect_bar_pct`` previously did four independent
# reductions over the sliced (H, eff_w) sample window:
#
#     mean_hue = hue.mean(axis=0)
#     mean_sat = sat.mean(axis=0)
#     mean_val = val.mean(axis=0)
#     hue_mask = ((hue >= h_min) & (hue <= h_max) & (sat >= s_floor))
#     hue_coverage = hue_mask.mean(axis=0)
#
# Each .mean(axis=0) walks the (H, eff_w) buffer separately, and the
# hue_mask computation walks it again to build a bool array. This kernel
# folds all five outputs into a single nogil pass.


cpdef tuple hsv_columns_and_hue_mask(object hsv_window,
                                      double h_min, double h_max,
                                      double s_floor):
    """One-pass per-column means + hue mask over a sliced HSV window.

    ``hsv_window`` is the ``(H, eff_w, 3) uint8`` HSV sample (the slice
    ``recognition._detect_bar_pct`` builds after horizontal padding).

    Returns ``(mean_hue, mean_sat, mean_val, hue_mask, hue_coverage)``:
      * ``mean_hue / mean_sat / mean_val`` — ``(eff_w,) float32`` column
        means matching the original ``ndarray.mean(axis=0)`` output.
      * ``hue_mask`` — ``(H, eff_w) bool`` per-pixel mask: ``True`` where
        ``h_min <= hue <= h_max`` and ``sat >= s_floor``.
      * ``hue_coverage`` — ``(eff_w,) float32`` per-column fraction of
        rows in ``hue_mask`` (matches ``hue_mask.mean(axis=0)``).
    """
    cdef const unsigned char[:, :, :] src = hsv_window
    cdef Py_ssize_t h = src.shape[0]
    cdef Py_ssize_t w = src.shape[1]
    cdef Py_ssize_t c = src.shape[2]
    cdef Py_ssize_t y, x
    cdef unsigned int hue_b, sat_b, val_b
    cdef bint in_mask

    if c < 3:
        raise ValueError('hsv_window must have a 3-channel third axis')

    sum_h_np = _np.zeros(w, dtype=_np.float64)
    sum_s_np = _np.zeros(w, dtype=_np.float64)
    sum_v_np = _np.zeros(w, dtype=_np.float64)
    mask_count_np = _np.zeros(w, dtype=_np.uint32)
    hue_mask_np = _np.zeros((h, w), dtype=_np.uint8)

    cdef double[::1] sh = sum_h_np
    cdef double[::1] ss = sum_s_np
    cdef double[::1] sv = sum_v_np
    cdef unsigned int[::1] mc = mask_count_np
    cdef unsigned char[:, ::1] mask_v = hue_mask_np

    if h == 0 or w == 0:
        empty_f32 = _np.zeros(w, dtype=_np.float32)
        return (empty_f32, empty_f32.copy(), empty_f32.copy(),
                hue_mask_np.astype(_np.bool_), empty_f32.copy())

    with nogil:
        for y in range(h):
            for x in range(w):
                hue_b = src[y, x, 0]
                sat_b = src[y, x, 1]
                val_b = src[y, x, 2]
                sh[x] += <double>hue_b
                ss[x] += <double>sat_b
                sv[x] += <double>val_b
                in_mask = (<double>hue_b >= h_min) and (<double>hue_b <= h_max) and (<double>sat_b >= s_floor)
                if in_mask:
                    mask_v[y, x] = 1
                    mc[x] += 1

    cdef double inv_h = 1.0 / <double>h
    mean_hue = (sum_h_np * inv_h).astype(_np.float32)
    mean_sat = (sum_s_np * inv_h).astype(_np.float32)
    mean_val = (sum_v_np * inv_h).astype(_np.float32)
    hue_coverage = mask_count_np.astype(_np.float32) * _np.float32(inv_h)
    return (mean_hue, mean_sat, mean_val, hue_mask_np.astype(_np.bool_), hue_coverage)


# ───────────────────────────────────────────────
#  5-wide moving-average smoothing (recognition._detect_bar_pct)
# ───────────────────────────────────────────────
#
# v3.1.4 round 7: ``_detect_bar_pct`` smooths ``col_score`` and
# ``hue_coverage`` with a 5-wide box kernel:
#
#     smooth_kernel = np.ones((5,), dtype=np.float32) / 5.0
#     smooth_score  = np.convolve(col_score, smooth_kernel, mode='same')
#     smooth_hue    = np.convolve(hue_coverage, smooth_kernel, mode='same')
#
# Both inputs are float32 1D arrays of length ~eff_w. The single-purpose
# cython kernel below avoids the kernel-array allocation + the generic
# FFT/direct path inside numpy and runs the smoothing in one nogil loop.
# It accumulates in double precision and casts back to float32, so the
# output matches numpy's float32 convolve to within float quantization.


cpdef object box_convolve5_same_f32(object arr):
    """5-wide moving-average smoothing with ``mode='same'`` edges.

    Mirrors ``np.convolve(arr, ones(5)/5, mode='same')`` for any
    contiguous ``float32`` 1D input. Returns a fresh ``float32`` ndarray
    of the same length. Accumulation is in double precision.
    """
    cdef const float[::1] src = arr
    cdef Py_ssize_t n = src.shape[0]
    cdef Py_ssize_t i
    cdef double fifth = 1.0 / 5.0

    out_np = _np.empty(n, dtype=_np.float32)
    cdef float[::1] out = out_np

    if n == 0:
        return out_np
    if n == 1:
        out[0] = <float>(src[0] * fifth)
        return out_np

    with nogil:
        if n == 2:
            out[0] = <float>((src[0] + src[1]) * fifth)
            out[1] = <float>((src[0] + src[1]) * fifth)
        elif n == 3:
            out[0] = <float>((src[0] + src[1] + src[2]) * fifth)
            out[1] = <float>((src[0] + src[1] + src[2]) * fifth)
            out[2] = <float>((src[0] + src[1] + src[2]) * fifth)
        elif n == 4:
            # full=[a0,a0+a1,a0+a1+a2,a0+a1+a2+a3,a1+a2+a3,a2+a3,a3]/5
            # mode='same' returns full[(5-1)//2 : (5-1)//2 + n] = full[2:6]
            out[0] = <float>((src[0] + src[1] + src[2]) * fifth)
            out[1] = <float>((src[0] + src[1] + src[2] + src[3]) * fifth)
            out[2] = <float>((src[1] + src[2] + src[3]) * fifth)
            out[3] = <float>((src[2] + src[3]) * fifth)
        else:
            # n >= 5: standard 5-wide with implicit-zero edges
            out[0] = <float>((src[0] + src[1] + src[2]) * fifth)
            out[1] = <float>((src[0] + src[1] + src[2] + src[3]) * fifth)
            for i in range(2, n - 2):
                out[i] = <float>((src[i - 2] + src[i - 1] + src[i]
                                   + src[i + 1] + src[i + 2]) * fifth)
            out[n - 2] = <float>((src[n - 4] + src[n - 3] + src[n - 2]
                                   + src[n - 1]) * fifth)
            out[n - 1] = <float>((src[n - 3] + src[n - 2] + src[n - 1]) * fifth)
    return out_np


# ───────────────────────────────────────────────
#  Rightmost-above-threshold scan (recognition._detect_bar_pct)
# ───────────────────────────────────────────────
#
# v3.1.4 round 8: ``_detect_bar_pct`` finds the last filled column via:
#
#     filled = smooth_score >= threshold
#     if filled.size >= 3:
#         filled[1:-1] = filled[1:-1] | (filled[:-2] & filled[2:])
#     if not np.any(filled):
#         threshold_pct = 0.0
#     else:
#         last_idx = int(np.max(np.where(filled)[0]))
#
# The "single-pixel-fill repair" turns ``[…, 1, 0, 1, …]`` into ``[…, 1, 1, 1, …]``.
# That operation can only fill GAPS — it never extends the rightmost True
# index, because doing so would require ``filled[i+1]`` to be True (and that
# would already place last_filled ≥ i+1). So we can find the rightmost
# True index directly without materialising the bool array or running the
# repair, and the threshold_pct is identical.
#
# This kernel collapses the bool allocation + `np.any` + `np.where`/`np.max`
# combo into a single nogil right-to-left scan.


cpdef Py_ssize_t find_last_above_threshold_f32(object smooth_score,
                                                double threshold):
    """Return rightmost index ``i`` with ``smooth_score[i] >= threshold``, else -1.

    Mirrors the result of:

        filled = smooth_score >= threshold
        # optional: filled[1:-1] |= filled[:-2] & filled[2:]
        np.max(np.where(filled)[0]) if filled.any() else -1

    The optional single-pixel-fill repair is **not needed** to find the
    rightmost index — it can only turn 0→1 in interior cells, never
    extending the rightmost 1. See ``_detect_bar_pct`` for context.
    """
    cdef const float[::1] src = smooth_score
    cdef Py_ssize_t n = src.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t last = -1
    if n == 0:
        return -1
    with nogil:
        for i in range(n - 1, -1, -1):
            if src[i] >= threshold:
                last = i
                break
    return last


# ───────────────────────────────────────────────
#  Combined col_score (recognition._detect_bar_pct)
# ───────────────────────────────────────────────
#
# v3.1.4 round 8: ``_detect_bar_pct`` builds the per-column score with
# eight chained numpy operations:
#
#     hue_delta = np.abs(mean_hue - fill_hue_ref)
#     hue_delta = np.minimum(hue_delta, 180.0 - hue_delta)
#     hue_bonus = 1.0 - np.clip(hue_delta / 24.0, 0.0, 1.0)
#     col_score = 0.78 * (mean_val / 255.0) + 0.22 * (mean_sat / 255.0)
#     col_score = np.where(hue_coverage >= 0.12, col_score,
#                          col_score * (0.72 + 0.18 * hue_bonus))
#
# Each of those creates a temp float32 array of length eff_w. Folding
# them into one nogil pass eliminates ~7 temporaries and walks the four
# input arrays once each.


cpdef object compute_bar_col_score_f32(object mean_hue,
                                        object mean_sat,
                                        object mean_val,
                                        object hue_coverage,
                                        double fill_hue_ref):
    """Fold _detect_bar_pct's per-column score computation into one pass.

    All four inputs must be contiguous ``float32`` 1D arrays of the same
    length. Returns a fresh ``float32`` ndarray of that length.
    """
    cdef const float[::1] mh = mean_hue
    cdef const float[::1] ms = mean_sat
    cdef const float[::1] mv = mean_val
    cdef const float[::1] hc = hue_coverage
    cdef Py_ssize_t n = mh.shape[0]
    cdef Py_ssize_t i
    cdef double delta, alt, bonus, base, hue_scale

    if (ms.shape[0] != n) or (mv.shape[0] != n) or (hc.shape[0] != n):
        raise ValueError(
            'mean_hue, mean_sat, mean_val, hue_coverage must share length')

    out_np = _np.empty(n, dtype=_np.float32)
    cdef float[::1] out = out_np

    with nogil:
        for i in range(n):
            # hue_delta = abs(mean_hue - fill_hue_ref), then wrap around 180
            delta = <double>mh[i] - fill_hue_ref
            if delta < 0.0:
                delta = -delta
            alt = 180.0 - delta
            if alt < delta:
                delta = alt
            # hue_bonus = 1 - clip(hue_delta / 24, 0, 1)
            bonus = delta * (1.0 / 24.0)
            if bonus > 1.0:
                bonus = 1.0
            elif bonus < 0.0:
                bonus = 0.0
            bonus = 1.0 - bonus
            # base = 0.78*mean_val/255 + 0.22*mean_sat/255
            base = (0.78 * <double>mv[i] + 0.22 * <double>ms[i]) * (1.0 / 255.0)
            # where hue_coverage < 0.12: scale base by (0.72 + 0.18 * bonus)
            if <double>hc[i] < 0.12:
                hue_scale = 0.72 + 0.18 * bonus
                base = base * hue_scale
            out[i] = <float>base
    return out_np


# ───────────────────────────────────────────────
#  Small-array percentile (recognition._detect_bar_pct)
# ───────────────────────────────────────────────
#
# v3.1.5 round 9: ``_detect_bar_pct`` runs three percentile calls per
# bar on prefix/suffix slices of length ~ref_width (~50 elements):
#
#     fill_hue_ref = np.percentile(mean_hue[:left_ref_width], 55)
#     left_ref     = np.percentile(smooth_score[:ref_width], 84)
#     right_ref    = np.percentile(smooth_score[-ref_width:], 62)
#
# np.percentile on a small float32 slice has ~5-7 µs of Python+dispatch
# overhead. The cython kernel below copies the slice into a private
# float64 buffer, sorts in place, and indexes the q-th rank with the
# same linear interpolation numpy uses by default.


cdef void _insertion_sort_double(double[::1] arr, Py_ssize_t n) nogil:
    """Plain in-place ascending insertion sort. Fast for the small (~50
    element) slices `_detect_bar_pct` feeds us; ~2.5k ops worst case."""
    cdef Py_ssize_t i, j
    cdef double tmp
    for i in range(1, n):
        tmp = arr[i]
        j = i - 1
        while j >= 0 and arr[j] > tmp:
            arr[j + 1] = arr[j]
            j -= 1
        arr[j + 1] = tmp


cpdef double percentile_slice_f32(object arr,
                                   Py_ssize_t start, Py_ssize_t stop,
                                   double q):
    """``np.percentile(arr[start:stop], q)`` with linear interpolation.

    ``arr`` is a contiguous ``float32`` 1D ndarray. ``q`` is in [0, 100].
    Returns 0.0 when the slice is empty (matches the ``_detect_bar_pct``
    guard at ``eff_w <= 4``).
    """
    cdef const float[::1] src = arr
    cdef Py_ssize_t n = src.shape[0]
    cdef Py_ssize_t lo = start
    cdef Py_ssize_t hi = stop
    cdef Py_ssize_t k
    cdef Py_ssize_t i

    if lo < 0:
        lo = 0
    if hi > n:
        hi = n
    if hi <= lo:
        return 0.0
    k = hi - lo
    if k == 1:
        return <double>src[lo]

    buf_np = _np.empty(k, dtype=_np.float64)
    cdef double[::1] buf = buf_np

    with nogil:
        for i in range(k):
            buf[i] = <double>src[lo + i]
        _insertion_sort_double(buf, k)

    # numpy default ``linear`` interpolation:
    #   rank = q/100 * (k - 1)
    #   low = floor(rank); frac = rank - low
    #   result = buf[low] + frac * (buf[low+1] - buf[low])
    cdef double rank = q * 0.01 * <double>(k - 1)
    if rank <= 0.0:
        return buf[0]
    cdef Py_ssize_t low = <Py_ssize_t>rank
    if low >= k - 1:
        return buf[k - 1]
    cdef double frac = rank - <double>low
    return buf[low] + frac * (buf[low + 1] - buf[low])
