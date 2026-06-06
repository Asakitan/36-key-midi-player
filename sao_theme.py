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
from overlay_scheduler import get_scheduler as _get_scheduler
from overlay_subpixel import subpixel_alpha_composite
from sao_menu_hud import MenuCircleButtonRenderer, MenuHudSpriteRenderer
from sao_sound import get_sao_font as _sao_font, get_cjk_font as _cjk_font

try:
    from linkstart_cy import build_tunnel_items as _build_tunnel_items_cy
except Exception:
    _build_tunnel_items_cy = None

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


def _symbol_font(size: int = 12, bold: bool = False):
    """Tk font for menu glyph symbols that SAOUI/ZhuZi may not cover."""
    weight = 'bold' if bold else ''
    family = 'Segoe UI Symbol'
    try:
        import tkinter.font as tkfont
        families = set(tkfont.families())
        if family not in families:
            family = 'Segoe UI Emoji' if 'Segoe UI Emoji' in families else 'Segoe UI'
    except Exception:
        pass
    return (family, size, weight) if weight else (family, size)


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
    MAX_SIZE = 70

    def __init__(self, parent, icon_text: str = '●', name: str = '',
                 can_activate: bool = True, command: Optional[Callable] = None, **kw):
        super().__init__(parent, width=self.MAX_SIZE, height=self.MAX_SIZE,
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
        self._renderer = MenuCircleButtonRenderer()
        self._bg_item = None
        self._bg_photo = None
        self._bg_canvas_image = Image.new(
            'RGBA', (self.MAX_SIZE, self.MAX_SIZE), (0, 0, 0, 0))
        self._visual_sig = None

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
        size_f = max(1.0, min(float(self.MAX_SIZE), float(self._size)))
        size = max(1, int(math.ceil(size_f)))
        t = self._hover_t

        if self._active:
            border_color = SAOColors.ACTIVE_BORDER
            inner_fill = SAOColors.ACTIVE_BG
            icon_color = SAOColors.ACTIVE_ICON
        else:
            border_color = lerp_color(SAOColors.CIRCLE_BORDER, SAOColors.ACTIVE_BORDER, t)
            inner_fill = lerp_color('#ffffff', SAOColors.HOVER_BG, t)
            icon_color = lerp_color(SAOColors.CIRCLE_ICON, SAOColors.HOVER_ICON, t)

        size_q = round(size_f * 4.0) / 4.0
        off = (self.MAX_SIZE - size_f) / 2.0
        ioff = round(off)
        snap = abs(off - ioff) < 0.25
        bg_key = self.cget('bg') or '#010101'
        sig_pos = (size, ioff, True) if snap else (size_q, round(off, 3), False)
        sig = (sig_pos, self.icon_text, border_color, inner_fill, icon_color, bg_key)
        if sig == self._visual_sig and self._bg_item is not None:
            return

        image = self._renderer.render(
            size, self.icon_text or '●', border_color, inner_fill, icon_color, bg_key)
        canvas_img = self._bg_canvas_image
        try:
            key_rgba = _hex_to_rgba(bg_key, 255)
        except Exception:
            key_rgba = (1, 1, 1, 255)
        canvas_img.paste(key_rgba, (0, 0, self.MAX_SIZE, self.MAX_SIZE))
        if snap:
            canvas_img.alpha_composite(image, (int(ioff), int(ioff)))
        else:
            subpixel_alpha_composite(canvas_img, image, off, off)

        if self._bg_photo is None:
            self._bg_photo = ImageTk.PhotoImage(canvas_img)
        else:
            try:
                self._bg_photo.paste(canvas_img)
            except Exception:
                self._bg_photo = ImageTk.PhotoImage(canvas_img)
        if self._bg_item is None:
            self.delete('all')
            self._bg_item = self.create_image(0, 0, image=self._bg_photo, anchor='nw')
        else:
            self.itemconfigure(self._bg_item, image=self._bg_photo)
        self._visual_sig = sig

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
        tq = round(max(0.0, min(1.0, t)) * 20.0) / 20.0
        if abs(tq - self._hover_t) < 1e-4:
            return
        self._hover_t = tq
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
        self._float_phases: List[float] = []
        self._float_registered = False
        self._float_sched_ident = f'sao_menu_bar_{id(self)}'
        self._enter_active = False
        self._enter_t0 = 0.0
        self._enter_delay_s = 0.08
        self._enter_duration_s = 0.28
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
            btn.place(x=0, y=0)
            self._buttons.append(btn)
            self._slots.append(slot)
            # 鱼眼: hover 时通知 MenuBar 更新所有按钮尺寸
            btn.bind('<Enter>', lambda e, i=idx: self._on_fisheye(i), add='+')
            btn.bind('<Leave>', lambda e: self._off_fisheye(),         add='+')
        self.bind_all_recursive('<MouseWheel>', self._on_scroll)
        self._float_phases = [i * 1.57 for i in range(len(self._buttons))]

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
        self._scroll_by_delta(getattr(e, 'delta', 0))

    def _scroll_by_delta(self, delta):
        if not self.icon_arr or len(self.icon_arr) <= 5:
            return
        if delta > 0:
            self.icon_arr.insert(0, self.icon_arr.pop())
        elif delta < 0:
            self.icon_arr.append(self.icon_arr.pop(0))
        else:
            return
        self._active_item = None
        if self.on_activate:
            self.on_activate(None)
        self._build()

    def play_enter_animation(self):
        """下落入场: 单一 scheduler 时间轴, 避免多路 after 抢帧。"""
        self._stop_float()
        self._enter_active = True
        self._enter_t0 = time.time()
        for btn in self._buttons:
            btn.configure(cursor='')
            btn._size = 1.0
            btn._visual_sig = None
            btn._draw()
        self._start_float()


    # ── 浮动 + 鱼眼循环 ──────────────────────────────────────────

    def _start_float(self):
        if self._float_registered or not self.winfo_exists():
            return
        try:
            top = self.winfo_toplevel()
            sched_root = getattr(top, 'master', None) or top
            _get_scheduler(sched_root).register(
                self._float_sched_ident, self._tick_float, self._float_animating)
            self._float_registered = True
        except Exception:
            self._float_registered = False
        self._tick_float(time.time())

    def _stop_float(self):
        if self._float_registered:
            try:
                _get_scheduler().unregister(self._float_sched_ident)
            except Exception:
                pass
            self._float_registered = False

    def _float_animating(self) -> bool:
        if not self.winfo_exists() or not self._buttons:
            return False
        if self._enter_active or self._hover_idx is not None:
            return True
        return any(abs(float(btn._size) - float(SAOCircleButton.SIZE)) > 0.18
                   for btn in self._buttons)

    def _tick_float(self, now):
        if not self.winfo_exists() or not self._buttons:
            return
        keep_animating = False
        for i, btn in enumerate(self._buttons):
            if self._enter_active:
                local_t = (now - self._enter_t0 - i * self._enter_delay_s) / self._enter_duration_s
                local_t = max(0.0, min(1.0, local_t))
                btn._size = float(max(1, int(round(SAOCircleButton.SIZE * ease_out(local_t)))))
                if local_t < 1.0:
                    keep_animating = True
                else:
                    btn.configure(cursor='hand2')
            elif self._hover_idx is not None:
                dist = abs(self._hover_idx - i)
                target = min(
                    SAOCircleButton.MAX_SIZE - 1.0,
                    SAOCircleButton.SIZE * (1.0 + 0.30 * math.exp(-0.9 * dist * dist)))
                delta = target - btn._size
                if abs(delta) > 0.18:
                    keep_animating = True
                    btn._size += delta * 0.36
                else:
                    btn._size = target
            else:
                target = float(SAOCircleButton.SIZE)
                delta = target - btn._size
                if abs(delta) > 0.18:
                    keep_animating = True
                    btn._size += delta * 0.28
                else:
                    btn._size = target
            sq = round(float(btn._size) * 4.0) / 4.0
            if getattr(btn, '_float_prev_q', None) != sq:
                btn._draw()
                btn._float_prev_q = sq
        if self._enter_active and not keep_animating:
            self._enter_active = False
        if not keep_animating and self._hover_idx is None:
            self._stop_float()

    def _on_fisheye(self, idx: int):
        self._hover_idx = idx
        self._start_float()

    def _off_fisheye(self):
        self._hover_idx = None
        self._start_float()


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
                            font=_symbol_font(12))
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
        self._menu_sched_ident = f'sao_popup_menu_{id(self)}'
        self._menu_anim_t0 = 0.0
        self._menu_anim_registered = False
        self._menu_hud_items = {}
        self._menu_hud_static_photo = None
        self._menu_hud_renderer = MenuHudSpriteRenderer()
        self._hud_cached_dims = None
        self._menu_open_grace_until = 0.0
        self._content_place_sig = None
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
        self._menu_open_grace_until = time.time() + 0.65
        self._menu_anim_t0 = time.time()
        self._create_overlay()

    def close(self):
        if not self._visible:
            return
        self._visible = False
        self._menu_open_grace_until = 0.0
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
        self._menu_hud_items = {}
        self._menu_hud_static_photo = None
        self._hud_cached_dims = None
        self._content_place_sig = None
        self._menu_hud_renderer.reset()

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
        smooth_dy = [float(spring_offset)]
        last_dy = [None]

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
            target_dy = 0.0 if t >= 0.995 else spring_offset * (1.0 - st)
            smooth_dy[0] = smooth_dy[0] * 0.55 + target_dy * 0.45
            dy = int(round(smooth_dy[0] / 2.0) * 2)
            if t >= 0.995:
                dy = 0
            if dy == last_dy[0]:
                return
            last_dy[0] = dy
            try:
                if self._content_x is not None:
                    self._content.place(
                        x=self._content_x,
                        y=self._content_y - dy,
                        anchor='se')
                else:
                    self._content.place(relx=0.5, rely=0.5, anchor='center',
                                        x=0, y=dy)
                self._draw_menu_hud(0, 0, phase=0.0)
            except Exception:
                pass

        def _finish_open():
            self._menu_anim_t0 = time.time()
            self._start_breath()

        # 菜单栏入场动画
        self._menu_bar.play_enter_animation()
        self._anim.animate('fade_in', 420, _anim_frame, on_done=_finish_open)

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
        cached = self._hud_cached_dims
        if cached is None:
            try:
                self._content.update_idletasks()
                sw = self._overlay.winfo_width()
                sh = self._overlay.winfo_height()
                cw = max(120, self._content.winfo_width() or self._content.winfo_reqwidth())
                ch = max(120, self._content.winfo_height() or self._content.winfo_reqheight())
            except Exception:
                return
            if sw <= 1 or sh <= 1 or cw <= 1 or ch <= 1:
                return
            self._hud_cached_dims = (sw, sh, cw, ch)
        else:
            sw, sh, cw, ch = cached

        if self._content_x is not None and self._content_y is not None:
            left = self._content.winfo_x() + dx
            top = self._content.winfo_y() + dy
        else:
            left = (sw - cw) // 2 + dx
            top = (sh - ch) // 2 + dy

        cv = self._menu_hud_cv
        frame = self._menu_hud_renderer.render(
            max(120, cw), max(120, ch), sw, sh, phase)
        ox, oy = self._menu_hud_renderer.sprite_origin(left, top)
        items = self._menu_hud_items

        if items.get('static') is None:
            items['static'] = cv.create_image(ox, oy, image=frame.static_photo, anchor='nw')
            items['static_origin'] = (ox, oy)
            self._menu_hud_static_photo = frame.static_photo
        else:
            if items.get('static_origin') != (ox, oy):
                cv.coords(items['static'], ox, oy)
                items['static_origin'] = (ox, oy)
            if frame.static_photo is not self._menu_hud_static_photo:
                cv.itemconfigure(items['static'], image=frame.static_photo)
                self._menu_hud_static_photo = frame.static_photo

        scan_y = oy + frame.scan_y
        cx1 = ox + frame.cx1
        cx2 = ox + frame.cx2
        self._ensure_line(items, 'scan', cx1, scan_y, cx2, scan_y, frame.scan_color)
        for idx, ty in enumerate(frame.trail_ys):
            self._ensure_line(
                items, f'trail{idx}', cx1, oy + ty, cx2, oy + ty,
                frame.trail_colors[idx])

        glow_off = frame.dot_glow_size // 2
        self._ensure_image(
            items, 'glow_l', frame.dot_photo_l,
            ox + frame.rail_x_l - glow_off, oy + frame.dot_y_l - glow_off)
        self._ensure_image(
            items, 'glow_r', frame.dot_photo_r,
            ox + frame.rail_x_r - glow_off, oy + frame.dot_y_r - glow_off)
        r = frame.dot_radius
        self._ensure_oval(
            items, 'dot_l',
            ox + frame.rail_x_l - r, oy + frame.dot_y_l - r,
            ox + frame.rail_x_l + r, oy + frame.dot_y_l + r,
            frame.dot_color_l)
        self._ensure_oval(
            items, 'dot_r',
            ox + frame.rail_x_r - r, oy + frame.dot_y_r - r,
            ox + frame.rail_x_r + r, oy + frame.dot_y_r + r,
            frame.dot_color_r)

        tx, ty = ox + frame.stamp_pos[0], oy + frame.stamp_pos[1]
        self._ensure_text(
            items, 'stamp', tx, ty, frame.stamp_text,
            frame.stamp_color, frame.stamp_font)

    def _ensure_line(self, items, key, x1, y1, x2, y2, color):
        cv = self._menu_hud_cv
        item = items.get(key)
        coords = (x1, y1, x2, y2)
        if item is None:
            items[key] = cv.create_line(*coords, fill=color, width=1)
            items[key + '_coords'] = coords
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != coords:
            cv.coords(item, *coords)
            items[key + '_coords'] = coords
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _ensure_image(self, items, key, photo, x, y):
        cv = self._menu_hud_cv
        item = items.get(key)
        coords = (x, y)
        if item is None:
            items[key] = cv.create_image(x, y, image=photo, anchor='nw')
            items[key + '_coords'] = coords
            items[key + '_photo'] = photo
            return
        if items.get(key + '_coords') != coords:
            cv.coords(item, x, y)
            items[key + '_coords'] = coords
        if items.get(key + '_photo') is not photo:
            cv.itemconfigure(item, image=photo)
            items[key + '_photo'] = photo

    def _ensure_oval(self, items, key, x1, y1, x2, y2, color):
        cv = self._menu_hud_cv
        item = items.get(key)
        coords = (x1, y1, x2, y2)
        if item is None:
            items[key] = cv.create_oval(*coords, fill=color, outline='')
            items[key + '_coords'] = coords
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != coords:
            cv.coords(item, *coords)
            items[key + '_coords'] = coords
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _ensure_text(self, items, key, x, y, text, color, font):
        cv = self._menu_hud_cv
        item = items.get(key)
        coords = (x, y)
        if item is None:
            items[key] = cv.create_text(
                x, y, text=text, fill=color, font=font, anchor='ne')
            items[key + '_coords'] = coords
            items[key + '_text'] = text
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != coords:
            cv.coords(item, x, y)
            items[key + '_coords'] = coords
        if items.get(key + '_text') != text:
            cv.itemconfigure(item, text=text)
            items[key + '_text'] = text
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _start_menu_hud_anim(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        self._draw_menu_hud(0, 0, phase=0.0)
        if self._menu_anim_registered:
            return
        try:
            _get_scheduler(self.root).register(
                self._menu_sched_ident,
                self._tick_menu_overlay,
                self._menu_overlay_animating)
            self._menu_anim_registered = True
        except Exception:
            self._menu_anim_registered = False

    def _on_root_click_outside(self, e):
        """root 层点击处理: 透明区域的点击穿透到 root, 判断是否在内容区外."""
        if not self._visible or not self._content:
            return
        try:
            bounds = self._get_visual_bounds()
            if bounds is None:
                if time.time() < self._menu_open_grace_until:
                    return
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
            now = time.time()
            try:
                focus = self._overlay.focus_displayof()
                if focus is None or str(focus) == 'None':
                    if now < self._menu_open_grace_until:
                        try:
                            delay_ms = max(20, int((self._menu_open_grace_until - now) * 1000) + 10)
                            self._overlay.after(delay_ms, _check)
                        except Exception:
                            pass
                        return
                    self.close()
                    return
            except Exception:
                if now < self._menu_open_grace_until:
                    try:
                        delay_ms = max(20, int((self._menu_open_grace_until - now) * 1000) + 10)
                        self._overlay.after(delay_ms, _check)
                    except Exception:
                        pass
                    return
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
            self._hud_cached_dims = None
            self._menu_hud_renderer.reset()
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
            self._hud_cached_dims = None
            self._menu_hud_renderer.reset()
        else:
            self._child_bar.hide_menu()
            self._hud_cached_dims = None
            self._menu_hud_renderer.reset()

    def refresh_child_menus(self, menus: Dict[str, List[Dict]], force: bool = False):
        """批量刷新子菜单，减少打开状态下逐项重建造成的抖动。"""
        menus = dict(menus or {})
        self.child_menus = menus
        if not self._child_bar:
            return False
        current = getattr(self._child_bar, '_current_name', None)
        for name, items in menus.items():
            self._child_bar.register_menu(name, items)
        changed = False
        if current:
            if current in menus:
                self._child_bar._current_name = None
                self._child_bar.show_menu(current)
                changed = True
            else:
                self._child_bar.hide_menu()
                changed = True
        if changed or force:
            self._hud_cached_dims = None
            self._menu_hud_renderer.reset()
            self._menu_hud_items = {}
            if self._menu_hud_cv:
                try:
                    self._menu_hud_cv.delete('all')
                except Exception:
                    pass
            self._draw_menu_hud(0, 0, phase=max(0.0, time.time() - self._menu_anim_t0))
        return changed

    def refresh_child_menu(self, name: str, items: List[Dict]):
        """动态更新某个子菜单的内容"""
        menus = dict(self.child_menus or {})
        menus[name] = items
        return self.refresh_child_menus(menus, force=True)

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
            self._menu_hud_cv = None
            self._menu_hud_items = {}
            self._menu_hud_static_photo = None
            self._hud_cached_dims = None
            self._menu_hud_renderer.reset()
            if self.on_close_callback:
                self.on_close_callback()

        anim = Animator(self._overlay)
        anim.animate('fade_out', 500, fade, on_done=destroy)

    def _start_breath(self):
        if not self._menu_anim_t0:
            self._menu_anim_t0 = time.time()
        self._start_menu_hud_anim()

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
        if self._menu_anim_registered:
            try:
                _get_scheduler(self.root).unregister(self._menu_sched_ident)
            except Exception:
                pass
            self._menu_anim_registered = False

    def _menu_overlay_animating(self) -> bool:
        return bool(self._visible and self._overlay and self._overlay.winfo_exists())

    def _tick_menu_overlay(self, now: float) -> None:
        if not self._visible or not self._overlay or not self._overlay.winfo_exists():
            return
        elapsed = max(0.0, now - self._menu_anim_t0)
        dx = int(round((4.8 * math.sin(elapsed * 0.44) +
                        1.8 * math.sin(elapsed * 0.96)) / 2.0) * 2)
        dy = int(round((3.8 * math.sin(elapsed * 0.32 + 1.0) +
                        1.4 * math.sin(elapsed * 0.79)) / 2.0) * 2)
        self._draw_menu_hud(dx, dy, elapsed)


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
# SAOLinkStart 已拆分到独立模块 link_start.py (GLFW/ModernGL 直出版启动动画, 取代旧的 FBO->Canvas 版本)
from link_start import SAOLinkStart  # noqa: E402  (re-export, keep `from sao_theme import SAOLinkStart`)


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
                 version="v3.5.3", on_close=None, **kw):
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
