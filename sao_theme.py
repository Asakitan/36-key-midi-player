# -*- coding: utf-8 -*-
"""
SAO Utils 风格 UI 组件
在 tkinter 中重现 SAO 风格的:
  - PopUpMenu (全屏弹出菜单 + 半透明遮罩)
  - MenuBar (圆形图标按钮条, 下落动画, 滚轮切换)
  - LeftInfo (左侧用户信息面板, 展开动画)
  - ChildBar (右侧子菜单, 下拉动画)
  - SAO Alert (对话框, 宽度展开动画, 文字渐现)
  - HP Bar (血条进度条, 绿/黄/红渐变)
  - LinkStart (LINK START 粒子入场动画)
"""

import tkinter as tk
import math
import time
import random
import os
import ctypes
import struct
from PIL import Image, ImageDraw, ImageFilter, ImageTk, ImageEnhance, ImageChops, ImageFont
from typing import Optional, Callable, List, Dict, Tuple
import numpy as np
from sao_sound import get_sao_font as _sao_font, get_cjk_font as _cjk_font

try:
    import moderngl
    _HAS_MODERNGL = True
except ImportError:
    _HAS_MODERNGL = False


# ──────────────────────── 配色 ────────────────────────
class SAOColors:
    """SAO Utils 原版配色 (来自 Vue 组件 CSS)"""
    # 遮罩 / 背景
    OVERLAY_BG = '#000000'
    OVERLAY_ALPHA = 0.70

    # 圆形按钮
    CIRCLE_BORDER = '#c9c6c6'
    CIRCLE_BG = '#ffffffd9'
    CIRCLE_ICON = '#b9b7b7'

    # 激活态 (金色)
    ACTIVE_BORDER = '#f3af12'
    ACTIVE_BG = '#f3af12'
    ACTIVE_ICON = '#ffffff'

    # 悬停
    HOVER_BG = '#f3af12'
    HOVER_ICON = '#ffffff'

    # 子菜单
    CHILD_BG = '#ffffffd9'
    CHILD_HOVER = '#dea620'
    CHILD_HOVER_FG = '#fbf5e7'
    CHILD_TEXT = '#333333'
    CHILD_LINE = '#7c7c7c'

    # 左侧信息面板
    INFO_BG = '#ffffffd9'
    INFO_BOTTOM = '#e5e3e3cc'
    INFO_TITLE_BORDER = '#aaaaaa'
    INFO_TRIANGLE = '#ffffff99'

    # Alert 对话框
    ALERT_BG = '#ffffffcc'
    ALERT_PANEL = '#eae9e9b3'
    ALERT_TITLE_FG = '#646364'
    ALERT_CONTENT_FG = '#646060'
    ALERT_SHADOW = '#00000033'
    CLOSE_RED = '#d13d4f'
    OK_BLUE = '#428ce6'

    # HP 血条
    HP_BG = '#cdddf880'
    HP_HOVER = '#e5e7ec99'
    HP_FONT_COLOR = '#e1dede'
    HP_GREEN_L = '#d3ea7c'
    HP_GREEN_R = '#9ad334'
    HP_YELLOW_L = '#ebee70'
    HP_YELLOW_R = '#f4fa49'
    HP_RED_L = '#f88c7a'
    HP_RED_R = '#ef684e'
    HP_BORDER = '#dad7d7'

    # LINK START
    LS_COLORS = ['#ff0000', '#ffff00', '#00ff00', '#0000ff',
                 '#ff00ff', '#00ffff', '#ffffff', '#ff8800']

    # 通用
    WHITE = '#ffffff'
    WHITE85 = '#ffffffd9'
    FONT_SAO = ('Segoe UI', 11)      # fallback; use _sao_font() at runtime
    FONT_ROUND = ('Microsoft YaHei UI', 10)  # fallback; use _cjk_font() at runtime

    # ── 深色应用背景 (SAO 菜单之下的播放器壳) ──
    APP_BG = '#0a0e14'
    APP_CARD = '#111820'
    APP_BORDER = '#1a3a4e'
    APP_TEXT = '#e8f4f8'
    APP_TEXT2 = '#7eb8c9'
    APP_TEXT_DIM = '#3d6070'
    APP_ACCENT = '#4de8f4'
    APP_BLUE = '#2196f3'
    APP_GREEN = '#4caf50'
    APP_RED = '#ff4444'
    APP_ORANGE = '#ff9800'
    APP_GOLD = '#ffd700'


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
    """Strip 8-digit RGBA hex to 6-digit RGB (tkinter doesn't support alpha)."""
    c = c.strip()
    if c.startswith('#') and len(c) == 9:
        return c[:7]
    return c


def lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = hex_to_rgb(_strip_alpha(c1))
    r2, g2, b2 = hex_to_rgb(_strip_alpha(c2))
    return rgb_to_hex(int(lerp(r1, r2, t)), int(lerp(g1, g2, t)), int(lerp(b1, b2, t)))


# ──────────────────── 通用动画引擎 ────────────────────
class Animator:
    """用 after() 驱动的属性动画引擎"""

    def __init__(self, widget: tk.Widget):
        self.widget = widget
        self._jobs: Dict[str, str] = {}

    def animate(self, name: str, duration_ms: int, callback: Callable[[float], None],
                on_done: Optional[Callable] = None, easing=ease_out):
        if name in self._jobs:
            self.widget.after_cancel(self._jobs[name])
        # 时间驱动 (不累积误差, 消除撕裂)
        t0 = time.time()
        dur = max(0.001, duration_ms / 1000.0)

        def tick():
            if not self.widget.winfo_exists():
                return
            t = min(1.0, (time.time() - t0) / dur)
            callback(easing(t))
            if t < 1.0:
                try:
                    self._jobs[name] = self.widget.after(16, tick)
                except Exception:
                    self._jobs.pop(name, None)
            else:
                self._jobs.pop(name, None)
                if on_done:
                    on_done()

        tick()

    def cancel(self, name: str):
        if name in self._jobs:
            try:
                self.widget.after_cancel(self._jobs[name])
            except Exception:
                pass
            del self._jobs[name]

    def cancel_all(self):
        for name in list(self._jobs):
            self.cancel(name)


