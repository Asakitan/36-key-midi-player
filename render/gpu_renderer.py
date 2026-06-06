"""gpu_renderer.py — Shared moderngl-backed GPU acceleration for overlays.

Goal: offload the expensive per-frame CPU pixel ops to the GPU while keeping
the existing ULW + PIL pipeline intact.  Each render-lane thread lazily
creates its own standalone moderngl context on first use (WGL contexts are
thread-affine).  FBOs and shader programs are cached per-thread.

Public entry points (all fall back to CPU if the GPU context fails):
    gpu_available()                              → bool
    gaussian_blur_rgba(img, sigma)               → PIL.Image
    render_shell_rgba(params)                    → PIL.Image
    premultiply_bgra_bytes(rgba_np)              → bytes   (BGRA, premult'd)

Threading: Each thread that calls these functions gets its own GL context
lazily.  Safe to call from any render-lane thread or the Tk main thread.

"""

from __future__ import annotations

import os
import threading
from typing import Optional, Tuple, Dict, Any

import numpy as np
from PIL import Image, ImageFilter

from utils.perf_probe import phase as _phase_trace


_DISABLED = os.environ.get('SAO_GPU_DISABLE', '') == '1'
_PREMULT_DISABLED = os.environ.get('SAO_GPU_PREMULT_DISABLE', '') == '1'

# ── Per-thread GL state ──────────────────────────────────────────
# Each render-lane thread (and the Tk main thread) gets its own
# standalone moderngl context.  WGL contexts are thread-affine, so
# this is the only safe way to share GPU acceleration across lanes.

_global_failed = False   # set once if the *first* init attempt fails
_global_lock = threading.Lock()

# v2.2.23: Single device-render lock.
# WGL standalone contexts are per-thread, but they all share one underlying
# GPU device. When 3-4 worker threads concurrently issue
# render+glReadPixels() the driver serializes them with poor scheduling and
# tail-latency cascades (skillfx compose wall: 80-180 ms with cpu_p95
# 15-30 ms — almost all in GPU readback contention). Serialize at the
# Python level so each readback finishes cleanly before the next starts;
# total wall stays the same in the steady state but the worst-case
# pipeline collapse goes away.
_render_lock = threading.Lock()

# v2.3.x: cross-driver WGL serialization.
# `_render_lock` above only protects worker threads from each other. The
# main-thread GLFW pump (gpu_overlay_window.GlfwPump._tick) does its own
# poll_events / make_context_current / swap_buffers under a different lock
# (`_wgl_serialize_lock`, an RLock). When a worker's premultiply / blur /
# shell render runs concurrently with poll_events on the main thread,
# both sides release the GIL inside ctypes and the Windows WGL driver
# corrupts the main thread's PyThreadState restoration on
# Py_END_ALLOW_THREADS — manifests as a hard native abort during the
# next user-input glfw callback (popup click), with no Python traceback
# and no faulthandler output.
#
# Acquire the WGL serialize RLock around every block of GL work in this
# module so worker GL ops and the main-thread pump cannot overlap on
# the driver. Lazy-imported to avoid an import cycle at startup.
_wgl_serialize_lock_ref: Any = None


def _get_wgl_serialize_lock() -> Any:
    global _wgl_serialize_lock_ref
    if _wgl_serialize_lock_ref is not None:
        return _wgl_serialize_lock_ref
    try:
        from render.gpu_overlay_window import get_wgl_serialize_lock as _g
        _wgl_serialize_lock_ref = _g()
    except Exception:
        # Fall back to a private RLock so the `with` statement still works.
        _wgl_serialize_lock_ref = threading.RLock()
    return _wgl_serialize_lock_ref


_tls = threading.local()  # per-thread: .ctx, .blur_prog, .blur_quad,
                           #              .shell_prog, .prem_prog,
                           #              .fbo_cache, .failed


# ---------------------------------------------------------------------------
# Context lifecycle (per-thread)
# ---------------------------------------------------------------------------

