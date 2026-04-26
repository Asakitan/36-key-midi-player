# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Cython helpers for the LinkStart canvas fallback renderer."""

from libc.math cimport cos, sin


cdef inline double _clamp(double value, double lo, double hi) noexcept:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


cdef inline int _lerp_int(double a, double b, double t) noexcept:
    return <int>(a + (b - a) * t)


def build_tunnel_items(object particles, double cam_z, tuple bg_rgb,
                       double fade, double t, double cx, double cy,
                       double focal, int sw, int sh, double streak_h):
    """Project particles into Canvas line items sorted far-to-near."""
    cdef double bgr = <double>bg_rgb[0]
    cdef double bgg = <double>bg_rgb[1]
    cdef double bgb = <double>bg_rgb[2]
    cdef double rot = t * 0.06
    cdef double cos_rot = cos(rot)
    cdef double sin_rot = sin(rot)
    cdef double margin = 800.0
    cdef double d, z_near, z_far, z_near_c, z_far_c
    cdef double s_near, s_far, r, c0, s0, cos_t, sin_t
    cdef double x_near, y_near, x_far, y_far
    cdef double wmult, alpha, depth_fog, bright, flkr, shimmer, sort_z
    cdef double desat
    cdef int cr, cg, cb, gray, mr, mg, mb, width
    cdef object p
    cdef tuple rgb
    cdef list items = []

    for p in particles:
        d = <double>p['d']
        z_near = d - cam_z
        z_far = (d + streak_h) - cam_z

        if z_far <= 2.0 or z_near > 5000.0 or z_near < 1.0:
            continue

        z_near_c = z_near if z_near > 5.0 else 5.0
        z_far_c = z_far if z_far > 5.0 else 5.0
        s_near = focal / z_near_c
        s_far = focal / z_far_c

        r = <double>p['r']
        c0 = <double>p['cos']
        s0 = <double>p['sin']
        cos_t = c0 * cos_rot - s0 * sin_rot
        sin_t = c0 * sin_rot + s0 * cos_rot

        x_near = cx + r * cos_t * s_near
        y_near = cy + r * sin_t * s_near
        x_far = cx + r * cos_t * s_far
        y_far = cy + r * sin_t * s_far

        if (x_near < -margin and x_far < -margin) or \
           (x_near > sw + margin and x_far > sw + margin) or \
           (y_near < -margin and y_far < -margin) or \
           (y_near > sh + margin and y_far > sh + margin):
            continue

        wmult = <double>p.get('width_mult', 1.0)
        alpha = fade
        depth_fog = 0.0
        if z_near > 150.0:
            depth_fog = (z_near - 150.0) / 2200.0
            if depth_fog > 0.95:
                depth_fog = 0.95

        bright = <double>p.get('brightness', 1.0)
        flkr = <double>p.get('flicker_freq', 5.0)
        shimmer = 0.85 + 0.15 * sin(t * flkr + d * 0.005)
        alpha *= bright * shimmer
        if alpha < 0.08:
            continue

        sort_z = z_near if z_near > 5.0 else 5.0
        rgb = <tuple>p['rgb']
        cr = <int>rgb[0]
        cg = <int>rgb[1]
        cb = <int>rgb[2]

        if depth_fog > 0.01:
            cr = _lerp_int(cr, bgr, depth_fog)
            cg = _lerp_int(cg, bgg, depth_fog)
            cb = _lerp_int(cb, bgb, depth_fog)
            gray = (cr + cg + cb) // 3
            desat = depth_fog * 0.5
            cr = _lerp_int(cr, gray, desat)
            cg = _lerp_int(cg, gray, desat)
            cb = _lerp_int(cb, gray, desat)

        if alpha < 0.95:
            mr = _lerp_int(bgr, cr, alpha)
            mg = _lerp_int(bgg, cg, alpha)
            mb = _lerp_int(bgb, cb, alpha)
        else:
            mr = cr
            mg = cg
            mb = cb

        mr = <int>_clamp(mr, 0.0, 255.0)
        mg = <int>_clamp(mg, 0.0, 255.0)
        mb = <int>_clamp(mb, 0.0, 255.0)
        width = <int>(3.5 * s_near * wmult)
        if width < 1:
            width = 1
        elif width > 40:
            width = 40

        items.append((-sort_z, x_far, y_far, x_near, y_near,
                      '#%02x%02x%02x' % (mr, mg, mb), width))

    items.sort()
    return items
