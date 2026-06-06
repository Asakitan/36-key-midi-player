# -*- coding: utf-8 -*-
"""SAOLinkStart (split from sao_theme.py — verbatim)."""
import tkinter as tk
import math
import time
import random
import os
import sys
from typing import Optional, Callable
from PIL import Image, ImageDraw, ImageFilter, ImageTk, ImageFont
import numpy as np
from config import FONTS_DIR
try:
    from overlay_scheduler import _WinTimerResolution
except Exception:
    _WinTimerResolution = None
try:
    import moderngl
    _HAS_MODERNGL = True
except ImportError:
    _HAS_MODERNGL = False
try:
    from _sao_cy_uihelpers import ease_out_cubic as _cy_ease_out_cubic
    from _sao_cy_uihelpers import lerp_clamped as _cy_lerp_clamped
except Exception:
    _cy_ease_out_cubic = None
    _cy_lerp_clamped = None
# ── 动画工具 (与 sao_theme.py 同步, 内联以保持本模块自包含) ──
def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3

def ease_in(t: float) -> float:
    return t ** 3

def ease_in_out(t: float) -> float:
    return 3 * t ** 2 - 2 * t ** 3

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def hex_to_rgb(h: str):
    h = h.lstrip('#')
    if len(h) == 8:
        h = h[:6]
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f'#{r:02x}{g:02x}{b:02x}'

def _strip_alpha(c: str) -> str:
    c = c.strip()
    if c.startswith('#') and len(c) == 9:
        return c[:7]
    return c

def lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = hex_to_rgb(_strip_alpha(c1))
    r2, g2, b2 = hex_to_rgb(_strip_alpha(c2))
    return rgb_to_hex(int(lerp(r1, r2, t)), int(lerp(g1, g2, t)), int(lerp(b1, b2, t)))