def _try_init() -> bool:
    """Ensure the current thread has its own moderngl context.

    Returns True when the thread-local context is ready.
    """
    global _global_failed
    if _DISABLED or _global_failed:
        return False

    ctx = getattr(_tls, 'ctx', None)
    if ctx is not None:
        return True
    if getattr(_tls, 'failed', False):
        return False

    with _global_lock:
        # Recheck inside lock (another thread might have set _global_failed)
        if _global_failed:
            return False
        try:
            _phase_trace('gpu.init.begin', threading.current_thread().name)
            import moderngl  # type: ignore
            if os.name == 'nt':
                ctx = moderngl.create_standalone_context(require=330)
            else:
                ctx = moderngl.create_standalone_context(
                    require=330, backend='egl',
                )
        except Exception as exc:
            try:
                print(f'[GPU] init failed on thread '
                      f'{threading.current_thread().name}, '
                      f'falling back to CPU: {exc}')
            except Exception:
                pass
            _phase_trace('gpu.init.fail', f'{threading.current_thread().name}: {exc}')
            _global_failed = True
            _tls.failed = True
            return False

    # Build shader programs for this thread's context
    _tls.ctx = ctx
    _tls.fbo_cache = {}
    try:
        _build_programs_tls()
    except Exception as exc:
        try:
            print(f'[GPU] program build failed: {exc}')
        except Exception:
            pass
        _tls.ctx = None
        _tls.failed = True
        return False
    _phase_trace('gpu.init.ok', threading.current_thread().name)
    return True


def gpu_available() -> bool:
    return _try_init()


# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VS_FULLSCREEN = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_FS_BLUR = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_dir;        // pixel step, e.g. (1/w, 0) or (0, 1/h)
uniform float u_sigma;
uniform int u_radius;
in vec2 v_uv;
out vec4 f_color;
void main() {
    float two_sigma2 = 2.0 * u_sigma * u_sigma;
    vec4 sum = vec4(0.0);
    float wsum = 0.0;
    for (int i = -64; i <= 64; ++i) {
        if (abs(i) > u_radius) continue;
        float w = exp(-float(i * i) / two_sigma2);
        sum += w * texture(u_tex, v_uv + float(i) * u_dir);
        wsum += w;
    }
    f_color = sum / wsum;
}
"""

_FS_SHELL = """
#version 330
uniform vec2 u_size;            // (w, h) pixels
uniform vec2 u_body_min;        // rect min
uniform vec2 u_body_max;        // rect max
uniform float u_radius;
uniform vec4 u_color_a;         // top
uniform vec4 u_color_b;         // bottom
uniform vec4 u_edge;            // outer border
uniform vec4 u_inner;           // inner highlight 1px
uniform vec4 u_scan;            // scanline colour
uniform float u_scan_period;
uniform vec4 u_shadow_color;
uniform float u_shadow_dx;
uniform float u_shadow_dy;
uniform float u_shadow_sigma;
uniform float u_shadow_radius;

in vec2 v_uv;
out vec4 f_color;

