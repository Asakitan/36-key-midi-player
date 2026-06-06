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


# ──── SAO 菜单: 升级为 sao_auto 新版 GPU 菜单 ────
# 旧的 Canvas 版 SAOCircleButton/SAOMenuBar/SAOLeftInfo/SAOChildBar/SAOPopUpMenu
# 已移植到 sao_menu/ 包 (GPU fisheye/动态模糊 + 新 HUD)。
# re-export 保持 `from sao_theme import SAOPopUpMenu / SAOCircleButton / ...` 不变。
from sao_menu.circle_button import SAOCircleButton  # noqa: E402
from sao_menu.menu_bar import SAOMenuBar            # noqa: E402
from sao_menu.left_info import SAOLeftInfo          # noqa: E402
from sao_menu.child_bar import SAOChildBar          # noqa: E402
from sao_menu.popup_menu import SAOPopUpMenu        # noqa: E402

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
