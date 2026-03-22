# -*- coding: utf-8 -*-
"""
SAO Link Start — pyglet 2.x OpenGL 渲染器

基于 SAO-UI (Cad-noob/SAO-UI) 的渲染手法:
  - ~400 条细长光束径向排列, 形成光隧道
  - 摄像机沿 Z 轴飞行穿过隧道 (perspective + translateZ)
  - 颜色阶段: 彩色 → 文字 → 蓝色 → 白闪
  - pyglet.shapes.Line + Batch 批量渲染, 每帧重建 batch

与 tkinter 协作:
  - 创建独立 pyglet 窗口 (全屏, 无边框)
  - 在子线程中 run(), 动画结束后回调 on_done
"""

import math
import random
import time
import ctypes
import sys

try:
    import pyglet
    from pyglet.gl import (
        glClearColor, glClear, GL_COLOR_BUFFER_BIT,
        glEnable, glBlendFunc,
        GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    )
    HAS_PYGLET = True
except ImportError:
    HAS_PYGLET = False

# ═══════════════ 色板 ═══════════════

COLOR_PALETTE = [
    (255, 0, 255),    # 品红
    (0, 255, 255),    # 青
    (0, 255, 0),      # 绿
    (255, 238, 0),    # 黄
    (34, 34, 34),     # 暗
    (255, 0, 0),      # 红
    (255, 136, 0),    # 橙
    (255, 255, 255),  # 白
    (220, 0, 220),    # 紫红
    (0, 200, 200),    # 暗青
    (0, 200, 0),      # 暗绿
    (200, 200, 0),    # 暗黄
]
COLOR_WEIGHTS = [7, 5, 5, 4, 4, 3, 2, 2, 3, 3, 3, 2]

BLUE_PALETTE = [
    (0, 68, 204),     # 中蓝
    (0, 204, 255),    # 青
    (0, 34, 136),     # 靛蓝
    (0, 136, 255),    # 亮蓝
    (136, 238, 255),  # 浅青
    (255, 255, 255),  # 白
    (0, 85, 221),     # 蓝
    (0, 170, 255),    # 天蓝
]
BLUE_WEIGHTS = [6, 6, 4, 4, 3, 3, 4, 3]


def _pick(palette, weights):
    return random.choices(palette, weights=weights, k=1)[0]


# ═══════════════ 粒子数据 ═══════════════

class Streak:
    """单条光束粒子"""
    __slots__ = (
        'angle', 'cos', 'sin', 'radius', 'z', 'length', 'thick',
        'r', 'g', 'b', 'speed', 'spawn_t',
    )

    def __init__(self, angle, radius, z, length, thick, color, speed, spawn_t):
        self.angle = angle
        self.cos = math.cos(angle)
        self.sin = math.sin(angle)
        self.radius = radius
        self.z = z
        self.length = length
        self.thick = thick
        self.r, self.g, self.b = color
        self.speed = speed
        self.spawn_t = spawn_t


# ═══════════════ 主渲染器 ═══════════════