// Signed distance to rounded rect
float sdf_round_rect(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + vec2(r);
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    vec2 px = v_uv * u_size;
    vec2 half_size = (u_body_max - u_body_min) * 0.5;
    vec2 center = (u_body_max + u_body_min) * 0.5;

    // Rounded-rect body SDF
    float d = sdf_round_rect(px - center, half_size, u_radius);

    // Vertical gradient between body top and bottom (clamped)
    float ty = clamp((px.y - u_body_min.y) / (u_body_max.y - u_body_min.y),
                     0.0, 1.0);
    vec4 grad = mix(u_color_a, u_color_b, ty);

    // Body alpha with 1px AA
    float body_a = 1.0 - smoothstep(-0.5, 0.5, d);

    // Scanlines (every u_scan_period px, 1px wide)
    if (u_scan_period > 0.5) {
        float row = mod(px.y - u_body_min.y, u_scan_period);
        if (row < 1.0) {
            grad.rgb = mix(grad.rgb, u_scan.rgb, u_scan.a);
        }
    }

    vec4 body = vec4(grad.rgb, grad.a * body_a);

    // Outer border (1px band around the rounded edge)
    float edge_band = 1.0 - smoothstep(0.5, 1.5, abs(d));
    vec4 edge = vec4(u_edge.rgb, u_edge.a * edge_band);

    // Inner highlight (1px inside at d=-1)
    float inner_band = 1.0 - smoothstep(0.5, 1.5, abs(d + 1.0));
    vec4 inner = vec4(u_inner.rgb, u_inner.a * inner_band * body_a);

    // Soft drop shadow: approximate via analytic SDF falloff.
    // Offset sample point, compute SDF, map positive distance to falloff.
    vec2 shadow_p = px - vec2(u_shadow_dx, u_shadow_dy) - center;
    float sd = sdf_round_rect(shadow_p, half_size, u_shadow_radius);
    float sh_a = u_shadow_color.a *
                 exp(-max(sd, 0.0) * max(sd, 0.0) /
                     (2.0 * u_shadow_sigma * u_shadow_sigma));
    // Only show shadow OUTSIDE the body (don't bleed through the body)
    sh_a *= (1.0 - body_a);
    vec4 shadow = vec4(u_shadow_color.rgb, sh_a);

    // Composite: shadow → body → inner highlight → edge
    vec4 c = shadow;
    c.rgb = mix(c.rgb, body.rgb, body.a);
    c.a = body.a + c.a * (1.0 - body.a);
    c.rgb = mix(c.rgb, inner.rgb, inner.a);
    c.a = inner.a + c.a * (1.0 - inner.a);
    c.rgb = mix(c.rgb, edge.rgb, edge.a);
    c.a = edge.a + c.a * (1.0 - edge.a);

    f_color = c;
}
"""

_FS_PREMULT = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    vec4 c = texture(u_tex, v_uv);
    // Output BGRA premultiplied; packed in vec4 rgba where R=B, G=G, B=R
    f_color = vec4(c.b * c.a, c.g * c.a, c.r * c.a, c.a);
}
"""


def _build_programs_tls() -> None:
    """Build shader programs for the current thread's GL context."""
    ctx = _tls.ctx
    assert ctx is not None
    quad = np.array([-1, -1,  1, -1, -1,  1,
                      1, -1,  1,  1, -1,  1], dtype='f4')
    vbo = ctx.buffer(quad.tobytes())

    _tls.blur_prog = ctx.program(
        vertex_shader=_VS_FULLSCREEN, fragment_shader=_FS_BLUR,
    )
    _tls.blur_quad = ctx.vertex_array(_tls.blur_prog, [(vbo, '2f', 'in_pos')])

    _tls.shell_prog = ctx.program(
        vertex_shader=_VS_FULLSCREEN, fragment_shader=_FS_SHELL,
    )
    _tls.shell_quad = ctx.vertex_array(
        _tls.shell_prog, [(vbo, '2f', 'in_pos')],
    )

    _tls.prem_prog = ctx.program(
        vertex_shader=_VS_FULLSCREEN, fragment_shader=_FS_PREMULT,
    )
    _tls.prem_quad = ctx.vertex_array(
        _tls.prem_prog, [(vbo, '2f', 'in_pos')],
    )


def _get_fbo(w: int, h: int, tag: str = 'rgba'):
    cache = _tls.fbo_cache
    key = (w, h, tag)
    fbo = cache.get(key)
    if fbo is not None:
        return fbo
    ctx = _tls.ctx
    tex = ctx.texture((w, h), 4, dtype='f1')
    tex.filter = (0x2600, 0x2600)  # GL_NEAREST
    fbo = ctx.framebuffer(color_attachments=[tex])
    cache[key] = fbo
    return fbo


def _to_rgba_np(img) -> np.ndarray:
    if isinstance(img, np.ndarray):
        arr = img
    elif isinstance(img, Image.Image):
        arr = np.asarray(img.convert('RGBA'))
    else:
        raise TypeError(f'unsupported image type: {type(img)}')
    if arr.dtype != np.uint8 or arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f'expected uint8 RGBA ndarray, got {arr.shape} {arr.dtype}')
    return np.ascontiguousarray(arr)