# ──────────────────── LINK START 动画 ────────────────────
class SAOLinkStart:
    """
    LINK START 入场动画 — 忠实还原 SAO-UI 粒子隧道飞行效果

    核心原理 (参考 Cad-noob/SAO-UI):
      ~250 个细长条粒子 (3px × 300px) 静止排列在圆柱隧道中,
      摄像机以 cubic-bezier(0.8, 0.1, 0.9, 0.8) 加速飞过隧道,
      透视投影使粒子从中心向四周急速飞散, 产生超时空隧道飞行感.

    完整动画序列 (总计~9.0s):
      Phase 1 (0.0~3.5s)  白闪→彩色隧道 — 摄像机飞过 250 根彩色粒子
      Phase 2 (3.5~5.5s)  灰底文字 — "Welcome to / 咲 MIDI PLAYER!" 飞入飞出
      Phase 3 (5.5~7.5s)  蓝色隧道 — 250 根蓝色粒子, 渐亮
      Phase 4 (7.5~9.0s)  全屏蓝白闪光 → 渐隐透出
    """

    # ──── SAO-UI 8色循环 (与原版一致) ────
    _COLORS_8 = [
        '#ff0000',    # red
        '#ffff00',    # yellow
        '#228b22',    # forestgreen
        '#222222',    # black (near-black for visibility on white)
        '#808080',    # gray
        '#00bfff',    # deepskyblue
        '#9370db',    # mediumpurple
        '#ff1493',    # deeppink
    ]

    # ──── 蓝色阶段 8色循环 ────
    _BLUES_8 = [
        '#0044cc',    # 中蓝
        '#0088ff',    # 亮蓝
        '#00ccff',    # 天蓝
        '#002288',    # 暗蓝
        '#88eeff',    # 浅青
        '#0066dd',    # 钴蓝
        '#aaeeff',    # 淡青
        '#ffffff',    # 白
    ]

    # ──── 隧道与透视常量 (匹配 SAO-UI CSS) ────
    _FOCAL = 720            # 更广一点的视角, 提升中心收束与镜头拉伸感
    _TUNNEL_R_MIN = 10      # 隧道更收束
    _TUNNEL_R_MAX = 38      # 隧道半径略收紧
    _STREAK_H = 420         # 更长的柱体拖尾, 提升速度感
    _NUM_PARTICLES = 300    # 粒子数量 (增加密度提升质感)
    _NUM_PARTICLES_CANVAS = 150  # Canvas 回退时使用较少粒子 (性能)

    # ──── 摄像机动画参数 (匹配 SAO-UI) ────
    _CAM_Z_START = -1200    # 摄像机起始 z (= CSS translateZ(-1200px))
    _CAM_Z_END = 1500       # 摄像机终止 z (= CSS translateZ(1500px))
    _CAM_EXIT_EXTRA = 900    # 结束段继续前推，让 STREAK_H 尾巴也飞出屏幕
    _CAM_DURATION = 3.5     # 单次飞行时长 = SAO-UI animation: 3.5s
    _STARTUP_PRELUDE = 0.72 # 启动扫描/光阀独占时长, 结束后再进入 P1

    # ──── 时间线 ────
    _DURATION = 10.0

    _P1_END = 3.5           # 彩色隧道结束
    _P2_START = 3.5         # 文字开始
    _P2_END = 5.5           # 文字结束
    _P3_START = 5.2         # 蓝色隧道开始 (与文字有少许重叠)
    _P3_END = 7.5           # 蓝色隧道结束
    _P4_START = 7.3         # 白闪开始
    _P4_HOLD_END = 9.2      # SYSTEM >> CONNECTED 保持可读更久
    _P4_FADE_END = 9.9      # P4 文字淡出结束

    # ════════════════════════════════════════════════════════
    #  GPU 后处理着色器源码 (运动模糊 + 色差)
    # ════════════════════════════════════════════════════════
    _POST_VERT = '''
#version 330
void main() {
    // Fullscreen triangle via gl_VertexID (no VBO needed)
    vec2 pos[3] = vec2[3](
        vec2(-1.0, -1.0),
        vec2( 3.0, -1.0),
        vec2(-1.0,  3.0)
    );
    gl_Position = vec4(pos[gl_VertexID], 0.0, 1.0);
}
'''
    _COPY_FRAG = '''
#version 330
uniform sampler2D u_tex;
uniform float u_alpha;
out vec4 fragColor;
void main() {
    ivec2 sz = textureSize(u_tex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(sz);
    vec3 rgb = texture(u_tex, uv).rgb;
    float alpha = clamp(u_alpha, 0.0, 1.0);
    fragColor = vec4(rgb * alpha, alpha);
}
'''
    _BG_FRAG = '''
#version 330
uniform float u_time;
uniform float u_energy;
uniform float u_flash;
uniform float u_startburst;
uniform float u_startwave;
uniform float u_aspect;
uniform vec2  u_resolution;
uniform vec3  u_bg_color;
uniform vec3  u_tint;
out vec4 fragColor;

float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    vec2 centered = uv - 0.5;
    vec2 lens = vec2(centered.x * u_aspect, centered.y);
    float radius = length(lens);
    float angle = atan(lens.y, lens.x);
    float energy = clamp(u_energy, 0.0, 1.0);
    float flash = clamp(u_flash, 0.0, 1.0);
    float startburst = clamp(u_startburst, 0.0, 1.0);
    float startwave = clamp(u_startwave, 0.0, 1.0);

    float apertureOpen = pow(smoothstep(0.02, 0.42, startwave), 0.78);
    float apertureFade = 1.0 - smoothstep(0.56, 0.96, startwave);
    float slitX = mix(0.10, 1.25, apertureOpen);
    float slitY = mix(0.008, 0.56, apertureOpen);
    float ellipse = (lens.x / max(slitX, 0.001));
    ellipse = ellipse * ellipse + (centered.y / max(slitY, 0.001)) * (centered.y / max(slitY, 0.001));
    float apertureMask = 1.0 - smoothstep(0.90, 1.10, ellipse);
    float shutterMask = (1.0 - apertureMask) * apertureFade;
    float valveLine = exp(-abs(centered.y) * mix(300.0, 56.0, apertureOpen));
    valveLine *= 1.0 - smoothstep(slitX * 0.10, slitX * 0.92, abs(lens.x));
    valveLine *= (0.08 + startburst * 0.56 + (1.0 - apertureFade) * 0.10);

    float spokeCount = mix(16.0, 28.0, energy);
    float angular = (angle / 6.2831853 + 0.5) * spokeCount;
    float cell = floor(angular);
    float ray = abs(fract(angular + u_time * (0.18 + energy * 0.42)) - 0.5);
    float jitter = hash11(cell + floor(u_time * 18.0)) * 0.22;
    float rayMask = smoothstep(0.22 + jitter, 0.03 + radius * 0.08, ray);
    float rayFade = smoothstep(1.08, 0.08, radius) * pow(max(0.0, 1.0 - radius), 1.65);
    float rays = rayMask * rayFade * (0.08 + energy * 0.22);

    float core = smoothstep(0.16, 0.0, radius);
    float halo = smoothstep(0.48, 0.05, radius);
    float flare = exp(-abs(centered.y) * (96.0 - energy * 24.0));
    flare *= smoothstep(0.72, 0.02, abs(centered.x));
    flare *= (0.05 + flash * 0.12 + energy * 0.08);

    float contract = smoothstep(0.0, 0.18, startwave) * (1.0 - smoothstep(0.18, 0.36, startwave));
    float explode = smoothstep(0.18, 0.44, startwave);
    float scan = smoothstep(0.38, 0.78, startwave) * (1.0 - smoothstep(0.78, 1.0, startwave));

    float waveRadius = mix(0.010, 0.64, explode);
    float waveWidth = mix(0.018, 0.070, startburst);
    float shock = smoothstep(waveWidth, 0.0, abs(radius - waveRadius));
    shock *= (1.0 - smoothstep(0.70, 1.0, startwave));
    float startupCore = smoothstep(0.24 - contract * 0.08, 0.0, radius) * startburst;
    float startupFlare = exp(-abs(centered.y) * 128.0) * smoothstep(0.82, 0.0, abs(centered.x));
    startupFlare *= (0.10 + startburst * 0.42);
    float scanRing = smoothstep(0.015, 0.0, abs(radius - mix(0.06, 0.72, scan)));
    scanRing *= scan * 0.65;
    float ripple = smoothstep(0.022, 0.0, abs(radius - mix(0.05, 0.56, explode)));
    ripple *= (1.0 - smoothstep(0.52, 0.92, startwave)) * (0.18 + startburst * 0.34);

    vec3 col = u_bg_color;
    vec3 shutterCol = mix(vec3(0.005, 0.010, 0.018), u_bg_color * 0.16, apertureOpen * 0.34);
    col += u_tint * (core * (0.08 + flash * 0.12));
    col += u_tint * (halo * 0.08 + rays + flare);
    col += vec3(1.0, 0.94, 0.82) * startupCore * (0.22 + startburst * 0.38);
    col += u_tint * shock * (0.16 + startburst * 0.34);
    col += vec3(0.92, 0.98, 1.0) * startupFlare;
    col += vec3(0.70, 0.95, 1.0) * scanRing;
    col += u_tint * ripple;
    col += vec3(1.0, 0.97, 0.88) * valveLine;
    col = mix(shutterCol, col, max(apertureMask * (0.22 + apertureOpen * 0.78), 1.0 - apertureFade));
    col += vec3(0.86, 0.96, 1.0) * shutterMask * 0.032;
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
'''
    _POST_FRAG = '''
#version 330
uniform sampler2D u_cur;   // 当前帧场景
uniform sampler2D u_prv;   // 历史模糊帧
uniform sampler2D u_ui;    // OpenGL 合成的透明 UI 层
uniform sampler2D u_boot_text; // 启动框小文字 atlas
uniform sampler2D u_connected_text; // P4 静态文字 atlas
uniform float     u_ca;    // 色差偏移 (单位: UV坐标)
uniform float     u_fx_energy;
uniform float     u_fx_flash;
uniform float     u_aspect;
uniform vec3      u_fx_tint;
uniform float     u_ui_alpha;
uniform float     u_motion_mix;
uniform vec2      u_resolution;
uniform vec4      u_boot_rect;
uniform float     u_boot_opacity;
uniform float     u_boot_progress;
uniform float     u_boot_scan;
uniform vec4      u_boot_text_rect;
uniform vec2      u_p2_center;
uniform float     u_p2_opacity;
uniform float     u_p2_scale;
uniform float     u_connected_opacity;
out vec4 fragColor;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

void main() {
    ivec2 sz = textureSize(u_cur, 0);
    vec2  uv = gl_FragCoord.xy / vec2(sz);
    vec2  centered = uv - 0.5;
    vec2  lens = vec2(centered.x * u_aspect, centered.y);
    float radius = length(lens);
    vec2  dir = radius > 0.0001 ? lens / radius : vec2(0.0, 0.0);

    float energy = clamp(u_fx_energy, 0.0, 1.0);
    float flash  = clamp(u_fx_flash, 0.0, 1.0);
    float ca     = u_ca * (1.0 + energy * 0.9 + flash * 0.8);

    vec2 smear = dir * (0.016 * energy + 0.022 * flash);
    vec2 squeeze = vec2(1.0 + flash * 0.015, 1.0 - energy * 0.010);
    vec2 zoomUv = centered * squeeze + 0.5;
    vec3 scene0 = texture(u_cur, clamp(zoomUv, 0.0, 1.0)).rgb;
    vec3 scene1 = texture(u_cur, clamp(zoomUv - smear * 0.8, 0.0, 1.0)).rgb;
    vec3 scene2 = texture(u_cur, clamp(zoomUv - smear * 1.8, 0.0, 1.0)).rgb;
    vec3 scene  = scene0 * 0.46 + scene1 * 0.34 + scene2 * 0.20;

    // 色差: R 右偏, G 原位, B 左偏
    float r = texture(u_cur, uv + vec2(ca, 0.0)).r;
    float g = scene.g;
    float b = texture(u_cur, uv - vec2(ca, 0.0)).b;
    // 运动模糊: 尾段/P4 会调高当前帧权重，避免已飞出的圆柱残影挂在屏幕上。
    vec3 prev   = texture(u_prv, uv).rgb;
    vec3 result = mix(prev, vec3(r, g, b), clamp(u_motion_mix, 0.58, 0.96));

    float centerGlow = pow(max(0.0, 1.0 - radius * 1.85), 2.6);
    float streak = exp(-abs(centered.y) * (74.0 - 22.0 * energy));
    streak *= smoothstep(0.52, 0.0, abs(centered.x));
    float outerGlow = pow(max(0.0, 1.0 - radius * 0.92), 1.8) * (0.010 + energy * 0.020 + flash * 0.018);
    float bloom = centerGlow * (0.055 + energy * 0.085 + flash * 0.080);
    float flare = streak * (energy * 0.125 + flash * 0.180);
    vec3 fx = u_fx_tint * (bloom + flare + outerGlow);
    float vignette = smoothstep(1.22, 0.18, radius);

    result += fx;
    result = mix(result, result + u_fx_tint * 0.12, flash * centerGlow);
    result *= mix(0.92, 1.04, vignette);
    float p2Opacity = clamp(u_p2_opacity * u_ui_alpha, 0.0, 1.0);
    if (p2Opacity > 0.001) {
        vec2 px = uv * u_resolution;
        vec2 basePx = (px - u_p2_center) / max(0.001, u_p2_scale) + u_p2_center;
        vec2 p2Uv = vec2(basePx.x / u_resolution.x, 1.0 - basePx.y / u_resolution.y);
        vec4 ui = texture(u_ui, clamp(p2Uv, 0.0, 1.0));
        result = mix(result, ui.rgb, clamp(ui.a * p2Opacity, 0.0, 1.0));
    }

    float connectedOpacity = clamp(u_connected_opacity * u_ui_alpha, 0.0, 1.0);
    if (connectedOpacity > 0.001) {
        vec4 connected = texture(u_connected_text, vec2(uv.x, 1.0 - uv.y));
        result = mix(result, connected.rgb, clamp(connected.a * connectedOpacity, 0.0, 1.0));
    }

    float bootOpacity = clamp(u_boot_opacity, 0.0, 1.0);
    if (bootOpacity > 0.001) {
        vec2 px = uv * u_resolution;
        vec2 rectMin = u_boot_rect.xy;
        vec2 rectMax = u_boot_rect.zw;
        vec2 rectSize = max(vec2(1.0), rectMax - rectMin);
        vec2 rectCenter = (rectMin + rectMax) * 0.5;
        vec2 local = (px - rectMin) / rectSize;
        vec2 centeredBoot = (px - rectCenter) / rectSize;
        float inside = step(rectMin.x, px.x) * step(px.x, rectMax.x) * step(rectMin.y, px.y) * step(px.y, rectMax.y);

        float radiusPx = 18.0;
        vec2 halfSize = rectSize * 0.5;
        vec2 q = abs(px - rectCenter) - halfSize + vec2(radiusPx);
        float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radiusPx;
        float panelMask = 1.0 - smoothstep(0.0, 1.75, sd);
        float softMask = 1.0 - smoothstep(10.0, 34.0, sd);
        float haloMask = exp(-max(sd, 0.0) * 0.045) * bootOpacity;
        result += vec3(0.36, 0.84, 1.00) * haloMask * 0.20;
        result += vec3(1.00, 0.70, 0.26) * haloMask * 0.09;

        vec3 bootBase = vec3(0.024, 0.078, 0.133);
        float scanline = step(fract((px.y - rectMin.y) / 8.0), 0.14);
        vec3 panel = bootBase + vec3(0.06, 0.16, 0.22) * scanline * 0.25;
        float border = 1.0 - smoothstep(0.8, 2.2, abs(sd));
        float borderBlur = exp(-abs(sd) * 0.18) * softMask;
        float innerTop = 1.0 - smoothstep(0.4, 1.3, abs((px.y - rectMin.y) - 10.0));
        innerTop *= panelMask * step(10.0, px.x - rectMin.x) * step(10.0, rectMax.x - px.x);
        float innerBot = 1.0 - smoothstep(0.4, 1.3, abs((rectMax.y - px.y) - 10.0));
        innerBot *= panelMask * step(10.0, px.x - rectMin.x) * step(10.0, rectMax.x - px.x);
        vec3 lineCol = vec3(0.50, 0.91, 1.00) * (border + borderBlur * 0.34) + vec3(1.00, 0.78, 0.24) * innerTop * 0.72 + vec3(0.48, 0.90, 1.00) * innerBot * 0.42;

        float arm = 34.0;
        float armY = 24.0;
        float corner = 0.0;
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.y - rectMin.y))) * step(px.x, rectMin.x + arm) * step(rectMin.x + radiusPx, px.x);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.x - rectMin.x))) * step(px.y, rectMin.y + armY) * step(rectMin.y + radiusPx, px.y);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.y - rectMin.y))) * step(rectMax.x - arm, px.x) * step(px.x, rectMax.x - radiusPx);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.x - rectMax.x))) * step(px.y, rectMin.y + armY) * step(rectMin.y + radiusPx, px.y);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.y - rectMax.y))) * step(px.x, rectMin.x + arm) * step(rectMin.x + radiusPx, px.x);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.x - rectMin.x))) * step(rectMax.y - armY, px.y) * step(px.y, rectMax.y - radiusPx);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.y - rectMax.y))) * step(rectMax.x - arm, px.x) * step(px.x, rectMax.x - radiusPx);
        corner += (1.0 - smoothstep(0.6, 1.6, abs(px.x - rectMax.x))) * step(rectMax.y - armY, px.y) * step(px.y, rectMax.y - radiusPx);

        float scanX = mix(rectMin.x - rectSize.x * 0.12, rectMax.x + rectSize.x * 0.12, fract(u_boot_scan));
        float sweep = exp(-pow((px.x - scanX) / max(1.0, rectSize.x * 0.055), 2.0));
        sweep *= panelMask;
        vec3 sweepCol = vec3(0.75, 0.95, 1.0) * sweep * (0.12 + u_boot_progress * 0.22);

        vec2 sparkCell = floor((px - rectCenter) / 9.0 + vec2(u_boot_scan * 19.0, u_boot_progress * 7.0));
        float rnd = hash21(sparkCell);
        float sparkBand = exp(-abs(sd) * 0.035) * (1.0 - panelMask);
        float spark = step(0.975, rnd) * sparkBand * bootOpacity;
        vec3 scatter = mix(vec3(0.34, 0.86, 1.0), vec3(1.0, 0.76, 0.24), hash21(sparkCell + vec2(17.0))) * spark * 0.42;

        float panelAlpha = panelMask * bootOpacity;
        vec3 bootCol = panel + lineCol * 0.72 + vec3(0.55, 0.93, 1.0) * min(corner, 1.0) * 0.84 + sweepCol;
        result = mix(result, bootCol, panelAlpha * 0.78);
        result += (lineCol + vec3(0.45, 0.90, 1.0) * min(corner, 1.0)) * bootOpacity * 0.22;
        result += scatter;

        vec2 textPx = u_boot_text_rect.xy + clamp(local, 0.0, 1.0) * max(vec2(1.0), u_boot_text_rect.zw - u_boot_text_rect.xy);
        vec4 text = texture(u_boot_text, vec2(textPx.x / u_resolution.x, 1.0 - textPx.y / u_resolution.y));
        result = mix(result, text.rgb, text.a * bootOpacity);
    }

    result = clamp(result, 0.0, 1.0);
    fragColor = vec4(result, 1.0);
}
'''

    def __init__(self, root: tk.Tk, on_done: Optional[Callable] = None,
                 monitor_rect: Optional[tuple] = None):
        self.root = root
        self.on_done = on_done
        # Optional (left, top, right, bottom) of the monitor the intro should
        # cover. Entity mode leaves this None and the animation fills the
        # primary monitor as before; WebView mode passes the game window's
        # monitor so the borderless GLFW present window does not land off the
        # game screen on a multi-monitor / high-DPI rig (the most likely
        # cause of "window won't render").
        self._monitor_rect = monitor_rect
        self._origin_x = 0
        self._origin_y = 0
        self._overlay = None
        self._canvas = None
        self._sound_player = None
        self._ls_font_cache = {}
        self._ls_sprite_cache = {}
        self._ls_live_photos = []
        self._ls_p2_prewarmed = False
        self._timer_resolution = None
        self._next_frame_deadline = 0.0
        self._gpu_present_window = None
        self._gpu_present_enabled = False
        self._gpu_present_frame_requested = False
        self._gpu_present_ready = False
        self._gpu_present_done = False
        self._gpu_present_finish_posted = False
        self._finished = False
        self._target_refresh_hz = 60.0
        self._gl_ctx = None
        self._gl_photo = None
        self._gl_photo_size = None
        self._gl_canvas_item = None
        self._gl_ui_tex = None
        self._gl_ui_img = None
        self._gl_ui_draw = None
        self._gl_ui_dirty = True
        self._gl_ui_sig = None
        self._gl_boot_text_tex = None
        self._gl_boot_text_img = None
        self._gl_boot_sig = None
        self._gl_connected_text_tex = None
        self._gl_static_text_sig = None
        self._gl_boot_text_rect = (0.0, 0.0, 0.0, 0.0)

    # ════════════════════════════════════════════════════════
    #  Link Start 音效播放 (3阶段)
    # ════════════════════════════════════════════════════════
    def _play_sound(self):
        """3阶段音效: LinkStart.SAO.Kirito → Startup.SAO.NerveGear → Popup.ALO.Welcome

        对应动画时间线:
          Phase 1 (t=0.0s):  "LINK START!" 桐人喊声 — 彩色隧道开始
          Phase 1 (t=1.5s):  NerveGear 启动音 — 隧道飞向中, 持续到 P2 结束
          Phase 3 (t=5.2s):  ALO 欢迎音 — 蓝色隧道开始, 持续到 P4 结束
        """
        import threading

        def _do_play(name):
            try:
                from sao_sound import play_sound as _ps
                _ps(name, volume=0.8)
            except Exception:
                try:
                    _base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from sao_sound import SAO_SOUNDS
                    fname = SAO_SOUNDS.get(name, '')
                    if fname and os.path.isfile(fname):
                        import pygame
                        if not pygame.mixer.get_init():
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                        pygame.mixer.Sound(fname).play()
                except Exception as e:
                    print(f'[LinkStart] Sound ({name}) failed: {e}')

        # Phase 1 (t=0): "LINK START!" 桐人 — 入场
        threading.Thread(target=lambda: _do_play('link_start'), daemon=True).start()
        # Phase 1 (t=1.5s): NerveGear 启动音 — 紧跟桐人喊声, 隧道飞行中
        threading.Timer(1.5, lambda: _do_play('nervegear')).start()
        # Phase 3 (t=5.2s): ALO 欢迎音 — 蓝色隧道
        threading.Timer(5.2, lambda: _do_play('alo_welcome')).start()

    def _detect_refresh_hz(self) -> float:
        """Detect display refresh rate for non-vsync fallback scheduling."""
        try:
            from render import gpu_overlay_window as _gow
            pump = _gow.get_glfw_pump(self.root)
            try:
                pump.exec_on_pump(lambda: None, timeout=3.0)
            except Exception:
                pass
            hz = float(getattr(pump, '_tick_hz', 0) or 0)
            if 30.0 <= hz <= 360.0:
                return hz
        except Exception:
            pass
        return 60.0

    # ════════════════════════════════════════════════════════
    #  启动
    # ════════════════════════════════════════════════════════
    def play(self):
        # Prefer the explicitly supplied monitor rect (WebView passes the game
        # window's monitor). Fall back to the root's primary-monitor metrics
        # for Entity mode — byte-for-byte unchanged when no rect is given.
        mr = self._monitor_rect
        if mr and len(mr) == 4:
            left, top, right, bottom = (int(mr[0]), int(mr[1]),
                                        int(mr[2]), int(mr[3]))
            sw = max(1, right - left)
            sh = max(1, bottom - top)
            self._origin_x, self._origin_y = left, top
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self._origin_x, self._origin_y = 0, 0
        self._cx, self._cy = sw // 2, sh // 2
        self._sw, self._sh = sw, sh
        self._diag = math.hypot(sw, sh)
        self._ls_p2_prewarmed = False
        self._next_frame_deadline = 0.0
        self._target_refresh_hz = self._detect_refresh_hz()
        self._gpu_present_enabled = False
        self._gpu_present_frame_requested = False
        self._gpu_present_ready = False
        self._finished = False
        self._gpu_present_done = False
        self._gpu_present_finish_posted = False
        if _WinTimerResolution is not None and self._timer_resolution is None:
            try:
                self._timer_resolution = _WinTimerResolution()
                self._timer_resolution.acquire()
            except Exception:
                self._timer_resolution = None

        # ── 播放 Link Start 音效 ──
        self._play_sound()

        # ── 预生成静态隧道粒子 (SAO-UI 模型) ──
        # GPU模式用300粒子, Canvas回退用150以保证帧率
        n_particles = self._NUM_PARTICLES if _HAS_MODERNGL else self._NUM_PARTICLES_CANVAS
        self._color_particles = self._gen_tunnel(self._COLORS_8, n_particles)
        self._blue_particles = self._gen_tunnel(self._BLUES_8, n_particles)

        # ── OpenGL 3D 渲染初始化 ──
        self._gl_ctx = None
        self._gl_photo = None     # 保持 PhotoImage 引用
        self._gl_photo_size = None  # 当前 PhotoImage 像素尺寸 (sw, sh) — 仅当尺寸变化时重新分配
        self._gl_canvas_item = None
        self._prev_gl_arr = None  # 运动模糊前帧帧缓存 (numpy uint8 HxWx3)
        self._gl_fx_energy = 0.0
        self._gl_fx_flash = 0.0
        self._gl_fx_tint = (0.95, 0.85, 0.35)
        self._gl_ui_img = None
        self._gl_ui_draw = None
        self._gl_ui_tex = None
        self._gl_ui_dirty = True
        self._gl_ui_sig = None
        self._gl_boot_text_tex = None
        self._gl_boot_text_img = None
        self._gl_boot_sig = None

        self._start_time = time.time()
        self._next_frame_deadline = time.perf_counter()

        self._gpu_present_enabled = self._try_start_gpu_present_window_strict(sw, sh)
        if self._gpu_present_enabled:
            self._overlay = None
            self._canvas = None
            return

        if _HAS_MODERNGL:
            print('[LinkStart] GPU present unavailable after retry; skip Tk/Canvas fallback to avoid CPU startup path')
            self._finish()
            return

        # ── 仅在没有 ModernGL 的旧环境才预热 Canvas sprite；正常启动动画不走 Tk/Canvas。 ──
        self._prewarm_linkstart_p2_sprites()

        # ── 创建全屏顶层窗口 ──
        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)
        self._overlay.geometry(
            f'{sw}x{sh}+{int(getattr(self, "_origin_x", 0))}'
            f'+{int(getattr(self, "_origin_y", 0))}')
        self._overlay.configure(bg='black')
        self._overlay.attributes('-alpha', 0.92)

        self._canvas = tk.Canvas(self._overlay, width=sw, height=sh,
                                 bg='black', highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        if _HAS_MODERNGL:
            try:
                self._init_gl()
            except Exception as e:
                print(f'[LinkStart] OpenGL init failed: {e}, fallback to Canvas')
                self._gl_ctx = None
        self._animate()

    # ════════════════════════════════════════════════════════
    #  隧道粒子生成 (SAO-UI 模型: 静态圆柱排列)
    # ════════════════════════════════════════════════════════
    def _gen_tunnel(self, colors: list, num_particles: int = None) -> list:
        """
        生成 ~300 根静态隧道粒子.
        粒子分布在较深的范围, 摄像机从后方飞向前方,
        视觉上粒子会从中心小点逐渐变大并飞过摄像机.
        """
        particles = []
        n = num_particles if num_particles is not None else self._NUM_PARTICLES
        for i in range(n):
            theta_deg = random.uniform(0, 360)
            rad = math.radians(theta_deg)
            r = random.uniform(self._TUNNEL_R_MIN, self._TUNNEL_R_MAX)
            # 粒子分布在更深更宽的范围, 保证任何时刻都有粒子在远处和近处
            d = random.uniform(-800, 1400)
            color = colors[i % len(colors)]
            particles.append({
                'r': r,
                'd': d,
                'cos': math.cos(rad),
                'sin': math.sin(rad),
                'color': color,
                'rgb': hex_to_rgb(color),   # 预计算, 避免每帧重新解析
                'brightness': random.uniform(0.7, 1.0),
                'flicker_freq': random.uniform(3.0, 8.0),
                'width_mult': random.uniform(0.8, 1.4),
            })
        return particles

    def _try_start_gpu_present_window(self, sw: int, sh: int) -> bool:
        """优先使用 GLFW/ModernGL 直出窗口，避免每帧 FBO.read → Tk 贴图。"""
        if not _HAS_MODERNGL:
            print('[LinkStart] GPU present unavailable: moderngl import failed')
            return False
        try:
            from render import gpu_overlay_window as _gow
        except Exception as e:
            print(f'[LinkStart] GPU present unavailable: import gpu_overlay_window failed: {e}')
            return False
        try:
            if not _gow.glfw_supported():
                print('[LinkStart] GPU present unavailable: glfw_supported() returned False')
                return False
            if not _gow.gpu_overlay_creation_allowed():
                print('[LinkStart] GPU present unavailable: overlay creation is suspended')
                return False
            pump = _gow.get_glfw_pump(self.root)
            win = _gow.GpuOverlayWindow(
                pump,
                w=sw,
                h=sh,
                x=int(getattr(self, '_origin_x', 0)),
                y=int(getattr(self, '_origin_y', 0)),
                render_fn=self._render_gpu_present_frame,
                click_through=True,
                title='sao_linkstart_gpu',
                vsync=True,
            )
            win.show()
            self._gpu_present_window = win
            self._gpu_present_ready = False
            self._gpu_present_done = False
            self._gpu_present_frame_requested = True
            win.request_redraw()
            return True
        except Exception as e:
            print(f'[LinkStart] GPU present window unavailable: {e}')
            self._gpu_present_window = None
            self._gpu_present_ready = False
            return False

    def _try_start_gpu_present_window_strict(self, sw: int, sh: int) -> bool:
        """Start direct GPU presentation; recover once if old startup code suspended creation."""
        if self._try_start_gpu_present_window(sw, sh):
            return True
        try:
            from render import gpu_overlay_window as _gow
            if not _gow.gpu_overlay_creation_allowed():
                print('[LinkStart] GPU present retry: resuming suspended overlay creation')
                _gow.resume_gpu_overlay_creation()
                if self._try_start_gpu_present_window(sw, sh):
                    return True
        except Exception as e:
            print(f'[LinkStart] GPU present retry failed: {e}')
        return False

    def _render_gpu_present_frame(self, ctx, _pump_t: float) -> None:
        """GpuOverlayWindow 回调：在 pump 拥有的 GL context 中直接渲染到屏幕。"""
        if getattr(self, '_gpu_present_done', False):
            return
        if not getattr(self, '_gpu_present_frame_requested', False):
            return
        try:
            if self._gl_ctx is not ctx:
                self._init_gl(ctx=ctx)
                self._gpu_present_ready = True
            elapsed = max(0.0, time.time() - self._start_time)
            scene_t = elapsed - self._STARTUP_PRELUDE
            if scene_t > self._DURATION:
                self._gpu_present_done = True
                self._gpu_present_frame_requested = False
                self._post_gpu_present_finish()
                return
            self._render_linkstart_gl_frame(elapsed, target_fbo=ctx.screen, readback_canvas=None)
            alpha = 1.0
            if scene_t >= self._P4_START and scene_t >= self._DURATION - 1.5:
                ft = min(1.0, (scene_t - (self._DURATION - 1.5)) / 1.5)
                alpha = max(0.0, 0.92 * (1.0 - ease_in_out(ft)))
            self._copy_present_tex_to_screen(alpha=alpha)
            self._gpu_present_frame_requested = True
            if self._gpu_present_window is not None:
                self._gpu_present_window.request_redraw()
        except Exception as e:
            # Surface the real cause: a driver-specific GLSL compile/link
            # failure here used to vanish silently and look like "the intro
            # never rendered". The traceback disambiguates it from a
            # geometry/occlusion problem.
            print(f'[LinkStart] GPU present render error: {e}')
            import traceback
            traceback.print_exc()
            self._gl_ctx = None
            self._gpu_present_ready = False
            self._gpu_present_done = True
            self._post_gpu_present_finish()

    def _post_gpu_present_finish(self) -> None:
        """GPU 直出结束后只投递一次 Tk 收尾；不使用 Tk 帧循环驱动动画。"""
        if getattr(self, '_gpu_present_finish_posted', False):
            return
        self._gpu_present_finish_posted = True
        try:
            pump = getattr(self._gpu_present_window, '_pump', None)
            if pump is not None:
                pump.post_to_tk(self._finish)
                return
        except Exception:
            pass
        try:
            self.root.after(0, self._finish)
        except Exception:
            self._finish()

    def _copy_present_tex_to_screen(self, alpha: float = 1.0) -> None:
        """把后处理 ping-pong 输出纹理直接 blit 到 GLFW framebuffer。"""
        if not self._gl_ctx or not hasattr(self, '_gl_copyvao'):
            return
        src_tex = self._gl_ptex_a if ((self._gl_pframe - 1) & 1) == 0 else self._gl_ptex_b
        self._gl_ctx.screen.use()
        self._gl_ctx.viewport = (0, 0, self._sw, self._sh)
        src_tex.use(location=0)
        self._gl_copyprog['u_tex'].value = 0
        self._gl_copyprog['u_alpha'].value = max(0.0, min(1.0, float(alpha)))
        self._gl_ctx.disable(moderngl.DEPTH_TEST)
        self._gl_copyvao.render(moderngl.TRIANGLES, vertices=3)

    # ════════════════════════════════════════════════════════
    #  Cubic-Bezier 缓动 (匹配 SAO-UI 的加速曲线)
    # ════════════════════════════════════════════════════════
    @staticmethod
    def _cubic_bezier_y(t_x: float, p1x: float, p1y: float,
                        p2x: float, p2y: float) -> float:
        """
        给定时间比例 t_x ∈ [0,1], 用二分法求 cubic-bezier 的输出 y.
        cubic-bezier(0.8, 0.1, 0.9, 0.8) → 前期极慢, 后期急加速.
        """
        lo, hi = 0.0, 1.0
        for _ in range(25):
            mid = (lo + hi) * 0.5
            inv = 1.0 - mid
            x = 3 * inv * inv * mid * p1x + 3 * inv * mid * mid * p2x + mid ** 3
            if x < t_x:
                lo = mid
            else:
                hi = mid
        s = (lo + hi) * 0.5
        inv = 1.0 - s
        return 3 * inv * inv * s * p1y + 3 * inv * s * s * p2y + s ** 3

    def _cam_z(self, phase_elapsed: float, duration: float) -> float:
        """摄像机 Z 坐标: cubic-bezier 从 _CAM_Z_START 到 _CAM_Z_END"""
        t = max(0.0, min(1.0, phase_elapsed / duration))
        eased = self._cubic_bezier_y(t, 0.8, 0.1, 0.9, 0.8)
        return self._CAM_Z_START + (self._CAM_Z_END - self._CAM_Z_START) * eased

    def _cam_z_end_velocity(self, duration: float) -> float:
        """_cam_z 在结束点的速度，用于飞出段无停顿续接。"""
        # cubic-bezier(0.8, 0.1, 0.9, 0.8) 在终点的 dy/dx。
        end_slope = (1.0 - 0.8) / max(1.0e-6, 1.0 - 0.9)
        return (self._CAM_Z_END - self._CAM_Z_START) * end_slope / max(0.01, duration)

    def _cam_z_with_exit(self, phase_elapsed: float, duration: float,
                         exit_start: float, exit_duration: float) -> float:
        """相机结束段继续 overshoot，确保圆柱体尾巴整体飞出屏幕。"""
        cam_z = self._cam_z(phase_elapsed, duration)
        if phase_elapsed <= exit_start or exit_duration <= 0.0:
            return cam_z
        base_z = self._cam_z(exit_start, duration)
        exit_t = max(0.0, min(1.0, (phase_elapsed - exit_start) / exit_duration))
        exit_dt = min(max(0.0, phase_elapsed - exit_start), exit_duration)
        exit_speed = self._cam_z_end_velocity(duration)
        linear_extra = exit_speed * exit_dt
        topup_extra = max(0.0, self._CAM_EXIT_EXTRA - exit_speed * exit_duration)
        return base_z + linear_extra + topup_extra * ease_in(exit_t)

    # ════════════════════════════════════════════════════════
    #  OpenGL 3D 隧道初始化
    # ════════════════════════════════════════════════════════
    _GL_CYL_SEGMENTS = 10     # 每根管子的截面段数
    _GL_TUBE_RADIUS = 1.8     # 管子视觉半径(世界单位)

    def _init_gl(self, ctx=None):
        """创建/绑定 ModernGL context, 着色器, 几何体, FBO."""
        if ctx is None:
            ctx = moderngl.create_standalone_context()
        self._gl_ctx = ctx

        # ── 着色器程序 ──
        self._gl_prog = ctx.program(
            vertex_shader='''
#version 330

// ─── per-vertex (单位圆柱体网格) ───
layout(location=0) in vec3 in_pos;   // (cos φ, sin φ, z∈[0,1])
layout(location=1) in vec3 in_norm;  // (cos φ, sin φ, 0)

// ─── per-instance ───
layout(location=2) in vec3  i_center;   // 管子起点 (x, y, z_start)
layout(location=3) in float i_len;      // 管子长度 (streak_h)
layout(location=4) in float i_radius;   // 管子半径
layout(location=5) in vec3  i_color;    // 颜色 [0,1]
layout(location=6) in float i_alpha;    // 综合透明度
layout(location=7) in float i_fog;      // 雾因子

uniform mat4  u_vp;       // view * projection
uniform float u_rot;      // 隧道旋转 (弧度)
uniform float u_alpha_mul;
uniform float u_radius_mul;

out vec3  v_world;
out vec3  v_normal;
out vec3  v_color;
out float v_alpha;
out float v_fog;

void main() {
    // 缩放单位圆柱到实际管子
    vec3 pos = in_pos;
    pos.xy *= i_radius * u_radius_mul;
    pos.z   = pos.z * i_len + i_center.z;
    pos.xy += i_center.xy;

    // 绕 Z 轴旋转 (隧道整体旋转)
    float cr = cos(u_rot), sr = sin(u_rot);
    vec2 rp  = vec2(pos.x*cr - pos.y*sr, pos.x*sr + pos.y*cr);
    pos.xy = rp;

    vec3 n  = in_norm;
    vec2 rn = vec2(n.x*cr - n.y*sr, n.x*sr + n.y*cr);
    n.xy = rn;

    v_world  = pos;
    v_normal = normalize(n);
    v_color  = i_color;
    v_alpha  = i_alpha * u_alpha_mul;
    v_fog    = i_fog;

    gl_Position = u_vp * vec4(pos, 1.0);
}
''',
            fragment_shader='''
#version 330

in vec3  v_world;
in vec3  v_normal;
in vec3  v_color;
in float v_alpha;
in float v_fog;

uniform vec3 u_cam_pos;   // 摄像机位置 (0, 0, cam_z)
uniform vec3 u_bg_color;  // 背景色 [0,1]

out vec4 fragColor;

void main() {
    vec3 N = normalize(v_normal);

    // ─── 光源 = 隧道中轴 (0,0,z) → 方向: 径向指向中心 ───
    vec3 L = normalize(vec3(-v_world.xy, 0.0));

    // ─── 视线方向 ───
    vec3 V = normalize(u_cam_pos - v_world);

    // ─── Blinn-Phong ───
    vec3 H = normalize(L + V);
    float diff = max(dot(N, L), 0.0);
    float spec = pow(max(dot(N, H), 0.0), 48.0);

    // Fresnel 边缘光
    float rim = 1.0 - max(dot(N, V), 0.0);
    rim = pow(rim, 2.5) * 0.45;

    // 组合光照
    vec3 ambient  = v_color * 0.20;
    vec3 diffuse  = v_color * diff * 0.55;
    vec3 specular = vec3(1.0) * spec * 0.65;
    vec3 emissive = v_color * 0.30;
    vec3 rim_c    = v_color * rim;

    vec3 lit = ambient + diffuse + specular + emissive + rim_c;
    lit = clamp(lit, 0.0, 1.0);

    // 综合淡入/淡出 + 雾；ghost-pass 会降低 v_alpha，保持拖影柔和而不是实心重影。
    float total_fade = clamp(v_alpha * (1.0 - v_fog), 0.0, 1.0);
    vec3 final_c = mix(u_bg_color, lit, total_fade);

    fragColor = vec4(final_c, 1.0);
}
''')

        # ── 单位圆柱网格 (z∈[0,1], r=1, N段) ──
        segs = self._GL_CYL_SEGMENTS
        verts = []
        for i in range(segs):
            a0 = 2.0 * math.pi * i / segs
            a1 = 2.0 * math.pi * (i + 1) / segs
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            # 两个三角形组成一个四边形
            # 顶点: pos(3) + normal(3)
            for (px, py, pz, nx, ny) in [
                (c0, s0, 0, c0, s0),
                (c1, s1, 0, c1, s1),
                (c0, s0, 1, c0, s0),
                (c1, s1, 0, c1, s1),
                (c1, s1, 1, c1, s1),
                (c0, s0, 1, c0, s0),
            ]:
                verts.extend([px, py, pz, nx, ny, 0.0])

        verts_np = np.array(verts, dtype='f4')
        self._gl_vbo = ctx.buffer(verts_np.tobytes())
        self._gl_num_verts = segs * 6

        # ── Instance buffer (预分配, 每帧更新) ──
        # 每实例: center(3) + len(1) + radius(1) + color(3) + alpha(1) + fog(1) = 10 floats
        max_inst = self._NUM_PARTICLES + 16
        self._gl_inst_buf = ctx.buffer(reserve=max_inst * 10 * 4)
        self._gl_max_inst = max_inst

        # ── VAO ──
        self._gl_vao = ctx.vertex_array(self._gl_prog, [
            (self._gl_vbo, '3f 3f', 'in_pos', 'in_norm'),
            (self._gl_inst_buf, '3f 1f 1f 3f 1f 1f /i',
             'i_center', 'i_len', 'i_radius', 'i_color', 'i_alpha', 'i_fog'),
        ])

        # ── Framebuffer ──
        sw, sh = self._sw, self._sh
        self._gl_color_tex = ctx.texture((sw, sh), 3)   # RGB
        self._gl_depth_rb = ctx.depth_renderbuffer((sw, sh))
        self._gl_fbo = ctx.framebuffer(
            color_attachments=[self._gl_color_tex],
            depth_attachment=self._gl_depth_rb)
        startup_w = max(480, sw // 3)
        startup_h = max(270, sh // 3)
        self._gl_startup_tex = ctx.texture((startup_w, startup_h), 3)
        self._gl_startup_fbo = ctx.framebuffer(color_attachments=[self._gl_startup_tex])
        self._gl_startup_size = (startup_w, startup_h)

        # 启用深度测试
        ctx.enable(moderngl.DEPTH_TEST)

        # ── GPU 背景层 + 后处理: 背景聚焦/速度线在底层, 再叠 3D 圆柱体 ──
        self._gl_bg_prog = ctx.program(
            vertex_shader=self._POST_VERT,
            fragment_shader=self._BG_FRAG,
        )
        self._gl_bg_vao = ctx.vertex_array(self._gl_bg_prog, [])
        self._gl_postprog = ctx.program(
            vertex_shader=self._POST_VERT,
            fragment_shader=self._POST_FRAG,
        )
        self._gl_copyprog = ctx.program(
            vertex_shader=self._POST_VERT,
            fragment_shader=self._COPY_FRAG,
        )
        # Ping-pong: 两对 FBO+纹理交替作为输出 / 历史输入
        self._gl_ptex_a = ctx.texture((sw, sh), 3)
        self._gl_pfbo_a = ctx.framebuffer(color_attachments=[self._gl_ptex_a])
        self._gl_ptex_b = ctx.texture((sw, sh), 3)
        self._gl_pfbo_b = ctx.framebuffer(color_attachments=[self._gl_ptex_b])
        self._gl_ui_tex = ctx.texture((sw, sh), 4)
        self._gl_ui_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._gl_ui_sig = None
        self._gl_boot_text_tex = ctx.texture((sw, sh), 4)
        self._gl_boot_text_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._gl_connected_text_tex = ctx.texture((sw, sh), 4)
        self._gl_connected_text_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._gl_ui_img = None
        self._gl_ui_draw = None
        self._gl_ui_dirty = False
        self._gl_boot_text_img = None
        self._gl_boot_sig = None
        self._gl_static_text_sig = None
        self._gl_boot_text_rect = (0.0, 0.0, 0.0, 0.0)
        self._gl_pframe  = 0   # 帧计数 (偏奇偶决定 ping-pong 方向)
        # Fullscreen triangle VAO (无顶点数据, 纯靠 gl_VertexID)
        self._gl_postvao = ctx.vertex_array(self._gl_postprog, [])
        self._gl_copyvao = ctx.vertex_array(self._gl_copyprog, [])
        # 色差 UV 偏移 = 2 像素 / 屏宽 (x 方向)
        self._gl_ca_uv  = 2.0 / sw
        self._gl_bg_prog['u_aspect'].value = sw / max(1.0, float(sh))
        self._gl_bg_prog['u_resolution'].value = (float(sw), float(sh))
        self._gl_bg_prog['u_startburst'].value = 0.0
        self._gl_bg_prog['u_startwave'].value = 0.0
        self._gl_postprog['u_fx_energy'].value = 0.0
        self._gl_postprog['u_fx_flash'].value = 0.0
        self._gl_postprog['u_aspect'].value = sw / max(1.0, float(sh))
        self._gl_postprog['u_fx_tint'].value = (0.95, 0.85, 0.35)
        self._gl_postprog['u_ui_alpha'].value = 1.0
        self._gl_postprog['u_motion_mix'].value = 0.60
        self._gl_postprog['u_resolution'].value = (float(sw), float(sh))
        self._gl_postprog['u_boot_rect'].value = (0.0, 0.0, 0.0, 0.0)
        self._gl_postprog['u_boot_opacity'].value = 0.0
        self._gl_postprog['u_boot_progress'].value = 0.0
        self._gl_postprog['u_boot_scan'].value = 0.0
        self._gl_postprog['u_boot_text_rect'].value = (0.0, 0.0, 0.0, 0.0)
        self._gl_postprog['u_p2_center'].value = (float(self._cx), float(self._cy))
        self._gl_postprog['u_p2_opacity'].value = 0.0
        self._gl_postprog['u_p2_scale'].value = 1.0
        self._gl_postprog['u_connected_opacity'].value = 0.0
        self._gl_copyprog['u_alpha'].value = 1.0
        self._ensure_gl_static_text_textures()

    def _destroy_gl(self):
        """释放 OpenGL 资源."""
        if self._gl_ctx and not getattr(self, '_gpu_present_enabled', False):
            try:
                self._gl_ctx.release()
            except Exception:
                pass
        self._gl_ctx = None
        self._gl_photo = None
        self._gl_canvas_item = None
        self._gl_startup_tex = None
        self._gl_startup_fbo = None
        self._gl_startup_size = None
        self._gl_ui_img = None
        self._gl_ui_draw = None
        self._gl_ui_tex = None
        self._gl_ui_sig = None
        self._gl_boot_text_tex = None
        self._gl_boot_text_img = None
        self._gl_boot_sig = None

    # ════════════════════════════════════════════════════════
    #  构建 View-Projection 矩阵
    # ════════════════════════════════════════════════════════
    def _build_vp_matrix(self, cam_z: float) -> np.ndarray:
        """
        构建 view-projection 矩阵, 转置后传给 GLSL.

        坐标系约定:
          - 世界空间 Z = 隧道前方 (+Z 为前)
          - 摄像机在 (0,0,cam_z), 朝 +Z 看
          - 眼空间 Z = -(world_z - cam_z)  → 标准 OpenGL (-Z 为前)
          - 近平面/远平面: near=1, far=10000

        Python 中用行主序写矩阵, 做 proj @ view, 再 .T 传 GLSL.
        GLSL 收到后: gl_Position = u_vp * vec4(pos, 1.0)
        等价于 math: vp_python @ pos  (正确)
        """
        sw, sh = self._sw, self._sh
        focal = self._FOCAL

        near = 1.0
        far = 10000.0
        half_h = sh * 0.5
        half_w = sw * 0.5
        f_y = focal / half_h     # cot(fov_y/2)
        f_x = focal / half_w     # cot(fov_x/2)
        nf = near - far           # negative

        # ── 视图矩阵 (行主序数学形式) ──
        # 对世界点 (x,y,z,1):
        #   eye_x = x
        #   eye_y = y
        #   eye_z = -z + cam_z   (翻转Z, 平移)
        #   eye_w = 1
        view = np.array([
            [1, 0,  0,     0    ],
            [0, 1,  0,     0    ],
            [0, 0, -1,     cam_z],   # row 2: eye_z = -world_z + cam_z
            [0, 0,  0,     1    ],
        ], dtype='f4')

        # ── 透视投影矩阵 (行主序数学形式, 标准 OpenGL) ──
        # 对眼空间点 (ex, ey, ez, 1):
        #   x_clip = f_x * ex
        #   y_clip = f_y * ey
        #   z_clip = (f+n)/nf * ez + 2fn/nf
        #   w_clip = -ez
        proj = np.array([
            [f_x, 0,   0,                       0              ],
            [0,   f_y, 0,                       0              ],
            [0,   0,   (far + near) / nf,       2*far*near/nf  ],
            [0,   0,   -1,                      0              ],
        ], dtype='f4')

        # VP = proj @ view (行主序乘法)
        vp = proj @ view

        # 转置后传 GLSL (GLSL mat4 列主序, 但 GLSL 做 mat*vec = 数学矩阵乘向量)
        return vp.T.astype('f4')

    # ════════════════════════════════════════════════════════
    #  OpenGL 3D 隧道渲染
    # ════════════════════════════════════════════════════════
    def _draw_tunnel(self, cv: tk.Canvas, particles: list,
                     cam_z: float, bg: str, fade: float = 1.0,
                     t: float = 0.0,
                     motion_blur: float = 0.0,
                     cam_velocity: float = 0.0):
        """
        3D 隧道渲染. 如果 OpenGL 可用, 使用真 3D 圆柱体 + Blinn-Phong;
        否则回退到 Canvas 2D.
        """
        if self._gl_ctx:
            try:
                self._draw_tunnel_gl(cv, particles, cam_z, bg, fade, t,
                                     motion_blur=motion_blur,
                                     cam_velocity=cam_velocity)
                return
            except Exception as e:
                print(f'[LinkStart] GL render error: {e}')
                self._gl_ctx = None   # 降级到 canvas

        # ── Canvas 2D 回退 ──
        self._draw_tunnel_canvas(cv, particles, cam_z, bg, fade, t)

    @staticmethod
    def _with_alpha(img: Image.Image, opacity: float) -> Image.Image:
        """返回 alpha 乘过 opacity 的 RGBA 图，用于 GL UI 纹理合成。"""
        opacity = max(0.0, min(1.0, float(opacity)))
        if opacity >= 0.999:
            return img
        out = img.copy()
        alpha = out.getchannel('A')
        alpha = alpha.point(lambda v: int(v * opacity))
        out.putalpha(alpha)
        return out

    def _paste_gl_ui(self, base: Image.Image, img: Image.Image, x: int, y: int,
                     anchor: str = 'center', opacity: float = 1.0):
        """把透明 UI 子图贴到 GL UI 纹理上，坐标语义接近 Tk anchor。"""
        if img is None or opacity <= 0.01:
            return
        w, h = img.size
        px, py = int(x), int(y)
        if anchor in ('center', 'c'):
            px -= w // 2
            py -= h // 2
        elif anchor == 'n':
            px -= w // 2
        elif anchor == 's':
            px -= w // 2
            py -= h
        elif anchor == 'e':
            px -= w
            py -= h // 2
        elif anchor == 'w':
            py -= h // 2
        elif anchor == 'ne':
            px -= w
        elif anchor == 'se':
            px -= w
            py -= h
        elif anchor == 'sw':
            py -= h
        if opacity < 0.999:
            img = self._with_alpha(img, opacity)
        base.alpha_composite(img, (px, py))

    def _make_gl_tracking_text(self, segments, size: int, fill_rgba,
                               stroke_rgba=(0, 0, 0, 0), glow_rgba=(0, 0, 0, 0),
                               stroke_width: int = 0, blur_radius: float = 0.0,
                               tracking: int = 0) -> Image.Image:
        """渲染带字距和辉光的文字贴图，供 OpenGL UI 层采样。"""
        qsize = max(6, int(round(size)))
        qstroke = max(0, int(round(stroke_width)))
        tracking = int(round(tracking))
        norm_segments = tuple((str(text), str(family)) for text, family in segments if text)
        key = ('gltext', norm_segments, qsize, tuple(fill_rgba), tuple(stroke_rgba),
               tuple(glow_rgba), qstroke, round(float(blur_radius), 2), tracking)
        cached = self._ls_sprite_cache.get(key)
        if cached is not None:
            return cached

        if len(self._ls_sprite_cache) > 260:
            self._ls_sprite_cache.clear()

        dummy = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dummy)
        glyphs = []
        total_w = 0.0
        top = 0
        bottom = 0
        for text, family in norm_segments:
            font = self._get_linkstart_pil_font(qsize, family)
            for ch in text:
                bbox = dd.textbbox((0, 0), ch, font=font, stroke_width=qstroke)
                try:
                    advance = float(dd.textlength(ch, font=font))
                except Exception:
                    advance = float(max(1, bbox[2] - bbox[0]))
                if ch == ' ':
                    advance = max(advance, qsize * 0.32)
                glyphs.append((ch, font, bbox, total_w))
                total_w += max(1.0, advance) + tracking
                top = min(top, bbox[1])
                bottom = max(bottom, bbox[3])
        if glyphs:
            total_w -= tracking
        pad = int(max(14, qsize * 0.62 + blur_radius * 3.0 + qstroke * 2))
        w = max(8, int(math.ceil(total_w)) + pad * 2)
        h = max(8, bottom - top + pad * 2)

        def _draw_layer(color, blurred=False):
            layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            for ch, font, bbox, xoff in glyphs:
                d.text((pad + xoff - bbox[0], pad - top), ch, font=font, fill=color,
                       stroke_width=0 if blurred else qstroke,
                       stroke_fill=None if blurred else stroke_rgba)
            if blurred and blur_radius > 0.01:
                layer = layer.filter(ImageFilter.GaussianBlur(radius=max(0.5, blur_radius)))
            return layer

        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        if glow_rgba[3] > 0 and blur_radius > 0.01:
            img = Image.alpha_composite(img, _draw_layer(glow_rgba, blurred=True))
        img = Image.alpha_composite(img, _draw_layer(fill_rgba, blurred=False))
        self._ls_sprite_cache[key] = img
        return img

    def _calc_boot_panel_state(self, t: float):
        """计算 Web 同款启动框时序和屏幕矩形，供 GPU shader 使用。"""
        if t < 0.0 or t >= 1.58:
            return None
        if t < 0.16:
            opacity = t / 0.16
        elif t < 1.05:
            opacity = 1.0
        else:
            opacity = max(0.0, 1.0 - (t - 1.05) / 0.53)
        if opacity <= 0.02:
            return None

        sw = self._sw
        cx, cy = self._cx, self._cy
        p = max(0.0, min(1.0, t / 1.08))
        ep = ease_out(p)
        scale = lerp(0.88, 1.015, ep)
        panel_w = int(max(360, min(560, sw * 0.34)) * scale)
        panel_h = int(122 * scale)
        y_off = int(lerp(18, -10, ep))
        x0 = cx - panel_w // 2
        y0 = cy - panel_h // 2 + y_off
        x1 = x0 + panel_w
        y1 = y0 + panel_h
        return {
            'opacity': opacity,
            'progress': p,
            'scale': scale,
            'rect': (float(x0), float(y0), float(x1), float(y1)),
            'x0': x0,
            'y0': y0,
            'x1': x1,
            'y1': y1,
            'panel_w': panel_w,
            'panel_h': panel_h,
            'scan': (t * 0.82) % 1.0,
        }

    def _ensure_gl_boot_text_texture(self, state):
        """Boot text is pre-baked once; shader maps it into animated panel rect."""
        return

    def _ensure_gl_static_text_textures(self):
        """Pre-bake all GL text atlases once; animation frames only update uniforms."""
        if not self._gl_ctx or self._gl_ui_tex is None or self._gl_boot_text_tex is None:
            return
        sig = (self._sw, self._sh)
        if sig == self._gl_static_text_sig:
            return
        sw, sh = self._sw, self._sh
        cx, cy = self._cx, self._cy

        p2_img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
        text1 = self._make_gl_tracking_text(
            [('WELCOME TO', 'sao')], 42,
            (245, 248, 255, 255), (30, 44, 72, 150),
            (110, 232, 255, 155), 0, 4.0, 10)
        text2 = self._make_gl_tracking_text(
            [('咲 ', 'cjk'), ('MIDI PLAYER', 'sao')], 64,
            (255, 248, 236, 255), (30, 44, 72, 150),
            (255, 214, 120, 130), 0, 4.0, 4)
        gap = 8
        top = cy - (text1.height + gap + text2.height) // 2
        self._paste_gl_ui(p2_img, text1, cx, top, anchor='n')
        self._paste_gl_ui(p2_img, text2, cx, top + text1.height + gap, anchor='n')
        self._gl_ui_tex.write(p2_img.tobytes())
        self._gl_ui_img = None
        self._gl_ui_dirty = False

        if self._gl_connected_text_tex is not None:
            connected_img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
            main = self._make_gl_tracking_text(
                [('SYSTEM >> CONNECTED', 'sao')], 38,
                (234, 246, 255, 255), (30, 44, 72, 150),
                (170, 238, 255, 180), 0, 4.0, 8)
            sub = self._make_gl_tracking_text(
                [('FULL DIVE INITIALIZED', 'sao')], 15,
                (159, 216, 255, 220), (22, 34, 48, 120),
                (170, 238, 255, 120), 0, 3.0, 5)
            connected_top = cy - (main.height + 14 + sub.height) // 2
            self._paste_gl_ui(connected_img, main, cx, connected_top, anchor='n')
            self._paste_gl_ui(connected_img, sub, cx, connected_top + main.height + 14, anchor='n')
            self._gl_connected_text_tex.write(connected_img.tobytes())

        boot_w = max(360, min(560, int(sw * 0.34)))
        boot_h = 122
        boot_img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
        bx0 = cx - boot_w // 2
        by0 = cy - boot_h // 2
        bx1 = bx0 + boot_w
        by1 = by0 + boot_h
        row_size = 11
        title_size = max(30, min(48, int(sw * 0.035)))
        sub_size = 12
        self._paste_gl_ui(boot_img, self._make_gl_tracking_text(
            [('SYSTEM', 'sao')], row_size,
            (170, 238, 255, 210), (10, 24, 40, 150),
            (110, 232, 255, 120), 1, 2.0, 3),
            bx0 + 20, by0 + 17, anchor='nw')
        self._paste_gl_ui(boot_img, self._make_gl_tracking_text(
            [('[ LINK STANDBY ]', 'sao')], row_size,
            (255, 218, 116, 224), (34, 28, 14, 150),
            (255, 196, 82, 120), 1, 2.0, 3),
            bx1 - 20, by0 + 17, anchor='ne')
        self._paste_gl_ui(boot_img, self._make_gl_tracking_text(
            [('NErVGEAR', 'sao')], title_size,
            (242, 251, 255, 255), (10, 26, 42, 232),
            (110, 232, 255, 210), 2, 6.0,
            int(max(7, min(14, sw * 0.0092)))),
            cx, by0 + 61, anchor='center')
        self._paste_gl_ui(boot_img, self._make_gl_tracking_text(
            [('FULLDIVE AUTHENTICATION', 'sao')], sub_size,
            (255, 218, 132, 224), (34, 28, 14, 150),
            (255, 196, 82, 120), 1, 2.2, 4),
            cx, by1 - 17, anchor='s')
        self._gl_boot_text_tex.write(boot_img.tobytes())
        self._gl_boot_text_img = None
        self._gl_boot_sig = sig
        self._gl_boot_text_rect = (float(bx0), float(by0), float(bx1), float(by1))
        self._gl_static_text_sig = sig

    def _draw_gl_boot_panel_ui(self, img: Image.Image, t: float):
        """启动框 GL 模式由 shader 绘制；这里保留空实现供旧调用兼容。"""
        return

    def _draw_gl_text_layer_ui(self, img: Image.Image, scene_t: float):
        """Web text-layer 的 OpenGL UI 纹理版本：只保留文字，不再画 P2 外框。"""
        op = 0.0
        scale = 0.2
        if self._P2_START - 0.2 <= scene_t < self._P2_END + 0.3:
            if scene_t < 4.2:
                f = max(0.0, min(1.0, (scene_t - 3.5) / 0.7))
                op = f
                scale = lerp(0.2, 1.0, ease_out(f))
            elif scene_t < 4.7:
                op = 1.0
                scale = 1.0
            elif scene_t < 5.25:
                f = max(0.0, min(1.0, (scene_t - 4.7) / 0.55))
                op = 1.0 - f * 0.16
                scale = lerp(1.0, 3.8, ease_in(f))
            else:
                f = max(0.0, min(1.0, (scene_t - 5.25) / 0.25))
                op = (1.0 - f) * 0.84
                scale = lerp(3.8, 8.0, ease_in(f))
        if op <= 0.02:
            return

        cx, cy = self._cx, self._cy
        size1 = max(8, int(42 * scale))
        size2 = max(10, int(64 * scale))
        gap = int(8 * scale)
        text1 = self._make_gl_tracking_text(
            [('WELCOME TO', 'sao')], size1,
            (245, 248, 255, int(255 * op)), (30, 44, 72, int(150 * op)),
            (110, 232, 255, int(155 * op)), 0, max(2.0, 4.0 * scale), int(10 * scale))
        text2 = self._make_gl_tracking_text(
            [('咲 ', 'cjk'), ('MIDI PLAYER', 'sao')], size2,
            (255, 248, 236, int(255 * op)), (30, 44, 72, int(150 * op)),
            (255, 214, 120, int(130 * op)), 0, max(2.0, 4.0 * scale), int(4 * scale))
        total_h = text1.height + gap + text2.height
        top = cy - total_h // 2
        self._paste_gl_ui(img, text1, cx, top, anchor='n')
        self._paste_gl_ui(img, text2, cx, top + text1.height + gap, anchor='n')

    def _draw_gl_connected_layer_ui(self, img: Image.Image, scene_t: float):
        """Web connected-layer 的 OpenGL UI 纹理版本。"""
        op = 0.0
        if scene_t >= self._P4_START:
            if scene_t < 7.7:
                op = max(0.0, min(1.0, (scene_t - 7.3) / 0.4))
            elif scene_t < self._P4_HOLD_END:
                op = 1.0
            else:
                op = max(0.0, 1.0 - (scene_t - self._P4_HOLD_END) / max(0.01, self._P4_FADE_END - self._P4_HOLD_END))
        if op <= 0.02:
            return
        cx, cy = self._cx, self._cy
        main = self._make_gl_tracking_text(
            [('SYSTEM >> CONNECTED', 'sao')], 38,
            (234, 246, 255, int(255 * op)), (30, 44, 72, int(150 * op)),
            (170, 238, 255, int(180 * op)), 0, 4.0, 8)
        sub = self._make_gl_tracking_text(
            [('FULL DIVE INITIALIZED', 'sao')], 15,
            (159, 216, 255, int(220 * op)), (22, 34, 48, int(120 * op)),
            (170, 238, 255, int(120 * op)), 0, 3.0, 5)
        total_h = main.height + 14 + sub.height
        top = cy - total_h // 2
        self._paste_gl_ui(img, main, cx, top, anchor='n')
        self._paste_gl_ui(img, sub, cx, top + main.height + 14, anchor='n')

    def _calc_gl_p2_text_state(self, scene_t: float):
        """P2 text state for shader-only animation; no PIL/Tk work per frame."""
        op = 0.0
        scale = 1.0
        if self._P2_START - 0.2 <= scene_t < self._P2_END + 0.3:
            if scene_t < 4.2:
                f = max(0.0, min(1.0, (scene_t - 3.5) / 0.7))
                op = f
                scale = lerp(0.2, 1.0, ease_out(f))
            elif scene_t < 4.7:
                op = 1.0
                scale = 1.0
            elif scene_t < 5.25:
                f = max(0.0, min(1.0, (scene_t - 4.7) / 0.55))
                op = 1.0 - f * 0.16
                scale = lerp(1.0, 3.8, ease_in(f))
            else:
                f = max(0.0, min(1.0, (scene_t - 5.25) / 0.25))
                op = (1.0 - f) * 0.84
                scale = lerp(3.8, 8.0, ease_in(f))
        return max(0.0, min(1.0, op)), max(0.001, float(scale))

    def _calc_gl_connected_opacity(self, scene_t: float) -> float:
        """P4 connected text opacity for shader-only animation."""
        if scene_t < self._P4_START:
            return 0.0
        if scene_t < 7.7:
            return max(0.0, min(1.0, (scene_t - 7.3) / 0.4))
        if scene_t < self._P4_HOLD_END:
            return 1.0
        return max(0.0, 1.0 - (scene_t - self._P4_HOLD_END) / max(0.01, self._P4_FADE_END - self._P4_HOLD_END))

    def _calc_p3_p4_fx_state(self, scene_t: float, p3_fade: float = 1.0):
        """Continuous cool-blue background FX through the P3→P4 handoff."""
        p3_dur = self._P3_END - self._P3_START
        p3_t = scene_t - self._P3_START
        exit_elapsed = max(0.0, scene_t - self._P3_END)
        phase = max(0.0, min(1.0, p3_t / max(0.01, p3_dur)))
        exit_tail = max(0.0, min(1.0, exit_elapsed / 0.55))
        smooth_tail = exit_tail * exit_tail * (3.0 - 2.0 * exit_tail)
        exit_keep = 1.0 - smooth_tail
        in_flash = max(0.0, 1.0 - p3_t / 0.70) * 0.18
        exit_flash = min(0.24, exit_elapsed * 0.52) * exit_keep
        base_energy = 0.20 + 0.80 * phase
        run_energy = p3_fade * base_energy * (exit_keep if scene_t >= self._P3_END else 1.0)
        exit_energy = p3_fade * min(0.38, exit_elapsed * 0.70) * exit_keep
        p4_floor = 0.12 * smooth_tail if scene_t >= self._P3_END else 0.0
        if scene_t >= self._P3_END:
            energy = max(0.12, run_energy + exit_energy + p4_floor)
        else:
            energy = run_energy
        motion_mix = 0.60 + 0.32 * exit_tail if exit_elapsed > 0.0 else 0.60
        return energy, in_flash + exit_flash, (0.45, 0.80, 1.00), motion_mix

    def _render_gl_ui_layer(self, elapsed: float, scene_t: float):
        """Ensure static GL text atlases exist; per-frame text animation is shader-only."""
        if not self._gl_ctx or self._gl_ui_tex is None:
            return
        self._ensure_gl_static_text_textures()

    def _postprocess_gl_scene(self, elapsed: float = 0.0):
        """把 scene FBO + history + UI texture 做最终后处理，结果留在 ping-pong 纹理。"""
        ctx = self._gl_ctx
        sw, sh = self._sw, self._sh
        scene_t = elapsed - self._STARTUP_PRELUDE
        self._ensure_gl_static_text_textures()

        boot_state = self._calc_boot_panel_state(max(0.0, elapsed))
        p2_opacity, p2_scale = self._calc_gl_p2_text_state(scene_t)
        connected_opacity = self._calc_gl_connected_opacity(scene_t)

        pf = self._gl_pframe
        write_fbo = self._gl_pfbo_a if (pf & 1) == 0 else self._gl_pfbo_b
        prev_tex = self._gl_ptex_b if (pf & 1) == 0 else self._gl_ptex_a

        write_fbo.use()
        ctx.disable(moderngl.DEPTH_TEST)
        self._gl_color_tex.use(location=0)
        prev_tex.use(location=1)
        if self._gl_ui_tex is not None:
            self._gl_ui_tex.use(location=2)
        if self._gl_boot_text_tex is not None:
            self._gl_boot_text_tex.use(location=3)
        if self._gl_connected_text_tex is not None:
            self._gl_connected_text_tex.use(location=4)
        self._gl_postprog['u_cur'].value = 0
        self._gl_postprog['u_prv'].value = 1
        self._gl_postprog['u_ui'].value = 2
        self._gl_postprog['u_boot_text'].value = 3
        self._gl_postprog['u_connected_text'].value = 4
        self._gl_postprog['u_ca'].value = self._gl_ca_uv
        self._gl_postprog['u_fx_energy'].value = float(getattr(self, '_gl_fx_energy', 0.0))
        self._gl_postprog['u_fx_flash'].value = float(getattr(self, '_gl_fx_flash', 0.0))
        self._gl_postprog['u_fx_tint'].value = tuple(getattr(self, '_gl_fx_tint', (0.95, 0.85, 0.35)))
        self._gl_postprog['u_ui_alpha'].value = 1.0
        self._gl_postprog['u_motion_mix'].value = float(getattr(self, '_gl_motion_mix', 0.60))
        self._gl_postprog['u_resolution'].value = (float(sw), float(sh))
        if boot_state:
            self._gl_postprog['u_boot_rect'].value = boot_state['rect']
            self._gl_postprog['u_boot_opacity'].value = float(boot_state['opacity'])
            self._gl_postprog['u_boot_progress'].value = float(boot_state['progress'])
            self._gl_postprog['u_boot_scan'].value = float(boot_state['scan'])
            self._gl_postprog['u_boot_text_rect'].value = self._gl_boot_text_rect
        else:
            self._gl_postprog['u_boot_rect'].value = (0.0, 0.0, 0.0, 0.0)
            self._gl_postprog['u_boot_opacity'].value = 0.0
            self._gl_postprog['u_boot_progress'].value = 0.0
            self._gl_postprog['u_boot_scan'].value = 0.0
            self._gl_postprog['u_boot_text_rect'].value = (0.0, 0.0, 0.0, 0.0)
        self._gl_postprog['u_p2_center'].value = (float(self._cx), float(self._cy))
        self._gl_postprog['u_p2_opacity'].value = float(p2_opacity)
        self._gl_postprog['u_p2_scale'].value = float(p2_scale)
        self._gl_postprog['u_connected_opacity'].value = float(connected_opacity)
        self._gl_postvao.render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self._gl_pframe = pf + 1

        return write_fbo

    def _present_gl_scene(self, cv: tk.Canvas, elapsed: float = 0.0):
        """把 scene FBO + history + UI texture 做最终后处理并读回给 Tk 仅展示。"""
        write_fbo = self._postprocess_gl_scene(elapsed)
        if write_fbo is None:
            return
        if cv is None:
            return
        sw, sh = self._sw, self._sh

        raw = write_fbo.read(components=3)
        img = Image.frombuffer('RGB', (sw, sh), raw, 'raw', 'RGB', 0, -1)
        if getattr(self, '_gl_photo', None) is None or getattr(self, '_gl_photo_size', None) != (sw, sh):
            self._gl_photo = ImageTk.PhotoImage(image=img)
            self._gl_photo_size = (sw, sh)
        else:
            self._gl_photo.paste(img)
        if getattr(self, '_gl_canvas_item', None) is None:
            self._gl_canvas_item = cv.create_image(0, 0, image=self._gl_photo, anchor='nw')
        else:
            try:
                cv.itemconfigure(self._gl_canvas_item, image=self._gl_photo)
            except Exception:
                self._gl_canvas_item = cv.create_image(0, 0, image=self._gl_photo, anchor='nw')

    def _draw_startup_gl(self, cv: tk.Canvas, bg: str, t: float = 0.0):
        """启动扫描前奏专用 GPU 渲染：只跑背景 shader，避免几何与后处理拖慢 FPS。"""
        if not self._gl_ctx:
            return
        ctx = self._gl_ctx
        sw, sh = self._sw, self._sh
        bgr, bgg, bgb = hex_to_rgb(bg)
        bg_norm = (bgr / 255.0, bgg / 255.0, bgb / 255.0)

        self._gl_fbo.use()
        ctx.clear(bg_norm[0], bg_norm[1], bg_norm[2], 1.0)
        ctx.disable(moderngl.DEPTH_TEST)
        self._gl_bg_prog['u_time'].value = t
        self._gl_bg_prog['u_energy'].value = float(getattr(self, '_gl_fx_energy', 0.0))
        self._gl_bg_prog['u_flash'].value = float(getattr(self, '_gl_fx_flash', 0.0))
        self._gl_bg_prog['u_startburst'].value = float(getattr(self, '_gl_start_burst', 0.0))
        self._gl_bg_prog['u_startwave'].value = float(getattr(self, '_gl_start_wave', 0.0))
        self._gl_bg_prog['u_bg_color'].value = bg_norm
        self._gl_bg_prog['u_tint'].value = tuple(getattr(self, '_gl_fx_tint', (0.95, 0.85, 0.35)))
        self._gl_bg_prog['u_aspect'].value = sw / max(1.0, float(sh))
        self._gl_bg_prog['u_resolution'].value = (float(sw), float(sh))
        self._gl_bg_vao.render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self._present_gl_scene(cv, elapsed=t)

    def _draw_tunnel_gl(self, cv: tk.Canvas, particles: list,
                        cam_z: float, bg: str, fade: float = 1.0,
                        t: float = 0.0,
                        motion_blur: float = 0.0,
                        cam_velocity: float = 0.0):
        """
        使用 ModernGL 渲染真 3D 圆柱体隧道.

        每根粒子 = 一根小圆柱管, 分布在大圆柱隧道表面.
        光源在隧道中轴 = 所有管子内侧受光, 外侧暗.
        Blinn-Phong + Fresnel rim = 逼真 3D 质感.
        深度缓冲自动处理 Z 排序, 粒子自然飞出屏幕.
        """
        ctx = self._gl_ctx
        sw, sh = self._sw, self._sh
        bgr, bgg, bgb = hex_to_rgb(bg)
        bg_norm = (bgr / 255.0, bgg / 255.0, bgb / 255.0)

        rot = t * 0.06
        streak_h = self._STREAK_H
        tube_r = self._GL_TUBE_RADIUS

        # ── 构建 instance data ──
        inst_data = []
        count = 0
        for p in particles:
            if count >= self._gl_max_inst:
                break

            d = p['d']
            z_near = d - cam_z
            z_far = (d + streak_h) - cam_z

            # 完全在摄像机后方 → 跳过
            if z_far <= 0.5:
                continue
            # 太远 → 跳过
            if z_near > 5000:
                continue

            r = p['r']
            # 管子中心位置 (旋转前, 旋转在 shader 中做)
            cx_p = r * p['cos']
            cy_p = r * p['sin']

            # ── alpha ──
            alpha = fade
            bright = p.get('brightness', 1.0)
            flkr = p.get('flicker_freq', 5.0)
            shimmer = 0.85 + 0.15 * math.sin(t * flkr + d * 0.005)
            alpha *= bright * shimmer
            if alpha < 0.02:
                continue

            # ── 深度雾 ──
            fog = 0.0
            if z_near > 150:
                fog = min(0.95, (z_near - 150) / 2200.0)

            # ── 颜色 → [0,1] ──
            cr, cg, cb = hex_to_rgb(p['color'])

            # ── 管子半径随 width_mult 缩放 ──
            wmult = p.get('width_mult', 1.0)
            actual_r = tube_r * wmult

            # instance: center(3) + len(1) + radius(1) + color(3) + alpha(1) + fog(1)
            inst_data.extend([
                cx_p, cy_p, d,
                streak_h,
                actual_r,
                cr / 255.0, cg / 255.0, cb / 255.0,
                alpha,
                fog
            ])
            count += 1

        # ── 渲染 ──
        self._gl_fbo.use()
        ctx.clear(bg_norm[0], bg_norm[1], bg_norm[2], 1.0)
        ctx.disable(moderngl.DEPTH_TEST)
        self._gl_bg_prog['u_time'].value = t
        self._gl_bg_prog['u_energy'].value = float(getattr(self, '_gl_fx_energy', 0.0))
        self._gl_bg_prog['u_flash'].value = float(getattr(self, '_gl_fx_flash', 0.0))
        self._gl_bg_prog['u_startburst'].value = float(getattr(self, '_gl_start_burst', 0.0))
        self._gl_bg_prog['u_startwave'].value = float(getattr(self, '_gl_start_wave', 0.0))
        self._gl_bg_prog['u_bg_color'].value = bg_norm
        self._gl_bg_prog['u_tint'].value = tuple(getattr(self, '_gl_fx_tint', (0.95, 0.85, 0.35)))
        self._gl_bg_vao.render(moderngl.TRIANGLES, vertices=3)
        if count > 0:
            # ── 上传 instance data ──
            inst_np = np.array(inst_data, dtype='f4')
            self._gl_inst_buf.write(inst_np.tobytes())

            # ── 设置 uniforms ──
            vp = self._build_vp_matrix(cam_z)
            self._gl_prog['u_vp'].write(vp.tobytes())
            self._gl_prog['u_rot'].value = rot
            self._gl_prog['u_cam_pos'].value = (0.0, 0.0, cam_z)
            self._gl_prog['u_bg_color'].value = bg_norm
            self._gl_prog['u_alpha_mul'].value = 1.0
            self._gl_prog['u_radius_mul'].value = 1.0

            blur_strength = max(0.0, min(1.0, float(motion_blur)))
            blur_speed = float(cam_velocity)
            if blur_strength > 0.01 and abs(blur_speed) > 1.0:
                # 额外 ghost-pass：不跳帧、不降 FPS，只在同一帧内画两层较旧相机位置，
                # 模拟 Web/GPU 风格的柱体速度拖影。
                ctx.disable(moderngl.DEPTH_TEST)
                for steps, alpha_mul, scale_mul in ((0.55, 0.30, 1.055), (1.05, 0.16, 1.095)):
                    ghost_cam_z = cam_z - blur_speed * (steps / 60.0)
                    ghost_vp = self._build_vp_matrix(ghost_cam_z)
                    self._gl_prog['u_vp'].write(ghost_vp.tobytes())
                    self._gl_prog['u_cam_pos'].value = (0.0, 0.0, ghost_cam_z)
                    self._gl_prog['u_alpha_mul'].value = alpha_mul * blur_strength
                    self._gl_prog['u_radius_mul'].value = scale_mul
                    self._gl_vao.render(moderngl.TRIANGLES,
                                        vertices=self._gl_num_verts,
                                        instances=count)
                self._gl_prog['u_vp'].write(vp.tobytes())
                self._gl_prog['u_cam_pos'].value = (0.0, 0.0, cam_z)
                self._gl_prog['u_alpha_mul'].value = 1.0
                self._gl_prog['u_radius_mul'].value = 1.0
                ctx.enable(moderngl.DEPTH_TEST)
            else:
                ctx.enable(moderngl.DEPTH_TEST)
            self._gl_vao.render(moderngl.TRIANGLES,
                                vertices=self._gl_num_verts,
                                instances=count)
        else:
            ctx.enable(moderngl.DEPTH_TEST)

        # ── GPU 后处理: 色差 + 运动模糊 + 透明 UI 层 (全在显卡内完成) ──
        self._present_gl_scene(cv, elapsed=getattr(self, '_gl_elapsed', t))

    def _render_linkstart_gl_frame(self, elapsed: float, target_fbo=None, readback_canvas=None) -> bool:
        """按当前时间线渲染一帧 GL LinkStart；target_fbo 保留给直出路径。"""
        if not self._gl_ctx:
            return False
        scene_t = elapsed - self._STARTUP_PRELUDE
        bg = self._calc_bg(max(0.0, scene_t))
        self._render_gl_ui_layer(elapsed, scene_t)
        rendered = False

        if scene_t < 0.0:
            startup_t = max(0.0, elapsed)
            startup_burst = max(0.0, 1.0 - startup_t / 0.52)
            startup_wave = min(1.0, startup_t / self._STARTUP_PRELUDE)
            self._gl_start_burst = startup_burst
            self._gl_start_wave = startup_wave
            self._gl_fx_energy = startup_wave * 0.18
            self._gl_fx_flash = max(0.0, 1.0 - startup_t / self._STARTUP_PRELUDE) * 0.42 + startup_burst * 0.30
            self._gl_fx_tint = (0.96, 0.78, 0.24)
            self._draw_startup_gl(readback_canvas, bg, t=elapsed)
            rendered = True

        if not rendered and scene_t < self._P1_END + 0.5:
            particle_fade = 1.0
            if scene_t < 0.28:
                particle_fade = lerp(0.22, 0.62, ease_out(scene_t / 0.28))
            elif scene_t < 1.0:
                particle_fade = lerp(0.62, 1.0, ease_out((scene_t - 0.28) / 0.72))
            exit_elapsed = max(0.0, scene_t - self._P1_END)
            cam_z = self._cam_z_with_exit(scene_t, self._CAM_DURATION, self._P1_END, 0.5)
            cam_velocity = self._cam_z_end_velocity(self._CAM_DURATION)
            startup_bridge_t = min(self._STARTUP_PRELUDE + 0.64, elapsed)
            startup_burst = max(0.0, 1.0 - startup_bridge_t / 1.06)
            startup_wave = min(1.0, startup_bridge_t / (self._STARTUP_PRELUDE + 0.64))
            self._gl_start_burst = startup_burst
            self._gl_start_wave = startup_wave
            self._gl_fx_energy = min(1.0, particle_fade * (0.20 + 0.88 * min(1.0, scene_t / max(0.01, self._CAM_DURATION)) + exit_elapsed * 0.55) + startup_burst * 0.28)
            self._gl_fx_flash = max(0.0, 1.0 - startup_bridge_t / 1.08) * 0.30 + startup_burst * 0.28 + min(0.22, exit_elapsed * 0.38)
            self._gl_fx_tint = (0.96, 0.78, 0.24)
            if readback_canvas is not None:
                self._draw_tunnel_gl(readback_canvas, self._color_particles, cam_z, bg,
                                     particle_fade, t=scene_t,
                                     motion_blur=0.70, cam_velocity=cam_velocity)
            else:
                self._gl_elapsed = elapsed
                self._draw_tunnel_gl(None, self._color_particles, cam_z, bg,
                                     particle_fade, t=scene_t,
                                     motion_blur=0.70, cam_velocity=cam_velocity)
            rendered = True

        if self._P3_START <= scene_t < self._P3_END + 0.55:
            p3_fade = 1.0
            if scene_t < self._P3_START + 0.5:
                p3_fade = (scene_t - self._P3_START) / 0.5
            exit_elapsed = max(0.0, scene_t - self._P3_END)
            p3_t = scene_t - self._P3_START
            p3_dur = self._P3_END - self._P3_START
            cam_z = self._cam_z_with_exit(p3_t, p3_dur, p3_dur, 0.55)
            cam_velocity = self._cam_z_end_velocity(p3_dur)
            self._gl_start_burst = 0.0
            self._gl_start_wave = 1.0
            self._gl_fx_energy, self._gl_fx_flash, self._gl_fx_tint, self._gl_motion_mix = self._calc_p3_p4_fx_state(scene_t, p3_fade)
            if readback_canvas is not None:
                self._draw_tunnel_gl(readback_canvas, self._blue_particles, cam_z, bg,
                                     p3_fade, t=scene_t,
                                     motion_blur=0.78, cam_velocity=cam_velocity)
            else:
                self._gl_elapsed = elapsed
                self._draw_tunnel_gl(None, self._blue_particles, cam_z, bg,
                                     p3_fade, t=scene_t,
                                     motion_blur=0.78, cam_velocity=cam_velocity)
            rendered = True

        if not rendered:
            self._gl_start_burst = 0.0
            self._gl_start_wave = 1.0
            if scene_t >= self._P3_START:
                self._gl_fx_energy, self._gl_fx_flash, self._gl_fx_tint, self._gl_motion_mix = self._calc_p3_p4_fx_state(scene_t, 0.0)
            else:
                self._gl_fx_energy = 0.12
                self._gl_fx_flash = 0.0
                self._gl_fx_tint = (0.96, 0.78, 0.24)
                self._gl_motion_mix = 0.60
            self._draw_startup_gl(readback_canvas, bg, t=elapsed)
            rendered = True

        return rendered

    # ════════════════════════════════════════════════════════
    #  Canvas 2D 回退渲染
    # ════════════════════════════════════════════════════════
    def _draw_tunnel_canvas(self, cv: tk.Canvas, particles: list,
                            cam_z: float, bg: str, fade: float = 1.0,
                            t: float = 0.0):
        """Canvas 回退: 锥形多边形 + 屏幕空间高光."""
        cx, cy = self._cx, self._cy
        focal = self._FOCAL
        sw, sh = self._sw, self._sh
        streak_h = self._STREAK_H
        bgr, bgg, bgb = hex_to_rgb(bg)

        rot = t * 0.06
        cos_rot, sin_rot = math.cos(rot), math.sin(rot)

        items = []
        for p in particles:
            d = p['d']
            z_near = d - cam_z
            z_far = (d + streak_h) - cam_z

            if z_far <= 2.0:
                continue
            if z_near > 5000:
                continue
            # 摄像机已穿过圆柱体起点 → 跳过, 防止 s_near 爆炸成巨型色块
            if z_near < 1.0:
                continue

            z_near_c = max(5.0, z_near)
            z_far_c = max(5.0, z_far)

            s_near = focal / z_near_c
            s_far = focal / z_far_c

            r = p['r']
            c0, s0 = p['cos'], p['sin']
            cos_t = c0 * cos_rot - s0 * sin_rot
            sin_t = c0 * sin_rot + s0 * cos_rot

            x_near = cx + r * cos_t * s_near
            y_near = cy + r * sin_t * s_near
            x_far = cx + r * cos_t * s_far
            y_far = cy + r * sin_t * s_far

            margin = 800
            if (x_near < -margin and x_far < -margin) or \
               (x_near > sw + margin and x_far > sw + margin) or \
               (y_near < -margin and y_far < -margin) or \
               (y_near > sh + margin and y_far > sh + margin):
                continue

            wmult = p.get('width_mult', 1.0)
            alpha = fade

            depth_fog = 0.0
            if z_near > 150:
                depth_fog = min(0.95, (z_near - 150) / 2200.0)

            bright = p.get('brightness', 1.0)
            flkr = p.get('flicker_freq', 5.0)
            shimmer = 0.85 + 0.15 * math.sin(t * flkr + d * 0.005)
            alpha *= bright * shimmer
            if alpha < 0.08:
                continue

            sort_z = max(5.0, z_near)

            # 用负値作第一元素就地插入倒序键, 避免 sort 时的 lambda 开销
            items.append((-sort_z, x_far, y_far, x_near, y_near,
                          s_near, s_far, wmult,
                          p['rgb'], alpha, depth_fog))

        items.sort()   # 第一元素已是 -z, 升序 = 远到近

        for (neg_z, x1, y1, x2, y2, sn, sf, wmult,
             rgb, a, fog) in items:
            if a < 0.03:
                continue
            cr, cg, cb = rgb

            if fog > 0.01:
                cr = int(lerp(cr, bgr, fog))
                cg = int(lerp(cg, bgg, fog))
                cb = int(lerp(cb, bgb, fog))
                gray = (cr + cg + cb) // 3
                desat = fog * 0.5
                cr = int(lerp(cr, gray, desat))
                cg = int(lerp(cg, gray, desat))
                cb = int(lerp(cb, gray, desat))

            if a < 0.95:
                mr = int(lerp(bgr, cr, a))
                mg = int(lerp(bgg, cg, a))
                mb = int(lerp(bgb, cb, a))
                fill_c = rgb_to_hex(mr, mg, mb)
            else:
                fill_c = rgb_to_hex(cr, cg, cb)

            w = max(1, min(40, int(3.5 * sn * wmult)))
            cv.create_line(x1, y1, x2, y2, fill=fill_c,
                           width=w, capstyle='round')

    # ════════════════════════════════════════════════════════
    #  主动画循环
    # ════════════════════════════════════════════════════════
    def _animate(self):
        _t0 = time.perf_counter()  # 帧计时起点
        if getattr(self, '_gpu_present_enabled', False):
            if not self._gpu_present_window:
                self._finish()
                return
            if getattr(self, '_gpu_present_done', False):
                self._finish()
                return
        elif not self._overlay or not self._overlay.winfo_exists():
            return

        elapsed = time.time() - self._start_time
        scene_t = elapsed - self._STARTUP_PRELUDE
        self._gl_elapsed = elapsed
        if scene_t > self._DURATION:
            self._finish()
            return
        if getattr(self, '_gpu_present_enabled', False):
            try:
                if not self._gpu_present_frame_requested:
                    self._gpu_present_frame_requested = True
                    self._gpu_present_window.request_redraw()
            except Exception as e:
                print(f'[LinkStart] GPU present request failed: {e}')
                self._finish()
                return
            return

        self._animate_canvas_frame(elapsed, scene_t)

    def _animate_canvas_frame(self, elapsed: float, scene_t: float):
        """Tk/Canvas 或非直出 GL 的单帧渲染；直出 GPU 不走这里。"""
        cv = self._canvas
        sw, sh = self._sw, self._sh
        use_gl = self._gl_ctx is not None
        if not use_gl:
            cv.delete('all')

        # ── 背景 ──
        bg = self._calc_bg(max(0.0, scene_t))
        if use_gl:
            self._render_gl_ui_layer(elapsed, scene_t)
        else:
            cv.create_rectangle(0, 0, sw, sh, fill=bg, outline='')
            self._draw_global_bloom_cv(cv, elapsed, bg)
        text_active = self._P2_START - 0.2 <= scene_t < self._P2_END + 0.3
        text_state = self._get_text_phase_state(scene_t) if text_active else None
        rendered_gl_scene = False

        # ── Startup prelude: 扫描环/光阀先完成, 再进入 P1 ──
        if scene_t < 0.0:
            startup_t = max(0.0, elapsed)
            startup_burst = max(0.0, 1.0 - startup_t / 0.52)
            startup_wave = min(1.0, startup_t / self._STARTUP_PRELUDE)
            self._gl_start_burst = startup_burst
            self._gl_start_wave = startup_wave
            self._gl_fx_energy = startup_wave * 0.18
            self._gl_fx_flash = max(0.0, 1.0 - startup_t / self._STARTUP_PRELUDE) * 0.42 + startup_burst * 0.30
            self._gl_fx_tint = (0.96, 0.78, 0.24)
            if self._gl_ctx:
                self._draw_startup_gl(cv, bg, t=elapsed)
                rendered_gl_scene = True
            else:
                self._draw_start_aperture_cv(cv, startup_t, bg)
                self._draw_start_connect_cv(cv, startup_t, bg)
                self._draw_entry_burst_cv(cv, startup_t, bg)
                self._draw_start_nervegear_panel_cv(cv, startup_t, bg)
            self._schedule_next_frame()
            return

        # ── Phase 1: 彩色隧道 (0 ~ P1_END) ──
        if scene_t < self._P1_END + 0.5:
            # 粒子淡入: 0~0.5s 不可见, 0.5~1.5s 渐入
            particle_fade = 1.0
            if scene_t < 0.28:
                particle_fade = lerp(0.22, 0.62, ease_out(scene_t / 0.28))
            elif scene_t < 1.0:
                particle_fade = lerp(0.62, 1.0, ease_out((scene_t - 0.28) / 0.72))
            exit_elapsed = max(0.0, scene_t - self._P1_END)

            # 使用原始 _CAM_DURATION (3.5s) 保持与 P3 相同的飞行速度.
            # z_near < 1.0 的近裁剪guard已处理摄像机追上粒子的情况 → 直接跳过不渲染.
            cam_z = self._cam_z_with_exit(scene_t, self._CAM_DURATION, self._P1_END, 0.5)
            cam_velocity = self._cam_z_end_velocity(self._CAM_DURATION)

            # 粒子隧道
            startup_bridge_t = min(self._STARTUP_PRELUDE + 0.64, elapsed)
            startup_burst = max(0.0, 1.0 - startup_bridge_t / 1.06)
            startup_wave = min(1.0, startup_bridge_t / (self._STARTUP_PRELUDE + 0.64))
            self._gl_start_burst = startup_burst
            self._gl_start_wave = startup_wave
            self._gl_fx_energy = min(1.0, particle_fade * (0.20 + 0.88 * min(1.0, scene_t / max(0.01, self._CAM_DURATION)) + exit_elapsed * 0.55) + startup_burst * 0.28)
            self._gl_fx_flash = max(0.0, 1.0 - startup_bridge_t / 1.08) * 0.30 + startup_burst * 0.28 + min(0.22, exit_elapsed * 0.38)
            self._gl_fx_tint = (0.96, 0.78, 0.24)
            if not self._gl_ctx:
                self._draw_focus_flow_cv(cv, scene_t, self._CAM_DURATION,
                                         particle_fade, bg, warm=True)
            self._draw_tunnel(cv, self._color_particles, cam_z, bg,
                              particle_fade, t=scene_t,
                              motion_blur=0.70,
                              cam_velocity=cam_velocity)
            if self._gl_ctx:
                rendered_gl_scene = True

            # P1 HUD 角标叠加
            if not self._gl_ctx:
                self._draw_tunnel_hud_overlay(cv, scene_t, particle_fade, warm=True)

            # P1 收尾: 暗色圆形从中心扩张扫过, 盖住未飞出的圆柱体
            if scene_t >= self._P1_END - 0.05 and not self._gl_ctx:
                self._draw_p1_circle_wipe(cv, scene_t)

        if elapsed < 1.58 and not self._gl_ctx:
            self._draw_start_nervegear_panel_cv(cv, elapsed, bg)

        # ── Phase 2 underlay: 先画底层 flare / frame，避免在 P3 重叠时盖住圆柱 ──
        if text_state and not self._gl_ctx:
            self._draw_text_phase_underlay(cv, scene_t, text_state)

        # ── Phase 3: 蓝色隧道 (5.2 ~ 7.5s + exit overshoot) ──
        if self._P3_START <= scene_t < self._P3_END + 0.55:
            p3_fade = 1.0
            if scene_t < self._P3_START + 0.5:
                p3_fade = (scene_t - self._P3_START) / 0.5
            exit_elapsed = max(0.0, scene_t - self._P3_END)

            p3_t = scene_t - self._P3_START
            p3_dur = self._P3_END - self._P3_START  # = 2.3s, 确保摄像机在相结束前走完全程
            cam_z = self._cam_z_with_exit(p3_t, p3_dur, p3_dur, 0.55)
            cam_velocity = self._cam_z_end_velocity(p3_dur)
            self._gl_start_burst = 0.0
            self._gl_start_wave = 1.0
            self._gl_fx_energy, self._gl_fx_flash, self._gl_fx_tint, self._gl_motion_mix = self._calc_p3_p4_fx_state(scene_t, p3_fade)
            if not self._gl_ctx:
                self._draw_focus_flow_cv(cv, p3_t, p3_dur,
                                         p3_fade, bg, warm=False)
            self._draw_tunnel(cv, self._blue_particles, cam_z, bg,
                              p3_fade, t=scene_t,
                              motion_blur=0.78,
                              cam_velocity=cam_velocity)
            if self._gl_ctx:
                rendered_gl_scene = True

            # P3 HUD 角标叠加
            if not self._gl_ctx:
                self._draw_tunnel_hud_overlay(cv, scene_t, p3_fade, warm=False)

        if self._gl_ctx and not rendered_gl_scene:
            if scene_t >= self._P3_START:
                self._gl_fx_energy, self._gl_fx_flash, self._gl_fx_tint, self._gl_motion_mix = self._calc_p3_p4_fx_state(scene_t, 0.0)
            else:
                self._gl_motion_mix = 0.60
            self._draw_startup_gl(cv, bg, t=elapsed)
            rendered_gl_scene = True

        # ── Phase 2 overlay: HUD / text 保持可见，但不把底层纹波放到圆柱体上方 ──
        if text_state and not self._gl_ctx:
            self._render_text_phase(cv, scene_t, text_state)

        # ── Phase 4: 渐隐 (7.3 ~ 9.0s) ──
        if scene_t >= self._P4_START and not self._gl_ctx:
            self._draw_whiteout_cv(cv, scene_t)
            self._draw_connected_overlay(cv, scene_t)
        elif scene_t >= self._P4_START:
            if scene_t >= self._DURATION - 1.5:
                ft = min(1.0, (scene_t - (self._DURATION - 1.5)) / 1.5)
                al = max(0.0, 0.92 * (1.0 - ease_in_out(ft)))
                try:
                    self._overlay.attributes('-alpha', al)
                except Exception:
                    pass

        self._schedule_next_frame()

    def _schedule_next_frame(self):
        """用绝对 deadline 调度下一帧，避免 Tk after 累计漂移。"""
        if getattr(self, '_gpu_present_enabled', False):
            if not self._gpu_present_window:
                return
        elif not self._overlay or not self._overlay.winfo_exists():
            return
        frame_sec = 1.0 / max(1.0, float(getattr(self, '_target_refresh_hz', 60.0)))
        now = time.perf_counter()
        deadline = getattr(self, '_next_frame_deadline', 0.0)
        if deadline <= 0.0 or deadline < now - frame_sec:
            deadline = now
        deadline += frame_sec
        self._next_frame_deadline = deadline
        delay_ms = max(1, int((deadline - now) * 1000.0))
        target = self.root if getattr(self, '_gpu_present_enabled', False) else self._overlay
        target.after(delay_ms, self._animate)

    # ════════════════════════════════════════════════════════
    #  背景颜色
    # ════════════════════════════════════════════════════════
    def _calc_bg(self, t: float) -> str:
        """背景: 深色开始, 微微变亮, 给粒子对比度"""
        if t < 0.12:
            return '#02040a'
        elif t < 0.72:
            return lerp_color('#02040a', '#16213e', (t - 0.12) / 0.60)
        elif t < 1.0:
            return '#16213e'
        elif t < 3.0:
            return '#16213e'
        elif t < 3.5:
            return lerp_color('#16213e', '#2a2a3a', (t - 3.0) / 0.5)
        elif t < 5.2:
            return '#2a2a3a'
        elif t < 5.7:
            return lerp_color('#2a2a3a', '#0a1628', (t - 5.2) / 0.5)
        elif t < 7.0:
            return '#0a1628'
        elif t < 7.5:
            return lerp_color('#0a1628', '#1a2a4a', (t - 7.0) / 0.5)
        else:
            return '#1a2a4a'

    def _blend_over_bg(self, bg_hex: str, fg_rgb: tuple, alpha: float) -> str:
        """将目标颜色按 alpha 混到当前背景上, 避免 Canvas 特效显得生硬."""
        alpha = max(0.0, min(1.0, alpha))
        br, bg, bb = hex_to_rgb(bg_hex)
        fr, fg, fb = fg_rgb
        return rgb_to_hex(
            int(lerp(br, fr, alpha)),
            int(lerp(bg, fg, alpha)),
            int(lerp(bb, fb, alpha)),
        )

    def _draw_start_aperture_cv(self, cv: tk.Canvas, t: float, bg: str):
        """Canvas 回退的中心光阀: 从一条水平狭缝快速扩张成椭圆视域."""
        if t < 0.0 or t > 0.72:
            return

        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh
        p = max(0.0, min(1.0, t / 0.72))
        aperture = ease_out(min(1.0, p / 0.42))
        contract = max(0.0, 1.0 - p / 0.20)
        fade_t = max(0.0, min(1.0, (p - 0.56) / 0.42))
        fade = 1.0 - ease_in_out(fade_t)

        slit_w = int(lerp(sw * 0.10, sw * 0.88, aperture))
        slit_h = int(lerp(4, sh * 0.30, aperture))
        slit_h = max(2, slit_h - int(contract * 10))
        shade_alpha = max(0.0, 0.46 * fade + contract * 0.16)
        shade = self._blend_over_bg(bg, (0, 0, 0), shade_alpha)
        cv.create_rectangle(0, 0, sw, max(0, cy - slit_h), fill=shade, outline='')
        cv.create_rectangle(0, min(sh, cy + slit_h), sw, sh, fill=shade, outline='')

        for idx, mul in enumerate((1.00, 1.38, 1.82)):
            alpha = fade * (0.18 - idx * 0.05) + contract * (0.10 - idx * 0.03)
            if alpha <= 0.01:
                continue
            cv.create_oval(
                cx - int(slit_w * mul), cy - int(slit_h * (0.95 + idx * 0.30)),
                cx + int(slit_w * mul), cy + int(slit_h * (0.95 + idx * 0.30)),
                fill=self._blend_over_bg(bg, (230 - idx * 34, 242 - idx * 10, 255), alpha),
                outline='')

        line_alpha = 0.12 + contract * 0.46 + fade * 0.16
        flare_half = int(lerp(sw * 0.08, sw * 0.36, aperture))
        for off, mul in [(-4, 0.12), (-2, 0.22), (0, 0.56), (2, 0.22), (4, 0.12)]:
            alpha = line_alpha * mul
            if alpha <= 0.02:
                continue
            half = int(flare_half * (1.0 - abs(off) * 0.06))
            cv.create_line(cx - half, cy + off, cx + half, cy + off,
                           fill=self._blend_over_bg(bg, (244, 248, 255), alpha),
                           width=1 if off else 2)

        feather_alpha = fade * 0.24
        if feather_alpha > 0.02:
            feather = self._blend_over_bg(bg, (120, 218, 255), feather_alpha)
            cv.create_line(0, cy - slit_h, sw, cy - slit_h, fill=feather, width=1)
            cv.create_line(0, cy + slit_h, sw, cy + slit_h, fill=feather, width=1)

    def _draw_entry_burst_cv(self, cv: tk.Canvas, t: float, bg: str):
        """开场聚焦: 更克制的中心 bloom + 横向镜头 flare."""
        if t <= 0.0 or t > 1.2:
            return

        cx, cy = self._cx, self._cy
        sw = self._sw
        et = max(0.0, min(1.0, t / 1.2))
        bloom = ease_out(min(1.0, et / 0.52))
        fade = 1.0 - ease_in(max(0.0, (et - 0.18) / 0.82))
        strength = bloom * fade
        if strength <= 0.03:
            return

        drift_x = int(lerp(-26, 14, bloom))
        core_rx = int(lerp(14, 126, bloom))
        core_ry = int(lerp(2, 18, bloom))

        fill_layers = [
            ((255, 255, 255), 0.42, 1.00, 1.00),
            ((116, 224, 255), 0.28, 1.55, 1.65),
            ((72, 170, 255), 0.16, 2.10, 2.30),
        ]
        for rgb, alpha, sx, sy in fill_layers:
            a = strength * alpha
            if a <= 0.02:
                continue
            rx = int(core_rx * sx)
            ry = int(core_ry * sy)
            cv.create_oval(cx + drift_x - rx, cy - ry,
                           cx + drift_x + rx, cy + ry,
                           fill=self._blend_over_bg(bg, rgb, a), outline='')

        ring_layers = [
            ((255, 246, 224), 0.52, 1.05, 1.75, 2),
            ((120, 228, 255), 0.30, 1.78, 2.60, 2),
        ]
        for rgb, alpha, sx, sy, width in ring_layers:
            a = strength * alpha
            if a <= 0.02:
                continue
            rx = int(core_rx * sx)
            ry = int(core_ry * sy)
            cv.create_oval(cx + drift_x - rx, cy - ry,
                           cx + drift_x + rx, cy + ry,
                           outline=self._blend_over_bg(bg, rgb, a),
                           width=width)

        flare_len = int(lerp(90, sw * 0.30, bloom))
        line_offsets = [(-5, 0.12), (-2, 0.26), (0, 0.56), (2, 0.26), (5, 0.12)]
        for off, alpha in line_offsets:
            y = cy + off
            half = int(flare_len * (1.0 - abs(off) * 0.08))
            cv.create_line(cx + drift_x - half, y,
                           cx + drift_x + half, y,
                           fill=self._blend_over_bg(bg, (214, 245, 255), strength * alpha),
                           width=1 if off else 2)

    def _draw_start_connect_cv(self, cv: tk.Canvas, t: float, bg: str):
        """LinkStart 最开头的 SAO 连接启动爆散: 中心白核 + 冲击环 + 水平闪光."""
        if t < 0.0 or t > 0.72:
            return

        cx, cy = self._cx, self._cy
        sw = self._sw
        p = max(0.0, min(1.0, t / 0.72))
        burst = 1.0 - p
        contract = ease_out(min(1.0, p / 0.18)) if p < 0.18 else max(0.0, 1.0 - (p - 0.18) / 0.16)
        explode = ease_out(max(0.0, min(1.0, (p - 0.16) / 0.32)))
        scan = max(0.0, min(1.0, (p - 0.38) / 0.32))

        core_rx = int(lerp(18, 7, contract * 0.9)) if p < 0.22 else int(lerp(10, 96, explode))
        core_ry = int(lerp(6, 2, contract * 0.9)) if p < 0.22 else int(lerp(3, 22, explode))
        core_a = 0.18 + burst * 0.52
        core_fill = self._blend_over_bg(bg, (255, 247, 224), core_a)
        cv.create_oval(cx - core_rx, cy - core_ry,
                       cx + core_rx, cy + core_ry,
                       fill=core_fill, outline='')

        wave_r = int(lerp(12, self._diag * 0.34, explode))
        wave_h = int(max(6, wave_r * 0.34))
        for i in range(3):
            alpha = max(0.0, burst * (0.38 - i * 0.10))
            if alpha <= 0.02:
                continue
            rr = wave_r + i * 18
            rh = wave_h + i * 7
            col = self._blend_over_bg(bg, (118, 228, 255), alpha)
            cv.create_oval(cx - rr, cy - rh, cx + rr, cy + rh,
                           outline=col, width=max(1, 3 - i))

        if scan > 0.01:
            scan_r = int(lerp(42, self._diag * 0.42, scan))
            scan_h = int(max(8, scan_r * 0.30))
            scan_col = self._blend_over_bg(bg, (154, 242, 255), (1.0 - scan) * 0.42)
            cv.create_oval(cx - scan_r, cy - scan_h, cx + scan_r, cy + scan_h,
                           outline=scan_col, width=2)

        flare_len = int(lerp(60, sw * 0.42, explode))
        for off, alpha_mul in [(-6, 0.10), (-3, 0.18), (0, 0.58), (3, 0.18), (6, 0.10)]:
            alpha = burst * alpha_mul
            if alpha <= 0.02:
                continue
            half = int(flare_len * (1.0 - abs(off) * 0.06))
            col = self._blend_over_bg(bg, (230, 246, 255), alpha)
            cv.create_line(cx - half, cy + off, cx + half, cy + off,
                           fill=col, width=1 if off else 2)

    def _draw_start_nervegear_panel_cv(self, cv: tk.Canvas, t: float, bg: str):
        """LinkStart 开头的 NErVGEAR 中央启动框，移植 C# splash 的方框感。"""
        if t < 0.0 or t > 1.58:
            return

        if t < 0.16:
            opacity = t / 0.16
        elif t < 1.05:
            opacity = 1.0
        else:
            opacity = max(0.0, 1.0 - (t - 1.05) / 0.53)
        if opacity <= 0.03:
            return

        cx, cy = self._cx, self._cy
        sw = self._sw
        p = max(0.0, min(1.0, t / 1.08))
        ep = ease_out(p)
        panel_w = int(max(360, min(560, sw * 0.34)) * lerp(0.88, 1.015, ep))
        panel_h = int(122 * lerp(0.92, 1.02, ep))
        y_off = int(lerp(18, -10, ep))
        x0 = cx - panel_w // 2
        y0 = cy - panel_h // 2 + y_off
        x1 = x0 + panel_w
        y1 = y0 + panel_h

        cyan = (110, 232, 255)
        warm = (255, 203, 82)
        white = (242, 251, 255)
        base = (6, 20, 34)

        for scale_x, scale_y, alpha, rgb in [
            (1.18, 1.82, 0.16, cyan),
            (1.05, 1.32, 0.11, warm),
            (0.82, 0.92, 0.08, white),
        ]:
            a = opacity * alpha
            if a <= 0.02:
                continue
            rx = int(panel_w * scale_x * 0.5)
            ry = int(panel_h * scale_y * 0.5)
            cv.create_oval(cx - rx, y0 + panel_h // 2 - ry,
                           cx + rx, y0 + panel_h // 2 + ry,
                           fill=self._blend_over_bg(bg, rgb, a), outline='')

        body_fill = self._blend_over_bg(bg, base, opacity * 0.72)
        cv.create_rectangle(x0, y0, x1, y1, fill=body_fill,
                            outline=self._blend_over_bg(bg, cyan, opacity * 0.70), width=1)

        line_col = self._blend_over_bg(body_fill, cyan, opacity * 0.12)
        for yy in range(y0 + 8, y1 - 7, 8):
            cv.create_line(x0 + 4, yy, x1 - 4, yy, fill=line_col, width=1)

        inner_cyan = self._blend_over_bg(body_fill, cyan, opacity * 0.52)
        inner_warm = self._blend_over_bg(body_fill, warm, opacity * 0.68)
        cv.create_line(x0 + 10, y0 + 10, x1 - 10, y0 + 10, fill=inner_warm, width=1)
        cv.create_line(x0 + 10, y1 - 10, x1 - 10, y1 - 10, fill=inner_cyan, width=1)

        arm_x = 34
        arm_y = 24
        for xx, yy, sx, sy, col in [
            (x0, y0, 1, 1, inner_cyan),
            (x1, y0, -1, 1, inner_warm),
            (x0, y1, 1, -1, inner_cyan),
            (x1, y1, -1, -1, inner_warm),
        ]:
            cv.create_line(xx, yy, xx + sx * arm_x, yy, fill=col, width=2)
            cv.create_line(xx, yy, xx, yy + sy * arm_y, fill=col, width=2)

        scan_t = (t * 0.82) % 1.0
        scan_x = int(lerp(x0 - panel_w * 0.10, x1 + panel_w * 0.10, scan_t))
        for off, alpha in [(-18, 0.06), (-6, 0.14), (0, 0.28), (6, 0.14), (18, 0.06)]:
            a = opacity * alpha
            if a <= 0.02:
                continue
            cv.create_line(scan_x + off, y0 + 3, scan_x + off, y1 - 3,
                           fill=self._blend_over_bg(body_fill, white if off == 0 else cyan, a), width=1)

        top_alpha = int(255 * opacity * 0.74)
        self._draw_linkstart_canvas_text(
            cv, x0 + 22, y0 + 17, 'SYSTEM', 11,
            (160, 238, 255, top_alpha),
            (10, 24, 40, int(top_alpha * 0.82)),
            (110, 232, 255, int(top_alpha * 0.24)),
            stroke_width=1, blur_radius=1.0, anchor='nw')
        self._draw_linkstart_canvas_text(
            cv, x1 - 20, y0 + 17, '[ LINK STANDBY ]', 11,
            (255, 218, 116, top_alpha),
            (34, 28, 14, int(top_alpha * 0.82)),
            (255, 196, 82, int(top_alpha * 0.24)),
            stroke_width=1, blur_radius=1.0, anchor='ne')

        title_size = max(26, min(48, int(panel_w / 12)))
        title_alpha = int(255 * opacity * (0.82 + 0.18 * math.sin(t * 16.0) ** 2))
        self._draw_linkstart_canvas_text(
            cv, cx, y0 + int(panel_h * 0.54), 'NErVGEAR', title_size,
            (242, 251, 255, title_alpha),
            (10, 26, 42, int(title_alpha * 0.92)),
            (110, 232, 255, int(title_alpha * 0.32)),
            stroke_width=2, blur_radius=2.5, anchor='center')

        sub_alpha = int(255 * opacity * 0.74)
        self._draw_linkstart_canvas_text(
            cv, cx, y1 - 17, 'FULLDIVE AUTHENTICATION', 12,
            (255, 218, 132, sub_alpha),
            (34, 28, 14, int(sub_alpha * 0.82)),
            (255, 196, 82, int(sub_alpha * 0.24)),
            stroke_width=1, blur_radius=1.0, anchor='s')

    def _draw_global_bloom_cv(self, cv: tk.Canvas, t: float, bg: str):
        """整段 LinkStart 的轻量辉光罩，让 Canvas 回退也有发光感。"""
        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh
        pulse = 0.5 + 0.5 * math.sin(t * 1.65)
        for rgb, alpha, sx, sy in [
            ((110, 232, 255), 0.055 + pulse * 0.025, 0.55, 0.42),
            ((255, 196, 82), 0.040 + (1.0 - pulse) * 0.018, 0.34, 0.24),
        ]:
            rx = int(sw * sx)
            ry = int(sh * sy)
            cv.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                           fill=self._blend_over_bg(bg, rgb, alpha), outline='')

    def _draw_focus_flow_cv(self, cv: tk.Canvas, phase_t: float, phase_dur: float,
                            fade: float, bg: str, warm: bool = True):
        """隧道聚焦层: 细长 flare、双层焦环、轻微扫光, 避免杂乱射线感."""
        if fade <= 0.03 or phase_dur <= 0:
            return

        cx, cy = self._cx, self._cy
        sw = self._sw
        tn = max(0.0, min(1.0, phase_t / phase_dur))
        accel = self._cubic_bezier_y(tn, 0.8, 0.1, 0.9, 0.8)
        mid_focus = 1.0 - abs(tn - 0.52) / 0.52
        mid_focus = max(0.0, min(1.0, mid_focus))
        strength = fade * (0.12 + accel * 0.46 + mid_focus * 0.26)
        if strength <= 0.03:
            return

        if warm:
            main_rgb = (243, 184, 56)
            sub_rgb = (116, 228, 255)
            core_rgb = (255, 248, 232)
        else:
            main_rgb = (92, 190, 255)
            sub_rgb = (164, 238, 255)
            core_rgb = (238, 251, 255)

        drift_x = int(lerp(-10, 22, accel))
        rx = int(lerp(18, 94, accel))
        ry = int(lerp(3, 18, accel))

        fill_passes = [
            (core_rgb, 0.22, 1.0, 1.0),
            (sub_rgb, 0.12, 1.8, 2.0),
        ]
        for rgb, alpha, sx, sy in fill_passes:
            a = strength * alpha
            if a <= 0.02:
                continue
            ex = int(rx * sx)
            ey = int(ry * sy)
            cv.create_oval(cx + drift_x - ex, cy - ey,
                           cx + drift_x + ex, cy + ey,
                           fill=self._blend_over_bg(bg, rgb, a), outline='')

        ring_specs = [
            (core_rgb, 0.34, 1.10, 1.70, 2),
            (main_rgb, 0.24, 1.65, 2.55, 2),
        ]
        for rgb, alpha, sx, sy, width in ring_specs:
            a = strength * alpha
            if a <= 0.02:
                continue
            ex = int(rx * sx)
            ey = int(ry * sy)
            cv.create_oval(cx + drift_x - ex, cy - ey,
                           cx + drift_x + ex, cy + ey,
                           outline=self._blend_over_bg(bg, rgb, a),
                           width=width)

        flare_len = int(lerp(100, sw * 0.34, accel))
        for off, alpha in [(-4, 0.10), (-2, 0.18), (0, 0.42), (2, 0.18), (4, 0.10)]:
            a = strength * alpha
            if a <= 0.02:
                continue
            half = int(flare_len * (1.0 - abs(off) * 0.07))
            cv.create_line(cx + drift_x - half, cy + off,
                           cx + drift_x + half, cy + off,
                           fill=self._blend_over_bg(bg, core_rgb if off == 0 else sub_rgb, a),
                           width=1 if off else 2)

        sweep_len = int(lerp(46, sw * 0.11, accel))
        sweep_y = int(lerp(14, 6, accel))
        sweep_alpha = strength * 0.18
        sweep_color = self._blend_over_bg(bg, main_rgb, sweep_alpha)
        cv.create_line(cx + drift_x - sweep_len, cy + sweep_y,
                       cx + drift_x - rx // 2, cy + 1,
                       fill=sweep_color, width=1)
        cv.create_line(cx + drift_x + rx // 2, cy - 1,
                       cx + drift_x + sweep_len, cy - sweep_y,
                       fill=sweep_color, width=1)

    # ════════════════════════════════════════════════════════
    #  P1 结束圆形扫场
    # ════════════════════════════════════════════════════════
    def _draw_p1_circle_wipe(self, cv: tk.Canvas, t: float):
        """
        P1 结束时从中心向外扩张的暗色圆形, 把残留圆柱体盖住.
        动画: 0.45s 内从半径 0 扩张到覆盖全屏.
        边缘带一圈青蓝色光晕, 呼应 SAO 风格.
        """
        sw, sh = self._sw, self._sh
        cx, cy = self._cx, self._cy
        diag = self._diag

        wipe_dur = 0.45
        wt = (t - (self._P1_END - 0.05)) / wipe_dur
        wt = max(0.0, min(1.0, wt))
        if wt <= 0.0:
            return

        progress = ease_out(wt)           # 0→1, 先快后慢
        max_r = int(diag * 1.1 * progress)
        if max_r <= 0:
            return

        bg = self._calc_bg(t)
        bgr, bgg, bgb = hex_to_rgb(bg)

        # 实心暗色填充圆 (盖住圆柱体)
        cv.create_oval(cx - max_r, cy - max_r, cx + max_r, cy + max_r,
                       fill=bg, outline='')

        # 边缘光晕: 几圈渐隐的青蓝色细环
        ring_alpha = 1.0 - wt * 0.6      # 扩张过程中光晕逐渐变淡
        for i in range(5):
            offset = i * 6
            r_ring = max_r - offset
            if r_ring <= 0:
                break
            blend = (1.0 - i / 5) * ring_alpha
            rv = min(255, int(bgr + (80 - bgr) * blend))
            gv = min(255, int(bgg + (200 - bgg) * blend))
            bv = min(255, int(bgb + (255 - bgb) * blend))
            color = f'#{rv:02x}{gv:02x}{bv:02x}'
            cv.create_oval(cx - r_ring, cy - r_ring,
                           cx + r_ring, cy + r_ring,
                           fill='', outline=color, width=2 - i * 0.3)

    def _draw_linkstart_canvas_text(self, cv: tk.Canvas, x: int, y: int,
                                    text: str, size: int, fill_rgba,
                                    stroke_rgba, glow_rgba,
                                    stroke_width: int = 1,
                                    blur_radius: float = 1.0,
                                    anchor: str = 'center'):
        """使用 LinkStart 的 SAOUI sprite 管线在 Canvas 上绘制英文文本."""
        sprite = self._get_linkstart_text_sprite(
            text, 'sao', size,
            fill_rgba, stroke_rgba, glow_rgba,
            stroke_width, blur_radius)
        self._ls_live_photos.append(sprite['photo'])

        ax, ay = x, y
        w = sprite['width']
        h = sprite['height']
        if anchor == 'n':
            ay = y + h // 2
        elif anchor == 'ne':
            ax = x - w // 2
            ay = y + h // 2
        elif anchor == 'e':
            ax = x - w // 2
        elif anchor == 'se':
            ax = x - w // 2
            ay = y - h // 2
        elif anchor == 's':
            ay = y - h // 2
        elif anchor == 'sw':
            ax = x + w // 2
            ay = y - h // 2
        elif anchor == 'w':
            ax = x + w // 2
        elif anchor == 'nw':
            ax = x + w // 2
            ay = y + h // 2
        cv.create_image(ax, ay, image=sprite['photo'], anchor='center')

    # ════════════════════════════════════════════════════════
    #  隧道 HUD 叠加层 — 飞行中的角标 / 系统数据
    # ════════════════════════════════════════════════════════
    def _draw_tunnel_hud_overlay(self, cv: tk.Canvas, t: float, fade: float,
                                  warm: bool = True):
        """在隧道飞行阶段叠加 SAO 风格 HUD 角标和数据标签."""
        if fade < 0.08:
            return
        sw, sh = self._sw, self._sh
        m = 32  # 角标到边缘距离
        arm = 28
        alpha = min(1.0, fade * 0.55)
        cyan_rgb = (110, 232, 255) if warm else (92, 190, 255)
        gold_rgb = (243, 175, 18) if warm else (164, 238, 255)
        cyan = self._blend_over_bg('#000000', cyan_rgb, alpha)
        gold = self._blend_over_bg('#000000', gold_rgb, alpha)
        dim = self._blend_over_bg('#000000', cyan_rgb, alpha * 0.3)

        # ── 四角 L 形角标 ──
        for (x0, y0, dx, dy, col) in [
            (m, m, 1, 1, cyan),
            (sw - m, m, -1, 1, gold),
            (m, sh - m, 1, -1, cyan),
            (sw - m, sh - m, -1, -1, gold),
        ]:
            cv.create_line(x0, y0, x0 + dx * arm, y0, fill=col, width=1)
            cv.create_line(x0, y0, x0, y0 + dy * arm, fill=col, width=1)

        # ── 顶部中央: 相位标签 ──
        phase_tag = 'PHASE:COLORSTREAM' if warm else 'PHASE:BLUESHIFT'
        tag_alpha = int(255 * alpha * 0.72)
        self._draw_linkstart_canvas_text(
            cv, sw // 2, m + 6, phase_tag, 12,
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], tag_alpha),
            (10, 20, 28, int(tag_alpha * 0.85)),
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], int(tag_alpha * 0.22)),
            stroke_width=1, blur_radius=1.0, anchor='n')

        # ── 左下角: 速度 / 帧数据 ──
        speed_pct = min(100, int(t * 30))
        data_alpha = int(255 * alpha * 0.56)
        self._draw_linkstart_canvas_text(
            cv, m + 4, sh - m - 26, f'SPD: {speed_pct:03d}%', 10,
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], data_alpha),
            (10, 20, 28, int(data_alpha * 0.82)),
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], int(data_alpha * 0.18)),
            stroke_width=1, blur_radius=0.8, anchor='sw')
        self._draw_linkstart_canvas_text(
            cv, m + 4, sh - m - 14, f'T: {t:.2f}S', 10,
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], data_alpha),
            (10, 20, 28, int(data_alpha * 0.82)),
            (cyan_rgb[0], cyan_rgb[1], cyan_rgb[2], int(data_alpha * 0.18)),
            stroke_width=1, blur_radius=0.8, anchor='sw')

        # ── 右上角: 系统标签 ──
        sys_alpha = int(255 * alpha * 0.56)
        self._draw_linkstart_canvas_text(
            cv, sw - m - 4, m + 6, 'SAO://LINK', 10,
            (gold_rgb[0], gold_rgb[1], gold_rgb[2], sys_alpha),
            (18, 18, 14, int(sys_alpha * 0.82)),
            (gold_rgb[0], gold_rgb[1], gold_rgb[2], int(sys_alpha * 0.18)),
            stroke_width=1, blur_radius=0.8, anchor='ne')
        self._draw_linkstart_canvas_text(
            cv, sw - m - 4, m + 18, 'NERVE:ACTIVE', 10,
            (gold_rgb[0], gold_rgb[1], gold_rgb[2], sys_alpha),
            (18, 18, 14, int(sys_alpha * 0.82)),
            (gold_rgb[0], gold_rgb[1], gold_rgb[2], int(sys_alpha * 0.18)),
            stroke_width=1, blur_radius=0.8, anchor='ne')

        # ── 底部中央: 扫描线 (水平细线左到右移动) ──
        scan_x = int((t * 120) % (sw - 2 * m)) + m
        scan_w = 80
        cv.create_line(max(m, scan_x - scan_w), sh - m + 4,
                       min(sw - m, scan_x), sh - m + 4,
                       fill=dim, width=1)

    # ════════════════════════════════════════════════════════
    #  P4 "CONNECTED" 叠加文字
    # ════════════════════════════════════════════════════════
    def _draw_connected_overlay(self, cv: tk.Canvas, t: float):
        """在 P4 早期闪现 'SYSTEM >> CONNECTED' 确认文字."""
        wt = t - self._P4_START
        fade_start = self._P4_HOLD_END - self._P4_START
        fade_end = self._P4_FADE_END - self._P4_START
        if wt < 0 or wt > fade_end:
            return
        alpha = 1.0
        if wt < 0.15:
            alpha = wt / 0.15
        elif wt > fade_start:
            alpha = max(0.0, 1.0 - (wt - fade_start) / max(0.01, fade_end - fade_start))
        if alpha < 0.05:
            return

        cx, cy = self._cx, self._cy
        main_alpha = int(255 * alpha * 0.90)
        sub_alpha = int(255 * alpha * 0.64)
        self._draw_linkstart_canvas_text(
            cv, cx, cy - 14, 'SYSTEM >> CONNECTED', 24,
            (255, 255, 255, main_alpha),
            (36, 48, 76, int(main_alpha * 0.88)),
            (160, 224, 255, int(main_alpha * 0.18)),
            stroke_width=2, blur_radius=1.6, anchor='center')
        self._draw_linkstart_canvas_text(
            cv, cx, cy + 14, 'FULL DIVE INITIALIZED', 12,
            (110, 232, 255, sub_alpha),
            (22, 34, 48, int(sub_alpha * 0.84)),
            (110, 232, 255, int(sub_alpha * 0.18)),
            stroke_width=1, blur_radius=1.0, anchor='center')

    # ════════════════════════════════════════════════════════
    #  白闪 + 渐隐
    # ════════════════════════════════════════════════════════
    def _draw_whiteout_cv(self, cv, t):
        """
        Phase 4: 从隧道中心向外扩散的光 → 整体渐亮 → 窗口淡出.
        不是廉价的矩形填充, 而是从中心径向扩散.
        """
        sw, sh = self._sw, self._sh
        cx, cy = self._cx, self._cy
        diag = self._diag
        wt = min(1.0, (t - self._P4_START) / 1.5)

        base_bg = self._calc_bg(t)
        pulse = ease_out(min(1.0, wt / 0.55))
        drift_x = int(lerp(18, 0, pulse))
        flare_len = int(lerp(120, sw * 0.44, pulse))
        flare_ry = int(lerp(4, sh * 0.08, pulse))

        for rgb, alpha, sx, sy in [
            ((255, 255, 255), 0.32, 0.42, 0.55),
            ((210, 238, 255), 0.18, 0.74, 1.25),
            ((166, 220, 255), 0.10, 1.10, 1.90),
        ]:
            a = max(0.0, (1.0 - wt * 0.30) * alpha)
            if a <= 0.02:
                continue
            rx = int(flare_len * sx)
            ry = int(flare_ry * sy)
            cv.create_oval(cx + drift_x - rx, cy - ry,
                           cx + drift_x + rx, cy + ry,
                           fill=self._blend_over_bg(base_bg, rgb, a), outline='')

        for off, alpha in [(-5, 0.10), (-2, 0.18), (0, 0.55), (2, 0.18), (5, 0.10)]:
            a = max(0.0, (1.0 - wt * 0.24) * alpha)
            if a <= 0.02:
                continue
            half = int(flare_len * (1.0 - abs(off) * 0.07))
            cv.create_line(cx + drift_x - half, cy + off,
                           cx + drift_x + half, cy + off,
                           fill=self._blend_over_bg(base_bg, (255, 255, 255), a),
                           width=1 if off else 2)

        if wt < 0.6:
            # 光从中心向外扩展
            expansion = ease_out(wt / 0.6)
            max_r = int(diag * 0.7 * expansion)
            step = max(8, max_r // 20)
            for r in range(0, max(1, max_r), step):
                f = r / max(1, max_r)
                a = (1.0 - f) * expansion * 0.58
                v = min(255, int(24 + 168 * a))
                b = min(255, int(50 + 188 * a))
                cv.create_oval(cx - r, cy - int(r * 0.65),
                               cx + r, cy + int(r * 0.65),
                               fill=f'#{v:02x}{v:02x}{b:02x}', outline='')
        else:
            bright_t = ease_out(min(1.0, (wt - 0.6) / 0.4))
            v = int(lerp(72, 208, bright_t))
            b = min(255, v + 26)
            cv.create_rectangle(0, 0, sw, sh,
                                fill=f'#{v:02x}{v:02x}{b:02x}', outline='')

        # 窗口整体淡出
        if t >= self._DURATION - 1.5:
            ft = min(1.0, (t - (self._DURATION - 1.5)) / 1.5)
            al = max(0.0, 0.92 * (1.0 - ease_in_out(ft)))
            try:
                self._overlay.attributes('-alpha', al)
            except Exception:
                pass

    def _get_linkstart_pil_font(self, size: int, family: str = 'sao'):
        """LinkStart 专用 PIL 字体加载: SAOUI / ZhuZiAYuanJWD."""
        size = max(6, int(size))
        key = (family, size)
        if key in self._ls_font_cache:
            return self._ls_font_cache[key]

        font_file = 'SAOUI.ttf' if family == 'sao' else 'ZhuZiAYuanJWD.ttf'
        font_path = os.path.join(FONTS_DIR, font_file)
        try:
            font = ImageFont.truetype(font_path, size=size)
        except Exception:
            font = ImageFont.load_default()
        self._ls_font_cache[key] = font
        return font

    def _prewarm_linkstart_p2_sprites(self):
        """预热 P2 文字 / HUD 所需 sprite，尽量把 PIL 开销前移到 P1。"""
        if self._ls_p2_prewarmed:
            return

        warm_jobs = [
            ('WELCOME TO', 'sao', 42,
             (240, 248, 255, 240), (30, 44, 72, 220), (140, 225, 255, 64), 2, 2.0),
            ('SYS CORE', 'sao', 15,
             (112, 232, 255, 192), (18, 34, 56, 164), (112, 232, 255, 44), 1, 1.0),
            ('COORD LOCK', 'sao', 14,
             (112, 232, 255, 180), (18, 34, 56, 150), (112, 232, 255, 36), 1, 1.0),
            ('GAIN ROUTE', 'sao', 15,
             (255, 196, 104, 188), (34, 30, 38, 156), (255, 214, 120, 40), 1, 1.0),
            ('NERVE GEAR', 'sao', 15,
             (112, 232, 255, 188), (18, 34, 56, 156), (112, 232, 255, 42), 1, 1.0),
            ('LINK RATE', 'sao', 15,
             (255, 196, 104, 180), (34, 30, 38, 150), (255, 214, 120, 36), 1, 1.0),
            ('AXIS LOCK', 'sao', 14,
             (112, 232, 255, 176), (18, 34, 56, 150), (112, 232, 255, 34), 1, 1.0),
              ('PHASE:COLORSTREAM', 'sao', 12,
               (112, 232, 255, 176), (10, 20, 28, 144), (112, 232, 255, 34), 1, 1.0),
              ('PHASE:BLUESHIFT', 'sao', 12,
               (92, 190, 255, 176), (10, 20, 28, 144), (92, 190, 255, 34), 1, 1.0),
              ('SPD: 100%', 'sao', 10,
               (112, 232, 255, 160), (10, 20, 28, 132), (112, 232, 255, 28), 1, 0.8),
              ('T: 7.50S', 'sao', 10,
               (112, 232, 255, 160), (10, 20, 28, 132), (112, 232, 255, 28), 1, 0.8),
              ('SAO://LINK', 'sao', 10,
               (255, 214, 120, 160), (18, 18, 14, 132), (255, 214, 120, 28), 1, 0.8),
              ('NERVE:ACTIVE', 'sao', 10,
               (255, 214, 120, 160), (18, 18, 14, 132), (255, 214, 120, 28), 1, 0.8),
              ('SYSTEM', 'sao', 11,
               (160, 238, 255, 192), (10, 24, 40, 164), (110, 232, 255, 44), 1, 1.0),
              ('[ LINK STANDBY ]', 'sao', 11,
               (255, 218, 116, 192), (34, 28, 14, 164), (255, 196, 82, 44), 1, 1.0),
              ('NErVGEAR', 'sao', 40,
               (242, 251, 255, 240), (10, 26, 42, 224), (110, 232, 255, 72), 2, 2.5),
              ('FULLDIVE AUTHENTICATION', 'sao', 12,
               (255, 218, 132, 192), (34, 28, 14, 164), (255, 196, 82, 44), 1, 1.0),
              ('SYSTEM >> CONNECTED', 'sao', 24,
               (255, 255, 255, 224), (36, 48, 76, 192), (160, 224, 255, 40), 2, 1.5),
              ('FULL DIVE INITIALIZED', 'sao', 12,
               (112, 232, 255, 176), (22, 34, 48, 144), (112, 232, 255, 30), 1, 1.0),
        ]
        for text, family, size, fill_rgba, stroke_rgba, glow_rgba, stroke_width, blur_radius in warm_jobs:
            try:
                self._get_linkstart_text_sprite(
                    text, family, size,
                    fill_rgba, stroke_rgba, glow_rgba,
                    stroke_width, blur_radius)
            except Exception:
                pass
        try:
            self._get_linkstart_mixed_text_sprite(
                [('咲 ', 'cjk'), ('MIDI PLAYER', 'sao')], 48,
                (255, 248, 236, 240), (30, 44, 72, 220), (255, 214, 120, 56), 2, 2.0)
        except Exception:
            pass
        self._ls_p2_prewarmed = True

    def _draw_text_layer(self, draw: ImageDraw.ImageDraw, pos, text: str, font,
                         fill, stroke_fill=None, stroke_width: int = 0,
                         anchor: str = 'mm'):
        kwargs = dict(text=text, font=font, fill=fill, anchor=anchor)
        if stroke_fill is not None and stroke_width > 0:
            kwargs['stroke_fill'] = stroke_fill
            kwargs['stroke_width'] = stroke_width
        draw.text(pos, **kwargs)

    def _get_linkstart_text_sprite(self, text: str, family: str, size: int,
                                   fill_rgba, stroke_rgba, glow_rgba,
                                   stroke_width: int, blur_radius: float = 3.0):
        """缓存化文字 sprite，避免文字阶段每帧整屏 PIL 合成。"""
        qsize = max(6, int(round(size / 4.0) * 4))
        qstroke = max(0, int(round(stroke_width)))
        qblur = round(float(blur_radius) * 2.0) / 2.0

        def _q_rgba(rgba):
            return tuple(max(0, min(255, int(round(v / 16.0) * 16))) for v in rgba)

        qfill = _q_rgba(fill_rgba)
        qstroke_rgba = _q_rgba(stroke_rgba)
        qglow = _q_rgba(glow_rgba)
        key = (text, family, qsize, qfill, qstroke_rgba, qglow, qstroke, qblur)
        cached = self._ls_sprite_cache.get(key)
        if cached is not None:
            return cached

        if len(self._ls_sprite_cache) > 220:
            self._ls_sprite_cache.clear()

        font = self._get_linkstart_pil_font(qsize, family)
        dummy = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dummy)
        bbox = dd.textbbox((0, 0), text, font=font,
                           stroke_width=max(0, qstroke))
        pad = int(max(12, qsize * 0.55))
        w = max(8, bbox[2] - bbox[0] + pad * 2)
        h = max(8, bbox[3] - bbox[1] + pad * 2)

        glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gx = pad - bbox[0]
        gy = pad - bbox[1]
        gdraw.text((gx, gy), text, font=font, fill=qglow)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(0.5, qblur)))

        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        img = Image.alpha_composite(img, glow)
        draw = ImageDraw.Draw(img)
        draw.text((gx, gy), text, font=font, fill=qfill,
              stroke_fill=qstroke_rgba, stroke_width=max(0, qstroke))

        photo = ImageTk.PhotoImage(img)
        payload = {'photo': photo, 'width': w, 'height': h}
        self._ls_sprite_cache[key] = payload
        return payload

    def _get_linkstart_mixed_text_sprite(self, segments, size: int,
                                         fill_rgba, stroke_rgba, glow_rgba,
                                         stroke_width: int, blur_radius: float = 3.0):
        """按片段混合 SAOUI / CJK 字体，保证英文数字走 SAOUI。"""
        qsize = max(6, int(round(size / 4.0) * 4))
        qstroke = max(0, int(round(stroke_width)))
        qblur = round(float(blur_radius) * 2.0) / 2.0

        def _q_rgba(rgba):
            return tuple(max(0, min(255, int(round(v / 16.0) * 16))) for v in rgba)

        qfill = _q_rgba(fill_rgba)
        qstroke_rgba = _q_rgba(stroke_rgba)
        qglow = _q_rgba(glow_rgba)
        norm_segments = tuple((str(text), str(family)) for text, family in segments if text)
        key = ('mixed', norm_segments, qsize, qfill, qstroke_rgba, qglow, qstroke, qblur)
        cached = self._ls_sprite_cache.get(key)
        if cached is not None:
            return cached

        if len(self._ls_sprite_cache) > 220:
            self._ls_sprite_cache.clear()

        dummy = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dummy)
        font_infos = []
        total_w = 0
        top = 0
        bottom = 0
        for text, family in norm_segments:
            font = self._get_linkstart_pil_font(qsize, family)
            bbox = dd.textbbox((0, 0), text, font=font, stroke_width=qstroke)
            seg_w = max(1, bbox[2] - bbox[0])
            top = min(top, bbox[1])
            bottom = max(bottom, bbox[3])
            font_infos.append((text, font, bbox, seg_w))
            total_w += seg_w

        pad = int(max(12, qsize * 0.55))
        w = max(8, total_w + pad * 2)
        h = max(8, bottom - top + pad * 2)

        def _render_layer(fill_rgba_value, blur=False):
            layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            x = pad
            for text, font, bbox, seg_w in font_infos:
                draw.text((x - bbox[0], pad - top), text, font=font, fill=fill_rgba_value,
                          stroke_fill=qstroke_rgba if not blur else None,
                          stroke_width=qstroke if not blur else 0)
                x += seg_w
            if blur:
                layer = layer.filter(ImageFilter.GaussianBlur(radius=max(0.5, qblur)))
            return layer

        glow = _render_layer(qglow, blur=True)
        img = Image.alpha_composite(Image.new('RGBA', (w, h), (0, 0, 0, 0)), glow)
        main = _render_layer(qfill, blur=False)
        img = Image.alpha_composite(img, main)

        photo = ImageTk.PhotoImage(img)
        payload = {'photo': photo, 'width': w, 'height': h}
        self._ls_sprite_cache[key] = payload
        return payload

    def _draw_linkstart_hud(self, cv: tk.Canvas, t: float, vis: float):
        """文字阶段 HUD: 左右两侧使用远近两层漂移, 保持非对称飞掠感."""
        cx, cy = self._cx, self._cy
        sw = self._sw
        phase = (t - self._P2_START) / max(0.01, (self._P2_END - self._P2_START))
        phase = max(0.0, min(1.0, phase))
        hud_tick = int(round(phase * 10.0))
        phase_q = hud_tick / 10.0

        slow = math.sin(t * 1.05)
        slow_b = math.sin(t * 0.72 + 0.9)
        fast = math.sin(t * 2.10 + 0.6)
        fast_b = math.sin(t * 1.64 + 1.7)

        def _draw_panel(x0, y0, side, scale, alpha, cool_rgb, warm_rgb,
                        label, sub_label, accent_up=True):
            sign = 1 if side == 'left' else -1
            line_c = self._blend_over_bg('#101826', cool_rgb, alpha)
            accent_c = self._blend_over_bg('#101826', warm_rgb, alpha * 0.86)
            arm = int(76 * scale)
            tail = int(36 * scale)
            box_w = int(130 * scale)
            box_h = int(24 * scale)
            ladder_h = int(36 * scale)
            grid_w = int(108 * scale)
            grid_h = int(34 * scale)

            cv.create_line(x0, y0, x0 + sign * arm, y0, fill=line_c, width=max(1, int(2 * scale)))
            cv.create_line(x0, y0 - tail, x0, y0 + tail, fill=line_c, width=1)
            cv.create_line(x0 + sign * (arm - 18), y0 - int(14 * scale),
                           x0 + sign * (arm + 24), y0 - int(14 * scale),
                           fill=accent_c if accent_up else line_c, width=1)

            bx1 = x0 + sign * 12
            bx2 = bx1 + sign * box_w
            x_min, x_max = min(bx1, bx2), max(bx1, bx2)
            box_y = y0 - box_h if accent_up else y0
            cv.create_rectangle(x_min, box_y, x_max, box_y + box_h,
                                outline=accent_c if accent_up else line_c, width=1)
            cv.create_line(x_min + 6, box_y + box_h // 2, x_max - 6, box_y + box_h // 2,
                           fill=line_c, width=1)

            grid_x1 = x0 + sign * 18
            grid_x2 = grid_x1 + sign * grid_w
            grid_y1 = y0 + (int(18 * scale) if accent_up else -grid_h - int(18 * scale))
            grid_y2 = grid_y1 + grid_h
            gminx, gmaxx = min(grid_x1, grid_x2), max(grid_x1, grid_x2)
            cv.create_rectangle(gminx, grid_y1, gmaxx, grid_y2, outline=line_c, width=1)
            for idx in range(1, 4):
                gy = grid_y1 + idx * (grid_h // 4)
                cv.create_line(gminx + 3, gy, gmaxx - 3, gy, fill=line_c, width=1)
            for idx in range(1, 5):
                gx = gminx + idx * (grid_w // 5)
                cv.create_line(gx, grid_y1 + 3, gx, grid_y2 - 3, fill=line_c, width=1)

            tick_base_y = y0 + (int(26 * scale) if accent_up else -int(26 * scale))
            tick_dir = 1 if accent_up else -1
            for idx in range(6):
                tx = x0 + sign * (18 + idx * int(14 * scale))
                th = int((5 + (idx % 3) * 3) * scale)
                cv.create_line(tx, tick_base_y, tx, tick_base_y + tick_dir * th,
                               fill=accent_c if idx % 2 else line_c, width=1)

            label_rgba = (cool_rgb[0], cool_rgb[1], cool_rgb[2], int(220 * alpha))
            sub_rgba = (warm_rgb[0], warm_rgb[1], warm_rgb[2], int(188 * alpha))
            label_sprite = self._get_linkstart_text_sprite(
                label, 'sao', max(11, int(15 * scale)),
                label_rgba,
                (18, 34, 56, int(label_rgba[3] * 0.84)),
                (cool_rgb[0], cool_rgb[1], cool_rgb[2], int(label_rgba[3] * 0.22)),
                1, 1.1)
            sub_sprite = self._get_linkstart_text_sprite(
                sub_label, 'sao', max(10, int(13 * scale)),
                sub_rgba,
                (30, 34, 44, int(sub_rgba[3] * 0.82)),
                (warm_rgb[0], warm_rgb[1], warm_rgb[2], int(sub_rgba[3] * 0.18)),
                1, 1.0)
            self._ls_live_photos.extend([label_sprite['photo'], sub_sprite['photo']])

            label_x = (x_min + x_max) // 2
            label_y = box_y + box_h // 2
            sub_x = x0 + sign * int((arm + box_w * 0.42) / 2)
            sub_y = y0 + (grid_h + int(28 * scale) if accent_up else -grid_h - int(28 * scale))
            cv.create_image(label_x, label_y, image=label_sprite['photo'], anchor='center')
            cv.create_image(sub_x, sub_y, image=sub_sprite['photo'], anchor='center')

        layers = [
            {
                'side': 'left', 'alpha': 0.16 * vis, 'scale': 0.90,
                'x': int(lerp(-180, cx - 352, ease_out(min(1.0, phase * 0.92))) + slow * 16 + slow_b * 9),
                'y': int(cy - 82 + slow_b * 11),
                'cool': (104, 228, 255), 'warm': (176, 232, 255),
                'label': 'SYS CORE',
                'sub': 'COORD LOCK',
                'accent_up': False,
            },
            {
                'side': 'left', 'alpha': 0.24 * vis, 'scale': 1.08,
                'x': int(lerp(-260, cx - 268, ease_out(min(1.0, max(0.0, (phase - 0.06) / 0.94)))) + fast * 28 + slow * 6),
                'y': int(cy + 96 + fast_b * 14),
                'cool': (110, 232, 255), 'warm': (255, 196, 104),
                'label': 'GAIN ROUTE',
                'sub': 'LINE 02',
                'accent_up': True,
            },
            {
                'side': 'right', 'alpha': 0.14 * vis, 'scale': 0.88,
                'x': int(lerp(sw + 190, cx + 344, ease_out(min(1.0, max(0.0, (phase - 0.02) / 0.98)))) - slow * 12 + slow_b * 15),
                'y': int(cy + 78 + slow * 9),
                'cool': (104, 228, 255), 'warm': (150, 230, 255),
                'label': 'NERVE GEAR',
                'sub': 'LINK RATE',
                'accent_up': True,
            },
            {
                'side': 'right', 'alpha': 0.22 * vis, 'scale': 1.12,
                'x': int(lerp(sw + 280, cx + 278, ease_out(min(1.0, max(0.0, (phase - 0.12) / 0.88)))) - fast * 30 + fast_b * 8),
                'y': int(cy - 102 + fast * 13),
                'cool': (110, 232, 255), 'warm': (255, 196, 104),
                'label': 'LINK RATE',
                'sub': 'AXIS LOCK',
                'accent_up': False,
            },
        ]

        for layer in layers:
            if layer['alpha'] <= 0.02:
                continue
            _draw_panel(
                layer['x'], layer['y'], layer['side'], layer['scale'], layer['alpha'],
                layer['cool'], layer['warm'], layer['label'], layer['sub'],
                accent_up=layer['accent_up'])

    def _get_text_phase_state(self, t: float):
        """计算 P2 文字段落的共享状态, 供 underlay / overlay 复用."""
        if t < self._P2_START or t > self._P2_END:
            return None

        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh

        t_fly_in_start = self._P2_START
        t_fly_in_end = t_fly_in_start + 0.7
        t_display_end = t_fly_in_end + 0.5
        t_fly_out_end = t_display_end + 0.55
        t_fade_end = self._P2_END

        base_size_1 = 42
        base_size_2 = 48
        ref_z = 34

        if t < t_fly_in_end:
            fly_t = (t - t_fly_in_start) / max(0.01, t_fly_in_end - t_fly_in_start)
            z_text = lerp(260, ref_z, ease_out(min(1.0, fly_t)))
        elif t < t_display_end:
            z_text = ref_z
        elif t < t_fly_out_end:
            out_t = (t - t_display_end) / max(0.01, t_fly_out_end - t_display_end)
            z_text = lerp(ref_z, 0.42, ease_in(min(1.0, out_t)))
        else:
            tail_t = (t - t_fly_out_end) / max(0.01, t_fade_end - t_fly_out_end)
            z_text = lerp(0.42, 0.08, ease_in(min(1.0, tail_t)))

        if z_text < 0.08:
            return None
        scale = ref_z / z_text
        size_1 = max(8, min(720, int(base_size_1 * scale)))
        size_2 = max(10, min(820, int(base_size_2 * scale)))
        if size_1 > 720:
            return None

        vis = 1.0
        if t < t_fly_in_start + 0.18:
            vis = (t - t_fly_in_start) / 0.18
        if t > t_fly_out_end - 0.18:
            vis = max(0.0, (t_fade_end - t) / max(0.01, (t_fade_end - t_fly_out_end + 0.18)))
        vis = max(0.0, min(1.0, vis))
        if vis < 0.03:
            return None

        txt_y1 = cy - int(38 * scale)
        txt_y2 = cy + int(26 * scale)
        phase = (t - self._P2_START) / max(0.01, (self._P2_END - self._P2_START))
        phase = max(0.0, min(1.0, phase))
        phase_mid = 0.0
        if t_fly_in_end <= t < t_display_end:
            phase_mid = (t - t_fly_in_end) / max(0.01, (t_display_end - t_fly_in_end))
        reveal_t = 0.0
        if t <= t_fly_in_end:
            reveal_t = ease_out((t - t_fly_in_start) / max(0.01, (t_fly_in_end - t_fly_in_start)))
        elif t <= t_display_end:
            reveal_t = 1.0
        else:
            reveal_t = max(0.0, 1.0 - ((t - t_display_end) / max(0.01, (t_fly_out_end - t_display_end))) * 0.22)

        pulse = 0.5 + 0.5 * math.sin((t - self._P2_START) * 8.8)
        glitch = 0.5 + 0.5 * math.sin(t * 37.0) * math.sin(t * 19.0)
        shift = int((4 + 8 * phase_mid) * glitch)
        shear_x = int(lerp(18, 0, min(1.0, vis)))
        frame_pad = int(max(size_1 * 4.2, size_2 * 3.5))

        frame_top = txt_y1 - int(size_1 * 0.90)
        frame_bottom = txt_y2 + int(size_2 * 0.86)
        frame_left = cx - frame_pad
        frame_right = cx + frame_pad
        text_left = frame_left + 18
        text_right = frame_right - 18
        text_top = txt_y1 - int(size_1 * 0.82)
        text_bottom = txt_y2 + int(size_2 * 0.74)

        return {
            't': t,
            'cx': cx,
            'cy': cy,
            'sw': sw,
            'sh': sh,
            'size_1': size_1,
            'size_2': size_2,
            'scale': scale,
            'vis': vis,
            'phase': phase,
            'phase_mid': phase_mid,
            'pulse': pulse,
            'glitch': glitch,
            'shift': shift,
            'shear_x': shear_x,
            'reveal_t': reveal_t,
            'txt_y1': txt_y1,
            'txt_y2': txt_y2,
            'frame_top': frame_top,
            'frame_bottom': frame_bottom,
            'frame_left': frame_left,
            'frame_right': frame_right,
            'text_left': text_left,
            'text_right': text_right,
            'text_top': text_top,
            'text_bottom': text_bottom,
            'txt1': 'WELCOME TO',
            'txt2': '咲 MIDI PLAYER',
        }

    def _draw_text_phase_underlay(self, cv: tk.Canvas, t: float, state=None):
        """P2 文本背景层: 只负责底层 flare / 框角, 以便与圆柱体层分离."""
        state = state or self._get_text_phase_state(t)
        if not state:
            return

        cx = state['cx']
        cy = state['cy']
        sw = state['sw']
        vis = state['vis']
        size_2 = state['size_2']
        frame_top = state['frame_top']
        frame_bottom = state['frame_bottom']
        frame_left = state['frame_left']
        frame_right = state['frame_right']

        flare_w = int(min(sw * 0.46, max(120, size_2 * 8)))
        flare_h = max(8, int(size_2 * 0.38))
        line_color = self._blend_over_bg('#101826', (210, 243, 255), 0.14 * vis)
        for idx, alpha_mul in [(0, 0.14), (1, 0.08)]:
            ex = flare_w + idx * int(size_2 * 1.8)
            ey = flare_h + idx * int(size_2 * 0.25)
            cv.create_oval(cx - ex, cy - ey, cx + ex, cy + ey,
                           outline=self._blend_over_bg('#101826', (140, 225, 255), vis * alpha_mul),
                           width=max(1, 3 - idx))
        cv.create_line(cx - flare_w, cy, cx + flare_w, cy, fill=line_color, width=2)

        accent = (255, 214, 120, int(92 * vis))
        cool = (108, 230, 255, int(86 * vis))
        for inset, col in [(0, accent), (12, cool)]:
            if col[3] <= 4:
                continue
            line = self._blend_over_bg('#101826', col[:3], col[3] / 255.0)
            cv.create_line(frame_left + inset, frame_top + inset,
                           frame_left + 90 + inset, frame_top + inset, fill=line, width=2)
            cv.create_line(frame_left + inset, frame_top + inset,
                           frame_left + inset, frame_top + 22 + inset, fill=line, width=2)
            cv.create_line(frame_right - inset, frame_bottom - inset,
                           frame_right - 120 - inset, frame_bottom - inset, fill=line, width=2)
            cv.create_line(frame_right - inset, frame_bottom - inset,
                           frame_right - inset, frame_bottom - 24 - inset, fill=line, width=2)

    def _draw_segmented_reveal_mask(self, cv: tk.Canvas, state):
        """P2 文字 reveal: 分段栅格扫描, 避免整块单向擦除."""
        reveal_t = state['reveal_t']
        vis = state['vis']
        if reveal_t >= 1.0 and vis >= 0.999:
            return

        left = state['text_left']
        right = state['text_right']
        top = state['text_top']
        bottom = state['text_bottom']
        width = max(1, right - left)
        height = max(1, bottom - top)
        bg_fill = self._calc_bg(state['t'])
        bands = 5
        cols = 3
        band_h = max(10, int(math.ceil(height / bands)))
        seg_w = width / float(cols)

        for band in range(bands):
            y1 = top + band * band_h
            y2 = min(bottom, y1 + band_h + 1)
            if y1 >= bottom:
                break
            row_delay = band * 0.044
            for col in range(cols):
                x1 = int(left + col * seg_w)
                x2 = int(left + (col + 1) * seg_w + 1)
                local_delay = row_delay + col * 0.014 + (0.018 if band % 2 else 0.0)
                prog = max(0.0, min(1.0, (reveal_t - local_delay) / 0.38))
                if prog >= 0.999:
                    continue
                direction = 1 if (band + col) % 3 != 1 else -1
                if direction > 0:
                    reveal_x = int(lerp(x1, x2, prog))
                    if reveal_x < x2:
                        cv.create_rectangle(reveal_x, y1, x2, y2, fill=bg_fill, outline='')
                        if prog > 0.02:
                            scan_c = self._blend_over_bg(bg_fill, (218, 246, 255), 0.36 * vis)
                            cv.create_line(reveal_x, y1 + 1, reveal_x, y2 - 1, fill=scan_c, width=1)
                else:
                    reveal_x = int(lerp(x2, x1, prog))
                    if reveal_x > x1:
                        cv.create_rectangle(x1, y1, reveal_x, y2, fill=bg_fill, outline='')
                        if prog > 0.02:
                            scan_c = self._blend_over_bg(bg_fill, (255, 214, 120), 0.28 * vis)
                            cv.create_line(reveal_x, y1 + 1, reveal_x, y2 - 1, fill=scan_c, width=1)

        scan_y = int(lerp(top - 6, bottom + 6, min(1.0, reveal_t * 1.08)))
        if top - 6 <= scan_y <= bottom + 6:
            cv.create_line(left - 8, scan_y, right + 8, scan_y,
                           fill=self._blend_over_bg(bg_fill, (212, 244, 255), 0.24 * vis), width=1)
            cv.create_line(left + 18, scan_y + 3, right - 18, scan_y + 3,
                           fill=self._blend_over_bg(bg_fill, (108, 230, 255), 0.16 * vis), width=1)

    def _render_text_phase(self, cv: tk.Canvas, t: float, state=None):
        """用 SAOUI / ZhuZiAYuanJWD 渲染更炫酷的 LinkStart 文字段落."""
        state = state or self._get_text_phase_state(t)
        if not state:
            return

        self._ls_live_photos = []

        cx = state['cx']
        txt_y1 = state['txt_y1']
        txt_y2 = state['txt_y2']
        txt1 = state['txt1']
        txt2 = state['txt2']
        size_1 = state['size_1']
        size_2 = state['size_2']
        vis = state['vis']
        pulse = state['pulse']
        glitch = state['glitch']
        shift = state['shift']
        shear_x = state['shear_x']

        core_alpha = int(lerp(150, 255, vis))
        accent_alpha = int(lerp(80, 185, vis * (0.72 + 0.28 * pulse)))
        ghost_alpha = int(lerp(40, 135, vis * (0.55 + 0.45 * glitch)))

        warm = (255, 214, 120, accent_alpha)
        cyan = (110, 232, 255, ghost_alpha)
        white = (245, 248, 255, core_alpha)
        stroke = (30, 44, 72, int(core_alpha * 0.86))

        self._draw_linkstart_hud(cv, t, vis)

        sprite_ghost_1 = self._get_linkstart_text_sprite(
            txt1, 'sao', size_1,
            cyan,
            (20, 34, 58, int(ghost_alpha * 0.45)),
            (110, 232, 255, int(ghost_alpha * 0.30)),
            max(1, size_1 // 22), max(1.4, size_1 * 0.025))
        sprite_ghost_2 = self._get_linkstart_mixed_text_sprite(
            [('咲 ', 'cjk'), ('MIDI PLAYER', 'sao')], size_2,
            warm,
            (34, 30, 38, int(accent_alpha * 0.40)),
            (255, 214, 120, int(accent_alpha * 0.22)),
            max(1, size_2 // 24), max(1.5, size_2 * 0.026))
        sprite_main_1 = self._get_linkstart_text_sprite(
            txt1, 'sao', size_1,
            white,
            stroke,
            (140, 225, 255, int(core_alpha * 0.28)),
            max(1, size_1 // 18), max(1.8, size_1 * 0.032))
        sprite_main_2 = self._get_linkstart_mixed_text_sprite(
            [('咲 ', 'cjk'), ('MIDI PLAYER', 'sao')], size_2,
            (255, 248, 236, core_alpha),
            stroke,
            (255, 214, 120, int(core_alpha * 0.22)),
            max(1, size_2 // 20), max(1.9, size_2 * 0.032))

        self._ls_live_photos.extend([
            sprite_ghost_1['photo'], sprite_ghost_2['photo'],
            sprite_main_1['photo'], sprite_main_2['photo']
        ])
        cv.create_image(cx - shift - shear_x, txt_y1, image=sprite_ghost_1['photo'], anchor='center')
        cv.create_image(cx + shift + shear_x, txt_y2, image=sprite_ghost_2['photo'], anchor='center')
        cv.create_image(cx + shear_x // 2, txt_y1, image=sprite_main_1['photo'], anchor='center')
        cv.create_image(cx, txt_y2, image=sprite_main_2['photo'], anchor='center')
        self._draw_segmented_reveal_mask(cv, state)

    # ════════════════════════════════════════════════════════
    #  结束
    # ════════════════════════════════════════════════════════
    def _finish(self):
        if getattr(self, '_finished', False):
            return
        self._finished = True
        self._gpu_present_done = True
        if self._timer_resolution is not None:
            try:
                self._timer_resolution.release()
            except Exception:
                pass
            self._timer_resolution = None
        self._destroy_gl()
        if self._gpu_present_window is not None:
            try:
                self._gpu_present_window.destroy()
            except Exception:
                pass
            self._gpu_present_window = None
        self._gpu_present_enabled = False
        self._gpu_present_frame_requested = False
        self._gpu_present_ready = False
        self._gpu_present_finish_posted = False
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.destroy()
        self._overlay = None
        if self.on_done:
            self.on_done()