class LinkStartGL:
    """
    pyglet 2.x Link Start 动画.

    使用 pyglet.shapes.Line 和 Batch 渲染光束隧道.
    每帧重建所有 shape 对象 (pyglet shapes 可以修改属性但重建更简洁).
    """

    # 时间轴
    DURATION = 9.5
    P1_END = 4.2
    P2_START = 3.6
    P2_END = 6.3
    P3_START = 5.5
    P3_END = 8.2
    P4_START = 7.8

    # 隧道参数
    TUNNEL_RADIUS = 250
    TUNNEL_DEPTH = 3000
    FOCAL = 800.0
    CAM_SPEED_1 = 280
    CAM_SPEED_3 = 350

    def __init__(self, on_done=None, tk_root=None):
        self.on_done = on_done
        self.tk_root = tk_root
        self._window = None
        self._start_time = 0
        self._streaks_color = []
        self._streaks_blue = []
        self._speed_lines = []
        self._finished = False
        self._shapes = []

    def run(self):
        """启动动画 (阻塞式)"""
        if not HAS_PYGLET:
            if self.on_done:
                self.on_done()
            return

        display = pyglet.display.get_display()
        screens = display.get_screens()
        screen = screens[0]
        sw, sh = screen.width, screen.height

        # 使用无边框窗口覆盖全屏 (避免 fullscreen 模式分辨率不匹配)
        try:
            config = pyglet.gl.Config(
                double_buffer=True,
                sample_buffers=1, samples=4,
                alpha_size=8,
            )
            self._window = pyglet.window.Window(
                width=sw, height=sh,
                style=pyglet.window.Window.WINDOW_STYLE_BORDERLESS,
                config=config, caption='Link Start',
            )
        except Exception:
            self._window = pyglet.window.Window(
                width=sw, height=sh,
                style=pyglet.window.Window.WINDOW_STYLE_BORDERLESS,
                caption='Link Start',
            )

        # 移动到屏幕原点 (确保覆盖全屏)
        self._window.set_location(0, 0)

        self._sw, self._sh = sw, sh
        self._cx, self._cy = sw / 2, sh / 2
        self._diag = math.hypot(sw, sh)

        # Win32 置顶
        try:
            if sys.platform == 'win32':
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                ctypes.windll.user32.SetWindowPos(
                    hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        except Exception:
            pass

        self._generate_streaks()
        self._start_time = time.time()

        @self._window.event
        def on_draw():
            self._render()

        @self._window.event
        def on_key_press(symbol, modifiers):
            if symbol == pyglet.window.key.ESCAPE:
                self._finish()

        pyglet.clock.schedule_interval(self._update, 1.0 / 60)

        try:
            pyglet.app.run()
        except Exception:
            pass

        if self.on_done:
            if self.tk_root:
                self.tk_root.after(50, self.on_done)
            else:
                self.on_done()

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        pyglet.clock.unschedule(self._update)
        if self._window:
            try:
                self._window.close()
            except Exception:
                pass
        pyglet.app.exit()

    # ───── 生成粒子 ─────

    def _generate_streaks(self):
        R = self.TUNNEL_RADIUS
        D = self.TUNNEL_DEPTH

        # 彩色阶段: 350 条光束
        self._streaks_color = []
        for _ in range(350):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(30, R)
            z = random.uniform(100, D)
            ln = random.uniform(80, 500)
            th = random.uniform(1.5, 5.0)
            if random.random() < 0.08:
                th = random.uniform(6.0, 14.0)
                ln = random.uniform(300, 800)
            c = _pick(COLOR_PALETTE, COLOR_WEIGHTS)
            sp = random.uniform(0, 50)
            st = random.uniform(0.0, 2.8)
            self._streaks_color.append(Streak(a, r, z, ln, th, c, sp, st))

        # 蓝色阶段: 300 条光束
        self._streaks_blue = []
        for _ in range(300):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(30, R)
            z = random.uniform(100, D)
            ln = random.uniform(80, 500)
            th = random.uniform(1.5, 5.0)
            if random.random() < 0.08:
                th = random.uniform(6.0, 14.0)
                ln = random.uniform(300, 800)
            c = _pick(BLUE_PALETTE, BLUE_WEIGHTS)
            sp = random.uniform(0, 50)
            st = random.uniform(5.5, 7.2)
            self._streaks_blue.append(Streak(a, r, z, ln, th, c, sp, st))

        # 速度线: 80 条白色细线
        self._speed_lines = []
        for _ in range(80):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(10, R * 1.5)
            z = random.uniform(100, D)
            ln = random.uniform(300, 1200)
            th = random.uniform(0.5, 2.0)
            sp = random.uniform(0, 30)
            st = random.uniform(0.0, 3.0)
            self._speed_lines.append(
                Streak(a, r, z, ln, th, (255, 255, 255), sp, st))

    # ───── 更新 ─────

    def _update(self, dt):
        t = time.time() - self._start_time
        if t >= self.DURATION:
            self._finish()

    # ───── 渲染 ─────

    def _render(self):
        t = time.time() - self._start_time
        if t > self.DURATION:
            return

        sw, sh = self._sw, self._sh

        # 背景色
        bg = self._get_bg(t)
        glClearColor(bg[0], bg[1], bg[2], 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        # 混合
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # 清除上一帧 shapes
        self._shapes.clear()
        batch = pyglet.graphics.Batch()

        bg_rgb = (int(bg[0] * 255), int(bg[1] * 255), int(bg[2] * 255))

        # Phase 1: 彩色隧道 (0~4.2s)
        if t < self.P1_END:
            fade = 1.0
            if t > 3.2:
                fade = max(0, 1.0 - (t - 3.2) / 1.0)
            cam_z = self.CAM_SPEED_1 * t
            self._add_streaks(batch, self._speed_lines, t, cam_z,
                              fade * 0.3, bg_rgb)
            self._add_streaks(batch, self._streaks_color, t, cam_z,
                              fade, bg_rgb)
            if fade > 0.1:
                self._add_glow(batch, t, 0.0, 3.5, (255, 255, 255), fade)

        # Phase 3: 蓝色隧道 (5.5~8.2s)
        if self.P3_START <= t < self.P3_END:
            fade = 1.0
            if t < 6.0:
                fade = min(1.0, (t - self.P3_START) / 0.5)
            cam_z = self.CAM_SPEED_3 * (t - self.P3_START)
            self._add_streaks(batch, self._streaks_blue, t, cam_z,
                              fade, bg_rgb)
            if fade > 0.1:
                self._add_glow(batch, t, 5.8, 8.0, (170, 221, 255), fade)

        # Phase 4: 白闪 (7.8~9.5s)
        if t >= self.P4_START:
            self._add_whiteout(batch, t)

        batch.draw()

        # Phase 2: 文字 (3.6~6.3s) — batch.draw 之后单独绘制
        if self.P2_START <= t < self.P2_END + 0.3:
            self._draw_text(t)

    # ───── 背景 ─────

    def _get_bg(self, t):
        if t < 3.3:
            return (0.94, 0.94, 0.94)
        elif t < 3.8:
            f = (t - 3.3) / 0.5
            return (0.94 - 0.12 * f, 0.94 - 0.13 * f, 0.94 - 0.13 * f)
        elif t < 7.5:
            return (0.82, 0.81, 0.81)
        elif t < 8.5:
            f = (t - 7.5) / 1.0
            return (0.82 + 0.15 * f, 0.81 + 0.18 * f, 0.81 + 0.19 * f)
        else:
            return (0.97, 0.99, 1.0)

    # ───── 光束渲染 ─────

    def _add_streaks(self, batch, streaks, t, cam_z, global_fade, bg_rgb):
        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh
        F = self.FOCAL
        D = self.TUNNEL_DEPTH
        bgr, bgg, bgb = bg_rgb

        for s in streaks:
            if t < s.spawn_t:
                continue

            # 相对摄像机的 z 坐标
            dt = t - s.spawn_t
            rel_z_head = s.z - cam_z + s.speed * dt
            rel_z_tail = rel_z_head + s.length

            if rel_z_tail <= 5.0 or rel_z_head > D:
                continue
            z1 = max(5.0, rel_z_head)
            z2 = max(5.1, rel_z_tail)
            if z1 >= z2:
                continue

            # 透视投影
            proj_r1 = s.radius * F / z1
            proj_r2 = s.radius * F / z2
            x1 = cx + s.cos * proj_r1
            y1 = sh - (cy + s.sin * proj_r1)
            x2 = cx + s.cos * proj_r2
            y2 = sh - (cy + s.sin * proj_r2)

            # 屏幕外裁剪
            if (x1 < -50 and x2 < -50) or (x1 > sw + 50 and x2 > sw + 50):
                continue
            if (y1 < -50 and y2 < -50) or (y1 > sh + 50 and y2 > sh + 50):
                continue

            # 线宽
            w = max(0.5, s.thick * F / z1 * 0.15)
            if w < 0.3:
                continue

            # 透明度
            alpha = global_fade
            if z1 < 30:
                alpha *= z1 / 30.0
            if z1 > D * 0.8:
                alpha *= max(0, (D - z1) / (D * 0.2))
            alpha = max(0, min(1, alpha))
            if alpha < 0.03:
                continue

            a_int = int(alpha * 255)

            # 主体光束
            line = pyglet.shapes.Line(
                x1, y1, x2, y2,
                thickness=max(1.0, w),
                color=(s.r, s.g, s.b, a_int),
                batch=batch,
            )
            self._shapes.append(line)

            # 辉光层
            if w > 2.0 and alpha > 0.15:
                ga = int(alpha * 0.15 * 255)
                glow = pyglet.shapes.Line(
                    x1, y1, x2, y2,
                    thickness=max(1.0, w * 2.5),
                    color=(s.r, s.g, s.b, max(1, ga)),
                    batch=batch,
                )
                self._shapes.append(glow)

    # ───── 中心辉光 ─────

    def _add_glow(self, batch, t, t_start, t_end, tint, fade=1.0):
        cx, cy = self._cx, self._cy
        sh = self._sh
        pt = (t - t_start) / max(0.01, t_end - t_start)
        if pt < 0 or pt > 1.3:
            return

        if pt < 0.15:
            intensity = (pt / 0.15) * 0.6
        elif pt < 0.7:
            intensity = 0.6 + 0.4 * ((pt - 0.15) / 0.55)
        else:
            intensity = max(0, 1.0 - (pt - 0.7) / 0.3)
        intensity *= fade

        max_r = int(90 * intensity)
        if max_r < 3:
            return

        tr, tg, tb = tint
        steps = min(max_r, 20)
        for i in range(steps):
            f = i / steps
            r = int(max_r * (1 - f))
            if r < 2:
                continue
            brightness = (1 - f) ** 0.5
            cr = min(255, int(tr * 0.3 + 225 * brightness * 0.7))
            cg = min(255, int(tg * 0.3 + 225 * brightness * 0.7))
            cb = min(255, int(tb * 0.3 + 225 * brightness * 0.7))
            a = int(intensity * brightness * 0.3 * 255)
            if a < 3:
                continue
            circ = pyglet.shapes.Circle(
                cx, sh - cy, r,
                segments=max(20, r),
                color=(cr, cg, cb, max(1, a)),
                batch=batch,
            )
            self._shapes.append(circ)

    # ───── 文字 ─────

    def _draw_text(self, t):
        cx, cy = self._cx, self._cy
        sh = self._sh

        t_in_s = self.P2_START
        t_in_e = t_in_s + 0.7
        t_disp_e = t_in_e + 0.5
        t_out_e = t_disp_e + 0.55
        t_fade_e = self.P2_END

        ref_z = 35.0
        bs1, bs2 = 36, 40

        if t < t_in_e:
            ft = (t - t_in_s) / max(0.01, t_in_e - t_in_s)
            et = 1 - (1 - min(1.0, ft)) ** 3
            z = 250 + (ref_z - 250) * et
        elif t < t_disp_e:
            z = ref_z
        elif t < t_out_e:
            ft = (t - t_disp_e) / max(0.01, t_out_e - t_disp_e)
            et = min(1.0, ft) ** 3
            z = ref_z + (0.8 - ref_z) * et
        else:
            z = 0.5

        if z < 0.5:
            return
        scale = ref_z / z
        s1 = max(4, min(300, int(bs1 * scale)))
        s2 = max(4, min(350, int(bs2 * scale)))
        if s1 > 250:
            return

        vis = 1.0
        if t < t_in_s + 0.15:
            vis = (t - t_in_s) / 0.15
        if t > t_out_e - 0.15:
            vis = max(0, (t_fade_e - t) / (t_fade_e - t_out_e + 0.15))
        vis = max(0, min(1, vis))
        if vis < 0.02:
            return

        tv = int(180 + (20 - 180) * vis)
        y1 = sh - (cy - 30 * scale)
        y2 = sh - (cy + 30 * scale)

        # Glitch
        gx, gy = 0, 0
        if t < t_in_e:
            ft = (t - t_in_s) / max(0.01, t_in_e - t_in_s)
            if ft > 0.3:
                g = math.sin(t * 67) * math.sin(t * 31)
                if abs(g) > 0.6:
                    gx = random.randint(-3, 3)
                    gy = random.randint(-2, 2)

        show_ghost = False
        gdx, gdy = 0, 0
        if t_in_e <= t < t_disp_e:
            show_ghost = True
            st = (t - t_in_e) / max(0.01, t_disp_e - t_in_e)
            if st < 0.3:
                e = 1 - (1 - st / 0.3) ** 3
                gdx, gdy = int(8 * e), int(4 * e)
            elif st < 0.7:
                gdx, gdy = 8, 4
                g = math.sin(t * 41) * math.sin(t * 19)
                if abs(g) > 0.7:
                    gdx += random.randint(-2, 2)
                    gdy += random.randint(-1, 1)
            else:
                e = 1 - (1 - min(1.0, (st - 0.7) / 0.3)) ** 3
                gdx, gdy = int(8 * (1 - e)), int(4 * (1 - e))
                if gdx == 0 and gdy == 0:
                    show_ghost = False
        if t >= t_disp_e and t < t_out_e:
            show_ghost = True
            ot = (t - t_disp_e) / max(0.01, t_out_e - t_disp_e)
            gdx, gdy = int(15 * ot), int(8 * ot)
            gx = random.randint(-5, 5)
            gy = random.randint(-3, 3)

        try:
            if show_ghost and (gdx > 0 or gdy > 0) and s1 < 200:
                gv = min(200, tv + 50)
                ga = int(vis * 180)
                pyglet.text.Label(
                    'Welcome to', font_name='Consolas', font_size=s1,
                    bold=True, color=(gv, gv, gv, max(1, ga)),
                    x=cx + gx + gdx, y=y1 + gy + gdy,
                    anchor_x='center', anchor_y='center').draw()
                pyglet.text.Label(
                    '咲 Midi Player !', font_name='Consolas', font_size=s2,
                    bold=True, color=(gv, gv, gv, max(1, ga)),
                    x=cx + gx + gdx, y=y2 + gy + gdy,
                    anchor_x='center', anchor_y='center').draw()

            if s1 < 200:
                a = int(vis * 255)
                pyglet.text.Label(
                    'Welcome to', font_name='Consolas', font_size=s1,
                    bold=True, color=(tv, tv, tv, max(1, a)),
                    x=cx + gx, y=y1 + gy,
                    anchor_x='center', anchor_y='center').draw()
                pyglet.text.Label(
                    '咲 Midi Player !', font_name='Consolas', font_size=s2,
                    bold=True, color=(tv, tv, tv, max(1, a)),
                    x=cx + gx, y=y2 + gy,
                    anchor_x='center', anchor_y='center').draw()
        except Exception:
            pass

    # ───── 白闪 ─────

    def _add_whiteout(self, batch, t):
        sw, sh = self._sw, self._sh
        wt = min(1.0, (t - self.P4_START) / 1.2)

        if wt < 0.4:
            et = 1 - (1 - wt / 0.4) ** 3
            v = int((0.82 + 0.18 * et) * 255)
        else:
            et = 1 - (1 - min(1, (wt - 0.4) / 0.3)) ** 3
            v = int((0.94 + 0.06 * et) * 255)

        v = min(255, v)
        rect = pyglet.shapes.Rectangle(
            0, 0, sw, sh,
            color=(v, v, min(255, v + 5), 255),
            batch=batch,
        )
        self._shapes.append(rect)

        # 中心光晕
        if wt < 0.7:
            cx, cy = self._cx, self._cy
            et = 1 - (1 - wt / 0.7) ** 3
            glow_r = int(30 + 470 * et)
            steps = min(glow_r, 15)
            for i in range(steps):
                f = i / steps
                r = int(glow_r * (1 - f))
                if r < 3:
                    continue
                brightness = (1 - f) ** 0.5
                gv = min(255, v + int(10 * brightness))
                a = int(80 * brightness)
                c = pyglet.shapes.Circle(
                    cx, sh - cy, r,
                    segments=max(20, r),
                    color=(gv, gv, min(255, gv + 3), max(1, a)),
                    batch=batch,
                )
                self._shapes.append(c)


def run_link_start(on_done=None, tk_root=None):
    """便捷启动函数"""
    renderer = LinkStartGL(on_done=on_done, tk_root=tk_root)
    renderer.run()


if __name__ == '__main__':
    run_link_start(on_done=lambda: print("Link Start 完成!"))