# ---------------------------------------------------------------------------
# Gaussian blur (two-pass separable)
# ---------------------------------------------------------------------------

def gaussian_blur_rgba(img, sigma: float) -> Image.Image:
    """GPU-accelerated gaussian blur. Returns a PIL RGBA image.

    Falls back to PIL.ImageFilter.GaussianBlur on any failure.
    """
    pil_in = img if isinstance(img, Image.Image) else None
    if sigma <= 0.05:
        return pil_in.copy() if pil_in is not None else Image.fromarray(
            _to_rgba_np(img), 'RGBA',
        )
    if not _try_init():
        if pil_in is None:
            pil_in = Image.fromarray(_to_rgba_np(img), 'RGBA')
        return pil_in.filter(ImageFilter.GaussianBlur(sigma))

    try:
        ctx = _tls.ctx
        blur_prog = _tls.blur_prog
        blur_quad = _tls.blur_quad
        arr = _to_rgba_np(img)
        h, w, _ = arr.shape
        radius = min(64, max(1, int(round(sigma * 3.0))))

        # Re-bind our context in case another standalone GL context (e.g.
        # skillfx Burst overlay) was made current on this thread.
        with _get_wgl_serialize_lock(), _render_lock, ctx:
            src_tex = ctx.texture((w, h), 4, arr.tobytes(), dtype='f1')
            src_tex.filter = (0x2601, 0x2601)  # GL_LINEAR
            src_tex.repeat_x = False
            src_tex.repeat_y = False

            fbo_h = _get_fbo(w, h, 'blurH')
            fbo_v = _get_fbo(w, h, 'blurV')

            blur_prog['u_sigma'].value = float(sigma)
            blur_prog['u_radius'].value = int(radius)
            blur_prog['u_tex'].value = 0

            # Horizontal pass
            fbo_h.use()
            ctx.clear(0.0, 0.0, 0.0, 0.0)
            src_tex.use(0)
            blur_prog['u_dir'].value = (1.0 / w, 0.0)
            blur_quad.render()

            # Vertical pass
            fbo_v.use()
            ctx.clear(0.0, 0.0, 0.0, 0.0)
            fbo_h.color_attachments[0].use(0)
            blur_prog['u_dir'].value = (0.0, 1.0 / h)
            blur_quad.render()

            data = fbo_v.read(components=4, alignment=1)
            out = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
            out = np.flipud(out).copy()

            src_tex.release()
        return Image.fromarray(out, 'RGBA')
    except Exception as exc:
        try:
            print(f'[GPU] blur failed, fallback: {exc}')
        except Exception:
            pass
        if pil_in is None:
            pil_in = Image.fromarray(_to_rgba_np(img), 'RGBA')
        return pil_in.filter(ImageFilter.GaussianBlur(sigma))


# ---------------------------------------------------------------------------
# One-pass shell renderer (shadow + body + gradient + scanlines + borders)
# ---------------------------------------------------------------------------

