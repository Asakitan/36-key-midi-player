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
from PIL import Image, ImageDraw, ImageFilter, ImageTk, ImageEnhance, ImageChops
from typing import Optional, Callable, List, Dict, Tuple
import numpy as np

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
    FONT_SAO = ('Segoe UI', 11)
    FONT_ROUND = ('Microsoft YaHei UI', 10)

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
                self._jobs[name] = self.widget.after(16, tick)
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
                         highlightthickness=0, bg=parent.cget('bg'), **kw)
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

        # ── 微弱投影 ──
        shadow_a = int(lerp(35, 55, t if not self._active else 1.0))
        shadow_c = f'#{shadow_a:02x}{shadow_a:02x}{shadow_a:02x}'
        self.create_oval(3, 4, _s - 1, _s,
                         outline=shadow_c, width=1, fill='')

        # ── 主边框 ──
        self.create_oval(2, 2, _s - 2, _s - 2,
                         outline=border_color, width=2, fill='')

        # ── 内圆填充 ──
        ir = _s // 2 - 4
        if self._active:
            inner_fill = SAOColors.ACTIVE_BG
        else:
            inner_fill = lerp_color('#ffffff', SAOColors.HOVER_BG, t)

        self.create_oval(cx - ir, cy - ir, cx + ir, cy + ir,
                         fill=inner_fill, outline='')

        # ── 图标 (字号随尺寸等比缩放) ──
        if self._active:
            icon_color = SAOColors.ACTIVE_ICON
        else:
            icon_color = lerp_color(SAOColors.CIRCLE_ICON, SAOColors.HOVER_ICON, t)

        fs = max(8, int(16 * self._size / self.SIZE))
        try:
            self.create_text(cx, cy, text=self.icon_text,
                             fill=icon_color, font=('Segoe UI Symbol', fs))
        except Exception:
            self.create_text(cx, cy, text='●',
                             fill=icon_color, font=('Segoe UI', fs))

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
                              font=('Microsoft YaHei UI', 13), fill='#333333')
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
                                 font=('Microsoft YaHei UI', 9), fill='#555',
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
                       width=160, height=40)
        row.pack(fill=tk.X)
        row.pack_propagate(False)

        # 左侧激活指示条 (2px, 初始透明)
        indicator = tk.Frame(row, bg='#ffffff', width=2, height=40)
        indicator.pack(side=tk.LEFT, fill=tk.Y)
        indicator.pack_propagate(False)

        icon_lbl = tk.Label(row, text=item.get('icon', ''),
                            bg='#ffffff', fg='#555555',
                            font=('Segoe UI Symbol', 12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 5))

        text_lbl = tk.Label(row, text=item.get('label', ''),
                            bg='#ffffff', fg=SAOColors.CHILD_TEXT,
                            font=('Microsoft YaHei UI', 10), anchor='w')
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

        def leave(e, a=_anim, hs=_hover_state):
            start = hs['t']
            a.animate('hover', 200, lambda t: _update_hover(lerp(start, 0, t)))

        for widget in [row, icon_lbl, text_lbl, indicator, arrow_lbl]:
            widget.bind('<Enter>', enter)
            widget.bind('<Leave>', leave)
            cmd = item.get('command')
            if cmd:
                widget.bind('<Button-1>', lambda e, c=cmd: c())

        # 入场动画: 从右侧滑入
        row.configure(width=0)
        delay = index * 60

        def slide_in(r=row):
            a = Animator(r)

            def grow(t, r2=r):
                w = max(1, int(160 * ease_out(t)))
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

    def _create_overlay(self):
        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._overlay.geometry(f'{sw}x{sh}+0+0')
        self._overlay.configure(bg='#111111')
        self._overlay.attributes('-alpha', 0.0)
        self._overlay.bind('<Button-1>', self._on_overlay_click)
        self._overlay.bind('<Escape>', lambda e: self.close())

        # 内容定位: anchor_widget 模式 → 贴近浮动按钮右上角向左上展开; 否则居中
        self._content = tk.Frame(self._overlay, bg='#111111', highlightthickness=0)
        try:
            aw = self.anchor_widget
            if aw and aw.winfo_exists():
                self._overlay.update_idletasks()
                ax = aw.winfo_rootx()
                ay = aw.winfo_rooty()
                awd = aw.winfo_width()
                # SE 角贴近 float 右上角 (向左上展开)
                self._content_x = ax + awd - 8
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
            alpha = t * 0.85
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

        if self.on_open_callback:
            self.on_open_callback()

    def _set_alpha(self, a):
        try:
            if self._overlay and self._overlay.winfo_exists():
                self._overlay.attributes('-alpha', a)
        except Exception:
            pass

    def _on_overlay_click(self, e):
        if e.widget == self._overlay:
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

        def fade(t):
            self._set_alpha(0.85 * (1 - t))

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

        if parent and parent.winfo_exists():
            px = parent.winfo_rootx() + (parent.winfo_width() - final_w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - final_h) // 2
        else:
            px = (dlg.winfo_screenwidth() - final_w) // 2
            py = (dlg.winfo_screenheight() - final_h) // 2

        dlg.geometry(f'{initial_w}x{final_h}+{px + (final_w - initial_w) // 2}+{py}')

        # ── 白色 SAO 对话框配色 (与截图匹配) ──
        dlg.configure(bg='#e0e0e0')

        main_box = tk.Frame(dlg, bg='#ffffff')
        main_box.pack(fill=tk.BOTH, expand=True)

        # 标题区 (68px)
        header = tk.Frame(main_box, bg='#ffffff', height=68)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_lbl = tk.Label(header, text='', bg='#ffffff',
                             fg=SAOColors.ALERT_TITLE_FG,
                             font=('Segoe UI', 13, 'bold'))
        title_lbl.pack(expand=True)

        tk.Frame(main_box, bg='#e0e0e0', height=1).pack(fill=tk.X)

        # 内容区 (浅灰)
        content_h = final_h - 68 - 83 - 2
        content = tk.Frame(main_box, bg='#eae9e9', height=max(25, content_h))
        content.pack(fill=tk.X)
        content.pack_propagate(False)

        content_lbl = tk.Label(content, text='', bg='#eae9e9',
                               fg='#888888',
                               font=('Microsoft YaHei UI', 10),
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
            # OK 蓝圆 (白底)
            ok_cv = tk.Canvas(btn_container, width=40, height=40,
                              bg='#ffffff', highlightthickness=0, cursor='hand2')
            ok_cv.pack(side=tk.LEFT, padx=20)
            ok_cv.create_oval(2, 2, 38, 38, outline=SAOColors.OK_BLUE, width=3, fill='')
            ok_cv.create_oval(9, 9, 31, 31, fill='#ffffff', outline='')
            ok_cv.create_oval(12, 12, 28, 28, fill=SAOColors.OK_BLUE, outline='')
            ok_cv.bind('<Button-1>', lambda e: do_ok())

            # Close 红圆 (白底)
            close_cv = tk.Canvas(btn_container, width=40, height=40,
                                 bg='#ffffff', highlightthickness=0, cursor='hand2')
            close_cv.pack(side=tk.LEFT, padx=20)
            close_cv.create_oval(2, 2, 38, 38, outline=SAOColors.CLOSE_RED, width=3, fill='')
            close_cv.create_oval(9, 9, 31, 31, fill=SAOColors.CLOSE_RED, outline='')
            close_cv.create_line(14, 14, 26, 26, fill='#ffffff', width=3)
            close_cv.create_line(14, 26, 26, 14, fill='#ffffff', width=3)
            close_cv.bind('<Button-1>', lambda e: do_close())
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
                         fill='#e1dede', font=('Segoe UI', 9))

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
                         fill='#e1dede', font=('Segoe UI', 7), anchor='s')
        self.create_text(bar_x + bar_w * 0.85, h - 2,
                         text=f'Lv.{self._level}',
                         fill='#e1dede', font=('Segoe UI', 7), anchor='s')


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
    _FOCAL = 800            # 透视焦距 = CSS perspective: 800px
    _TUNNEL_R_MIN = 15      # 隧道最小半径 (粒子距中轴的最小距离)
    _TUNNEL_R_MAX = 45      # 隧道最大半径
    _STREAK_H = 300         # 粒子轴向长度 (= CSS height: 300px)
    _NUM_PARTICLES = 300    # 粒子数量 (增加密度提升质感)

    # ──── 摄像机动画参数 (匹配 SAO-UI) ────
    _CAM_Z_START = -1200    # 摄像机起始 z (= CSS translateZ(-1200px))
    _CAM_Z_END = 1500       # 摄像机终止 z (= CSS translateZ(1500px))
    _CAM_DURATION = 3.5     # 单次飞行时长 = SAO-UI animation: 3.5s

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
    _POST_FRAG = '''
#version 330
uniform sampler2D u_cur;   // 当前帧场景
 uniform sampler2D u_prv;   // 历史模糊帧
uniform float     u_ca;    // 色差偏移 (单位: UV坐标)
out vec4 fragColor;
void main() {
    ivec2 sz = textureSize(u_cur, 0);
    vec2  uv = gl_FragCoord.xy / vec2(sz);
    // 色差: R 右偏, G 原位, B 左偏
    float r = texture(u_cur, uv + vec2(u_ca, 0.0)).r;
    float g = texture(u_cur, uv).g;
    float b = texture(u_cur, uv - vec2(u_ca, 0.0)).b;
    // 运动模糊: 22% 历史 + 78% 当前
    vec3 prev   = texture(u_prv, uv).rgb;
    vec3 result = mix(prev, vec3(r, g, b), 0.60);  // 40% history = stronger motion trail
    fragColor = vec4(result, 1.0);
}
'''

    def __init__(self, root: tk.Tk, on_done: Optional[Callable] = None):
        self.root = root
        self.on_done = on_done
        self._overlay = None
        self._sound_player = None

    # ════════════════════════════════════════════════════════
    #  Link Start 音效播放
    # ════════════════════════════════════════════════════════
    def _play_sound(self):
        """在后台线程中播放 linkstart.mp3 音效"""
        import threading
        def _do_play():
            try:
                _snd = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'linkstart.mp3')
                if not os.path.isfile(_snd):
                    return
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                snd = pygame.mixer.Sound(_snd)
                self._sound_player = snd
                snd.play()
            except Exception as e:
                print(f'[LinkStart] Sound play failed: {e}')
        threading.Thread(target=_do_play, daemon=True).start()

    # ════════════════════════════════════════════════════════
    #  启动
    # ════════════════════════════════════════════════════════
    def play(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._cx, self._cy = sw // 2, sh // 2
        self._sw, self._sh = sw, sh
        self._diag = math.hypot(sw, sh)

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
        self._color_particles = self._gen_tunnel(self._COLORS_8)
        self._blue_particles = self._gen_tunnel(self._BLUES_8)

        # ── OpenGL 3D 渲染初始化 ──
        self._gl_ctx = None
        self._gl_photo = None     # 保持 PhotoImage 引用
        self._prev_gl_arr = None  # 运动模糊前帧帧缓存 (numpy uint8 HxWx3)
        if _HAS_MODERNGL:
            try:
                self._init_gl()
            except Exception as e:
                print(f'[LinkStart] OpenGL init failed: {e}, fallback to Canvas')
                self._gl_ctx = None

        self._start_time = time.time()
        self._animate()

    # ════════════════════════════════════════════════════════
    #  隧道粒子生成 (SAO-UI 模型: 静态圆柱排列)
    # ════════════════════════════════════════════════════════
    def _gen_tunnel(self, colors: list) -> list:
        """
        生成 ~300 根静态隧道粒子.
        粒子分布在较深的范围, 摄像机从后方飞向前方,
        视觉上粒子会从中心小点逐渐变大并飞过摄像机.
        """
        particles = []
        for i in range(self._NUM_PARTICLES):
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

        # 启用深度测试
        ctx.enable(moderngl.DEPTH_TEST)

        # ── GPU 后处理: 运动模糊 + 色差 (ping-pong FBO) ──
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

    def _destroy_gl(self):
        """释放 OpenGL 资源."""
        if self._gl_ctx:
            try:
                self._gl_ctx.release()
            except Exception:
                pass
            self._gl_ctx = None
        self._gl_photo = None

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
        self._gl_postvao.render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self._gl_pframe = pf + 1

        # ── 读回后处理结果: 已含色差+模糊, 无需 CPU 运算 ──
        raw = write_fbo.read(components=3)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(sh, sw, 3)[::-1].copy()
        img = Image.fromarray(arr, 'RGB')
        photo = ImageTk.PhotoImage(img)
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
        if elapsed > self._DURATION:
            self._finish()
            return

        cv = self._canvas
        cv.delete('all')
        sw, sh = self._sw, self._sh

        # ── 背景 ──
        bg = self._calc_bg(elapsed)
        cv.create_rectangle(0, 0, sw, sh, fill=bg, outline='')

        # ── Phase 1: 彩色隧道 (0 ~ P1_END) ──
        if elapsed < self._P1_END + 0.5:
            # 粒子淡入: 0~0.5s 不可见, 0.5~1.5s 渐入
            particle_fade = 1.0
            if elapsed < 0.5:
                particle_fade = 0.0
            elif elapsed < 1.5:
                particle_fade = ease_out((elapsed - 0.5) / 1.0)
            if elapsed > self._P1_END:
                particle_fade = max(0, 1.0 - (elapsed - self._P1_END) / 0.5)

            # 使用原始 _CAM_DURATION (3.5s) 保持与 P3 相同的飞行速度.
            # z_near < 1.0 的近裁剪guard已处理摄像机追上粒子的情况 → 直接跳过不渲染.
            cam_z = self._cam_z(elapsed, self._CAM_DURATION)

            # 粒子隧道
            self._draw_tunnel(cv, self._color_particles, cam_z, bg,
                              particle_fade, t=elapsed)

            # P1 收尾: 暗色圆形从中心扩张扫过, 盖住未飞出的圆柱体
            if elapsed >= self._P1_END - 0.05:
                self._draw_p1_circle_wipe(cv, elapsed)

        # ── Phase 2: 文字 (3.5 ~ 5.5s) ──
        if self._P2_START - 0.2 <= elapsed < self._P2_END + 0.3:
            self._render_text_phase(cv, elapsed)

        # ── Phase 3: 蓝色隧道 (5.2 ~ 7.5s + 0.3s 渐隐) ──
        if self._P3_START <= elapsed < self._P3_END + 0.3:
            p3_fade = 1.0
            if elapsed < self._P3_START + 0.5:
                p3_fade = (elapsed - self._P3_START) / 0.5
            if elapsed > self._P3_END:
                p3_fade = max(0, 1.0 - (elapsed - self._P3_END) / 0.3)

            p3_t = elapsed - self._P3_START
            p3_dur = self._P3_END - self._P3_START  # = 2.3s, 确保摄像机在相结束前走完全程
            cam_z = self._cam_z(p3_t, p3_dur)
            self._draw_tunnel(cv, self._blue_particles, cam_z, bg,
                              p3_fade, t=elapsed)

        # ── Phase 4: 渐隐 (7.3 ~ 9.0s) ──
        if elapsed >= self._P4_START:
            self._draw_whiteout_cv(cv, elapsed)

        # 自适应调度: 用实际渲染耗时虚追 16.7ms 帧限, 尽量维持 60fps
        _render_ms = (time.perf_counter() - _t0) * 1000
        _delay = max(1, int(16.67 - _render_ms))
        self._overlay.after(_delay, self._animate)

    # ════════════════════════════════════════════════════════
    #  背景颜色
    # ════════════════════════════════════════════════════════
    def _calc_bg(self, t: float) -> str:
        """背景: 深色开始, 微微变亮, 给粒子对比度"""
        if t < 0.3:
            return '#1a1a2e'
        elif t < 1.0:
            return lerp_color('#1a1a2e', '#16213e', (t - 0.3) / 0.7)
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

        if wt < 0.6:
            # 光从中心向外扩展
            expansion = ease_out(wt / 0.6)
            max_r = int(diag * 0.7 * expansion)
            step = max(8, max_r // 20)
            for r in range(0, max(1, max_r), step):
                f = r / max(1, max_r)
                a = (1.0 - f) * expansion * 0.7
                v = min(255, int(20 + 180 * a))
                b = min(255, int(30 + 200 * a))
                cv.create_oval(cx - r, cy - int(r * 0.65),
                               cx + r, cy + int(r * 0.65),
                               fill=f'#{v:02x}{v:02x}{b:02x}', outline='')
        else:
            bright_t = ease_out(min(1.0, (wt - 0.6) / 0.4))
            v = int(lerp(60, 200, bright_t))
            b = min(255, v + 20)
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

    # ════════════════════════════════════════════════════════
    #  文字阶段
    # ════════════════════════════════════════════════════════
    def _render_text_phase(self, cv: tk.Canvas, t: float):
        """
        文字 "Welcome to / 咲 Midi Player !" 从远处飞入并飞过摄像机.

        3D 模型: 文字在 z 轴上移动, 近小远大 → 用字号模拟透视.
          z_text = 远(200) → 中(35, 正常显示) → 近(0.5, 飞过)
          font_size = base_size * reference_z / z_text

        时间线:
          3.8~4.3s: 飞入 (z 200→35, 字号 8→42)
          4.3~5.0s: 正常显示 (z≈35), glitch 双影
          5.0~5.6s: 飞过 (z 35→0.5, 字号 42→巨大)
          5.6~6.0s: 残影消散
        """
        # ── 文字 z 深度计算 ──
        if t < self._P2_START:
            return
        if t > self._P2_END:
            return

        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh
        # 时间分段
        t_fly_in_start = self._P2_START
        t_fly_in_end = t_fly_in_start + 0.7
        t_display_end = t_fly_in_end + 0.5
        t_fly_out_end = t_display_end + 0.55
        t_fade_end = self._P2_END

        base_size_1 = 38   # "Welcome to" 正常字号
        base_size_2 = 42   # "咲 Midi Player !" 正常字号
        ref_z = 35         # 正常显示时的 z 值

        if t < t_fly_in_end:
            # ── 飞入: z 从 250 → ref_z ──
            fly_t = (t - t_fly_in_start) / max(0.01, t_fly_in_end - t_fly_in_start)
            fly_e = ease_out(min(1.0, fly_t))
            z_text = lerp(250, ref_z, fly_e)
        elif t < t_display_end:
            # ── 正常显示 ──
            z_text = ref_z
        elif t < t_fly_out_end:
            # ── 飞过: z 从 ref_z → 0.8 ──
            out_t = (t - t_display_end) / max(0.01, t_fly_out_end - t_display_end)
            out_e = ease_in(min(1.0, out_t))  # ease_in = 先慢后快 (加速飞过)
            z_text = lerp(ref_z, 0.8, out_e)
        else:
            # ── 残影消散 ──
            z_text = 0.5

        # ── 字号 = base * ref_z / z ──
        if z_text < 0.5:
            return
        scale = ref_z / z_text
        size_1 = max(4, min(300, int(base_size_1 * scale)))
        size_2 = max(4, min(350, int(base_size_2 * scale)))

        # ── 可见性 (太大 = 飞过了, 太小 = 还很远) ──
        if size_1 > 250:
            return  # 已飞过视角

        # ── 文字颜色 (深灰/黑) ──
        vis = 1.0
        # 飞入淡入
        if t < t_fly_in_start + 0.15:
            vis = (t - t_fly_in_start) / 0.15
        # 飞过淡出
        if t > t_fly_out_end - 0.15:
            vis = max(0, (t_fade_end - t) / (t_fade_end - t_fly_out_end + 0.15))
        vis = max(0, min(1, vis))
        if vis < 0.02:
            return
        tv = int(lerp(180, 230, vis))
        tc = f'#{tv:02x}{tv:02x}{tv:02x}'

        # ── 文字位置 (居中, 靠近时可能偏移) ──
        txt_y1 = cy - int(30 * scale)  # "Welcome to"
        txt_y2 = cy + int(30 * scale)  # "咲 Midi Player !"

        # ── Glitch 双影效果 ──
        show_ghost = False
        ghost_dx, ghost_dy = 0, 0
        gx, gy = 0, 0

        # 飞入时: 轻微抖动
        if t < t_fly_in_end:
            fly_t = (t - t_fly_in_start) / max(0.01, t_fly_in_end - t_fly_in_start)
            if fly_t > 0.3:
                glitch = math.sin(t * 67) * math.sin(t * 31)
                if abs(glitch) > 0.6:
                    gx = random.randint(-3, 3)
                    gy = random.randint(-2, 2)

        # 显示期: 明显双影 (截图 img7 效果)
        if t_fly_in_end <= t < t_display_end:
            show_t = (t - t_fly_in_end) / max(0.01, t_display_end - t_fly_in_end)
            show_ghost = True
            if show_t < 0.3:
                # 双影展开
                ghost_dx = int(lerp(0, 8, ease_out(show_t / 0.3)))
                ghost_dy = int(lerp(0, 4, ease_out(show_t / 0.3)))
            elif show_t < 0.7:
                # 双影保持
                ghost_dx = 8
                ghost_dy = 4
                # 偶尔抖动
                glitch = math.sin(t * 41) * math.sin(t * 19)
                if abs(glitch) > 0.7:
                    ghost_dx += random.randint(-2, 2)
                    ghost_dy += random.randint(-1, 1)
            else:
                # 双影合拢
                merge_t = (show_t - 0.7) / 0.3
                ghost_dx = int(lerp(8, 0, ease_out(merge_t)))
                ghost_dy = int(lerp(4, 0, ease_out(merge_t)))
                if ghost_dx == 0 and ghost_dy == 0:
                    show_ghost = False

        # 飞过时: 激烈抖动
        if t >= t_display_end and t < t_fly_out_end:
            out_t = (t - t_display_end) / max(0.01, t_fly_out_end - t_display_end)
            show_ghost = True
            ghost_dx = int(lerp(0, 15, out_t))
            ghost_dy = int(lerp(0, 8, out_t))
            gx = random.randint(-5, 5)
            gy = random.randint(-3, 3)

        # ── 绘制双影层 ──
        if show_ghost and (ghost_dx > 0 or ghost_dy > 0) and size_1 < 200:
            ghost_v = max(80, min(255, tv - 40))
            ghost_c = f'#{ghost_v:02x}{ghost_v:02x}{ghost_v:02x}'
            try:
                cv.create_text(
                    cx + gx + ghost_dx, txt_y1 + gy + ghost_dy,
                    text='Welcome to',
                    fill=ghost_c,
                    font=('Consolas', size_1, 'bold'))
                cv.create_text(
                    cx + gx + ghost_dx, txt_y2 + gy + ghost_dy,
                    text='咲 Midi Player !',
                    fill=ghost_c,
                    font=('Consolas', size_2, 'bold'))
            except tk.TclError:
                pass

        # ── 绘制主文字 ──
        if size_1 < 200:
            try:
                cv.create_text(
                    cx + gx, txt_y1 + gy,
                    text='Welcome to',
                    fill=tc,
                    font=('Consolas', size_1, 'bold'))
                cv.create_text(
                    cx + gx, txt_y2 + gy,
                    text='咲 Midi Player !',
                    fill=tc,
                    font=('Consolas', size_2, 'bold'))
            except tk.TclError:
                pass

        # ── 结束: 不再画蓝色光点 ──

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
        self._current_dir = os.path.abspath(initial_dir)
        self._filetypes = filetypes or [('All Files', '*.*')]
        self._entries = []
        self._mode = mode  # 'file' or 'dir'

        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg=self._BG)

        w, h = 520, 480
        # 始终居中于屏幕
        px = (self.winfo_screenwidth()  - w) // 2
        py = (self.winfo_screenheight() - h) // 2
        self.geometry(f'{w}x{h}+{px}+{py}')

        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

        self._build_ui(w, h, title)
        self._load_dir(self._current_dir)

        self._drag = {'x': 0, 'y': 0}
        self.transient(parent)
        # 延迟 grab — 等窗口完整绘制后再抢占焦点, 避免窗口一闪即灭
        self.after(120, self._delayed_grab)

    def _delayed_grab(self):
        """窗口完全映射后才 grab_set, 防止 grab 冲突导致窗口闪退"""
        try:
            if self.winfo_exists():
                self.lift()
                self.grab_set()
                self.focus_force()
        except Exception:
            pass

    def _build_ui(self, w, h, title):
        # ── 外边框 1px ──
        outer = tk.Frame(self, bg=self._BORDER, padx=1, pady=1)
        outer.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(outer, bg=self._BG)
        inner.pack(fill=tk.BOTH, expand=True)

        # ── 左侧青色竖条 ──
        accent_bar = tk.Frame(inner, bg=self._ACCENT, width=2)
        accent_bar.pack(side=tk.LEFT, fill=tk.Y)

        main = tk.Frame(inner, bg=self._BG)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── 标题栏 (44px) ──
        header = tk.Frame(main, bg=self._BG2, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        # 菱形图标
        hcv = tk.Canvas(header, width=24, height=24,
                        bg=self._BG2, highlightthickness=0)
        hcv.pack(side=tk.LEFT, padx=(10, 0), pady=10)
        hcv.create_polygon(12, 2, 22, 12, 12, 22, 2, 12,
                           fill=self._ACCENT, outline='')

        title_lbl = tk.Label(header, text=title, bg=self._BG2,
                             fg='#646364',
                             font=('Segoe UI', 11, 'bold'))
        title_lbl.pack(side=tk.LEFT, padx=8)

        # 关闭 ×
        close_cv = tk.Canvas(header, width=28, height=28,
                             bg=self._BG2, highlightthickness=0, cursor='hand2')
        close_cv.pack(side=tk.RIGHT, padx=8, pady=8)
        close_cv.create_oval(2, 2, 26, 26,
                             outline=SAOColors.CLOSE_RED, width=2, fill='')
        close_cv.create_line(9, 9, 19, 19, fill=SAOColors.CLOSE_RED, width=2)
        close_cv.create_line(9, 19, 19, 9,  fill=SAOColors.CLOSE_RED, width=2)
        close_cv.bind('<Button-1>', lambda e: self._cancel())

        for w_item in [header, title_lbl]:
            w_item.bind('<Button-1>', self._start_drag)
            w_item.bind('<B1-Motion>', self._do_drag)

        # 顶部发光线
        tk.Frame(main, bg=self._ACCENT, height=1).pack(fill=tk.X)

        # ── 路径行 ──
        path_row = tk.Frame(main, bg=self._BG, height=26)
        path_row.pack(fill=tk.X)
        path_row.pack_propagate(False)

        tk.Label(path_row, text='▸', bg=self._BG, fg=self._ACCENT2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(8, 2), pady=4)
        self._path_lbl = tk.Label(path_row, text='', bg=self._BG,
                                  fg=self._TEXT_DIM,
                                  font=('Segoe UI', 8), anchor='w')
        self._path_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)

        # ── 列表区 ──
        list_outer = tk.Frame(main, bg=self._BORDER, padx=0, pady=0)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

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
            font=('Microsoft YaHei UI', 9),
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
        tk.Frame(main, bg=self._BORDER, height=1).pack(fill=tk.X, padx=6)

        # ── 文件名预览行 ──
        fname_row = tk.Frame(main, bg=self._BG, height=28)
        fname_row.pack(fill=tk.X, padx=6)
        fname_row.pack_propagate(False)
        self._fname_lbl = tk.Label(fname_row, text='', bg=self._BG,
                                   fg=self._ACCENT, font=('Microsoft YaHei UI', 9),
                                   anchor='w')
        self._fname_lbl.pack(fill=tk.X, padx=4, pady=4)
        self._listbox.bind('<<ListboxSelect>>', self._on_select)

        # ── 按钮区 (52px) ──
        tk.Frame(main, bg=self._BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(main, bg=self._BG2, height=52)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        btn_frame = tk.Frame(footer, bg=self._BG2)
        btn_frame.place(relx=0.5, rely=0.5, anchor='center')

        # 目录模式: 添加 "选择此文件夹" 按钮
        if self._mode == 'dir':
            sel_dir_cv = tk.Canvas(btn_frame, width=36, height=36,
                                   bg=self._BG2, highlightthickness=0, cursor='hand2')
            sel_dir_cv.pack(side=tk.LEFT, padx=(0, 4))
            sel_dir_cv.create_oval(2, 2, 34, 34, outline='#4caf50', width=2, fill='')
            sel_dir_cv.create_oval(8, 8, 28, 28, fill=self._BG2, outline='')
            sel_dir_cv.create_oval(11, 11, 25, 25, fill='#4caf50', outline='')
            sel_dir_cv.bind('<Button-1>', lambda e: self._confirm_dir())
            tk.Label(btn_frame, text='选择此文件夹', bg=self._BG2, fg='#999999',
                     font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(0, 16))

        # 确认 (蓝圆)
        ok_cv = tk.Canvas(btn_frame, width=36, height=36,
                          bg=self._BG2, highlightthickness=0, cursor='hand2')
        ok_cv.pack(side=tk.LEFT, padx=16)
        ok_cv.create_oval(2, 2, 34, 34, outline=SAOColors.OK_BLUE, width=2, fill='')
        ok_cv.create_oval(8, 8, 28, 28, fill=self._BG2, outline='')
        ok_cv.create_oval(11, 11, 25, 25, fill=SAOColors.OK_BLUE, outline='')
        ok_cv.bind('<Button-1>', lambda e: self._confirm())

        tk.Label(btn_frame, text='确认', bg=self._BG2, fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(0, 20))

        # 取消 (红圆)
        cancel_cv = tk.Canvas(btn_frame, width=36, height=36,
                              bg=self._BG2, highlightthickness=0, cursor='hand2')
        cancel_cv.pack(side=tk.LEFT, padx=(0, 4))
        cancel_cv.create_oval(2, 2, 34, 34, outline=SAOColors.CLOSE_RED, width=2, fill='')
        cancel_cv.create_oval(8, 8, 28, 28, fill=SAOColors.CLOSE_RED, outline='')
        cancel_cv.create_line(13, 13, 23, 23, fill='#ffffff', width=2)
        cancel_cv.create_line(13, 23, 23, 13, fill='#ffffff', width=2)
        cancel_cv.bind('<Button-1>', lambda e: self._cancel())

        tk.Label(btn_frame, text='取消', bg=self._BG2, fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)

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
        # 先释放 grab 并销毁窗口, 再通过 after 调用回调
        # 避免 grab 冲突导致第二个对话框被阻塞
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if callback and result:
            try:
                parent.after(80, lambda: callback(result))
            except Exception:
                callback(result)


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
                 version="v3.1.15+3115", on_close=None, **kw):
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
