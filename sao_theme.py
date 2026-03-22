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
from typing import Optional, Callable, List, Dict, Tuple


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
        cx, cy = self.SIZE // 2, self.SIZE // 2
        t = self._hover_t

        if self._active:
            border_color = SAOColors.ACTIVE_BORDER
        else:
            border_color = lerp_color(SAOColors.CIRCLE_BORDER, SAOColors.ACTIVE_BORDER, t)

        self.create_oval(2, 2, self.SIZE - 2, self.SIZE - 2,
                         outline=border_color, width=2, fill='')

        ir = self.RADIUS - 4
        if self._active:
            inner_fill = SAOColors.ACTIVE_BG
        else:
            inner_fill = lerp_color('#ffffff', SAOColors.HOVER_BG, t)

        self.create_oval(cx - ir, cy - ir, cx + ir, cy + ir,
                         fill=inner_fill, outline='')

        if self._active:
            icon_color = SAOColors.ACTIVE_ICON
        else:
            icon_color = lerp_color(SAOColors.CIRCLE_ICON, SAOColors.HOVER_ICON, t)

        try:
            self.create_text(cx, cy, text=self.icon_text,
                             fill=icon_color, font=('Segoe UI Symbol', 16))
        except Exception:
            # 回退: 用简单字符
            self.create_text(cx, cy, text='●',
                             fill=icon_color, font=('Segoe UI', 16))

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
        self._active_item = None
        self._anim = Animator(self)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self._buttons.clear()
        for item in self.icon_arr[:5]:
            btn = SAOCircleButton(
                self,
                icon_text=item.get('icon', '●'),
                name=item.get('name', ''),
                can_activate=item.get('can_active', True),
                command=lambda it=item: self._on_item_click(it)
            )
            btn.pack(pady=7)
            self._buttons.append(btn)
        self.bind_all_recursive('<MouseWheel>', self._on_scroll)

    def bind_all_recursive(self, event, handler):
        self.bind(event, handler)
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
        for i, btn in enumerate(self._buttons):
            delay = i * 80
            btn.configure(cursor='')  # 先隐藏光标提示

            def animate_btn(b=btn, d=delay):
                anim = Animator(b)
                # 初始: 缩小 + 隐藏
                b.configure(width=1, height=1)

                def grow(t, button=b):
                    s = int(SAOCircleButton.SIZE * ease_out(t))
                    s = max(1, s)
                    button.configure(width=s, height=s)
                    if t >= 1.0:
                        button.configure(cursor='hand2')
                        button._draw()

                b.after(d, lambda: anim.animate('grow', 300, grow))

            animate_btn()


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
        # 右三角
        self._top.create_polygon(w, h * 0.77, w + 18, h * 0.77 + 7, w, h * 0.77 + 14,
                                 fill='#ffffff', outline='')
        self._top.create_text(w // 2, 30, text=self.username,
                              font=('Microsoft YaHei UI', 13), fill='#333333')
        if h > 50:
            self._top.create_line(10, 50, w - 10, 50, fill='#aaaaaa', width=2)

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

        # 连接线
        line_h = len(items) * 43 - 3
        line_cv = tk.Canvas(content, width=6, height=max(1, line_h),
                            bg=self.cget('bg'), highlightthickness=0)
        line_cv.create_line(3, 5, 3, line_h - 5, fill='#7c7c7c', width=2)
        line_cv.pack(side=tk.LEFT, padx=(0, 3), anchor='n', pady=5)

        # 箭头指示器
        arrow_cv = tk.Canvas(content, width=12, height=max(1, line_h),
                             bg=self.cget('bg'), highlightthickness=0)
        # 小圆点
        arrow_cv.create_oval(4, line_h // 2 - 2, 9, line_h // 2 + 3,
                             fill='#c0c0c0', outline='')
        arrow_cv.pack(side=tk.LEFT, padx=(0, 2), anchor='n', pady=5)

        list_frame = tk.Frame(content, bg=self.cget('bg'), highlightthickness=0)
        list_frame.pack(side=tk.LEFT, anchor='n')

        for i, item in enumerate(items):
            row = self._create_item(list_frame, item, i)
            self._items.append(row)

    def _create_item(self, parent, item: Dict, index: int) -> tk.Frame:
        row = tk.Frame(parent, bg='#ffffff', highlightthickness=0,
                       width=160, height=40)
        row.pack(fill=tk.X, pady=(0, 3))
        row.pack_propagate(False)

        icon_lbl = tk.Label(row, text=item.get('icon', ''),
                            bg='#ffffff', fg='#555555',
                            font=('Segoe UI Symbol', 12))
        icon_lbl.pack(side=tk.LEFT, padx=(10, 5))

        text_lbl = tk.Label(row, text=item.get('label', ''),
                            bg='#ffffff', fg=SAOColors.CHILD_TEXT,
                            font=('Microsoft YaHei UI', 10), anchor='w')
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 平滑悬停过渡
        _anim = Animator(row)
        _hover_state = {'t': 0.0}

        def _update_hover(t, r=row, il=icon_lbl, tl=text_lbl):
            _hover_state['t'] = t
            bg = lerp_color('#ffffff', SAOColors.CHILD_HOVER, t)
            fg = lerp_color(SAOColors.CHILD_TEXT, SAOColors.CHILD_HOVER_FG, t)
            icon_fg = lerp_color('#555555', SAOColors.CHILD_HOVER_FG, t)
            r.configure(bg=bg)
            il.configure(bg=bg, fg=icon_fg)
            tl.configure(bg=bg, fg=fg)

        def enter(e, a=_anim):
            a.animate('hover', 150, lambda t: _update_hover(t))

        def leave(e, a=_anim, hs=_hover_state):
            start = hs['t']
            a.animate('hover', 200, lambda t: _update_hover(lerp(start, 0, t)))

        for widget in [row, icon_lbl, text_lbl]:
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

        return row


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
            # SAO Utils: 8s 周期, 4 waypoints (0,0)→(0,8)→(-8,0)→(-8,8)→(0,0)
            phase = (elapsed % 8.0) / 8.0
            waypoints = [(0, 0), (0, 8), (-8, 0), (-8, 8), (0, 0)]
            idx = min(int(phase * 4), 3)
            local_t = (phase * 4) - idx
            x0, y0 = waypoints[idx]
            x1, y1 = waypoints[idx + 1]
            dx = int(x0 + (x1 - x0) * local_t)
            dy = int(y0 + (y1 - y0) * local_t)
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
            self._breath_job = self._overlay.after(50, breathe)

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
    LINK START 高品质粒子入场动画 v2
    - Phase 0 (0~0.7s):  黑屏 → 中心脉冲光点
    - Phase 1 (0.4~3.0s): 速度隧道 — 大量蓝白速度线向外飞射 (速度感拖尾)
    - Phase 2 (1.8~4.2s): 彩色粒子爆发, 长拖尾 (lookback 算法)
    - Phase 3 (3.4~5.4s): "LINK START" 逐字出现 + 光芒效果
    - Phase 4 (5.0~5.8s): 白闪脉冲 → ease_in_out 平滑渐隐
    """

    def __init__(self, root: tk.Tk, on_done: Optional[Callable] = None):
        self.root = root
        self.on_done = on_done
        self._overlay = None
        self._DURATION = 5.8

    def play(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)
        self._overlay.geometry(f'{sw}x{sh}+0+0')
        self._overlay.configure(bg='#000000')
        self._overlay.attributes('-alpha', 0.95)

        self._canvas = tk.Canvas(self._overlay, width=sw, height=sh,
                                 bg='#000000', highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        cx, cy = sw // 2, sh // 2
        self._cx, self._cy = cx, cy
        self._sw, self._sh = sw, sh

        # 速度线 (蓝白隧道) — 数量 * 2, 速度更高
        self._speed_lines = []
        for i in range(100):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(300, 1600)
            delay = random.uniform(0, 1.0)
            brightness = random.randint(140, 255)
            # 速度越快的线拖尾越长
            tail_frac = random.uniform(0.06, 0.18)
            self._speed_lines.append({
                'angle': angle, 'speed': speed,
                'delay': delay, 'brightness': brightness,
                'tail_frac': tail_frac
            })

        # 彩色粒子 — 更多粒子, 更长拖尾
        self._particles = []
        for i in range(160):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(60, 900)
            color = random.choice(SAOColors.LS_COLORS)
            size = random.uniform(2.0, 5.0)
            delay = random.uniform(0, 0.7)
            trail_len = random.randint(14, 24)   # 大幅延长拖尾段数
            trail_step = random.uniform(0.055, 0.09)  # 每段回溯时间
            self._particles.append({
                'angle': angle, 'speed': speed, 'color': color,
                'size': size, 'delay': delay,
                'trail_len': trail_len, 'trail_step': trail_step
            })

        # 星尘
        self._dust = []
        for i in range(60):
            x = random.uniform(0, sw)
            y = random.uniform(0, sh)
            vx = random.uniform(-20, 20)
            vy = random.uniform(-30, -5)
            alpha = random.uniform(0.2, 0.8)
            self._dust.append({'x': x, 'y': y, 'vx': vx, 'vy': vy, 'alpha': alpha})

        self._text_chars = list('LINK START')
        self._start_time = time.time()
        self._animate()

    def _animate(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return

        elapsed = time.time() - self._start_time
        if elapsed > self._DURATION:
            self._finish()
            return

        self._canvas.delete('all')
        cx, cy = self._cx, self._cy
        sw, sh = self._sw, self._sh
        edge_dist = math.hypot(sw, sh) * 0.55  # 大致到屏幕角落的距离

        # ── Phase 0: 黑屏 + 中心脉冲光点 (0~0.7s) ──
        if elapsed < 0.7:
            t = elapsed / 0.7
            glow_r = int(40 * t)
            for r in range(glow_r, 0, -3):
                alpha_val = int(100 * (1 - r / max(1, glow_r)) * t)
                c = f'#{alpha_val:02x}{alpha_val:02x}{min(255, alpha_val + 60):02x}'
                self._canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         fill=c, outline='')
            pulse = math.sin(t * math.pi * 5) * 0.35 + 0.65
            pr = max(1, int(7 * pulse))
            self._canvas.create_oval(cx - pr, cy - pr, cx + pr, cy + pr,
                                     fill='#66aaff', outline='')

        # ── Phase 1: 速度隧道 — 蓝白速度线 (0.4~3.0s) ──
        if 0.4 <= elapsed < 3.2:
            phase_t = max(0.0, (elapsed - 0.4) / 2.6)  # 0→1 over 2.6s

            for sl in self._speed_lines:
                if phase_t < sl['delay'] / 2.6:
                    continue
                # 局部时间: 从该线的 delay 开始
                local_raw = phase_t - sl['delay'] / 2.6
                local_t = min(1.0, local_raw / max(0.01, 1.0 - sl['delay'] / 2.6))
                eased_head = ease_out(local_t)

                # 头部位置
                dist_head = sl['speed'] * eased_head
                if dist_head < 3:
                    continue

                # 尾部: 向早一段时间的位置回溯
                tail_raw = max(0.0, local_t - sl['tail_frac'])
                dist_tail = sl['speed'] * ease_out(tail_raw)

                x1 = cx + math.cos(sl['angle']) * dist_tail
                y1 = cy + math.sin(sl['angle']) * dist_tail
                x2 = cx + math.cos(sl['angle']) * dist_head
                y2 = cy + math.sin(sl['angle']) * dist_head

                # 亮度: 靠近中心渐入, 超过边缘渐出
                fade_in  = min(1.0, dist_head / 60.0)
                fade_out = max(0.0, 1.0 - dist_head / edge_dist)
                overall  = fade_in * fade_out
                if overall < 0.04:
                    continue

                b   = sl['brightness']
                bv  = int(b * overall)
                # 蓝白渐变色: 亮处偏白, 暗处偏蓝
                blue_boost = min(255, bv + 50)
                color = f'#{bv:02x}{bv:02x}{blue_boost:02x}'
                width = max(1, int(2 * overall + 0.5))
                self._canvas.create_line(x1, y1, x2, y2, fill=color, width=width)

            # 中心脉冲光环
            ring_phase = min(1.0, phase_t * 2.0)
            ring_alpha = int(140 * (1 - ring_phase * 0.6))
            if ring_alpha > 5:
                ring_r = int(80 * ease_out(ring_phase))
                c = f'#{ring_alpha:02x}{ring_alpha:02x}{min(255, ring_alpha + 80):02x}'
                self._canvas.create_oval(cx - ring_r, cy - ring_r,
                                         cx + ring_r, cy + ring_r,
                                         outline=c, width=2, fill='')

        # ── Phase 2: 彩色粒子爆发 (1.8~4.2s) ──
        if 1.8 <= elapsed < 4.4:
            phase_t = max(0.0, (elapsed - 1.8) / 2.4)  # 0→1 over 2.4s

            for p in self._particles:
                if phase_t < p['delay']:
                    continue
                local_t = (phase_t - p['delay']) / max(0.01, 1.0 - p['delay'])
                local_t = min(1.0, local_t)

                # 粒子整体从 phase_t=0.75 起逐渐消隐
                particle_fade = max(0.0, 1.0 - max(0.0, (phase_t - 0.72) / 0.28))

                trail_len  = p['trail_len']
                trail_step = p['trail_step']

                # 从尾到头绘制, 确保头部覆盖在最上层
                for ti in range(trail_len, -1, -1):
                    # ti=0 是头, ti=trail_len 是最远的尾
                    look_back = ti * trail_step
                    raw_t = max(0.0, local_t - look_back)
                    eased = ease_out(raw_t)

                    trail_dist = p['speed'] * eased
                    tx = cx + math.cos(p['angle']) * trail_dist
                    ty = cy + math.sin(p['angle']) * trail_dist

                    # 头 alpha=1, 尾 alpha→0, 整体乘以消隐因子
                    trail_alpha = (1.0 - ti / trail_len) * particle_fade
                    if trail_alpha < 0.04:
                        continue

                    r0, g0, b0 = hex_to_rgb(p['color'])
                    r1 = int(r0 * trail_alpha)
                    g1 = int(g0 * trail_alpha)
                    b1 = int(b0 * trail_alpha)
                    tc = rgb_to_hex(r1, g1, b1)
                    s = max(1, int(p['size'] * (1.0 - ti / trail_len * 0.7)))
                    self._canvas.create_oval(tx - s, ty - s, tx + s, ty + s,
                                             fill=tc, outline='')

            # 星尘漂浮
            for d in self._dust:
                d['x'] += d['vx'] * 0.016
                d['y'] += d['vy'] * 0.016
                vis = min(1.0, phase_t * 2.0) * d['alpha'] * max(0.0, 1.0 - phase_t * 0.8)
                if vis < 0.08:
                    continue
                bval = int(255 * vis)
                dc = f'#{bval:02x}{bval:02x}{bval:02x}'
                self._canvas.create_oval(d['x'] - 1, d['y'] - 1,
                                         d['x'] + 1, d['y'] + 1,
                                         fill=dc, outline='')

        # ── Phase 3: "LINK START" 逐字出现 (3.4~5.4s) ──
        if elapsed >= 3.4:
            text_t = min(1.0, max(0.0, (elapsed - 3.4) / 2.0))
            total_chars = len(self._text_chars)
            char_spacing = 42
            total_width = total_chars * char_spacing
            start_x = cx - total_width // 2
            visible_count = int(total_chars * ease_out(text_t))

            # 背景辉光晕
            if text_t > 0.04:
                ga = min(1.0, text_t * 2.2)
                # 文字消隐时辉光也消退
                glow_fade = max(0.0, 1.0 - max(0.0, (text_t - 0.75) / 0.25))
                for gr in range(60, 0, -5):
                    a = int(32 * ga * glow_fade * (1 - gr / 60))
                    gc = f'#{a:02x}{int(a * 0.5):02x}{min(255, a * 3 + 50):02x}'
                    self._canvas.create_oval(cx - gr * 7, cy - gr * 2,
                                             cx + gr * 7, cy + gr * 2,
                                             fill=gc, outline='')

            # 扫描线
            if 0.02 < text_t < 0.92:
                scan_x = start_x + char_spacing // 2 + int(
                    (total_width - char_spacing) * min(1.0, text_t * 1.08))
                for si, sy in enumerate(range(cy - 38, cy + 38, 4)):
                    line_alpha = int(200 * (1 - abs(si - 9) / 10))
                    if line_alpha < 10:
                        continue
                    lc = f'#{line_alpha:02x}{line_alpha:02x}{min(255, line_alpha + 60):02x}'
                    self._canvas.create_line(scan_x - 1, sy, scan_x + 2, sy + 3,
                                             fill=lc, width=2)

            # 逐字绘制
            char_global_fade = max(0.0, 1.0 - max(0.0, (text_t - 0.80) / 0.20))
            for i in range(visible_count):
                char = self._text_chars[i]
                char_x = start_x + i * char_spacing + char_spacing // 2

                char_t = ease_out(min(1.0, max(0.0, text_t * total_chars - i + 0.5)))
                draw_alpha = char_t * char_global_fade
                if draw_alpha < 0.02:
                    continue

                if char == ' ':
                    if char_t > 0.3:
                        sp_a = int(220 * draw_alpha)
                        self._canvas.create_text(char_x, cy - 4,
                                                 text='✦',
                                                 fill=f'#{sp_a:02x}{int(sp_a * 0.68):02x}00',
                                                 font=('Segoe UI Symbol', 16))
                    continue

                # LINK (i<4) 金色, START (i>=5) 青色
                if i < 4:
                    base_r, base_g, base_b = 243, 175, 18
                else:
                    base_r, base_g, base_b = 77, 232, 244

                r = int(lerp(lerp(255, base_r, char_t), base_r, char_global_fade))
                g = int(lerp(lerp(255, base_g, char_t), base_g, char_global_fade))
                b = int(lerp(lerp(255, base_b, char_t), base_b, char_global_fade))
                r = int(r * char_global_fade + 255 * (1 - char_global_fade))
                g = int(g * char_global_fade + 255 * (1 - char_global_fade))
                b = int(b * char_global_fade + 255 * (1 - char_global_fade))
                text_color = rgb_to_hex(
                    int(lerp(255, base_r, char_t * char_global_fade)),
                    int(lerp(255, base_g, char_t * char_global_fade)),
                    int(lerp(255, base_b, char_t * char_global_fade))
                )

                offset_y = int(30 * (1 - char_t))

                # 字符辉光
                if char_t > 0.15 and char_global_fade > 0.1:
                    glow_r = int(30 * char_t * char_global_fade)
                    ga_v = int(60 * char_t * (1 - char_t * 0.5) * char_global_fade)
                    if ga_v > 4:
                        gc = rgb_to_hex(int(base_r * ga_v / 255),
                                        int(base_g * ga_v / 255),
                                        int(base_b * ga_v / 255))
                        self._canvas.create_oval(char_x - glow_r, cy - glow_r + offset_y,
                                                 char_x + glow_r, cy + glow_r + offset_y,
                                                 fill=gc, outline='')

                fsize = max(24, int(32 + 14 * (1 - char_t)))
                self._canvas.create_text(char_x, cy - 2 + offset_y, text=char,
                                         fill=text_color,
                                         font=('Segoe UI', fsize, 'bold'))

                # 落定下划线
                if char_t > 0.70 and char_global_fade > 0.2:
                    line_prog = ease_out((char_t - 0.70) / 0.30) * char_global_fade
                    line_w = int(36 * line_prog)
                    lc = rgb_to_hex(
                        int(lerp(255, base_r, char_global_fade)),
                        int(lerp(255, base_g, char_global_fade)),
                        int(lerp(255, base_b, char_global_fade))
                    )
                    self._canvas.create_line(char_x - line_w // 2, cy + 28 + offset_y,
                                             char_x + line_w // 2, cy + 28 + offset_y,
                                             fill=lc, width=2)

            # 全字出现后向外扩散光环
            if text_t > 0.85:
                ring_t = ease_out((text_t - 0.85) / 0.15)
                ring_r = int(260 * ring_t)
                ring_a = int(180 * (1 - ring_t))
                if ring_a > 5:
                    rc = f'#{min(255, ring_a + 80):02x}{ring_a:02x}{min(255, ring_a * 2 + 20):02x}'
                    self._canvas.create_oval(cx - ring_r, cy - ring_r // 2,
                                             cx + ring_r, cy + ring_r // 2,
                                             outline=rc, width=3, fill='')

            # 副标题淡入
            if text_t > 0.60:
                sub_in  = min(1.0, (text_t - 0.60) / 0.30)
                sub_out = char_global_fade
                sv = int(200 * sub_in * sub_out)
                sc = f'#{sv:02x}{sv:02x}{sv:02x}'
                self._canvas.create_text(cx, cy + 62, text='咲 Midi Player  v3.0.3',
                                         fill=sc, font=('Segoe UI', 13))

        # ── Phase 4: 白闪脉冲 + ease_in_out 平滑渐隐 (5.0~5.8s) ──
        if elapsed >= 5.0:
            fade_t = min(1.0, (elapsed - 5.0) / 0.8)
            # 开头短暂白闪
            flash = max(0.0, 1.0 - fade_t * 6.0)
            if flash > 0.02:
                wv = int(255 * flash * 0.7)
                self._canvas.create_rectangle(0, 0, sw, sh,
                                              fill=f'#{wv:02x}{wv:02x}{wv:02x}',
                                              outline='')
            # overlay 整体渐隐
            alpha = max(0.0, 0.95 * (1.0 - ease_in_out(fade_t)))
            try:
                self._overlay.attributes('-alpha', alpha)
            except Exception:
                pass

        self._overlay.after(16, self._animate)

    def _finish(self):
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
                 filetypes=None, callback=None, **kw):
        super().__init__(parent)
        self.result = None
        self.callback = callback
        self._current_dir = os.path.abspath(initial_dir)
        self._filetypes = filetypes or [('All Files', '*.*')]
        self._entries = []

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
                self._load_dir(os.path.join(self._current_dir, name))
            else:
                self.result = os.path.join(self._current_dir, name)
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
                 version="v3.0.3+3003", on_close=None, **kw):
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