def render_shell_rgba(
    w: int, h: int,
    body_pad: int,
    radius: float,
    color_a: Tuple[int, int, int, int],
    color_b: Tuple[int, int, int, int],
    edge: Tuple[int, int, int, int],
    inner: Tuple[int, int, int, int],
    scan: Tuple[int, int, int, int] = (0, 0, 0, 0),
    scan_period: float = 0.0,
    shadow: Tuple[int, int, int, int] = (0, 0, 0, 0),
    shadow_dx: float = 0.0, shadow_dy: float = 0.0,
    shadow_sigma: float = 0.0, shadow_radius: Optional[float] = None,
) -> Optional[Image.Image]:
    """Render the static shell in a single shader pass.

    Returns a PIL RGBA image. Returns None (caller should fall back to CPU
    path) if the GPU context is unavailable.
    """
    if not _try_init():
        return None
    try:
        ctx = _tls.ctx
        with _get_wgl_serialize_lock(), _render_lock, ctx:
            fbo = _get_fbo(w, h, 'shell')
            fbo.use()
            ctx.viewport = (0, 0, w, h)
            ctx.clear(0.0, 0.0, 0.0, 0.0)
            p = _tls.shell_prog
            p['u_size'].value = (float(w), float(h))
            p['u_body_min'].value = (float(body_pad), float(body_pad))
            p['u_body_max'].value = (float(w - body_pad), float(h - body_pad))
            p['u_radius'].value = float(radius)
            p['u_color_a'].value = tuple(c / 255.0 for c in color_a)
            p['u_color_b'].value = tuple(c / 255.0 for c in color_b)
            p['u_edge'].value = tuple(c / 255.0 for c in edge)
            p['u_inner'].value = tuple(c / 255.0 for c in inner)
            p['u_scan'].value = tuple(c / 255.0 for c in scan)
            p['u_scan_period'].value = float(scan_period)
            p['u_shadow_color'].value = tuple(c / 255.0 for c in shadow)
            p['u_shadow_dx'].value = float(shadow_dx)
            p['u_shadow_dy'].value = float(shadow_dy)
            p['u_shadow_sigma'].value = float(shadow_sigma) if shadow_sigma > 0 else 1.0
            p['u_shadow_radius'].value = float(
                shadow_radius if shadow_radius is not None else radius,
            )
            _tls.shell_quad.render()

            data = fbo.read(components=4, alignment=1)
            arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
            arr = np.flipud(arr).copy()
        return Image.fromarray(arr, 'RGBA')
    except Exception as exc:
        try:
            print(f'[GPU] shell render failed, fallback: {exc}')
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Premultiply + BGRA swizzle for UpdateLayeredWindow
# ---------------------------------------------------------------------------

def premultiply_bgra_bytes(rgba: np.ndarray) -> Optional[bytes]:
    """GPU-accelerated RGBA → premultiplied BGRA conversion for ULW upload.

    Returns the raw byte buffer (top-down) suitable for the DIB section, or
    None if the GPU path is unavailable. Only worth calling for larger
    surfaces; for ~260×220 panels numpy is already fast enough.
    """
    if _PREMULT_DISABLED:
        _phase_trace('gpu.premult.disabled')
        return None
    if not _try_init():
        return None
    try:
        ctx = _tls.ctx
        # Re-bind this context current for the calling thread. If another
        # standalone ModernGL context lives on the same thread (e.g. skillfx
        # Burst overlay), the most recently created one is current on Windows
        # WGL; without this guard its FBO operations would silently clobber
        # ours (and vice-versa), producing garbage or flipped output.
        arr = _to_rgba_np(rgba)
        h, w, _ = arr.shape
        _phase_trace('gpu.premult.lock.wait', f'{w}x{h}')
        with _get_wgl_serialize_lock(), _render_lock:
            _phase_trace('gpu.premult.lock.acquired', f'{w}x{h}')
            with ctx:
                src_tex = ctx.texture((w, h), 4, arr.tobytes(), dtype='f1')
                src_tex.filter = (0x2600, 0x2600)
                fbo = _get_fbo(w, h, 'prem')
                fbo.use()
                ctx.viewport = (0, 0, w, h)
                ctx.clear(0.0, 0.0, 0.0, 0.0)
                src_tex.use(0)
                _tls.prem_prog['u_tex'].value = 0
                _tls.prem_quad.render()
                _phase_trace('gpu.premult.read.begin', f'{w}x{h}')
                data = fbo.read(components=4, alignment=1)
                _phase_trace('gpu.premult.read.end', f'{w}x{h}')
                # UpdateLayeredWindow uses a top-down DIB (negative biHeight), and
                # the CPU premultiply path already writes rows in top-down order.
                # Do not flip here or every async ULW overlay ends up mirrored.
                out = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4).copy()
                src_tex.release()
        _phase_trace('gpu.premult.end', f'{w}x{h}')
        return out.tobytes()
    except Exception as exc:
        try:
            print(f'[GPU] premult failed, fallback: {exc}')
        except Exception:
            pass
        return None