# ──────────────────── 圆形图标按钮 ────────────────────
class SAOCircleButton(tk.Canvas):
    """
    SAO 风格圆形图标按钮 (54px)
    - 边框 2px solid rgba(201,198,198,0.6)
    - 内圆白底 + 图标
    - 激活: 金色边框 + 金色填充
    - 悬停: 金色高亮
    """
    RADIUS = 27
    SIZE = 54

    def __init__(self, parent, icon_text: str = '●', name: str = '',
                 can_activate: bool = True, command: Optional[Callable] = None, **kw):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, bd=0, bg=parent.cget('bg'), **kw)
        self.icon_text = icon_text
        self.name = name
        self.can_activate = can_activate
        self.command = command
        self._active = False
        self._hovering = False
        self._hover_t = 0.0  # 0=normal, 1=hover/active (用于平滑过渡)
        self._size = float(self.SIZE)  # 实例级尺寸, 鱼眼缩放时动态修改
        self._anim = Animator(self)

        self._draw()
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, v):
        self._active = v
        self._draw()

    def _draw(self):
        self.delete('all')
        _s = int(self._size)       # 当前实例尺寸 (鱼眼时与 SIZE 不同)
        cx, cy = _s // 2, _s // 2
        t = self._hover_t

        if self._active:
            border_color = SAOColors.ACTIVE_BORDER
        else:
            border_color = lerp_color(SAOColors.CIRCLE_BORDER, SAOColors.ACTIVE_BORDER, t)

        # ── PIL 4× 超采样抗锯齿 (premultiplied-alpha composite) ──
        scale = 4
        ss = _s * scale
        scx, scy = ss // 2, ss // 2
        # 在透明底上绘制, 避免 LANCZOS ringing 污染背景 RGB
        img = Image.new('RGBA', (ss, ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 主边框
        border_rgba = _hex_to_rgba(border_color, 255)
        draw.ellipse((2 * scale, 2 * scale, ss - 2 * scale, ss - 2 * scale),
                     outline=border_rgba, width=2 * scale, fill=None)

        # 内圆填充
        ir = scx - 4 * scale
        if self._active:
            inner_fill = _hex_to_rgba(SAOColors.ACTIVE_BG, 255)
        else:
            inner_hex = lerp_color('#ffffff', SAOColors.HOVER_BG, t)
            inner_fill = _hex_to_rgba(inner_hex, 255)
        draw.ellipse((scx - ir, scy - ir, scx + ir, scy + ir),
                     fill=inner_fill, outline=None)

        # ── premultiplied-alpha LANCZOS → 消除 dark-halo ──
        arr = np.array(img, dtype=np.float32)
        a = arr[:, :, 3:4] / 255.0
        arr[:, :, :3] *= a                          # premultiply
        premul = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')
        resized = premul.resize((_s, _s), Image.LANCZOS)

        # ── composite against transparent-key bg (1,1,1) ──
        r_arr = np.array(resized, dtype=np.float32)
        fg_a = r_arr[:, :, 3:4] / 255.0
        # premul composite:  result = fg_premul + bg*(1-fg_a)
        key_f = np.float32(1.0)                      # key color channel value
        out_rgb = r_arr[:, :, :3] + key_f * (1.0 - fg_a)
        # build final opaque image
        final_arr = np.empty((_s, _s, 4), dtype=np.uint8)
        final_arr[:, :, :3] = out_rgb.clip(0, 255).astype(np.uint8)
        final_arr[:, :, 3] = 255
        # snap background (original alpha ≈ 0) to exact key → 100% match
        bg_mask = r_arr[:, :, 3] < 32.0
        final_arr[bg_mask, 0] = 1
        final_arr[bg_mask, 1] = 1
        final_arr[bg_mask, 2] = 1

        final = Image.fromarray(final_arr, 'RGBA')
        photo = ImageTk.PhotoImage(final)
        self._bg_photo = photo  # prevent GC
        self.create_image(0, 0, image=photo, anchor='nw')

        # ── 图标 (保留 Tk 文字渲染 — ClearType 抗锯齿) ──
        if self._active:
            icon_color = SAOColors.ACTIVE_ICON
        else:
            icon_color = lerp_color(SAOColors.CIRCLE_ICON, SAOColors.HOVER_ICON, t)

        fs = max(8, int(16 * self._size / self.SIZE))
        try:
            self.create_text(cx, cy, text=self.icon_text,
                             fill=icon_color, font=_sao_font(fs))
        except Exception:
            self.create_text(cx, cy, text='●',
                             fill=icon_color, font=_sao_font(fs))

    def _on_enter(self, e=None):
        self._hovering = True
        self._anim.animate('hover', 200,
                           lambda t: self._set_hover_t(t))

    def _on_leave(self, e=None):
        self._hovering = False
        start = self._hover_t

        def fade(t):
            self._set_hover_t(lerp(start, 0, t))

        self._anim.animate('hover', 200, fade)

    def _set_hover_t(self, t):
        self._hover_t = max(0, min(1, t))
        self._draw()

    def _on_click(self, e=None):
        if self.can_activate:
            self._active = not self._active
        if self.command:
            self.command()
        self._draw()


# ──────────────────── 菜单栏 (MenuBar) ────────────────────
class SAOMenuBar(tk.Frame):
    """
    SAO 风格垂直菜单栏
    - 最多显示 5 个圆形按钮
    - 下落动画 (from top:-500 to top:0)
    - 滚轮滚动
    - 点击激活 → 触发 LeftInfo + ChildBar
    """

    def __init__(self, parent, icon_arr: List[Dict], on_activate=None, **kw):
        super().__init__(parent, bg='', highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self.icon_arr = list(icon_arr)
        self.on_activate = on_activate
        self._buttons: List[SAOCircleButton] = []
        self._slots:   List[tk.Frame] = []
        self._active_item = None
        self._hover_idx: Optional[int] = None
        self._float_job = None
        self._float_phases: List[float] = []
        self._anim = Animator(self)
        self.bind('<Destroy>', lambda e: self._stop_float())
        self._build()

    _SLOT = 70  # 按钮槽尺寸(px) — 大于 SIZE=54 以容纳鱼眼放大后的按钮

    def _build(self):
        self._stop_float()
        for w in self.winfo_children():
            w.destroy()
        self._buttons.clear()
        self._slots.clear()
        bg = self.cget('bg')
        for idx, item in enumerate(self.icon_arr[:5]):
            slot = tk.Frame(self, width=self._SLOT, height=self._SLOT, bg=bg)
            slot.pack_propagate(False)
            slot.pack(side='top')
            btn = SAOCircleButton(
                slot,
                icon_text=item.get('icon', '●'),
                name=item.get('name', ''),
                can_activate=item.get('can_active', True),
                command=lambda it=item: self._on_item_click(it)
            )
            _off = (self._SLOT - SAOCircleButton.SIZE) // 2
            btn.place(x=_off, y=_off)
            self._buttons.append(btn)
            self._slots.append(slot)
            # 鱼眼: hover 时通知 MenuBar 更新所有按钮尺寸
            btn.bind('<Enter>', lambda e, i=idx: self._on_fisheye(i), add='+')
            btn.bind('<Leave>', lambda e: self._off_fisheye(),         add='+')
        self.bind_all_recursive('<MouseWheel>', self._on_scroll)
        self._float_phases = [i * 1.57 for i in range(len(self._buttons))]
        self._start_float()

    def bind_all_recursive(self, event, handler):
        self.bind(event, handler)
        for slot in self._slots:
            slot.bind(event, handler)
        for btn in self._buttons:
            btn.bind(event, handler)

    def _on_item_click(self, item):
        if not item.get('can_active', True):
            return
        try:
            from sao_sound import play_sound as _ps
            _ps('click', volume=0.5)
        except Exception:
            pass
        if self._active_item and self._active_item.get('name') == item.get('name'):
            self._active_item = None
            for btn in self._buttons:
                btn.active = False
            if self.on_activate:
                self.on_activate(None)
            return
        self._active_item = item
        for btn in self._buttons:
            btn.active = (btn.name == item.get('name'))
        if self.on_activate:
            self.on_activate(item)

    def _on_scroll(self, e):
        if not self.icon_arr or len(self.icon_arr) <= 5:
            return
        if e.delta > 0:
            self.icon_arr.insert(0, self.icon_arr.pop())
        else:
            self.icon_arr.append(self.icon_arr.pop(0))
        self._active_item = None
        if self.on_activate:
            self.on_activate(None)
        self._build()

    def play_enter_animation(self):
        """下落入场: 按钮逐个从透明变为可见, 带缩放效果"""
        self._stop_float()
        total = len(self._buttons)
        for i, (btn, slot) in enumerate(zip(self._buttons, self._slots)):
            delay = i * 80
            btn.configure(cursor='')

            def animate_btn(b=btn, d=delay, sl=slot, is_last=(i == total - 1)):
                anim = Animator(b)
                b._size = 1.0
                b.configure(width=1, height=1)
                _c = (self._SLOT - 1) // 2
                b.place(in_=sl, x=_c, y=_c)

                def grow(t, button=b, slt=sl, last=is_last):
                    s = int(SAOCircleButton.SIZE * ease_out(t))
                    s = max(1, s)
                    button._size = float(s)
                    button.configure(width=s, height=s)
                    _off = (self._SLOT - s) // 2
                    button.place(in_=slt, x=_off, y=_off)
                    if t >= 1.0:
                        button.configure(cursor='hand2')
                        button._draw()
                        if last:
                            self._start_float()

                b.after(d, lambda: anim.animate('grow', 300, grow))

            animate_btn()


    # ── 浮动 + 鱼眼循环 ──────────────────────────────────────────

    def _start_float(self):
        self._stop_float()
        if not self.winfo_exists():
            return
        self._do_float()

    def _stop_float(self):
        if self._float_job:
            try:
                self.after_cancel(self._float_job)
            except Exception:
                pass
            self._float_job = None

    def _do_float(self):
        if not self.winfo_exists() or not self._buttons:
            return
        now = time.time()
        for i, (btn, slot) in enumerate(zip(self._buttons, self._slots)):
            # 鱼眼目标尺寸: 高斯衰减, 悬停按钮 +22%, 相邻 +8%
            if self._hover_idx is not None:
                dist = abs(self._hover_idx - i)
                target = SAOCircleButton.SIZE * (1.0 + 0.22 * math.exp(-0.9 * dist * dist))
            else:
                target = float(SAOCircleButton.SIZE)
            # 平滑插值 (每帧趋近 28%)
            btn._size += (target - btn._size) * 0.28
            s = max(1, int(btn._size))
            if abs(s - btn.winfo_width()) > 0:
                btn.configure(width=s, height=s)
                btn._draw()
            # 垂直浮动 (各按钮相位不同, 像海浪)
            dy = 2.5 * math.sin(now * 1.4 + self._float_phases[i])
            _off = (self._SLOT - s) // 2
            btn.place(in_=slot, x=_off, y=int(_off + dy))
        self._float_job = self.after(16, self._do_float)

    def _on_fisheye(self, idx: int):
        self._hover_idx = idx

    def _off_fisheye(self):
        self._hover_idx = None


# ──────────────────── 左侧信息面板 (LeftInfo) ────────────────────
class SAOLeftInfo(tk.Frame):
    """
    SAO 风格左侧用户信息面板
    - 顶部: 白色背景, 用户名 + 插槽内容
    - 底部: 灰色背景, 描述文字
    - 右三角箭头指示器
    - 展开/关闭动画
    """

    def __init__(self, parent, username: str = 'Player',
                 description: str = 'Welcome to SAO world', **kw):
        super().__init__(parent, bg='', highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self.username = username
        self.description = description
        self._active = False
        self._anim = Animator(self)
        self._target_w = 240
        self._top_h = 200
        self._bottom_h = 80

        self._build()

    def _build(self):
        self._top = tk.Canvas(self, width=0, height=0,
                              bg='#ffffff', highlightthickness=0)
        self._top.pack(anchor='nw')

        self._bottom = tk.Canvas(self, width=0, height=0,
                                 bg='#e5e3e3', highlightthickness=0)
        self._bottom.pack(anchor='nw')

    def set_active(self, active: bool):
        if active == self._active:
            return
        self._active = active
        if active:
            self._animate_open()
        else:
            self._animate_close()

    def _animate_open(self):
        def phase1(t):
            w = max(1, int(self._target_w * t))
            h = max(1, int(self._top_h * t))
            self._top.configure(width=w, height=h)
            self._redraw_top(w, h)

        def phase2(t):
            h = max(1, int(self._bottom_h * t))
            self._bottom.configure(width=self._target_w, height=h)
            self._redraw_bottom(self._target_w, h)

        self._anim.animate('top_open', 500, phase1,
                           on_done=lambda: self._anim.animate('bottom_open', 500, phase2))

    def _animate_close(self):
        def fade(t):
            inv = 1 - t
            w = max(1, int(self._target_w * inv))
            self._top.configure(width=w, height=max(1, int(self._top_h * inv)))
            self._bottom.configure(width=w, height=max(1, int(self._bottom_h * inv)))

        self._anim.animate('close', 200, fade)

    def _redraw_top(self, w, h):
        self._top.delete('all')
        if w < 20 or h < 20:
            return
        # 底部阴影渐变
        for i in range(6):
            av = int(20 * (1 - i / 6))
            sc = f'#{av:02x}{av:02x}{av:02x}'
            self._top.create_line(3, h - i, w - 3, h - i, fill=sc)
        # 右三角
        self._top.create_polygon(w, h * 0.77, w + 18, h * 0.77 + 7, w, h * 0.77 + 14,
                                 fill='#ffffff', outline='')
        self._top.create_text(w // 2, 30, text=self.username,
                              font=_cjk_font(13), fill='#333333')
        if h > 50:
            # 分隔线: 渐变效果
            for i in range(3):
                lv = int(170 + i * 25)
                self._top.create_line(10 + i * 2, 50 - 1 + i, w - 10 - i * 2, 50 - 1 + i,
                                      fill=f'#{lv:02x}{lv:02x}{lv:02x}', width=1)

    def _redraw_bottom(self, w, h):
        self._bottom.delete('all')
        if w < 20 or h < 15:
            return
        # 下三角
        self._bottom.create_polygon(30, 0, 30 + 7, -10, 30 + 15, 0,
                                    fill='#e5e3e3', outline='')
        self._bottom.create_text(10, 15, text=self.description,
                                 font=_cjk_font(9), fill='#555',
                                 anchor='nw', width=w - 20)


# ──────────────────── 子菜单 (ChildBar) ────────────────────
class SAOChildBar(tk.Frame):
    """
    SAO 风格子菜单
    - 列表项: 160px宽, 40px高, 白色半透明
    - 悬停: 金色背景
    - 左侧连接线
    - 下拉动画
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg='', highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self._menus: Dict[str, List[Dict]] = {}
        self._current_name = None
        self._items: List[tk.Frame] = []
        self._anim = Animator(self)

    def register_menu(self, name: str, items: List[Dict]):
        self._menus[name] = items

    def show_menu(self, name: str):
        if name == self._current_name:
            return
        self._current_name = name
        items = self._menus.get(name, [])
        self._rebuild(items)

    def hide_menu(self):
        self._current_name = None
        for w in self.winfo_children():
            w.destroy()
        self._items.clear()

    def _rebuild(self, items: List[Dict]):
        for w in self.winfo_children():
            w.destroy()
        self._items.clear()

        if not items:
            return

        content = tk.Frame(self, bg=self.cget('bg'), highlightthickness=0)
        content.pack(anchor='nw')

        # 连接线 (带微弱辉光)
        line_h = len(items) * 43 - 3
        line_cv = tk.Canvas(content, width=10, height=max(1, line_h),
                            bg=self.cget('bg'), highlightthickness=0)
        # 辉光层
        line_cv.create_line(5, 5, 5, line_h - 5, fill='#d4d0d0', width=4)
        # 主线
        line_cv.create_line(5, 5, 5, line_h - 5, fill='#9c9999', width=2)
        # 顶部高光点
        line_cv.create_oval(3, 3, 7, 7, fill='#b0b0b0', outline='')
        # 底部高光点
        line_cv.create_oval(3, line_h - 7, 7, line_h - 3, fill='#b0b0b0', outline='')
        line_cv.pack(side=tk.LEFT, padx=(0, 3), anchor='n', pady=5)

        # 箭头指示器 (微弱金色点)
        arrow_cv = tk.Canvas(content, width=12, height=max(1, line_h),
                             bg=self.cget('bg'), highlightthickness=0)
        # 辉光
        for gr in range(6, 0, -2):
            ga = int(15 * (1 - gr / 6))
            gc = f'#{int(ga * 3.5):02x}{int(ga * 2.2):02x}{int(ga * 0.3):02x}'
            arrow_cv.create_oval(6 - gr, line_h // 2 - gr,
                                 6 + gr, line_h // 2 + gr,
                                 fill=gc, outline='')
        arrow_cv.create_oval(4, line_h // 2 - 2, 9, line_h // 2 + 3,
                             fill='#c9b896', outline='#d4c8a8')
        arrow_cv.pack(side=tk.LEFT, padx=(0, 2), anchor='n', pady=5)

        list_frame = tk.Frame(content, bg=self.cget('bg'), highlightthickness=0)
        list_frame.pack(side=tk.LEFT, anchor='n')

        for i, item in enumerate(items):
            row = self._create_item(list_frame, item, i)
            self._items.append(row)

    def _create_item(self, parent, item: Dict, index: int) -> tk.Frame:
        # 外容器: 包含阴影层 + 主体
        outer = tk.Frame(parent, bg=self.cget('bg'), highlightthickness=0)
        outer.pack(fill=tk.X, pady=(0, 3))

        row = tk.Frame(outer, bg='#ffffff', highlightthickness=0,
                       width=220, height=40)
        row.pack(fill=tk.X)
        row.pack_propagate(False)

        # 左侧激活指示条 (2px, 初始透明)
        indicator = tk.Frame(row, bg='#ffffff', width=2, height=40)
        indicator.pack(side=tk.LEFT, fill=tk.Y)
        indicator.pack_propagate(False)

        icon_lbl = tk.Label(row, text=item.get('icon', ''),
                            bg='#ffffff', fg='#555555',
                            font=_sao_font(12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 5))

        text_lbl = tk.Label(row, text=item.get('label', ''),
                            bg='#ffffff', fg=SAOColors.CHILD_TEXT,
                            font=_cjk_font(10), anchor='w')
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 右侧箭头 (hover 时显示)
        arrow_lbl = tk.Label(row, text='›', bg='#ffffff', fg='#ffffff',
                             font=('Consolas', 14))
        arrow_lbl.pack(side=tk.RIGHT, padx=(0, 8))

        # 平滑悬停过渡
        _anim = Animator(row)
        _hover_state = {'t': 0.0}

        def _update_hover(t, r=row, il=icon_lbl, tl=text_lbl,
                          ind=indicator, arr=arrow_lbl):
            _hover_state['t'] = t
            bg = lerp_color('#ffffff', SAOColors.CHILD_HOVER, t)
            fg = lerp_color(SAOColors.CHILD_TEXT, SAOColors.CHILD_HOVER_FG, t)
            icon_fg = lerp_color('#555555', SAOColors.CHILD_HOVER_FG, t)
            ind_color = lerp_color('#ffffff', SAOColors.ACTIVE_BORDER, t)
            arr_fg = lerp_color('#ffffff', SAOColors.CHILD_HOVER_FG, t)
            r.configure(bg=bg)
            il.configure(bg=bg, fg=icon_fg)
            tl.configure(bg=bg, fg=fg)
            ind.configure(bg=ind_color)
            arr.configure(bg=bg, fg=arr_fg)

        def enter(e, a=_anim):
            a.animate('hover', 150, lambda t: _update_hover(t))
            try:
                from sao_sound import play_sound as _ps
                _ps('click', volume=0.3)
            except Exception:
                pass

        def leave(e, a=_anim, hs=_hover_state):
            start = hs['t']
            a.animate('hover', 200, lambda t: _update_hover(lerp(start, 0, t)))

        for widget in [row, icon_lbl, text_lbl, indicator, arrow_lbl]:
            widget.bind('<Enter>', enter)
            widget.bind('<Leave>', leave)
            cmd = item.get('command')
            if cmd:
                def _click_with_sound(e, c=cmd):
                    try:
                        from sao_sound import play_sound as _ps
                        _ps('click', volume=0.5)
                    except Exception:
                        pass
                    c()
                widget.bind('<Button-1>', _click_with_sound)

        # 入场动画: 从右侧滑入
        row.configure(width=0)
        delay = index * 60

        def slide_in(r=row):
            a = Animator(r)

            def grow(t, r2=r):
                w = max(1, int(220 * ease_out(t)))
                r2.configure(width=w)

            a.animate('slide', 250, grow)

        row.after(delay, slide_in)

        return outer


# ──────────────────── 弹出菜单容器 (PopUpMenu) ────────────────────
class SAOPopUpMenu:
    """
    SAO 风格全屏弹出菜单
    - Alt+A 或滑动下拉呼出
    - 半透明深色遮罩 (70% 黑)
    - 居中: MenuBar + LeftInfo + ChildBar
    - 呼吸浮动动画 (8px偏移, 8s周期)
    - fadeIn/fadeOut 过渡
    - 点击空白关闭
    """

    def __init__(self, root: tk.Tk, icon_arr: List[Dict],
                 child_menus: Dict[str, List[Dict]],
                 username: str = 'Player',
                 description: str = 'Welcome to SAO world',
                 on_close: Optional[Callable] = None,
                 on_open: Optional[Callable] = None,
                 key_code: str = 'a',
                 slide_down: bool = True,
                 left_widget_factory: Optional[Callable] = None,
                 anchor_widget=None):
        self.root = root
        self.icon_arr = icon_arr
        self.child_menus = child_menus
        self.username = username
        self.description = description
        self.on_close_callback = on_close
        self.on_open_callback = on_open
        self.key_code = key_code
        self.slide_down = slide_down
        self.left_widget_factory = left_widget_factory
        self.anchor_widget = anchor_widget
        # 锚定位置 (anchor_widget 模式下存储内容左上角坐标)
        self._content_x: Optional[int] = None
        self._content_y: Optional[int] = None

        self._overlay: Optional[tk.Toplevel] = None
        self._left_widget = None
        self._visible = False
        self._throttle_timer = None
        self._breath_job = None
        self._menu_hud_job = None
        self._menu_hud_cv = None
        self._menu_hud_backdrop = None
        self._menu_hud_backdrop_key = None
        self._root_click_id = None
        self._first_y = 0
        self._first_time = 0
        self._slide_threshold = 250
        self._slide_duration = 666

    def bind_events(self):
        self.root.bind_all('<Alt-KeyPress>', self._on_alt_key)
        if self.slide_down:
            self.root.bind_all('<ButtonPress-1>', self._on_mouse_down)
            self.root.bind_all('<B1-Motion>', self._on_mouse_drag)

    def unbind_events(self):
        try:
            self.root.unbind_all('<Alt-KeyPress>')
            self.root.unbind_all('<ButtonPress-1>')
            self.root.unbind_all('<B1-Motion>')
        except Exception:
            pass

    def _on_alt_key(self, e):
        if e.keysym.lower() == self.key_code.lower():
            if not self._visible:
                self.open()
            else:
                self.close()

    def _on_mouse_down(self, e):
        self._first_y = e.y_root
        self._first_time = time.time() * 1000

    def _on_mouse_drag(self, e):
        if self._visible:
            return
        dy = e.y_root - self._first_y
        dt = time.time() * 1000 - self._first_time
        if dy > self._slide_threshold and dt < self._slide_duration:
            if not self._throttle_timer:
                self.open()
                self._throttle_timer = self.root.after(1000, self._reset_throttle)

    def _reset_throttle(self):
        self._throttle_timer = None

    def open(self):
        if self._visible:
            return
        self._visible = True
        self._create_overlay()

    def close(self):
        if not self._visible:
            return
        self._visible = False
        self._fade_out_and_destroy()

    def toggle(self):
        if self._visible:
            self.close()
        else:
            self.open()

    @property
    def visible(self):
        return self._visible

    _TRANSPARENT_KEY = '#010101'   # 透明色键 (Windows -transparentcolor)

    def _create_overlay(self):
        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._overlay.geometry(f'{sw}x{sh}+0+0')
        self._overlay.configure(bg=self._TRANSPARENT_KEY)
        self._overlay.attributes('-alpha', 0.0)
        # 透明色键: 使 overlay 背景完全透明, 只保留 HUD 元素和内容组件
        try:
            self._overlay.attributes('-transparentcolor', self._TRANSPARENT_KEY)
        except Exception:
            pass
        self._overlay.bind('<Escape>', lambda e: self.close())
        self._overlay.bind('<FocusOut>', self._on_overlay_focus_out)

        self._menu_hud_cv = tk.Canvas(
            self._overlay, bg=self._TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self._menu_hud_cv.place(x=0, y=0, relwidth=1, relheight=1)

        # 在 root 窗口层检测点击 → 实现 "点击外部关闭" (透明区域点击穿透到 root)
        self._root_click_id = self.root.bind('<Button-1>',
            self._on_root_click_outside, add='+')

        # 内容定位: anchor_widget 模式 → 贴近浮动按钮右上角向左上展开; 否则居中
        self._content = tk.Frame(self._overlay, bg=self._TRANSPARENT_KEY, highlightthickness=0)
        try:
            aw = self.anchor_widget
            if aw and aw.winfo_exists():
                self._overlay.update_idletasks()
                ax = aw.winfo_rootx()
                ay = aw.winfo_rooty()
                awd = aw.winfo_width()
                # SE 角贴近 float 右上角 (向左上展开)
                # 确保右侧不超出屏幕
                self._content_x = min(ax + awd - 8, sw - 20)
                self._content_y = ay - 8
                self._content.place(x=self._content_x, y=self._content_y, anchor='se')
            else:
                self._content_x = None
                self._content_y = None
                self._content.place(relx=0.5, rely=0.5, anchor='center')
        except Exception:
            self._content_x = None
            self._content_y = None
            self._content.place(relx=0.5, rely=0.5, anchor='center')

        # 水平: LeftInfo | MenuBar | ChildBar
        if self.left_widget_factory:
            self._left_widget = self.left_widget_factory(self._content)
            self._left_widget.pack(side=tk.LEFT, padx=(0, 25), anchor='n')
            self._left_info = None
        else:
            self._left_info = SAOLeftInfo(self._content, self.username, self.description)
            self._left_info.pack(side=tk.LEFT, padx=(0, 25), anchor='n')
            self._left_widget = self._left_info

        self._menu_bar = SAOMenuBar(self._content, self.icon_arr,
                                    on_activate=self._on_menu_activate)
        self._menu_bar.pack(side=tk.LEFT, anchor='n')

        self._child_bar = SAOChildBar(self._content)
        self._child_bar.pack(side=tk.LEFT, padx=(25, 0), anchor='n')

        for name, items in self.child_menus.items():
            self._child_bar.register_menu(name, items)

        self._overlay.update_idletasks()
        self._draw_menu_hud(0, 0, phase=0.0)

        # fadeIn 0.4s + 弹出入场动画
        self._anim = Animator(self._overlay)

        # 内容入场: 在 fade-in 期间从稍高处向下弹入 (spring pop)
        spring_offset = 28  # 入场起始偏移量(px)

        def _spring_ease(t: float) -> float:
            """spring: overshoot 则小弹超, 平滑落地"""
            # 使用近似弹簧曲线: ease-out 加轻微反射
            if t < 0.7:
                return ease_out(t / 0.7) * 1.06
            else:
                return 1.0 + (1.06 - 1.0) * (1.0 - (t - 0.7) / 0.3)  # 回弹到 1.0

        def _anim_frame(t: float):
            alpha = t * 0.92
            self._set_alpha(alpha)
            # 内容各sprite 从偏移位置弹至目标
            st = _spring_ease(t)
            dy = int(spring_offset * (1.0 - st))
            try:
                if self._content_x is not None:
                    self._content.place(
                        x=self._content_x,
                        y=self._content_y - dy,
                        anchor='se')
                else:
                    self._content.place(relx=0.5, rely=0.5, anchor='center',
                                        x=0, y=dy)
            except Exception:
                pass

        self._anim.animate('fade_in', 420, _anim_frame)

        # 菜单栏入场动画
        self._menu_bar.play_enter_animation()
        self._start_breath()
        self._start_menu_hud_anim()

        if self.on_open_callback:
            self.on_open_callback()

        try:
            self._overlay.focus_force()
        except Exception:
            pass

    def _set_alpha(self, a):
        try:
            if self._overlay and self._overlay.winfo_exists():
                # 映射 0..0.92 → 0..1.0, 最终态 alpha=1.0 消除 transparentcolor 黑色描边
                if a <= 0.005:
                    self._overlay.attributes('-alpha', 0.0)
                else:
                    self._overlay.attributes('-alpha', min(1.0, a / 0.92))
        except Exception:
            pass

    def _get_visual_bounds(self):
        """返回当前实际可见菜单区域边界，忽略透明占位区域."""
        if not self._content or not self._content.winfo_exists():
            return None
        try:
            self._content.update_idletasks()
            boxes = []
            for child in self._content.winfo_children():
                w = child.winfo_width() or child.winfo_reqwidth()
                h = child.winfo_height() or child.winfo_reqheight()
                if w <= 4 or h <= 4:
                    continue
                x = child.winfo_x()
                y = child.winfo_y()
                boxes.append((x, y, x + w, y + h))
            if not boxes:
                x = self._content.winfo_x()
                y = self._content.winfo_y()
                w = self._content.winfo_width() or self._content.winfo_reqwidth()
                h = self._content.winfo_height() or self._content.winfo_reqheight()
                return (x, y, x + w, y + h)
            return (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
        except Exception:
            return None

    def _get_menu_backdrop_sprite(self, width: int, height: int):
        width = max(260, int(width))
        height = max(180, int(height))
        key = (width, height)
        if self._menu_hud_backdrop_key == key and self._menu_hud_backdrop is not None:
            return self._menu_hud_backdrop

        pad = 64
        img_w = width + pad * 2
        img_h = height + pad * 2

        shadow = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle((pad + 12, pad + 16, pad + width + 12, pad + height + 16),
                radius=46, fill=(0, 0, 0, 56))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=22))

        plate = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(plate)
        outer = (pad, pad, pad + width, pad + height)
        inner = (pad + 10, pad + 10, pad + width - 10, pad + height - 10)
        pdraw.rounded_rectangle(outer, radius=44,
                fill=(10, 16, 24, 180), outline=(110, 210, 240, 60), width=1)
        pdraw.rounded_rectangle(inner, radius=36,
                fill=(14, 20, 30, 140), outline=(160, 230, 255, 36), width=1)
        gloss = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(gloss)
        gdraw.rounded_rectangle((pad + 10, pad + 8, pad + width - 12, int(pad + height * 0.40)),
                radius=34, fill=(200, 240, 255, 18))
        gloss = gloss.filter(ImageFilter.GaussianBlur(radius=18))
        plate = Image.alpha_composite(plate, gloss)

        merged = Image.alpha_composite(shadow, plate)
        self._menu_hud_backdrop = ImageTk.PhotoImage(merged)
        self._menu_hud_backdrop_key = key
        return self._menu_hud_backdrop

    def _draw_menu_hud(self, dx: int = 0, dy: int = 0, phase: float = 0.0):
        if not self._menu_hud_cv or not self._overlay or not self._overlay.winfo_exists():
            return
        try:
            self._content.update_idletasks()
            sw = self._overlay.winfo_width()
            sh = self._overlay.winfo_height()
            cw = max(120, self._content.winfo_width() or self._content.winfo_reqwidth())
            ch = max(120, self._content.winfo_height() or self._content.winfo_reqheight())
            left = self._content.winfo_x()
            top = self._content.winfo_y()
            right = left + cw
            bottom = top + ch
        except Exception:
            return

        cv = self._menu_hud_cv
        cv.delete('all')

        CYAN = '#5eb8ca'
        GOLD = '#f3af12'
        DIM_CYAN = '#5eb8ca'
        DIM_GOLD = '#c8910e'

        # ── 2. 内容区角标 (四角 L 型支架) ──
        bk = 20
        m = 12  # margin outside content
        cx1, cy1 = left - m, top - m
        cx2, cy2 = right + m, bottom + m
        for (x, y, dx1, dy1, dx2, dy2, col) in [
            (cx1, cy1, bk, 0, 0, bk, CYAN),
            (cx2, cy1, -bk, 0, 0, bk, GOLD),
            (cx1, cy2, bk, 0, 0, -bk, CYAN),
            (cx2, cy2, -bk, 0, 0, -bk, GOLD),
        ]:
            cv.create_line(x, y, x + dx1, y + dy1, fill=col, width=1)
            cv.create_line(x, y, x + dx2, y + dy2, fill=col, width=1)

        # ── 4. 水平扫描线 (动态, 从上到下缓慢移动) ──
        scan_period = 6.0  # seconds for full sweep
        scan_pos = (phase % scan_period) / scan_period
        scan_y = int(cy1 + (cy2 - cy1) * scan_pos)
        # 扫描线本体
        cv.create_line(cx1, scan_y, cx2, scan_y, fill=CYAN, width=1)
        # 扫描线拖影 (上方2条渐淡)
        for i, a_hex in enumerate(['#3a6a78', '#2a5060']):
            cv.create_line(cx1, scan_y - 3 - i * 3,
                           cx2, scan_y - 3 - i * 3,
                           fill=a_hex, width=1)

        # ── 5. 数据标签 (系统信息风格) ──
        # 左上
        cv.create_text(cx1 + 4, cy1 - 4, text='SYS:MENU', anchor='sw',
                       font=('Consolas', 7), fill=DIM_CYAN)
        # 右上
        cv.create_text(cx2 - 4, cy1 - 4, text=f'RES:{sw}x{sh}', anchor='se',
                       font=('Consolas', 7), fill=DIM_GOLD)
        # 左下
        cv.create_text(cx1 + 4, cy2 + 4, text='ACTIVE', anchor='nw',
                       font=('Consolas', 7), fill=DIM_CYAN)
        # 右下时间戳
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        cv.create_text(cx2 - 4, cy2 + 4, text=ts, anchor='ne',
                       font=('Consolas', 7), fill=DIM_GOLD)

        # ── 6. 侧边导轨 (左右各一条, 带呼吸光点) ──
        rail_x_l = cx1 - 8
        rail_x_r = cx2 + 8
        cv.create_line(rail_x_l, cy1 + bk, rail_x_l, cy2 - bk,
                       fill=CYAN, width=1)
        cv.create_line(rail_x_r, cy1 + bk, rail_x_r, cy2 - bk,
                       fill=GOLD, width=1)

        # 呼吸光点沿导轨上下移动
        dot_travel = cy2 - cy1 - bk * 2
        dot_y_l = cy1 + bk + int(dot_travel * ((math.sin(phase * 0.8) + 1) / 2))
        dot_y_r = cy1 + bk + int(dot_travel * ((math.sin(phase * 0.8 + math.pi) + 1) / 2))
        cv.create_oval(rail_x_l - 3, dot_y_l - 3, rail_x_l + 3, dot_y_l + 3,
                       fill=CYAN, outline='')
        cv.create_oval(rail_x_r - 3, dot_y_r - 3, rail_x_r + 3, dot_y_r + 3,
                       fill=GOLD, outline='')

    def _start_menu_hud_anim(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return

        t0 = time.time()

        def _tick():
            if not self._visible or not self._overlay or not self._overlay.winfo_exists():
                return
            elapsed = time.time() - t0
            self._draw_menu_hud(0, 0, elapsed)
            self._menu_hud_job = self._overlay.after(16, _tick)

        _tick()

    def _on_root_click_outside(self, e):
        """root 层点击处理: 透明区域的点击穿透到 root, 判断是否在内容区外."""
        if not self._visible or not self._content:
            return
        try:
            bounds = self._get_visual_bounds()
            if bounds is None:
                self.close()
                return
            x1, y1, x2, y2 = bounds
            ox = self._overlay.winfo_rootx()
            oy = self._overlay.winfo_rooty()
            cx1, cy1 = ox + x1 - 12, oy + y1 - 12
            cx2, cy2 = ox + x2 + 12, oy + y2 + 12
            if cx1 <= e.x_root <= cx2 and cy1 <= e.y_root <= cy2:
                return  # 点击在内容区内, 不关闭
        except Exception:
            pass
        self.close()

    def _on_overlay_focus_out(self, _e=None):
        if not self._visible or not self._overlay or not self._overlay.winfo_exists():
            return

        def _check():
            if not self._visible or not self._overlay or not self._overlay.winfo_exists():
                return
            try:
                focus = self._overlay.focus_displayof()
                if focus is None or str(focus) == 'None':
                    self.close()
                    return
            except Exception:
                self.close()

        try:
            self._overlay.after(1, _check)
        except Exception:
            self.close()

    def _on_menu_activate(self, item):
        lw = self._left_widget
        if item is None:
            if lw and hasattr(lw, 'set_active'):
                lw.set_active(False)
            self._child_bar.hide_menu()
            return
        if lw and hasattr(lw, 'set_active'):
            lw.set_active(True)
        name = item.get('name', '')
        if name in self.child_menus:
            try:
                from sao_sound import play_sound as _ps
                _ps('submenu', volume=0.5)
            except Exception:
                pass
            self._child_bar.show_menu(name)
        else:
            self._child_bar.hide_menu()

    def refresh_child_menu(self, name: str, items: List[Dict]):
        """动态更新某个子菜单的内容"""
        self.child_menus[name] = items
        if self._child_bar:
            self._child_bar.register_menu(name, items)
            if self._child_bar._current_name == name:
                self._child_bar.show_menu(name)

    @property
    def left_widget(self):
        return self._left_widget

    def _fade_out_and_destroy(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        self._stop_breath()
        # 解除 root 层点击监听
        try:
            if hasattr(self, '_root_click_id') and self._root_click_id:
                self.root.unbind('<Button-1>', self._root_click_id)
                self._root_click_id = None
        except Exception:
            pass

        def fade(t):
            self._set_alpha(0.92 * (1 - t))

        def destroy():
            if self._overlay and self._overlay.winfo_exists():
                self._overlay.destroy()
            self._overlay = None
            if self.on_close_callback:
                self.on_close_callback()

        anim = Animator(self._overlay)
        anim.animate('fade_out', 500, fade, on_done=destroy)

    def _start_breath(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        t0 = time.time()

        def breathe():
            if not self._visible or not self._overlay or not self._overlay.winfo_exists():
                return
            elapsed = time.time() - t0
            # 双正弦叠加 → 李萨如浮动轨迹, 自然且永不重复
            # 16ms 间隔保证 60fps 流畅度
            dx = int(7 * math.sin(elapsed * 0.52) + 3 * math.sin(elapsed * 1.13))
            dy = int(5 * math.sin(elapsed * 0.38 + 1.0) + 2 * math.sin(elapsed * 0.91))
            try:
                if self._content_x is not None:
                    self._content.place(
                        x=int(self._content_x + dx),
                        y=int(self._content_y + dy),
                        anchor='se')
                else:
                    self._content.place(relx=0.5, rely=0.5, anchor='center',
                                        x=int(dx), y=int(dy))
            except Exception:
                return
            self._breath_job = self._overlay.after(16, breathe)

        breathe()

    def _stop_breath(self):
        if self._breath_job and self._overlay and self._overlay.winfo_exists():
            try:
                self._overlay.after_cancel(self._breath_job)
            except Exception:
                pass
            self._breath_job = None
        if self._menu_hud_job and self._overlay and self._overlay.winfo_exists():
            try:
                self._overlay.after_cancel(self._menu_hud_job)
            except Exception:
                pass
            self._menu_hud_job = None


# ──────────────────── SAO 对话框 (Alert) ────────────────────
class SAODialog:
    """
    SAO Utils 风格对话框
    - 三段式: 标题区(68px) + 内容区 + 按钮区(83px)
    - 宽度展开动画 (135px → 375px, 0.5s)
    - 文字 clip 渐现
    - Close: 红圆 rgb(209,61,79)
    - OK: 蓝圆 rgb(66,140,230)
    """

    @staticmethod
    def showinfo(parent, title, message, on_ok=None):
        SAODialog._show(parent, title, message, show_icon=True, on_ok=on_ok)

    @staticmethod
    def showwarning(parent, title, message, on_ok=None):
        SAODialog._show(parent, title, message, show_icon=True, on_ok=on_ok)

    @staticmethod
    def showerror(parent, title, message, on_ok=None):
        SAODialog._show(parent, title, message, show_icon=True, on_ok=on_ok)

    @staticmethod
    def ask(parent, title, message, on_ok=None, on_cancel=None):
        SAODialog._show(parent, title, message, show_icon=True,
                        on_ok=on_ok, on_cancel=on_cancel)

    @staticmethod
    def _show(parent, title, message, show_icon=True,
              on_ok=None, on_cancel=None):
        dlg = tk.Toplevel(parent)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)

        try:
            dlg.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(dlg.winfo_id())
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

        final_w = 375
        final_h = 240
        initial_w = 135

        px = (dlg.winfo_screenwidth() - final_w) // 2
        py = (dlg.winfo_screenheight() - final_h) // 2

        dlg.geometry(f'{initial_w}x{final_h}+{px + (final_w - initial_w) // 2}+{py}')

        # ── 白色 SAO 对话框配色 (与截图匹配) ──
        dlg.configure(bg='#e0e0e0')

        main_box = tk.Frame(dlg, bg='#ffffff')
        main_box.pack(fill=tk.BOTH, expand=True)
        main_box.pack_forget()

        # 标题区 (68px)
        header = tk.Frame(main_box, bg='#ffffff', height=68)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_lbl = tk.Label(header, text='', bg='#ffffff',
                             fg=SAOColors.ALERT_TITLE_FG,
                             font=_sao_font(13, True))
        title_lbl.pack(expand=True)

        tk.Frame(main_box, bg='#e0e0e0', height=1).pack(fill=tk.X)

        # 内容区 (浅灰)
        content_h = final_h - 68 - 83 - 2
        content = tk.Frame(main_box, bg='#eae9e9', height=max(25, content_h))
        content.pack(fill=tk.X)
        content.pack_propagate(False)

        content_lbl = tk.Label(content, text='', bg='#eae9e9',
                               fg='#888888',
                               font=_cjk_font(10),
                               wraplength=final_w - 48, justify='center')
        content_lbl.pack(expand=True)

        tk.Frame(main_box, bg='#e0e0e0', height=1).pack(fill=tk.X)

        # 按钮区 (83px)
        footer = tk.Frame(main_box, bg='#ffffff', height=83)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        btn_container = tk.Frame(footer, bg='#ffffff')
        btn_container.place(relx=0.5, rely=0.5, anchor='center')

        def do_close():
            _close_alert(dlg)
            if on_cancel:
                on_cancel()

        def do_ok():
            _close_alert(dlg)
            if on_ok:
                on_ok()

        if show_icon:
            ok_btn = _make_aa_icon_button(btn_container, 'ok', do_ok,
                                          SAOColors.OK_BLUE, SAOColors.OK_BLUE, bg='#ffffff')
            ok_btn.pack(side=tk.LEFT, padx=20)

            close_btn = _make_aa_icon_button(btn_container, 'close', do_close,
                                             SAOColors.CLOSE_RED, SAOColors.CLOSE_RED, bg='#ffffff')
            close_btn.pack(side=tk.LEFT, padx=20)
        else:
            dlg.bind('<Button-1>', lambda e: do_close())

        # 展开动画
        anim = Animator(dlg)

        def expand(t):
            if not dlg.winfo_exists():
                return
            w = int(lerp(initial_w, final_w, t))
            x = px + (final_w - w) // 2
            dlg.geometry(f'{w}x{final_h}+{x}+{py}')

        def reveal_text():
            if not main_box.winfo_manager():
                main_box.pack(fill=tk.BOTH, expand=True)
                dlg.update_idletasks()
            _clip_reveal(title_lbl, title, dlg, 400, delay=100)
            _clip_reveal(content_lbl, message, dlg, 350, delay=600)

        anim.animate('expand', 500, expand, on_done=reveal_text)

        # 拖拽
        _drag = {'x': 0, 'y': 0}
        def start_drag(e):
            _drag['x'], _drag['y'] = e.x_root, e.y_root
        def do_drag(e):
            dx = e.x_root - _drag['x']
            dy = e.y_root - _drag['y']
            dlg.geometry(f'+{dlg.winfo_x() + dx}+{dlg.winfo_y() + dy}')
            _drag['x'], _drag['y'] = e.x_root, e.y_root
        for w in [header, title_lbl]:
            w.bind('<Button-1>', start_drag)
            w.bind('<B1-Motion>', do_drag)

        # 非阻塞: 不调用 wait_window / grab_set — 纯回调驱动
        # overrideredirect Toplevel 的 grab_set 在 Windows 上经常静默失败
        # 并导致 wait_window 永久挂起 (假性卡死)
        dlg.focus_force()


def _clip_reveal(label: tk.Label, full_text: str, dlg: tk.Toplevel,
                 duration_ms: int, delay: int = 0):
    """模拟 CSS clip-path inset 渐现: 从中间向两边展开"""
    if not full_text:
        label.configure(text='')
        return

    def start():
        if not dlg.winfo_exists():
            return
        steps = max(1, duration_ms // 30)
        step = [0]

        def tick():
            if not dlg.winfo_exists():
                return
            t = min(step[0] / steps, 1.0)
            n = len(full_text)
            visible = int(n * t)
            s = (n - visible) // 2
            e = s + visible
            display = ' ' * s + full_text[s:e] + ' ' * (n - e)
            label.configure(text=display)
            step[0] += 1
            if t < 1.0:
                dlg.after(30, tick)
            else:
                label.configure(text=full_text)

        tick()

    if delay > 0:
        dlg.after(delay, start)
    else:
        start()


def _close_alert(dlg: tk.Toplevel):
    """关闭对话框: 宽度收缩 → 消失"""
    if not dlg.winfo_exists():
        return

    # 先释放 grab
    try:
        dlg.grab_release()
    except Exception:
        pass

    cur_w = dlg.winfo_width()
    cur_h = dlg.winfo_height()
    cur_x = dlg.winfo_x()
    cur_y = dlg.winfo_y()

    anim = Animator(dlg)

    def shrink(t):
        if not dlg.winfo_exists():
            return
        w = max(1, int(lerp(cur_w, 0, t)))
        x = cur_x + (cur_w - w) // 2
        try:
            dlg.geometry(f'{w}x{cur_h}+{x}+{cur_y}')
            dlg.attributes('-alpha', 1.0 - t)
        except Exception:
            pass

    def finish():
        try:
            if dlg.winfo_exists():
                dlg.destroy()
        except Exception:
            pass

    anim.animate('close', 350, shrink, on_done=finish)


class SAOLeaderboardDialog:
    """SAO 风格排行榜对话框：分页、搜索、自适应高度、显示自身设备名与排名。"""

    def __init__(self, parent, title='排行榜', sort_by='xp'):
        self._parent = parent
        self._title = title
        self._sort_by = sort_by
        self._entries: List[Dict] = []
        self._filtered: List[Dict] = []
        self._page = 0
        self._per_page = 10
        self._self_device = ''
        self._self_device_name = ''
        self._self_rank = None
        self._focus_rank = None

        self._dlg = tk.Toplevel(parent)
        self._dlg.overrideredirect(True)
        self._dlg.attributes('-topmost', True)
        self._dlg.configure(bg='#d9dde3')

        try:
            self._dlg.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self._dlg.winfo_id())
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

        self._final_w = 660
        self._min_h = 300
        self._max_h = 600
        self._initial_w = 180
        self._current_h = self._min_h
        self._px = (self._dlg.winfo_screenwidth() - self._final_w) // 2
        self._py = (self._dlg.winfo_screenheight() - self._current_h) // 2
        self._dlg.geometry(f'{self._initial_w}x{self._current_h}+{self._px + (self._final_w - self._initial_w)//2}+{self._py}')

        main = tk.Frame(self._dlg, bg='#ffffff')
        main.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(main, bg='#ffffff', height=58)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Frame(header, bg='#f3af12', height=3).pack(fill=tk.X)
        self._title_lbl = tk.Label(header, text=title, bg='#ffffff', fg='#646364', font=_sao_font(13, True))
        self._title_lbl.pack(expand=True)

        toolbar = tk.Frame(main, bg='#f4f5f7', height=54)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)
        search_wrap = tk.Frame(toolbar, bg='#d1d7df')
        search_wrap.pack(side=tk.LEFT, padx=(14, 8), pady=10, fill=tk.X, expand=True)
        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(search_wrap, textvariable=self._search_var,
                                      relief='flat', bd=0, bg='#ffffff', fg='#333333',
                                      font=_cjk_font(9), insertbackground='#f3af12')
        self._search_entry.pack(fill=tk.X, padx=2, pady=2, ipady=5)
        self._search_entry.bind('<Return>', lambda e: self._apply_search())
        search_btn = tk.Label(toolbar, text='搜索', bg='#1a2030', fg='#e8f4f8', font=_cjk_font(8, True),
                              padx=10, pady=5, cursor='hand2')
        search_btn.pack(side=tk.LEFT, padx=(0, 14), pady=10)
        search_btn.bind('<Button-1>', lambda e: self._apply_search())
        self._mine_btn = tk.Label(toolbar, text='我的排名', bg='#273244', fg='#f5f8fb', font=_cjk_font(8, True),
                      padx=10, pady=5, cursor='hand2')
        self._mine_btn.pack(side=tk.LEFT, padx=(0, 14), pady=10)
        self._mine_btn.bind('<Button-1>', lambda e: self._jump_to_self())

        self._info_bar = tk.Frame(main, bg='#eef1f5', height=34)
        self._info_bar.pack(fill=tk.X)
        self._info_bar.pack_propagate(False)
        self._self_lbl = tk.Label(self._info_bar, text='PLAYER ID: --', bg='#eef1f5', fg='#5b6978', font=_sao_font(8))
        self._self_lbl.pack(side=tk.LEFT, padx=14)
        self._rank_lbl = tk.Label(self._info_bar, text='SELF RANK: --', bg='#eef1f5', fg='#f3af12', font=_sao_font(8, True))
        self._rank_lbl.pack(side=tk.RIGHT, padx=14)

        list_host = tk.Frame(main, bg='#ececec')
        list_host.pack(fill=tk.BOTH, expand=True)
        self._list_wrap = tk.Frame(list_host, bg='#ececec')
        self._list_wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        head = tk.Frame(self._list_wrap, bg='#dde3ea', height=28)
        head.pack(fill=tk.X)
        head.pack_propagate(False)
        for text, width, anchor in [('RANK', 8, 'w'), ('NAME', 22, 'w'), ('LV', 7, 'center'), ('STAT', 12, 'e')]:
            tk.Label(head, text=text, bg='#dde3ea', fg='#6b7888', font=_sao_font(8), width=width, anchor=anchor).pack(side=tk.LEFT, padx=(6, 0))

        self._rows_host = tk.Frame(self._list_wrap, bg='#ececec')
        self._rows_host.pack(fill=tk.BOTH, expand=True)

        footer = tk.Frame(main, bg='#ffffff', height=68)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)
        pager = tk.Frame(footer, bg='#ffffff')
        pager.place(relx=0.5, rely=0.5, anchor='center')
        self._prev_btn = tk.Label(pager, text='PREV', bg='#1a2030', fg='#e8f4f8', font=_sao_font(8), padx=10, pady=5, cursor='hand2')
        self._prev_btn.pack(side=tk.LEFT, padx=8)
        self._prev_btn.bind('<Button-1>', lambda e: self._change_page(-1))
        self._page_lbl = tk.Label(pager, text='1 / 1', bg='#ffffff', fg='#646364', font=_sao_font(9, True), width=10)
        self._page_lbl.pack(side=tk.LEFT, padx=8)
        self._next_btn = tk.Label(pager, text='NEXT', bg='#1a2030', fg='#e8f4f8', font=_sao_font(8), padx=10, pady=5, cursor='hand2')
        self._next_btn.pack(side=tk.LEFT, padx=8)
        self._next_btn.bind('<Button-1>', lambda e: self._change_page(1))
        close_btn = tk.Label(footer, text='CLOSE', bg='#d13d4f', fg='#ffffff', font=_sao_font(8, True), padx=10, pady=5, cursor='hand2')
        close_btn.place(relx=0.94, rely=0.5, anchor='center')
        close_btn.bind('<Button-1>', lambda e: self.close())

        self._drag = {'x': 0, 'y': 0}
        for w in (header, self._title_lbl):
            w.bind('<Button-1>', self._start_drag)
            w.bind('<B1-Motion>', self._do_drag)

        self._animate_expand()
        self.set_loading('加载中...')
        try:
            self._dlg.focus_force()
        except Exception:
            pass

    def _start_drag(self, e):
        self._drag['x'], self._drag['y'] = e.x_root, e.y_root

    def _do_drag(self, e):
        dx = e.x_root - self._drag['x']
        dy = e.y_root - self._drag['y']
        self._dlg.geometry(f'+{self._dlg.winfo_x() + dx}+{self._dlg.winfo_y() + dy}')
        self._drag['x'], self._drag['y'] = e.x_root, e.y_root

    def _animate_expand(self):
        t0 = time.time()
        dur = 0.35

        def _step():
            if not self._dlg.winfo_exists():
                return
            t = min(1.0, (time.time() - t0) / dur)
            et = ease_out(t)
            w = int(lerp(self._initial_w, self._final_w, et))
            x = self._px + (self._final_w - w) // 2
            self._dlg.geometry(f'{w}x{self._current_h}+{x}+{self._py}')
            if t < 1.0:
                self._dlg.after(16, _step)
        _step()

    def close(self):
        _close_alert(self._dlg)

    def set_loading(self, message='加载中...'):
        self._entries = []
        self._filtered = []
        self._render_rows(message=message, empty=True)

    def set_error(self, message: str):
        self._render_rows(message=message, empty=True)

    def set_entries(self, entries: List[Dict], self_device: str, self_device_name: str = '', sort_by: str = 'xp'):
        self._entries = list(entries or [])
        self._self_device = self_device or ''
        self._self_device_name = self_device_name or ''
        self._sort_by = sort_by
        self._self_rank = None
        self._focus_rank = None
        for i, row in enumerate(self._entries):
            row.setdefault('rank', i + 1)
            if row.get('device_id', '') == self_device:
                self._self_rank = row.get('rank', i + 1)
                self._self_device_name = self._self_device_name or str(row.get('player_id', '') or row.get('username', '')).strip()
        self._apply_search()

    def _stat_text(self, row: Dict) -> str:
        if self._sort_by == 'level':
            return f"LV {row.get('level', 1)}"
        if self._sort_by == 'songs_played':
            return f"{row.get('songs_played', 0)}曲"
        if self._sort_by == 'play_time':
            sec = float(row.get('play_time', 0) or 0)
            if sec < 60:
                return f'{int(sec)}S'
            if sec < 3600:
                return f'{int(sec // 60)}M'
            return f'{sec / 3600:.1f}H'
        return f"XP {row.get('xp', row.get('total_xp', 0))}"

    def _apply_search(self):
        q = (self._search_var.get() or '').strip().lower()
        self._focus_rank = None
        if not q:
            self._filtered = list(self._entries)
        elif (q.startswith('#') and q[1:].isdigit()) or q.isdigit():
            target_rank = int(q[1:] if q.startswith('#') else q)
            self._filtered = list(self._entries)
            idx = next((i for i, row in enumerate(self._filtered) if int(row.get('rank', -1)) == target_rank), -1)
            if idx >= 0:
                self._focus_rank = target_rank
                self._page = idx // self._per_page
                self._refresh()
                return
            self._filtered = []
        else:
            self._filtered = []
            for row in self._entries:
                hay = ' '.join([
                    str(row.get('rank', '')),
                    str(row.get('player_id', '')),
                    str(row.get('username', '')),
                    str(row.get('profession', '')),
                    str(row.get('device_id', '')),
                ]).lower()
                if q in hay:
                    self._filtered.append(row)
        self._page = 0
        self._refresh()

    def _jump_to_self(self):
        if not self._self_rank:
            return
        self._search_var.set(f'#{self._self_rank}')
        self._apply_search()

    def _change_page(self, delta: int):
        pages = max(1, math.ceil(len(self._filtered) / self._per_page))
        self._page = max(0, min(pages - 1, self._page + delta))
        self._refresh()

    def _refresh(self):
        if self._self_device_name or self._self_device:
            shown = self._self_device_name or 'Player'
            self._self_lbl.configure(text=f'PLAYER ID: {shown}')
        else:
            self._self_lbl.configure(text='PLAYER ID: --')
        if self._self_rank:
            self._rank_lbl.configure(text=f'SELF RANK: #{self._self_rank}')
        else:
            self._rank_lbl.configure(text='SELF RANK: --')

        if not self._filtered:
            self._render_rows(message='未找到匹配的排名记录', empty=True)
            self._page_lbl.configure(text='0 / 0')
            return

        pages = max(1, math.ceil(len(self._filtered) / self._per_page))
        self._page = max(0, min(pages - 1, self._page))
        start = self._page * self._per_page
        page_rows = self._filtered[start:start + self._per_page]
        self._page_lbl.configure(text=f'{self._page + 1} / {pages}')
        self._prev_btn.configure(bg='#1a2030' if self._page > 0 else '#9aa4b3')
        self._next_btn.configure(bg='#1a2030' if self._page < pages - 1 else '#9aa4b3')
        self._render_rows(rows=page_rows)

    def _render_rows(self, rows: Optional[List[Dict]] = None, message: str = '', empty: bool = False):
        for w in self._rows_host.winfo_children():
            w.destroy()

        visible_rows = 1
        if empty:
            tk.Label(self._rows_host, text=message, bg='#ececec', fg='#8892a0', font=_cjk_font(10), pady=28).pack(fill=tk.BOTH, expand=True)
        else:
            rows = rows or []
            visible_rows = max(1, min(self._per_page, len(rows)))
            for idx, row in enumerate(rows):
                bg = '#f7f9fb' if idx % 2 == 0 else '#eef2f6'
                if row.get('device_id', '') == self._self_device:
                    bg = '#e7f1fb'
                if self._focus_rank and int(row.get('rank', -1)) == int(self._focus_rank):
                    bg = '#fff1d8'
                line = tk.Frame(self._rows_host, bg=bg, height=34)
                line.pack(fill=tk.X, pady=1)
                line.pack_propagate(False)
                rank_text = f"#{row.get('rank', idx + 1)}"
                if row.get('rank', 99) <= 3:
                    rank_text = ['TOP1', 'TOP2', 'TOP3'][row.get('rank', 1) - 1]
                tk.Label(line, text=rank_text, bg=bg, fg='#f3af12' if row.get('rank', 9) <= 3 else '#7a8796',
                         font=_sao_font(8, True), width=8, anchor='w').pack(side=tk.LEFT, padx=(8, 0))
                primary = str(row.get('player_id', '') or row.get('username', '???'))[:18]
                alt = str(row.get('username', '') or '').strip()
                prof = row.get('profession', '')
                pieces = [primary]
                if alt and alt != primary:
                    pieces.append(f'@{alt[:10]}')
                if prof:
                    pieces.append(f'[{prof}]')
                tk.Label(line, text='  '.join(pieces), bg=bg, fg='#333333',
                         font=_cjk_font(9), anchor='w').pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(line, text=f"Lv.{row.get('level', 1)}", bg=bg, fg='#428ce6',
                         font=_sao_font(8), width=7, anchor='center').pack(side=tk.LEFT)
                tk.Label(line, text=self._stat_text(row), bg=bg, fg='#666666',
                         font=_sao_font(8), width=12, anchor='e').pack(side=tk.RIGHT, padx=(0, 8))

        target_h = 58 + 54 + 34 + 10 + 28 + visible_rows * 36 + 68
        self._current_h = max(self._min_h, min(self._max_h, target_h))
        self._py = (self._dlg.winfo_screenheight() - self._current_h) // 2
        try:
            self._dlg.geometry(f'{self._final_w}x{self._current_h}+{self._px}+{self._py}')
        except Exception:
            pass


# ──────────────────── HP 血条 ────────────────────
class SAOHPBar(tk.Canvas):
    """
    SAO Utils 风格 HP 条
    - 左侧缺口方块
    - 用户名标签
    - HP 数值 + Lv 等级
    - 绿/黄/红 渐变条
    - SVG polygon 风格边框
    """

    def __init__(self, parent, username='Player', current=100, total=100,
                 level=1, width=400, height=40, **kw):
        parent_bg = '#0a0e14'
        try:
            parent_bg = parent.cget('bg')
        except Exception:
            pass
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=parent_bg, **kw)
        self.username = username
        self._current = current
        self._total = total
        self._level = level
        self._hp_w = width
        self._hp_h = height
        self._display_current = current
        self._anim = Animator(self)
        self._draw()

    @property
    def current(self):
        return self._current

    @current.setter
    def current(self, val):
        old = self._current
        self._current = max(0, min(val, self._total))
        self._animate_hp(old, self._current)

    @property
    def total(self):
        return self._total

    @total.setter
    def total(self, val):
        self._total = max(1, val)
        self._draw()

    @property
    def level(self):
        return self._level

    @level.setter
    def level(self, val):
        self._level = val
        self._draw()

    def _animate_hp(self, old_val, new_val):
        def update(t):
            self._display_current = int(lerp(old_val, new_val, t))
            self._draw()
        self._anim.animate('hp', 1000, update)

    def _draw(self):
        self.delete('all')
        w, h = self._hp_w, self._hp_h
        percent = self._display_current / max(1, self._total)

        bg_color = '#9db5d0'

        # 左侧标识方块 (22px)
        self.create_rectangle(0, 0, 22, h, fill=bg_color, outline='')
        self.create_rectangle(0, h * 0.25, 11, h * 0.75,
                              fill=self.cget('bg'), outline='')

        # 用户名区域
        self.create_rectangle(25, 0, 120, h, fill=bg_color, outline='')
        self.create_text(72, h // 2, text=self.username,
                         fill='#e1dede', font=_sao_font(9))

        # HP 条区域
        bar_x = 125
        bar_w = w - bar_x - 5
        bar_h = 23
        bar_y = (h - bar_h) // 2

        # 边框 polygon
        pts = [bar_x, bar_y,
               bar_x + bar_w, bar_y,
               bar_x + bar_w - 5, bar_y + 16,
               bar_x + bar_w * 0.45 + 4, bar_y + 16,
               bar_x + bar_w * 0.45, bar_y + bar_h,
               bar_x, bar_y + bar_h]
        self.create_polygon(pts, outline='#dad7d7', fill='', width=1)

        # HP 填充
        fill_w = int(bar_w * percent * 0.95)
        if fill_w > 0:
            if percent > 0.5:
                fill_color = '#9ad334'
            elif percent > 0.25:
                fill_color = '#f4fa49'
            else:
                fill_color = '#ef684e'
            self.create_rectangle(bar_x + 2, bar_y + 1,
                                  bar_x + 2 + fill_w, bar_y + bar_h - 1,
                                  fill=fill_color, outline='')

        # 数值
        self.create_text(bar_x + bar_w * 0.6, h - 2,
                         text=f'{self._display_current}/{self._total}',
                         fill='#e1dede', font=_sao_font(7), anchor='s')
        self.create_text(bar_x + bar_w * 0.85, h - 2,
                         text=f'Lv.{self._level}',
                         fill='#e1dede', font=_sao_font(7), anchor='s')


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
      Phase 2 (3.5~5.5s)  灰底文字 — "Welcome to / 咲 Midi Player !" 飞入飞出
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
    _CAM_DURATION = 3.5     # 单次飞行时长 = SAO-UI animation: 3.5s
    _STARTUP_PRELUDE = 0.72 # 启动扫描/光阀独占时长, 结束后再进入 P1

    # ──── 时间线 ────
    _DURATION = 9.0

    _P1_END = 3.5           # 彩色隧道结束
    _P2_START = 3.5         # 文字开始
    _P2_END = 5.5           # 文字结束
    _P3_START = 5.2         # 蓝色隧道开始 (与文字有少许重叠)
    _P3_END = 7.5           # 蓝色隧道结束
    _P4_START = 7.3         # 白闪开始

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
uniform float     u_ca;    // 色差偏移 (单位: UV坐标)
uniform float     u_fx_energy;
uniform float     u_fx_flash;
uniform float     u_aspect;
uniform vec3      u_fx_tint;
out vec4 fragColor;
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
    // 运动模糊: 22% 历史 + 78% 当前
    vec3 prev   = texture(u_prv, uv).rgb;
    vec3 result = mix(prev, vec3(r, g, b), 0.60);  // 40% history = stronger motion trail

    float centerGlow = pow(max(0.0, 1.0 - radius * 1.85), 2.6);
    float streak = exp(-abs(centered.y) * (74.0 - 22.0 * energy));
    streak *= smoothstep(0.52, 0.0, abs(centered.x));
    float bloom = centerGlow * (0.035 + energy * 0.05 + flash * 0.05);
    float flare = streak * (energy * 0.08 + flash * 0.12);
    vec3 fx = u_fx_tint * (bloom + flare);
    float vignette = smoothstep(1.22, 0.18, radius);

    result += fx;
    result = mix(result, result + u_fx_tint * 0.08, flash * centerGlow);
    result *= mix(0.92, 1.04, vignette);
    result = clamp(result, 0.0, 1.0);
    fragColor = vec4(result, 1.0);
}
'''

    def __init__(self, root: tk.Tk, on_done: Optional[Callable] = None):
        self.root = root
        self.on_done = on_done
        self._overlay = None
        self._sound_player = None
        self._ls_font_cache = {}
        self._ls_sprite_cache = {}
        self._ls_live_photos = []
        self._ls_p2_prewarmed = False

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
                    _base = os.path.dirname(os.path.abspath(__file__))
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

    # ════════════════════════════════════════════════════════
    #  启动
    # ════════════════════════════════════════════════════════
    def play(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._cx, self._cy = sw // 2, sh // 2
        self._sw, self._sh = sw, sh
        self._diag = math.hypot(sw, sh)
        self._ls_p2_prewarmed = False

        # ── 播放 Link Start 音效 ──
        self._play_sound()

        # ── 创建全屏顶层窗口 ──
        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)
        self._overlay.geometry(f'{sw}x{sh}+0+0')
        self._overlay.configure(bg='black')
        self._overlay.attributes('-alpha', 0.92)

        self._canvas = tk.Canvas(self._overlay, width=sw, height=sh,
                                 bg='black', highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # ── 预生成静态隧道粒子 (SAO-UI 模型) ──
        # GPU模式用300粒子, Canvas回退用150以保证帧率
        n_particles = self._NUM_PARTICLES if _HAS_MODERNGL else self._NUM_PARTICLES_CANVAS
        self._color_particles = self._gen_tunnel(self._COLORS_8, n_particles)
        self._blue_particles = self._gen_tunnel(self._BLUES_8, n_particles)

        # ── OpenGL 3D 渲染初始化 ──
        self._gl_ctx = None
        self._gl_photo = None     # 保持 PhotoImage 引用
        self._prev_gl_arr = None  # 运动模糊前帧帧缓存 (numpy uint8 HxWx3)
        self._gl_fx_energy = 0.0
        self._gl_fx_flash = 0.0
        self._gl_fx_tint = (0.95, 0.85, 0.35)
        if _HAS_MODERNGL:
            try:
                self._init_gl()
            except Exception as e:
                print(f'[LinkStart] OpenGL init failed: {e}, fallback to Canvas')
                self._gl_ctx = None

        # ── 预热 P2 文字 sprite，避免进入 P2 时首次 PIL 光栅化掉帧 ──
        self._prewarm_linkstart_p2_sprites()

        self._start_time = time.time()
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

    # ════════════════════════════════════════════════════════
    #  OpenGL 3D 隧道初始化
    # ════════════════════════════════════════════════════════
    _GL_CYL_SEGMENTS = 10     # 每根管子的截面段数
    _GL_TUBE_RADIUS = 1.8     # 管子视觉半径(世界单位)

    def _init_gl(self):
        """创建 ModernGL standalone context, 着色器, 几何体, FBO."""
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

out vec3  v_world;
out vec3  v_normal;
out vec3  v_color;
out float v_alpha;
out float v_fog;

void main() {
    // 缩放单位圆柱到实际管子
    vec3 pos = in_pos;
    pos.xy *= i_radius;
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
    v_alpha  = i_alpha;
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

    // 综合淡入/淡出 + 雾
    float total_fade = v_alpha * (1.0 - v_fog);
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
        # Ping-pong: 两对 FBO+纹理交替作为输出 / 历史输入
        self._gl_ptex_a = ctx.texture((sw, sh), 3)
        self._gl_pfbo_a = ctx.framebuffer(color_attachments=[self._gl_ptex_a])
        self._gl_ptex_b = ctx.texture((sw, sh), 3)
        self._gl_pfbo_b = ctx.framebuffer(color_attachments=[self._gl_ptex_b])
        self._gl_pframe  = 0   # 帧计数 (偏奇偶决定 ping-pong 方向)
        # Fullscreen triangle VAO (无顶点数据, 纯靠 gl_VertexID)
        self._gl_postvao = ctx.vertex_array(self._gl_postprog, [])
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

    def _destroy_gl(self):
        """释放 OpenGL 资源."""
        if self._gl_ctx:
            try:
                self._gl_ctx.release()
            except Exception:
                pass
            self._gl_ctx = None
        self._gl_photo = None
        self._gl_startup_tex = None
        self._gl_startup_fbo = None
        self._gl_startup_size = None

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
                     t: float = 0.0):
        """
        3D 隧道渲染. 如果 OpenGL 可用, 使用真 3D 圆柱体 + Blinn-Phong;
        否则回退到 Canvas 2D.
        """
        if self._gl_ctx:
            try:
                self._draw_tunnel_gl(cv, particles, cam_z, bg, fade, t)
                return
            except Exception as e:
                print(f'[LinkStart] GL render error: {e}')
                self._gl_ctx = None   # 降级到 canvas

        # ── Canvas 2D 回退 ──
        self._draw_tunnel_canvas(cv, particles, cam_z, bg, fade, t)

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

        raw = self._gl_fbo.read(components=3)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(sh, sw, 3)
        photo = ImageTk.PhotoImage(Image.fromarray(arr[::-1], 'RGB'))
        self._gl_photo = photo
        cv.create_image(0, 0, image=photo, anchor='nw')

    def _draw_tunnel_gl(self, cv: tk.Canvas, particles: list,
                        cam_z: float, bg: str, fade: float = 1.0,
                        t: float = 0.0):
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

        if count == 0:
            return

        # ── 上传 instance data ──
        inst_np = np.array(inst_data, dtype='f4')
        self._gl_inst_buf.write(inst_np.tobytes())

        # ── 设置 uniforms ──
        vp = self._build_vp_matrix(cam_z)
        self._gl_prog['u_vp'].write(vp.tobytes())
        self._gl_prog['u_rot'].value = rot
        self._gl_prog['u_cam_pos'].value = (0.0, 0.0, cam_z)
        self._gl_prog['u_bg_color'].value = bg_norm

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
        ctx.enable(moderngl.DEPTH_TEST)
        self._gl_vao.render(moderngl.TRIANGLES,
                            vertices=self._gl_num_verts,
                            instances=count)

        # ── GPU 后处理: 色差 + 运动模糊 (全在显卡内完成) ──
        pf = self._gl_pframe
        write_fbo = self._gl_pfbo_a if (pf & 1) == 0 else self._gl_pfbo_b
        prev_tex  = self._gl_ptex_b if (pf & 1) == 0 else self._gl_ptex_a

        write_fbo.use()
        ctx.disable(moderngl.DEPTH_TEST)
        self._gl_color_tex.use(location=0)   # 当前场景 (u_cur)
        prev_tex.use(location=1)              # 历史模糊 (u_prv)
        self._gl_postprog['u_cur'].value = 0
        self._gl_postprog['u_prv'].value = 1
        self._gl_postprog['u_ca'].value  = self._gl_ca_uv
        self._gl_postprog['u_fx_energy'].value = float(getattr(self, '_gl_fx_energy', 0.0))
        self._gl_postprog['u_fx_flash'].value = float(getattr(self, '_gl_fx_flash', 0.0))
        self._gl_postprog['u_fx_tint'].value = tuple(getattr(self, '_gl_fx_tint', (0.95, 0.85, 0.35)))
        self._gl_postvao.render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self._gl_pframe = pf + 1

        # ── 读回后处理结果: 已含色差+模糊, 无需 CPU 运算 ──
        raw = write_fbo.read(components=3)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(sh, sw, 3)
        photo = ImageTk.PhotoImage(Image.fromarray(arr[::-1], 'RGB'))
        self._gl_photo = photo   # 防止 GC
        cv.create_image(0, 0, image=photo, anchor='nw')

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
        if not self._overlay or not self._overlay.winfo_exists():
            return

        elapsed = time.time() - self._start_time
        scene_t = elapsed - self._STARTUP_PRELUDE
        if scene_t > self._DURATION:
            self._finish()
            return

        cv = self._canvas
        cv.delete('all')
        sw, sh = self._sw, self._sh

        # ── 背景 ──
        bg = self._calc_bg(max(0.0, scene_t))
        cv.create_rectangle(0, 0, sw, sh, fill=bg, outline='')
        text_active = self._P2_START - 0.2 <= scene_t < self._P2_END + 0.3
        text_state = self._get_text_phase_state(scene_t) if text_active else None

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
            else:
                self._draw_start_aperture_cv(cv, startup_t, bg)
                self._draw_start_connect_cv(cv, startup_t, bg)
                self._draw_entry_burst_cv(cv, startup_t, bg)
            _render_ms = (time.perf_counter() - _t0) * 1000
            _delay = max(1, int(16.67 - _render_ms))
            self._overlay.after(_delay, self._animate)
            return

        # ── Phase 1: 彩色隧道 (0 ~ P1_END) ──
        if scene_t < self._P1_END + 0.5:
            # 粒子淡入: 0~0.5s 不可见, 0.5~1.5s 渐入
            particle_fade = 1.0
            if scene_t < 0.28:
                particle_fade = lerp(0.22, 0.62, ease_out(scene_t / 0.28))
            elif scene_t < 1.0:
                particle_fade = lerp(0.62, 1.0, ease_out((scene_t - 0.28) / 0.72))
            if scene_t > self._P1_END:
                particle_fade = max(0, 1.0 - (scene_t - self._P1_END) / 0.5)

            # 使用原始 _CAM_DURATION (3.5s) 保持与 P3 相同的飞行速度.
            # z_near < 1.0 的近裁剪guard已处理摄像机追上粒子的情况 → 直接跳过不渲染.
            cam_z = self._cam_z(scene_t, self._CAM_DURATION)

            # 粒子隧道
            startup_bridge_t = min(self._STARTUP_PRELUDE + 0.64, elapsed)
            startup_burst = max(0.0, 1.0 - startup_bridge_t / 1.06)
            startup_wave = min(1.0, startup_bridge_t / (self._STARTUP_PRELUDE + 0.64))
            self._gl_start_burst = startup_burst
            self._gl_start_wave = startup_wave
            self._gl_fx_energy = min(1.0, particle_fade * (0.20 + 0.88 * min(1.0, scene_t / max(0.01, self._CAM_DURATION))) + startup_burst * 0.28)
            self._gl_fx_flash = max(0.0, 1.0 - startup_bridge_t / 1.08) * 0.30 + startup_burst * 0.28
            self._gl_fx_tint = (0.96, 0.78, 0.24)
            if not self._gl_ctx:
                self._draw_focus_flow_cv(cv, scene_t, self._CAM_DURATION,
                                         particle_fade, bg, warm=True)
            self._draw_tunnel(cv, self._color_particles, cam_z, bg,
                              particle_fade, t=scene_t)

            # P1 HUD 角标叠加
            self._draw_tunnel_hud_overlay(cv, scene_t, particle_fade, warm=True)

            # P1 收尾: 暗色圆形从中心扩张扫过, 盖住未飞出的圆柱体
            if scene_t >= self._P1_END - 0.05:
                self._draw_p1_circle_wipe(cv, scene_t)

        # ── Phase 2 underlay: 先画底层 flare / frame，避免在 P3 重叠时盖住圆柱 ──
        if text_state:
            self._draw_text_phase_underlay(cv, scene_t, text_state)

        # ── Phase 3: 蓝色隧道 (5.2 ~ 7.5s + 0.3s 渐隐) ──
        if self._P3_START <= scene_t < self._P3_END + 0.3:
            p3_fade = 1.0
            if scene_t < self._P3_START + 0.5:
                p3_fade = (scene_t - self._P3_START) / 0.5
            if scene_t > self._P3_END:
                p3_fade = max(0, 1.0 - (scene_t - self._P3_END) / 0.3)

            p3_t = scene_t - self._P3_START
            p3_dur = self._P3_END - self._P3_START  # = 2.3s, 确保摄像机在相结束前走完全程
            cam_z = self._cam_z(p3_t, p3_dur)
            self._gl_start_burst = 0.0
            self._gl_start_wave = 1.0
            self._gl_fx_energy = p3_fade * (0.20 + 0.80 * min(1.0, p3_t / max(0.01, p3_dur)))
            self._gl_fx_flash = max(0.0, 1.0 - p3_t / 0.70) * 0.18
            self._gl_fx_tint = (0.45, 0.80, 1.00)
            if not self._gl_ctx:
                self._draw_focus_flow_cv(cv, p3_t, p3_dur,
                                         p3_fade, bg, warm=False)
            self._draw_tunnel(cv, self._blue_particles, cam_z, bg,
                              p3_fade, t=scene_t)

            # P3 HUD 角标叠加
            self._draw_tunnel_hud_overlay(cv, scene_t, p3_fade, warm=False)

        # ── Phase 2 overlay: HUD / text 保持可见，但不把底层纹波放到圆柱体上方 ──
        if text_state:
            self._render_text_phase(cv, scene_t, text_state)

        # ── Phase 4: 渐隐 (7.3 ~ 9.0s) ──
        if scene_t >= self._P4_START:
            self._draw_whiteout_cv(cv, scene_t)
            self._draw_connected_overlay(cv, scene_t)

        # 自适应调度: 用实际渲染耗时虚追 16.7ms 帧限, 尽量维持 60fps
        _render_ms = (time.perf_counter() - _t0) * 1000
        _delay = max(1, int(16.67 - _render_ms))
        self._overlay.after(_delay, self._animate)

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
        if wt < 0 or wt > 1.2:
            return
        alpha = 1.0
        if wt < 0.15:
            alpha = wt / 0.15
        elif wt > 0.7:
            alpha = max(0.0, 1.0 - (wt - 0.7) / 0.5)
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
            ft = min(1.0, (t - (self._DURATION - 1.5)) / 1.3)
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

        base = os.path.dirname(os.path.abspath(__file__))
        font_file = 'SAOUI.ttf' if family == 'sao' else 'ZhuZiAYuanJWD.ttf'
        font_path = os.path.join(base, 'assets', 'fonts', font_file)
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
            z_text = lerp(ref_z, 0.85, ease_in(min(1.0, out_t)))
        else:
            z_text = 0.5

        if z_text < 0.5:
            return None
        scale = ref_z / z_text
        size_1 = max(8, min(320, int(base_size_1 * scale)))
        size_2 = max(10, min(360, int(base_size_2 * scale)))
        if size_1 > 260:
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
        self._destroy_gl()
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.destroy()
        self._overlay = None
        if self.on_done:
            self.on_done()


# ──────────────────── SAO 文件选择器 ────────────────────
class SAOFilePicker(tk.Toplevel):
    """SAO 风格文件浏览器 — 白色主题"""

    _BG       = '#ffffff'
    _BG2      = '#f5f5f7'
    _BORDER   = '#d1d1d6'
    _ACCENT   = '#f3af12'
    _ACCENT2  = '#dea620'
    _TEXT     = '#333333'
    _TEXT_DIM = '#999999'
    _SEL_BG   = '#fff3c0'
    _SEL_FG   = '#333333'
    _DIR_FG   = '#e67c00'
    _FILE_FG  = '#444444'

    def __init__(self, parent, title='选择文件', initial_dir='.',
                 filetypes=None, callback=None, mode='file', **kw):
        super().__init__(parent)
        self.result = None
        self.callback = callback
        self._dialog_title = title
        self._current_dir = os.path.abspath(initial_dir)
        self._filetypes = filetypes or [('All Files', '*.*')]
        self._entries = []
        self._mode = mode  # 'file' or 'dir'

        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.0)
        self.configure(bg='#e0e0e0')

        self._final_w, self._final_h = 520, 480
        self._initial_w = 135
        # 始终居中于屏幕
        self._px = (self.winfo_screenwidth()  - self._final_w) // 2
        self._py = (self.winfo_screenheight() - self._final_h) // 2
        # 从窄条开始 (与 SAODialog 展开风格一致)
        self.geometry(f'{self._initial_w}x{self._final_h}'
                      f'+{self._px + (self._final_w - self._initial_w) // 2}'
                      f'+{self._py}')

        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

        self._build_ui(self._final_w, self._final_h, title)
        if getattr(self, '_main_box', None):
            self._main_box.pack_forget()
        self._load_dir(self._current_dir)
        self.update_idletasks()

        self._drag = {'x': 0, 'y': 0}
        self.transient(parent)
        self.deiconify()
        # 展开动画 → 完成后 grab
        self.after(50, self._animate_expand)

    def _delayed_grab(self):
        """窗口完全映射后才 grab_set, 防止 grab 冲突导致窗口闪退"""
        try:
            if self.winfo_exists():
                self.lift()
                self.grab_set()
                self.focus_force()
        except Exception:
            pass

    def _animate_expand(self):
        """SAO 风格宽度展开动画 (135px → 520px, 500ms ease-out cubic)."""
        import time as _time
        t0 = _time.time()
        dur = 0.5
        fw = self._final_w
        fh = self._final_h
        iw = self._initial_w
        px = self._px
        py = self._py

        def _step():
            if not self.winfo_exists():
                return
            elapsed = _time.time() - t0
            t = min(1.0, elapsed / dur)
            et = 1.0 - (1.0 - t) ** 3  # ease-out cubic
            w = int(iw + (fw - iw) * et)
            x = px + (fw - w) // 2
            self.geometry(f'{w}x{fh}+{x}+{py}')
            try:
                self.attributes('-alpha', min(1.0, 0.15 + t * 0.85))
            except Exception:
                pass
            if t < 1.0:
                self.after(16, _step)
            else:
                try:
                    self.attributes('-alpha', 1.0)
                except Exception:
                    pass
                if getattr(self, '_main_box', None) and not self._main_box.winfo_manager():
                    self._main_box.pack(fill=tk.BOTH, expand=True)
                    self.update_idletasks()
                if hasattr(self, '_title_lbl'):
                    _clip_reveal(self._title_lbl, self._dialog_title, self, 380, delay=40)
                # 展开完成, grab 焦点
                self.after(50, self._delayed_grab)
        _step()

    def _build_ui(self, w, h, title):
        # ── SAODialog 式三段壳 ──
        main_box = tk.Frame(self, bg='#ffffff')
        main_box.pack(fill=tk.BOTH, expand=True)
        self._main_box = main_box

        # 标题区 (68px)
        header = tk.Frame(main_box, bg='#ffffff', height=68)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        # 菱形图标
        hcv = tk.Canvas(header, width=24, height=24,
                        bg='#ffffff', highlightthickness=0)
        hcv.pack(side=tk.LEFT, padx=(16, 0), pady=22)
        hcv.create_polygon(12, 2, 22, 12, 12, 22, 2, 12,
                           fill=self._ACCENT, outline='')

        self._title_lbl = tk.Label(header, text='', bg='#ffffff',
                                   fg=SAOColors.ALERT_TITLE_FG,
                                   font=_sao_font(13, True))
        self._title_lbl.place(relx=0.5, rely=0.5, anchor='center')

        # 关闭 ×
        close_btn = _make_aa_icon_button(header, 'close', self._cancel,
                         SAOColors.CLOSE_RED, SAOColors.CLOSE_RED, bg='#ffffff')
        close_btn.pack(side=tk.RIGHT, padx=16, pady=14)

        tk.Frame(main_box, bg='#e0e0e0', height=1).pack(fill=tk.X)

        # 内容区 (浅灰)
        content = tk.Frame(main_box, bg='#eae9e9')
        content.pack(fill=tk.BOTH, expand=True)

        for w_item in [header, self._title_lbl]:
            w_item.bind('<Button-1>', self._start_drag)
            w_item.bind('<B1-Motion>', self._do_drag)

        # ── 路径行 ──
        path_row = tk.Frame(content, bg='#eae9e9', height=30)
        path_row.pack(fill=tk.X, padx=10, pady=(10, 0))
        path_row.pack_propagate(False)

        tk.Label(path_row, text='▸', bg='#eae9e9', fg=self._ACCENT2,
                 font=_sao_font(8)).pack(side=tk.LEFT, padx=(6, 4), pady=6)
        self._path_lbl = tk.Label(path_row, text='', bg=self._BG,
                                  fg=self._TEXT_DIM,
                                  font=_sao_font(8), anchor='w')
        self._path_lbl.configure(bg='#eae9e9')
        self._path_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)

        # ── 列表区 ──
        list_outer = tk.Frame(content, bg=self._BORDER, padx=0, pady=0)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=14, pady=(8, 8))

        list_frame = tk.Frame(list_outer, bg=self._BG2)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 自定义滚动条
        sb_frame = tk.Frame(list_frame, bg=self._BG2, width=8)
        sb_frame.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar = tk.Scrollbar(sb_frame, orient=tk.VERTICAL,
                                 troughcolor=self._BG2,
                                 bg=self._BORDER, width=8,
                                 highlightthickness=0, bd=0)
        scrollbar.pack(fill=tk.Y, expand=True)

        self._listbox = tk.Listbox(
            list_frame,
            bg=self._BG2, fg=self._FILE_FG,
            font=_cjk_font(9),
            selectbackground=self._SEL_BG,
            selectforeground=self._SEL_FG,
            highlightthickness=0, bd=0,
            activestyle='none',
            yscrollcommand=scrollbar.set,
            relief=tk.FLAT,
        )
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._listbox.yview)
        self._listbox.bind('<Double-Button-1>', self._on_double_click)
        self._listbox.bind('<Return>', lambda e: self._confirm())

        # ── 底部分隔线 ──
        tk.Frame(content, bg=self._BORDER, height=1).pack(fill=tk.X, padx=14)

        # ── 文件名预览行 ──
        fname_row = tk.Frame(content, bg='#eae9e9', height=30)
        fname_row.pack(fill=tk.X, padx=14, pady=(4, 10))
        fname_row.pack_propagate(False)
        self._fname_lbl = tk.Label(fname_row, text='未选择文件', bg='#eae9e9',
                                   fg=self._ACCENT, font=_cjk_font(9),
                                   anchor='w')
        self._fname_lbl.pack(fill=tk.X, padx=4, pady=4)
        self._listbox.bind('<<ListboxSelect>>', self._on_select)

        # 按钮区 (83px)
        tk.Frame(main_box, bg='#e0e0e0', height=1).pack(fill=tk.X)
        footer = tk.Frame(main_box, bg='#ffffff', height=83)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        btn_frame = tk.Frame(footer, bg='#ffffff')
        btn_frame.place(relx=0.5, rely=0.5, anchor='center')

        # 目录模式: 添加 "选择此文件夹" 按钮
        if self._mode == 'dir':
            sel_dir_btn = _make_aa_icon_button(btn_frame, 'ok', self._confirm_dir,
                                               '#4caf50', '#4caf50', bg='#ffffff')
            sel_dir_btn.pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(btn_frame, text='选择此文件夹', bg='#ffffff', fg='#999999',
                     font=_sao_font(8)).pack(side=tk.LEFT, padx=(0, 18))

        ok_btn = _make_aa_icon_button(btn_frame, 'ok', self._confirm,
                                      SAOColors.OK_BLUE, SAOColors.OK_BLUE, bg='#ffffff')
        ok_btn.pack(side=tk.LEFT, padx=20)

        tk.Label(btn_frame, text='确认', bg='#ffffff', fg='#999999',
                 font=_sao_font(8)).pack(side=tk.LEFT, padx=(0, 20))

        cancel_btn = _make_aa_icon_button(btn_frame, 'close', self._cancel,
                          SAOColors.CLOSE_RED, SAOColors.CLOSE_RED, bg='#ffffff')
        cancel_btn.pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(btn_frame, text='取消', bg='#ffffff', fg='#999999',
                 font=_sao_font(8)).pack(side=tk.LEFT)

    def _start_drag(self, e):
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root

    def _do_drag(self, e):
        dx = e.x_root - self._drag['x']
        dy = e.y_root - self._drag['y']
        self.geometry(f'+{self.winfo_x() + dx}+{self.winfo_y() + dy}')
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root

    def _load_dir(self, path):
        self._current_dir = os.path.abspath(path)
        self._path_lbl.configure(text=self._current_dir)
        self._listbox.delete(0, tk.END)
        self._entries = [('..', True)]
        self._listbox.insert(tk.END, '▴ ..')
        self._listbox.itemconfig(0, fg=self._ACCENT2)

        try:
            entries = sorted(os.listdir(self._current_dir))
        except PermissionError:
            entries = []

        dirs = [e for e in entries if os.path.isdir(os.path.join(self._current_dir, e))]
        files = [e for e in entries if os.path.isfile(os.path.join(self._current_dir, e))]

        exts = set()
        for _, pattern in self._filetypes:
            for p in pattern.split(';'):
                p = p.strip()
                if p.startswith('*.'):
                    exts.add(p[1:].lower())
                elif p == '*.*':
                    exts = None
                    break
            if exts is None:
                break

        for d in dirs:
            if not d.startswith('.'):
                idx = self._listbox.size()
                self._listbox.insert(tk.END, f'▸ {d}')
                self._listbox.itemconfig(idx, fg=self._DIR_FG)
                self._entries.append((d, True))

        for f in files:
            if exts is None or any(f.lower().endswith(ext) for ext in exts):
                idx = self._listbox.size()
                self._listbox.insert(tk.END, f'♪ {f}')
                self._listbox.itemconfig(idx, fg=self._FILE_FG)
                self._entries.append((f, False))

    def _on_select(self, e):
        sel = self._listbox.curselection()
        if not sel:
            return
        name, is_dir = self._entries[sel[0]]
        if not is_dir and hasattr(self, '_fname_lbl'):
            self._fname_lbl.configure(text=name)

    def _on_double_click(self, e):
        sel = self._listbox.curselection()
        if not sel:
            return
        name, is_dir = self._entries[sel[0]]
        full = os.path.join(self._current_dir, name)
        if is_dir:
            self._load_dir(full)
        else:
            self.result = full
            self._finish()

    def _confirm(self):
        sel = self._listbox.curselection()
        if sel:
            name, is_dir = self._entries[sel[0]]
            if is_dir:
                if self._mode == 'dir' and name != '..':
                    # 目录模式: 确认选中的子文件夹
                    self.result = os.path.join(self._current_dir, name)
                    self._finish()
                else:
                    self._load_dir(os.path.join(self._current_dir, name))
            else:
                self.result = os.path.join(self._current_dir, name)
                self._finish()

    def _confirm_dir(self):
        """目录模式: 选择当前浏览的文件夹"""
        self.result = self._current_dir
        self._finish()

    def _cancel(self):
        self.result = None
        self._finish()

    def _finish(self):
        result = self.result
        callback = self.callback
        parent = self.master
        try:
            self.grab_release()
        except Exception:
            pass
        # 收起动画 (反向 520→135px, 300ms)
        self._animate_collapse(result, callback, parent)

    def _animate_collapse(self, result, callback, parent):
        """SAO 风格收起动画 (宽度 → 135px, 300ms ease-in)."""
        import time as _time
        t0 = _time.time()
        dur = 0.3
        fw = self._final_w
        iw = self._initial_w
        try:
            cx = self.winfo_x() + self.winfo_width() // 2
            cy = self.winfo_y()
        except Exception:
            cx = self._px + fw // 2
            cy = self._py

        def _step():
            if not self.winfo_exists():
                if callback and result:
                    try:
                        parent.after(50, lambda: callback(result))
                    except Exception:
                        callback(result)
                return
            elapsed = _time.time() - t0
            t = min(1.0, elapsed / dur)
            et = t ** 2  # ease-in quad
            w = int(fw - (fw - iw) * et)
            x = cx - w // 2
            self.geometry(f'{w}x{self._final_h}+{x}+{cy}')
            try:
                self.attributes('-alpha', max(0.0, 1.0 - t))
            except Exception:
                pass
            if t < 1.0:
                self.after(16, _step)
            else:
                self.destroy()
                if callback and result:
                    try:
                        parent.after(50, lambda: callback(result))
                    except Exception:
                        callback(result)
        _step()


# ──────────────────── SAO 通用按钮 ────────────────────
class SAOButton(tk.Canvas):
    """SAO 风格按钮 (矩形白底, 金色悬停)"""

    def __init__(self, parent, text='', command=None,
                 width=120, height=36, **kw):
        parent_bg = '#0a0e14'
        try:
            parent_bg = parent.cget('bg')
        except Exception:
            pass
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, cursor='hand2',
                         bg=parent_bg, **kw)
        self.text = text
        self.command = command
        self._btn_w = width
        self._btn_h = height
        self._hovering = False

        self._draw()

        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)

    def _draw(self):
        self.delete('all')
        if self._hovering:
            fill = SAOColors.CHILD_HOVER
            fg = '#ffffff'
        else:
            fill = '#ffffff'
            fg = '#333333'

        self.create_rectangle(0, 0, self._btn_w, self._btn_h, fill=fill, outline='#c9c6c6')
        self.create_text(self._btn_w // 2, self._btn_h // 2, text=self.text,
                         fill=fg, font=('Microsoft YaHei UI', 10))

    def set_text(self, text):
        self.text = text
        self._draw()

    def _on_enter(self, e=None):
        self._hovering = True
        self._draw()

    def _on_leave(self, e=None):
        self._hovering = False
        self._draw()

    def _on_click(self, e=None):
        if self.command:
            self.command()


# ──────────────────── SAO 进度条 / 状态 ────────────────────
class SAOProgressBar(tk.Canvas):
    """SAO 风格进度条 (HP 条简化版，嵌入式)"""

    def __init__(self, parent, width=300, height=20, **kw):
        parent_bg = '#0a0e14'
        try:
            parent_bg = parent.cget('bg')
        except Exception:
            pass
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=parent_bg, **kw)
        self._bar_w = width
        self._bar_h = height
        self._value = 0.0
        self._draw()

    def set_value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self._draw()

    def _draw(self):
        self.delete('all')
        w, h = self._bar_w, self._bar_h
        self.create_rectangle(0, 0, w, h, fill='#1a2535', outline='#2a4a5e')
        fw = int(w * self._value)
        if fw > 0:
            if self._value > 0.5:
                c = '#9ad334'
            elif self._value > 0.25:
                c = '#f4fa49'
            else:
                c = '#ef684e'
            self.create_rectangle(1, 1, fw, h - 1, fill=c, outline='')
        self.create_text(w // 2, h // 2, text=f'{int(self._value * 100)}%',
                         fill='#e8f4f8', font=('Segoe UI', 8))


class SAOStatusPill(tk.Canvas):
    """SAO 风格状态指示器"""

    def __init__(self, parent, text='Ready', color='#4caf50',
                 width=100, height=24, **kw):
        parent_bg = '#0a0e14'
        try:
            parent_bg = parent.cget('bg')
        except Exception:
            pass
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=parent_bg, **kw)
        self._text = text
        self._color = color
        self._pill_w = width
        self._pill_h = height
        self._draw()

    def set_status(self, text: str, color: str = None):
        self._text = text
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete('all')
        w, h = self._pill_w, self._pill_h
        self.create_rectangle(0, 0, w, h, fill='#111820', outline='#2a4a5e')
        self.create_rectangle(2, 2, 8, h - 2, fill=self._color, outline='')
        self.create_text(w // 2 + 3, h // 2, text=self._text,
                         fill='#e8f4f8', font=('Segoe UI', 8))


class SAOResizeGrip(tk.Canvas):
    """SAO 风格调整大小手柄"""

    def __init__(self, parent, root, size=16, **kw):
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, cursor='size_nw_se', **kw)
        self.root = root
        self._size = size
        self.configure(bg=parent.cget('bg'))
        self._draw()
        self.bind('<Button-1>', self._start)
        self.bind('<B1-Motion>', self._resize)

    def _draw(self):
        self.delete('all')
        s = self._size
        for i in range(3):
            offset = s - 4 - i * 5
            self.create_polygon(offset, s, s, offset, s, s,
                                fill='#4de8f4', outline='')

    def _start(self, e):
        self._sx = e.x_root
        self._sy = e.y_root
        self._sw = self.root.winfo_width()
        self._sh = self.root.winfo_height()

    def _resize(self, e):
        dx = e.x_root - self._sx
        dy = e.y_root - self._sy
        w = max(400, self._sw + dx)
        h = max(300, self._sh + dy)
        self.root.geometry(f'{w}x{h}')


class SAOSeparator(tk.Canvas):
    """SAO 风格分隔线"""

    def __init__(self, parent, width=200, **kw):
        super().__init__(parent, width=width, height=2,
                         highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self.create_line(0, 1, width, 1, fill='#2a4a5e', width=1)


# ──────────────────── SAO 标题栏 ────────────────────
class SAOTitleBar(tk.Frame):
    """SAO 风格标题栏"""

    def __init__(self, parent, root, title="咲 Midi Player",
                 version="v3.5.0", on_close=None, **kw):
        super().__init__(parent, bg='#080c12', height=36, **kw)
        self.root = root
        self.on_close = on_close
        self.pack_propagate(False)

        # 菱形图标
        icon_cv = tk.Canvas(self, width=12, height=12, bg='#080c12',
                            highlightthickness=0)
        icon_cv.create_polygon(6, 0, 12, 6, 6, 12, 0, 6,
                               fill='#4de8f4', outline='')
        icon_cv.pack(side=tk.LEFT, padx=(12, 6), pady=12)

        self._title_lbl = tk.Label(self, text=title, bg='#080c12',
                                   fg='#4de8f4',
                                   font=('Segoe UI', 10, 'bold'))
        self._title_lbl.pack(side=tk.LEFT)

        self._version_lbl = tk.Label(self, text=version, bg='#080c12',
                                     fg='#3d6070',
                                     font=('Segoe UI', 8))
        self._version_lbl.pack(side=tk.LEFT, padx=(6, 0))

        self._ctrl_btns = []
        for txt, cmd in [('×', on_close), ('—', self._minimize), ('□', self._maximize)]:
            cv = tk.Canvas(self, width=28, height=28, bg='#080c12',
                           highlightthickness=0, cursor='hand2')
            cv.create_text(14, 14, text=txt, fill='#3d6070',
                           font=('Consolas', 12))
            cv.pack(side=tk.RIGHT, padx=2, pady=4)
            if cmd:
                cv.bind('<Button-1>', lambda e, c=cmd: c())
            cv.bind('<Enter>', lambda e, c=cv: c.itemconfig('all', fill='#4de8f4'))
            cv.bind('<Leave>', lambda e, c=cv: c.itemconfig('all', fill='#3d6070'))
            self._ctrl_btns.append((cv, txt))

        self._drag = {'x': 0, 'y': 0}
        for w in [self, self._title_lbl, self._version_lbl, icon_cv]:
            w.bind('<Button-1>', self._start_drag)
            w.bind('<B1-Motion>', self._on_drag)
            w.bind('<Double-Button-1>', self._maximize)

    def _start_drag(self, e):
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root

    def _on_drag(self, e):
        dx = e.x_root - self._drag['x']
        dy = e.y_root - self._drag['y']
        self.root.geometry(f'+{self.root.winfo_x() + dx}+{self.root.winfo_y() + dy}')
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root

    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.after(100, lambda: self.root.overrideredirect(True))

    def _maximize(self, e=None):
        if self.root.state() == 'zoomed':
            self.root.state('normal')
        else:
            self.root.state('zoomed')
