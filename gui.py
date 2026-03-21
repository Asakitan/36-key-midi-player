# -*- coding: utf-8 -*-
"""
GUI模块 - Apple 风格深色主题 + 自定义无边框窗口
支持自定义快捷键、窗口置顶、MIDI可视化柱状图、透明度控制
波纹按钮、辉光按键、48键钢琴可视化
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import json
import ctypes
import math
import time
from typing import Optional, Dict, Callable, List

from player import MidiPlayer
from midi_parser import NoteEvent
from config import (
    WINDOW_TITLE, WINDOW_SIZE,
    KEYBOARD_LAYOUT, NOTE_NAMES, BLACK_KEY_LAYOUT, BLACK_KEY_NAMES,
    DEFAULT_HOTKEYS, CONFIG_FILE
)

# 检查是否有管理员权限（Windows）
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

KEYBOARD_HOTKEY_AVAILABLE = False
KEYBOARD_ERROR_MSG = None

try:
    import keyboard as kb
    try:
        test_callback = lambda: None
        kb.add_hotkey('ctrl+alt+shift+f12', test_callback, suppress=False)
        kb.remove_hotkey('ctrl+alt+shift+f12')
        KEYBOARD_HOTKEY_AVAILABLE = True
    except Exception as e:
        KEYBOARD_ERROR_MSG = str(e)
        if not is_admin():
            KEYBOARD_ERROR_MSG = "需要管理员权限才能使用全局快捷键"
except ImportError:
    KEYBOARD_ERROR_MSG = "未安装keyboard库"

PYNPUT_HOTKEY_AVAILABLE = False
try:
    from pynput import keyboard as pynput_kb
    from pynput.keyboard import Key, KeyCode
    PYNPUT_HOTKEY_AVAILABLE = True
except ImportError:
    pass

GLOBAL_HOTKEY_AVAILABLE = PYNPUT_HOTKEY_AVAILABLE or KEYBOARD_HOTKEY_AVAILABLE


# ==================== 主题系统 ====================
_THEMES = {
    'dark': {
        'BG_DARK': '#1C1C1E', 'BG_CARD': '#2C2C2E', 'BG_HOVER': '#3A3A3C',
        'BG_INPUT': '#1C1C1E', 'BG_PANEL': '#2C2C2E',
        'ACCENT_BLUE': '#0A84FF', 'ACCENT_GREEN': '#30D158', 'ACCENT_RED': '#FF453A',
        'ACCENT_ORANGE': '#FF9F0A', 'ACCENT_PURPLE': '#BF5AF2', 'ACCENT_CYAN': '#64D2FF',
        'ACCENT_PINK': '#FF375F',
        'TEXT_PRIMARY': '#F5F5F7', 'TEXT_SECONDARY': '#98989D',
        'TEXT_BRIGHT': '#FFFFFF', 'TEXT_DIM': '#636366',
        'ROW_HIGH': '#323236', 'ROW_MID_HIGH': '#2E3230',
        'ROW_MID': '#302E34', 'ROW_CHORD': '#342E2E',
        'KEY_NORMAL': '#3A3A3C', 'KEY_PRESSED': '#0A84FF', 'KEY_BORDER': '#48484A',
        'VIZ_LOW': '#30D158', 'VIZ_MID': '#64D2FF', 'VIZ_HIGH': '#0A84FF', 'VIZ_TOP': '#BF5AF2',
        'BTN_PRIMARY': '#0A84FF', 'BTN_SECONDARY': '#48484A', 'BTN_DANGER': '#FF453A',
        'BORDER': '#38383A', 'BORDER_BRIGHT': '#48484A',
        'GLOW_BLUE': '#1A5AFF', 'GLOW_CYAN': '#28C8FF',
        'TITLEBAR': '#161618', 'VIZ_BG': '#131315',
        'PIANO_WHITE': '#DCDCE0', 'PIANO_BLACK': '#2A2A2E', 'PIANO_BG': '#1A1A1C',
    },
    'light': {
        'BG_DARK': '#F2F2F7', 'BG_CARD': '#FFFFFF', 'BG_HOVER': '#E5E5EA',
        'BG_INPUT': '#F2F2F7', 'BG_PANEL': '#FFFFFF',
        'ACCENT_BLUE': '#007AFF', 'ACCENT_GREEN': '#34C759', 'ACCENT_RED': '#FF3B30',
        'ACCENT_ORANGE': '#FF9500', 'ACCENT_PURPLE': '#AF52DE', 'ACCENT_CYAN': '#5AC8FA',
        'ACCENT_PINK': '#FF2D55',
        'TEXT_PRIMARY': '#1C1C1E', 'TEXT_SECONDARY': '#8E8E93',
        'TEXT_BRIGHT': '#000000', 'TEXT_DIM': '#AEAEB2',
        'ROW_HIGH': '#E8E8ED', 'ROW_MID_HIGH': '#E4E8E5',
        'ROW_MID': '#E6E4E9', 'ROW_CHORD': '#EAE4E4',
        'KEY_NORMAL': '#E5E5EA', 'KEY_PRESSED': '#007AFF', 'KEY_BORDER': '#C7C7CC',
        'VIZ_LOW': '#34C759', 'VIZ_MID': '#5AC8FA', 'VIZ_HIGH': '#007AFF', 'VIZ_TOP': '#AF52DE',
        'BTN_PRIMARY': '#007AFF', 'BTN_SECONDARY': '#E5E5EA', 'BTN_DANGER': '#FF3B30',
        'BORDER': '#D1D1D6', 'BORDER_BRIGHT': '#C7C7CC',
        'GLOW_BLUE': '#4DA3FF', 'GLOW_CYAN': '#7DD6FC',
        'TITLEBAR': '#EBEBF0', 'VIZ_BG': '#F8F8FA',
        'PIANO_WHITE': '#FFFFFF', 'PIANO_BLACK': '#3A3A3C', 'PIANO_BG': '#E8E8ED',
    },
}

_current_theme = 'dark'


class ModernColors:
    """动态主题 - 支持 Dark SE / Light SE 切换"""
    BG_DARK = '#1C1C1E'
    BG_CARD = '#2C2C2E'
    BG_HOVER = '#3A3A3C'
    BG_INPUT = '#1C1C1E'
    BG_PANEL = '#2C2C2E'
    ACCENT_BLUE = '#0A84FF'
    ACCENT_GREEN = '#30D158'
    ACCENT_RED = '#FF453A'
    ACCENT_ORANGE = '#FF9F0A'
    ACCENT_PURPLE = '#BF5AF2'
    ACCENT_CYAN = '#64D2FF'
    ACCENT_PINK = '#FF375F'
    TEXT_PRIMARY = '#F5F5F7'
    TEXT_SECONDARY = '#98989D'
    TEXT_BRIGHT = '#FFFFFF'
    TEXT_DIM = '#636366'
    ROW_HIGH = '#323236'
    ROW_MID_HIGH = '#2E3230'
    ROW_MID = '#302E34'
    ROW_CHORD = '#342E2E'
    KEY_NORMAL = '#3A3A3C'
    KEY_PRESSED = '#0A84FF'
    KEY_BORDER = '#48484A'
    VIZ_LOW = '#30D158'
    VIZ_MID = '#64D2FF'
    VIZ_HIGH = '#0A84FF'
    VIZ_TOP = '#BF5AF2'
    BTN_PRIMARY = '#0A84FF'
    BTN_SECONDARY = '#48484A'
    BTN_DANGER = '#FF453A'
    BORDER = '#38383A'
    BORDER_BRIGHT = '#48484A'
    GLOW_BLUE = '#1A5AFF'
    GLOW_CYAN = '#28C8FF'
    TITLEBAR = '#161618'
    VIZ_BG = '#131315'
    PIANO_WHITE = '#DCDCE0'
    PIANO_BLACK = '#2A2A2E'
    PIANO_BG = '#1A1A1C'

    @classmethod
    def apply_theme(cls, name):
        global _current_theme
        theme = _THEMES.get(name, _THEMES['dark'])
        _current_theme = name
        for k, v in theme.items():
            setattr(cls, k, v)

    @classmethod
    def current_theme(cls):
        return _current_theme

    @classmethod
    def toggle_theme(cls):
        new = 'light' if _current_theme == 'dark' else 'dark'
        cls.apply_theme(new)
        return new


# ==================== 主题对话框 ====================
class ThemedDialog(tk.Toplevel):
    """与主题一致的自定义消息框"""
    @staticmethod
    def showinfo(parent, title, message):
        ThemedDialog._show(parent, title, message, 'info')

    @staticmethod
    def showwarning(parent, title, message):
        ThemedDialog._show(parent, title, message, 'warning')

    @staticmethod
    def showerror(parent, title, message):
        ThemedDialog._show(parent, title, message, 'error')

    @staticmethod
    def _show(parent, title, message, level='info'):
        C = ModernColors
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.configure(bg=C.BG_DARK)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)
        # 尺寸
        lines = message.count('\n') + 1
        dlg_w = min(420, max(280, len(max(message.split('\n'), key=len)) * 9 + 60))
        dlg_h = min(500, max(160, lines * 18 + 100))
        if parent and parent.winfo_exists():
            px = parent.winfo_rootx() + (parent.winfo_width() - dlg_w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - dlg_h) // 2
        else:
            px = (dlg.winfo_screenwidth() - dlg_w) // 2
            py = (dlg.winfo_screenheight() - dlg_h) // 2
        dlg.geometry(f"{dlg_w}x{dlg_h}+{max(0,px)}+{max(0,py)}")
        # DWM 圆角
        try:
            dlg.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(dlg.winfo_id())
            DWMWA = 33
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass
        # 边框
        border = tk.Frame(dlg, bg=C.BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=C.BG_CARD)
        inner.pack(fill=tk.BOTH, expand=True)
        # 标题栏
        top = tk.Frame(inner, bg=C.BG_CARD, height=36)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        icon_colors = {'info': C.ACCENT_BLUE, 'warning': C.ACCENT_ORANGE, 'error': C.ACCENT_RED}
        icon_texts = {'info': 'i', 'warning': '!', 'error': '×'}
        icv = tk.Canvas(top, width=20, height=20, bg=C.BG_CARD, highlightthickness=0)
        icv.create_oval(2, 2, 18, 18, fill=icon_colors.get(level, C.ACCENT_BLUE), outline='')
        icv.create_text(10, 10, text=icon_texts.get(level, 'i'), fill='#FFFFFF',
                        font=('Consolas', 10, 'bold'))
        icv.pack(side=tk.LEFT, padx=(14, 6), pady=8)
        tk.Label(top, text=title, bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT)
        # 关闭按钮
        close_cv = tk.Canvas(top, width=24, height=24, bg=C.BG_CARD, highlightthickness=0, cursor='hand2')
        close_cv.create_text(12, 12, text='×', fill=C.TEXT_DIM, font=('Consolas', 14))
        close_cv.pack(side=tk.RIGHT, padx=8, pady=6)
        close_cv.bind('<Button-1>', lambda e: dlg.destroy())
        close_cv.bind('<Enter>', lambda e: close_cv.itemconfig('all', fill=C.ACCENT_RED))
        close_cv.bind('<Leave>', lambda e: close_cv.itemconfig('all', fill=C.TEXT_DIM))
        # 分隔线
        tk.Frame(inner, bg=C.BORDER, height=1).pack(fill=tk.X, padx=12)
        # 内容
        msg_frame = tk.Frame(inner, bg=C.BG_CARD)
        msg_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 6))
        msg_label = tk.Label(msg_frame, text=message, bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                             font=('Microsoft YaHei UI', 9), justify=tk.LEFT, anchor='nw',
                             wraplength=dlg_w - 60)
        msg_label.pack(fill=tk.BOTH, expand=True)
        # 确定按钮
        btn_frame = tk.Frame(inner, bg=C.BG_CARD)
        btn_frame.pack(fill=tk.X, padx=20, pady=(4, 14))
        ok_btn = SmoothButton(btn_frame, text="确定", command=dlg.destroy,
                              width=70, height=28, bg=C.BTN_PRIMARY, font_size=9)
        ok_btn.pack(side=tk.RIGHT)
        # 拖拽
        _drag = {'x': 0, 'y': 0}
        def start_drag(e):
            _drag['x'], _drag['y'] = e.x_root, e.y_root
        def on_drag(e):
            dx, dy = e.x_root - _drag['x'], e.y_root - _drag['y']
            x, y = dlg.winfo_x() + dx, dlg.winfo_y() + dy
            dlg.geometry(f'+{x}+{y}')
            _drag['x'], _drag['y'] = e.x_root, e.y_root
        for w in [top, icv]:
            w.bind('<Button-1>', start_drag)
            w.bind('<B1-Motion>', on_drag)
        dlg.update()
        dlg.lift()
        dlg.wait_window()


class SettingsManager:
    """设置管理器"""
    def __init__(self):
        self.settings = {
            'hotkeys': DEFAULT_HOTKEYS.copy(),
            'last_file': '',
            'speed': 1.0,
            'transpose': 0,
            'chord_mode': False,
        }
        self.load()
    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    self.settings.update(saved)
        except:
            pass
    def save(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except:
            pass
    def get(self, key, default=None):
        return self.settings.get(key, default)
    def set(self, key, value):
        self.settings[key] = value
        self.save()


def get_icon_path():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, 'icon.ico')
    return icon_path if os.path.exists(icon_path) else None


# ==================== Custom Title Bar ====================
class CustomTitleBar(tk.Frame):
    """自定义无边框窗口标题栏 - 扁平暗色设计"""

    def __init__(self, parent, root, title="咲 Midi Player", version="v2.0.1+2001",
                 on_close=None, **kwargs):
        super().__init__(parent, bg=ModernColors.TITLEBAR, height=36, **kwargs)
        self.root = root
        self._on_close = on_close
        self._drag_data = {'x': 0, 'y': 0}
        self._maximized = False
        self._restore_geo = None
        self.pack_propagate(False)

        # 左侧: 图标点 + 标题
        icon_cv = tk.Canvas(self, width=12, height=12, bg=ModernColors.TITLEBAR, highlightthickness=0)
        icon_cv.create_oval(2, 2, 10, 10, fill=ModernColors.ACCENT_BLUE, outline='')
        icon_cv.pack(side=tk.LEFT, padx=(14, 6), pady=12)

        ttl = tk.Label(self, text=title, bg=ModernColors.TITLEBAR,
                       fg=ModernColors.TEXT_PRIMARY,
                       font=('Microsoft YaHei UI', 10, 'bold'))
        ttl.pack(side=tk.LEFT)
        self._title_lbl = ttl

        v_lbl = tk.Label(self, text=version, bg=ModernColors.TITLEBAR,
                         fg=ModernColors.TEXT_DIM,
                         font=('Microsoft YaHei UI', 8))
        v_lbl.pack(side=tk.LEFT, padx=(5, 0), pady=(3, 0))
        self._version_lbl = v_lbl

        # 右侧: 窗口控制按钮 (紧凑圆角 Canvas)
        controls = tk.Frame(self, bg=ModernColors.TITLEBAR)
        controls.pack(side=tk.RIGHT, padx=(0, 8))
        self._ctrl_btns = []
        btn_defs = [
            ('─', self._do_minimize, '#505054', '#8E8E93'),
            ('□', self._do_maximize, '#505054', '#8E8E93'),
            ('×', self._do_close, '#E81123', '#FF6B6B'),
        ]
        for txt, cmd, hover_bg, hover_fg in btn_defs:
            cv = tk.Canvas(controls, width=32, height=24, bg=ModernColors.TITLEBAR,
                           highlightthickness=0, cursor='hand2')
            cv.pack(side=tk.LEFT, padx=1, pady=6)
            _normal_bg = ModernColors.TITLEBAR
            _hover_bg = hover_bg
            _hover_fg = hover_fg
            _cmd = cmd
            # 初始绘制
            self._draw_ctrl_btn(cv, txt, _normal_bg, '#6E6E73')
            cv.bind("<Enter>", lambda e, c=cv, t=txt, hbg=_hover_bg, hfg=_hover_fg: self._draw_ctrl_btn(c, t, hbg, hfg))
            cv.bind("<Leave>", lambda e, c=cv, t=txt: self._draw_ctrl_btn(c, t, ModernColors.TITLEBAR, '#6E6E73'))
            cv.bind("<Button-1>", lambda e, c=_cmd: c())
            self._ctrl_btns.append((cv, txt))

        # 拖拽绑定
        for w in [self, ttl, v_lbl, icon_cv]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<Double-Button-1>", lambda e: self._do_maximize())

    def _draw_ctrl_btn(self, cv, text, bg, fg):
        cv.delete('all')
        w, h = 32, 24
        r = 6
        # 圆角矩形背景
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h,
               w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0, r, 0]
        cv.create_polygon(pts, fill=bg, smooth=True, outline='')
        cv.create_text(w / 2, h / 2, text=text, fill=fg, font=('Consolas', 11), anchor='center')

    def _start_drag(self, e):
        self._drag_data = {'x': e.x_root, 'y': e.y_root,
                           'wx': self.root.winfo_x(), 'wy': self.root.winfo_y()}

    def _on_drag(self, e):
        if self._maximized:
            old_w = self.root.winfo_width()
            self._do_maximize()
            new_w = self.root.winfo_width()
            ratio = min(1.0, e.x_root / max(1, old_w))
            new_x = e.x_root - int(new_w * ratio)
            new_y = e.y_root - 18
            self.root.geometry(f"+{max(0, new_x)}+{max(0, new_y)}")
            self._drag_data = {'x': e.x_root, 'y': e.y_root, 'wx': new_x, 'wy': new_y}
            return
        dx = e.x_root - self._drag_data['x']
        dy = e.y_root - self._drag_data['y']
        self.root.geometry(f"+{self._drag_data['wx'] + dx}+{self._drag_data['wy'] + dy}")

    def _do_minimize(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)
        except:
            self.root.iconify()

    def _do_maximize(self):
        if self._maximized:
            if self._restore_geo:
                self.root.geometry(self._restore_geo)
            self._maximized = False
        else:
            self._restore_geo = self.root.geometry()
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                rect = RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                self.root.geometry(f"{w}x{h}+{rect.left}+{rect.top}")
            except:
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight() - 40
                self.root.geometry(f"{sw}x{sh}+0+0")
            self._maximized = True

    def _do_close(self):
        if self._on_close:
            self._on_close()
        else:
            self.root.destroy()


class ResizeGrip(tk.Canvas):
    """窗口右下角拖拽调整大小手柄"""
    def __init__(self, parent, root, size=14, **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=ModernColors.BG_PANEL, highlightthickness=0,
                         cursor='size_nw_se', **kwargs)
        self.root = root
        self._min_w, self._min_h = 860, 750
        # 绘制抓手点
        for i in range(3):
            for j in range(i + 1):
                x = size - 4 - j * 4
                y = size - 4 - (2 - i) * 4
                self.create_oval(x, y, x + 2, y + 2, fill='#636366', outline='')
        self.bind("<Button-1>", self._start)
        self.bind("<B1-Motion>", self._resize)
        self._sd = None

    def _start(self, e):
        self._sd = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _resize(self, e):
        if self._sd:
            sx, sy, sw, sh = self._sd
            nw = max(self._min_w, sw + e.x_root - sx)
            nh = max(self._min_h, sh + e.y_root - sy)
            self.root.geometry(f"{nw}x{nh}")


# ==================== StatusPill 指示器 ====================
class StatusPill(tk.Canvas):
    """胶囊形状态指示器 - SHIFT/延音等"""
    def __init__(self, parent, text="", active_color=ModernColors.ACCENT_BLUE,
                 inactive_color=None, width=100, height=22, **kwargs):
        try:
            pbg = parent.cget('bg')
        except:
            pbg = ModernColors.BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=pbg, highlightthickness=0, **kwargs)
        self._text = text
        self._active = False
        self._active_color = active_color
        self._inactive_color = inactive_color  # None = 自动跟随主题
        self._draw()

    def set_active(self, active, text=None):
        self._active = active
        if text is not None:
            self._text = text
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        r = h // 2
        inactive_c = self._inactive_color if self._inactive_color is not None else ModernColors.BORDER
        color = self._active_color if self._active else inactive_c
        # 胶囊背景
        self.create_oval(0, 0, h, h, fill=color, outline='')
        self.create_oval(w - h, 0, w, h, fill=color, outline='')
        self.create_rectangle(r, 0, w - r, h, fill=color, outline='')
        # 边框轮廓 (inactive 时用主题边框, active 时用辉光色)
        border_col = ModernColors.BORDER_BRIGHT if not self._active else self._brighten(color, 35)
        self.create_oval(0, 0, h, h, outline=border_col, width=1, fill='')
        self.create_oval(w - h, 0, w, h, outline=border_col, width=1, fill='')
        self.create_line(r, 0, w - r, 0, fill=border_col)
        self.create_line(r, h - 1, w - r, h - 1, fill=border_col)
        # 左侧小圆点
        dot_r = 3
        dot_x = r
        dot_y = h // 2
        dot_color = '#FFFFFF' if self._active else ModernColors.TEXT_DIM
        self.create_oval(dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r,
                         fill=dot_color, outline='')
        # 文字
        fg = '#FFFFFF' if self._active else ModernColors.TEXT_SECONDARY
        self.create_text(w // 2 + 4, h // 2, text=self._text, fill=fg,
                         font=('Microsoft YaHei UI', 8), anchor='center')

    def _brighten(self, color, amount=20):
        r = min(255, int(color[1:3], 16) + amount)
        g = min(255, int(color[3:5], 16) + amount)
        b = min(255, int(color[5:7], 16) + amount)
        return f"#{r:02x}{g:02x}{b:02x}"


# ==================== GlowProgressBar ====================
class GlowProgressBar(tk.Canvas):
    """Apple 风格圆角进度条 - 渐变填充 + 辉光尖端"""
    def __init__(self, parent, height=8, **kwargs):
        try:
            pbg = parent.cget('bg')
        except:
            pbg = ModernColors.BG_CARD
        super().__init__(parent, height=height, highlightthickness=0, bg=pbg, **kwargs)
        self._value = 0.0
        self._bar_h = height
        self._seek_cb = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_click)

    def set(self, value):
        self._value = max(0.0, min(100.0, float(value)))
        self._draw()

    def get(self):
        return self._value

    def on_seek(self, callback):
        self._seek_cb = callback

    def _on_click(self, event):
        if self._seek_cb:
            w = self.winfo_width()
            if w > 0:
                self._seek_cb(max(0, min(1.0, event.x / w)))

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self._bar_h
        if w <= 1:
            return
        pad = 0
        track_r = h // 2

        # 轨道背景 (pill shape)
        _track_c = ModernColors.BG_HOVER
        self.create_oval(pad, pad, pad + h, h, fill=_track_c, outline='')
        self.create_oval(w - h - pad, pad, w - pad, h, fill=_track_c, outline='')
        self.create_rectangle(pad + track_r, pad, w - pad - track_r, h, fill=_track_c, outline='')

        # 填充
        fill_w = int((w - 2 * pad) * self._value / 100.0)
        if fill_w > 2:
            fw = min(fill_w, w - 2 * pad)
            # 渐变分段
            segs = max(1, fw // 4)
            seg_w = fw / segs
            for i in range(segs):
                sx = pad + int(i * seg_w)
                ex = pad + int((i + 1) * seg_w)
                t = i / max(1, segs - 1)
                cr = int(0x06 + (0x0A - 0x06) * t)
                cg = int(0x60 + (0x84 - 0x60) * t)
                cb = int(0xD0 + (0xFF - 0xD0) * t)
                self.create_rectangle(sx, pad, ex, h, fill=f"#{cr:02x}{cg:02x}{cb:02x}", outline='')
            # 左端圆角
            self.create_oval(pad, pad, pad + h, h, fill='#065ACD', outline='')
            # 右端散光辉光
            if fw > h:
                tip = pad + fw
                # 多层散光 (渐变圆形辉光)
                for expand, mix_t in [(10, 0.04), (7, 0.09), (4, 0.18), (2, 0.32)]:
                    lr = int(0x25 + (0x64 - 0x25) * mix_t)
                    lg = int(0x25 + (0xD2 - 0x25) * mix_t)
                    lb = int(0x28 + (0xFF - 0x28) * mix_t)
                    self.create_oval(
                        tip - expand, h // 2 - expand, tip + expand, h // 2 + expand,
                        fill=f"#{lr:02x}{lg:02x}{lb:02x}", outline='')
                self.create_rectangle(max(pad, tip - 3), pad + 1, tip, h - 1,
                                      fill='#64D2FF', outline='')

        # 悬停鼠标变手型
        self.bind("<Enter>", lambda e: self.configure(cursor='hand2'))


# ==================== SmoothButton 波纹按钮 ====================
class SmoothButton(tk.Canvas):
    """Apple 风格圆角按钮 - 波纹点击 + 悬停辉光"""

    def __init__(self, parent, text="", command=None, width=100, height=34,
                 bg=None, fg="#FFFFFF", radius=8, font_size=11, **kwargs):
        if bg is None:
            bg = ModernColors.BTN_SECONDARY
        try:
            parent_bg = parent.cget('bg')
        except:
            parent_bg = ModernColors.BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=parent_bg, highlightthickness=0, **kwargs)
        self.command = command
        self.base_bg = bg
        self.current_bg = bg
        self.fg = fg
        self.radius = radius
        self.text = text
        self.font_size = font_size
        self._pressed = False
        self._ripples = []
        self._hover_t = 0.0
        self._hover_id = None
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _lerp_color(self, c1, c2, t):
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _brighten(self, color, amount=20):
        r = min(255, int(color[1:3], 16) + amount)
        g = min(255, int(color[3:5], 16) + amount)
        b = min(255, int(color[5:7], 16) + amount)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _darken(self, color, amount=20):
        r = max(0, int(color[1:3], 16) - amount)
        g = max(0, int(color[3:5], 16) - amount)
        b = max(0, int(color[5:7], 16) - amount)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw(self, color=None):
        self.delete("body")
        self.delete("text_item")
        color = color or self.current_bg
        w, h, r = self.winfo_reqwidth(), self.winfo_reqheight(), self.radius
        # 底部阴影 (悬停时带散光色调)
        if self._hover_t > 0:
            shadow_c = self._lerp_color(self._darken(color, 30), '#64D2FF', 0.10)
        else:
            shadow_c = self._darken(color, 30)
        self._mk_rrect(0, 1, w, h, r, shadow_c, "body")
        # 主体
        self._mk_rrect(0, 0, w, h - 1, r, color, "body")
        # 顶部高光 (悬停时带散光色调)
        if self._hover_t > 0:
            hi = self._lerp_color(color, '#64D2FF', 0.20)
        else:
            hi = self._brighten(color, 8)
        self._mk_rrect(2, 1, w - 2, 2, max(1, r - 1), hi, "body")
        # 悬停散光轮廓
        if self._hover_t > 0:
            glow_c = self._lerp_color(color, '#64D2FF', 0.28)
            r_o = min(r, w // 2, (h - 1) // 2)
            if r_o >= 1:
                pts = [r_o, 0, w - r_o, 0, w, 0, w, r_o, w, h - 1 - r_o, w, h - 1,
                       w - r_o, h - 1, r_o, h - 1, 0, h - 1, 0, h - 1 - r_o,
                       0, r_o, 0, 0, r_o, 0]
                self.create_polygon(pts, fill='', outline=glow_c,
                                   smooth=True, width=1, tags="body")
        # 文字 - 自动根据背景亮度选择文字颜色
        _r, _g, _b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        _lum = 0.299 * _r + 0.587 * _g + 0.114 * _b
        text_fg = self.fg if _lum < 150 else ModernColors.TEXT_PRIMARY
        self.create_text(w / 2, (h - 1) / 2, text=self.text, fill=text_fg,
                         font=('Microsoft YaHei UI', self.font_size), anchor='center', tags="text_item")
        # 保持z-order: body < ripple < text
        try:
            self.tag_raise("ripple", "body")
            self.tag_raise("text_item")
        except Exception:
            pass

    def _mk_rrect(self, x, y, w, h, r, color, tag=""):
        r = min(r, (w - x) // 2, (h - y) // 2)
        if r < 1:
            self.create_rectangle(x, y, w, h, fill=color, outline='', tags=tag)
            return
        pts = [x + r, y, w - r, y, w, y, w, y + r, w, h - r, w, h,
               w - r, h, x + r, h, x, h, x, h - r, x, y + r, x, y, x + r, y]
        self.create_polygon(pts, fill=color, smooth=True, outline='', tags=tag)

    # --- Ripple 波纹效果 (简洁微亮) ---
    def _spawn_ripple(self, cx, cy):
        # 只做一次亮度闪烁，不做圆形扩展 (更精致)
        self._draw(self._brighten(self.base_bg, 22))
        self.after(120, lambda: self._draw(self.base_bg))

    # --- Hover ---
    def _on_enter(self, e):
        self.configure(cursor='hand2')
        self._hover_t = 1.0
        self._draw(self._brighten(self.base_bg, 12))

    def _on_leave(self, e):
        self._pressed = False
        self._hover_t = 0.0
        self._draw(self.base_bg)

    def _on_click(self, e):
        self._pressed = True
        self._draw(self._darken(self.base_bg, 12))

    def _on_release(self, e):
        if self._pressed:
            self._pressed = False
            self._spawn_ripple(e.x, e.y)
            if self.command:
                self.command()

    def set_text(self, text):
        self.text = text
        self._draw()

    def set_bg(self, color):
        self.base_bg = color
        self.current_bg = color
        self._draw()


# ==================== PianoKey 辉光按键 ====================
class PianoKey(tk.Canvas):
    """钢琴按键 - 支持渐亮渐暗 + 辉光效果"""
    FADE_IN_STEPS = 3
    FADE_OUT_STEPS = 8
    FRAME_DELAY = 16

    def __init__(self, parent, note_name: str, key_char: str,
                 row_color: str = ModernColors.KEY_NORMAL, is_black: bool = False,
                 color_role: str = 'KEY_NORMAL', **kwargs):
        self._is_black_key = is_black
        if is_black:
            super().__init__(parent, width=52, height=46,
                             bg=ModernColors.BG_CARD, highlightthickness=0, **kwargs)
        else:
            super().__init__(parent, width=72, height=68,
                             bg=ModernColors.BG_CARD, highlightthickness=0, **kwargs)
        self.note_name = note_name
        self.key_char = key_char
        self.color_role = color_role          # 主题属性名, 如 'ROW_HIGH'
        self.base_color = row_color
        self.current_color = row_color
        self._highlight_id = None
        self._fade_animation_id = None
        self._is_pressed = False
        self._draw()

    def _lerp_color(self, c1, c2, t):
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def reset_theme(self):
        """主题切换后更新基础色, 如果当前没有按下则直接应用"""
        new_base = getattr(ModernColors, self.color_role, self.base_color)
        self.base_color = new_base
        if not self._is_pressed:
            self._cancel_animations()
            self.current_color = new_base
        self.configure(bg=ModernColors.BG_CARD)
        self._draw()

    def _draw(self):
        """绘制按键 - 渐变填充 + 多层柔和辉光"""
        self.delete("all")
        is_active = self._is_pressed or (self.current_color != self.base_color)
        cr = int(self.current_color[1:3], 16)
        cg = int(self.current_color[3:5], 16)
        cb = int(self.current_color[5:7], 16)

        if self._is_black_key:
            w, h = 52, 46
            r = 8
            bx2, by2 = w - 3, h - 3
            if is_active:
                # 多层散光辉光 - 平滑渐变 (lerp 混合背景)
                bg_r = int(ModernColors.BG_CARD[1:3], 16)
                bg_g = int(ModernColors.BG_CARD[3:5], 16)
                bg_b = int(ModernColors.BG_CARD[5:7], 16)
                for off, mix_t in [(8, 0.01), (7, 0.03), (5, 0.08), (4, 0.16), (2, 0.26), (1, 0.38)]:
                    lr = int(bg_r + (cr - bg_r) * mix_t)
                    lg = int(bg_g + (cg - bg_g) * mix_t)
                    lb = int(bg_b + (cb - bg_b) * mix_t)
                    self._draw_rounded_rect(-off, -off, bx2 + off, by2 + off,
                                            r + off, f"#{lr:02x}{lg:02x}{lb:02x}")
            else:
                self._draw_rounded_rect(2, 2, w - 1, h - 1, r, ModernColors.BG_DARK)
            # 主体填充
            self._draw_rounded_rect(0, 0, bx2, by2, r, self.current_color)
            # 渐变覆盖: 上半部分更亮 (玻璃效果)
            top_h = by2 // 2
            bright = 35 if is_active else 8
            top_c = f"#{min(255,cr+bright):02x}{min(255,cg+bright):02x}{min(255,cb+bright):02x}"
            self._draw_rounded_rect(2, 1, bx2 - 2, top_h, max(3, r - 2), top_c)
            # 顶部高光线
            if is_active:
                shine_c = f"#{min(255,cr+65):02x}{min(255,cg+65):02x}{min(255,cb+65):02x}"
                self._draw_rounded_rect(4, 2, bx2 - 4, min(r + 2, top_h // 2),
                                        max(2, r - 3), shine_c)
            # 轮廓
            if is_active:
                self._draw_rounded_rect_outline(0, 0, bx2, by2, r, ModernColors.ACCENT_CYAN)
                self._draw_rounded_rect_outline(1, 1, bx2 - 1, by2 - 1, r - 1, '#4ABCF0')
            else:
                self._draw_rounded_rect_outline(0, 0, bx2, by2, r, ModernColors.KEY_BORDER)
            tfg = ModernColors.TEXT_BRIGHT if is_active else ModernColors.TEXT_PRIMARY
            kfg = ModernColors.ACCENT_CYAN if is_active else ModernColors.TEXT_DIM
            self.create_text(24, 14, text=self.note_name, fill=tfg,
                             font=('Microsoft YaHei UI', 10))
            self.create_text(24, 32, text=f"[{self.key_char.upper()}]", fill=kfg,
                             font=('Microsoft YaHei UI', 8))
        else:
            w, h = 72, 68
            r = 12
            bx2, by2 = w - 4, h - 4
            if is_active:
                # 多层散光辉光 - 平滑渐变 (lerp 混合背景)
                bg_r = int(ModernColors.BG_CARD[1:3], 16)
                bg_g = int(ModernColors.BG_CARD[3:5], 16)
                bg_b = int(ModernColors.BG_CARD[5:7], 16)
                for off, mix_t in [(9, 0.01), (8, 0.03), (6, 0.07), (4, 0.14), (3, 0.24), (1, 0.36)]:
                    lr = int(bg_r + (cr - bg_r) * mix_t)
                    lg = int(bg_g + (cg - bg_g) * mix_t)
                    lb = int(bg_b + (cb - bg_b) * mix_t)
                    self._draw_rounded_rect(-off, -off, bx2 + off, by2 + off,
                                            r + off, f"#{lr:02x}{lg:02x}{lb:02x}")
            else:
                self._draw_rounded_rect(3, 3, w - 1, h - 1, r, ModernColors.BG_DARK)
            # 主体填充
            self._draw_rounded_rect(0, 0, bx2, by2, r, self.current_color)
            # 渐变覆盖: 上半部分更亮
            top_h = by2 // 2
            bright = 30 if is_active else 8
            top_c = f"#{min(255,cr+bright):02x}{min(255,cg+bright):02x}{min(255,cb+bright):02x}"
            self._draw_rounded_rect(3, 1, bx2 - 3, top_h, max(4, r - 3), top_c)
            # 顶部高光线
            if is_active:
                shine_c = f"#{min(255,cr+55):02x}{min(255,cg+55):02x}{min(255,cb+55):02x}"
                self._draw_rounded_rect(5, 2, bx2 - 5, min(r + 2, top_h // 2),
                                        max(3, r - 4), shine_c)
            # 轮廓
            if is_active:
                self._draw_rounded_rect_outline(0, 0, bx2, by2, r, ModernColors.ACCENT_CYAN)
                self._draw_rounded_rect_outline(1, 1, bx2 - 1, by2 - 1, r - 1, '#4ABCF0')
            else:
                self._draw_rounded_rect_outline(0, 0, bx2, by2, r, ModernColors.KEY_BORDER)
            tfg = ModernColors.TEXT_BRIGHT if is_active else ModernColors.TEXT_PRIMARY
            kfg = ModernColors.ACCENT_CYAN if is_active else ModernColors.TEXT_DIM
            self.create_text(34, 24, text=self.note_name, fill=tfg,
                             font=('Microsoft YaHei UI', 13))
            self.create_text(34, 48, text=f"[{self.key_char.upper()}]", fill=kfg,
                             font=('Microsoft YaHei UI', 9))

    def _draw_rounded_rect(self, x, y, w, h, r, color):
        pts = [x + r, y, w - r, y, w, y, w, y + r, w, h - r, w, h,
               w - r, h, x + r, h, x, h, x, h - r, x, y + r, x, y, x + r, y]
        self.create_polygon(pts, fill=color, smooth=True)

    def _draw_rounded_rect_outline(self, x, y, w, h, r, color):
        pts = [x + r, y, w - r, y, w, y, w, y + r, w, h - r, w, h,
               w - r, h, x + r, h, x, h, x, h - r, x, y + r, x, y, x + r, y]
        self.create_line(pts, fill=color, smooth=True, width=1)

    def _cancel_animations(self):
        if self._highlight_id:
            self.after_cancel(self._highlight_id)
            self._highlight_id = None
        if self._fade_animation_id:
            self.after_cancel(self._fade_animation_id)
            self._fade_animation_id = None

    def highlight(self, duration_ms: int = 180):
        self._cancel_animations()
        self._is_pressed = True
        self._fade_in(duration_ms)

    def _fade_in(self, hold_duration_ms: int):
        start_color = self.current_color
        target_color = ModernColors.KEY_PRESSED
        step = [0]
        def animate():
            if step[0] >= self.FADE_IN_STEPS:
                self.current_color = target_color
                self._draw()
                fade_in_time = self.FADE_IN_STEPS * self.FRAME_DELAY
                fade_out_time = self.FADE_OUT_STEPS * self.FRAME_DELAY
                hold_time = max(0, hold_duration_ms - fade_in_time - fade_out_time)
                self._highlight_id = self.after(hold_time, self._fade_out)
                return
            t = (step[0] + 1) / self.FADE_IN_STEPS
            t = 1 - (1 - t) ** 2
            self.current_color = self._lerp_color(start_color, target_color, t)
            self._draw()
            step[0] += 1
            self._fade_animation_id = self.after(self.FRAME_DELAY, animate)
        animate()

    def _fade_out(self):
        if not self._is_pressed:
            return
        self._is_pressed = False
        start_color = self.current_color
        target_color = self.base_color
        step = [0]
        def animate():
            if step[0] >= self.FADE_OUT_STEPS:
                self.current_color = target_color
                self._draw()
                self._fade_animation_id = None
                return
            t = (step[0] + 1) / self.FADE_OUT_STEPS
            t = t * t * (3 - 2 * t)
            self.current_color = self._lerp_color(start_color, target_color, t)
            self._draw()
            step[0] += 1
            self._fade_animation_id = self.after(self.FRAME_DELAY, animate)
        animate()

    def _restore(self):
        self._fade_out()

    def reset(self):
        self._cancel_animations()
        self._is_pressed = False
        self.current_color = self.base_color
        self._draw()


class PianoKeyboard(tk.Frame):
    """虚拟键盘 - 36键布局（含黑键）"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.keys: Dict[str, PianoKey] = {}
        self._create()

    def _create(self):
        row_labels = ['高音', '中音', '低音']
        row_colors = [ModernColors.ROW_HIGH, ModernColors.ROW_MID_HIGH, ModernColors.ROW_MID]
        for row_idx, (row_name, keys) in enumerate(KEYBOARD_LAYOUT.items()):
            lbl = tk.Label(self, text=row_labels[row_idx], width=5,
                           bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                           font=('Microsoft YaHei UI', 10))
            lbl.grid(row=row_idx * 2, column=0, padx=8, pady=2, rowspan=2)
            for col_idx, key in enumerate(keys):
                note_name = NOTE_NAMES[row_name][col_idx]
                piano_key = PianoKey(self, note_name, key,
                                     row_colors[row_idx],
                                     color_role=('ROW_HIGH', 'ROW_MID_HIGH', 'ROW_MID')[row_idx])
                piano_key.grid(row=row_idx * 2 + 1, column=col_idx + 1, padx=2, pady=2)
                self.keys[key] = piano_key
            black_row_name = f'{row_name}_black'
            if black_row_name in BLACK_KEY_LAYOUT:
                black_keys = BLACK_KEY_LAYOUT[black_row_name]
                black_names = BLACK_KEY_NAMES[black_row_name]
                for col_idx, bkey in enumerate(black_keys):
                    if bkey is not None:
                        bname = black_names[col_idx] if black_names[col_idx] else '♯'
                        piano_key = PianoKey(self, bname, bkey,
                                             ModernColors.KEY_NORMAL, is_black=True,
                                             color_role='KEY_NORMAL')
                        piano_key.grid(row=row_idx * 2, column=col_idx + 1, padx=2, pady=1)
                        self.keys[bkey] = piano_key

    def highlight_key(self, key: str, duration_ms: int = 180):
        key = key.lower()
        if key in self.keys:
            self.keys[key].highlight(duration_ms)

    def reset_all(self):
        for k in self.keys.values():
            k.reset()

    def refresh_theme(self):
        """主题切换后刷新所有按键颜色"""
        for k in self.keys.values():
            k.reset_theme()


# ==================== MiniPianoBar 48键可视化钢琴 ====================
class MiniPianoBar(tk.Frame):
    """60键可视化钢琴键盘 C2-B6 - 实时显示音符"""
    MIDI_START = 36   # C2
    MIDI_END = 95     # B6
    NUM_OCTAVES = 5
    WHITE_NOTES = [0, 2, 4, 5, 7, 9, 11]
    BLACK_NOTES = [1, 3, 6, 8, 10]
    BLACK_POS = [0.58, 1.58, 3.40, 4.40, 5.40]
    MAX_KEY_H = 80    # 琴键最大高度

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.canvas = tk.Canvas(self, bg=ModernColors.PIANO_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self._white_items = {}
        self._black_items = {}
        self._glow_items = {}   # 辉光层
        self._label_items = []
        self._active = {}       # midi -> {remaining_ms, velocity}
        self._decay_running = False
        self.canvas.bind("<Configure>", lambda e: self._build_keys())

    def _build_keys(self):
        self.canvas.delete("all")
        self._white_items.clear()
        self._black_items.clear()
        self._glow_items.clear()
        self._label_items.clear()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        key_h = min(h - 2, self.MAX_KEY_H)
        top_pad = max(1, (h - key_h) // 2)  # 居中
        if w <= 1:
            return
        num_white = self.NUM_OCTAVES * 7
        ww = w / num_white
        bw = ww * 0.62
        bh = key_h * 0.58
        C = ModernColors
        # 白键
        for octave in range(self.NUM_OCTAVES):
            for i, offset in enumerate(self.WHITE_NOTES):
                midi = self.MIDI_START + octave * 12 + offset
                idx = octave * 7 + i
                x1 = idx * ww
                x2 = (idx + 1) * ww - 0.8
                item = self.canvas.create_rectangle(x1, top_pad, x2, top_pad + key_h,
                    fill=C.PIANO_WHITE, outline=C.BORDER, width=0.5)
                self._white_items[midi] = item
        # 黑键
        for octave in range(self.NUM_OCTAVES):
            for offset, bpos in zip(self.BLACK_NOTES, self.BLACK_POS):
                midi = self.MIDI_START + octave * 12 + offset
                cx = (octave * 7 + bpos) * ww + ww / 2
                x1 = cx - bw / 2
                x2 = cx + bw / 2
                item = self.canvas.create_rectangle(x1, top_pad, x2, top_pad + bh,
                    fill=C.PIANO_BLACK, outline=C.PIANO_BG, width=0.5)
                self._black_items[midi] = item
        # 八度标签 + 竖分隔线
        labels = ['C2', 'C3', 'C4', 'C5', 'C6']
        for octave, name in enumerate(labels):
            cx = octave * 7 * ww
            if octave > 0:
                lid = self.canvas.create_line(cx, top_pad, cx, top_pad + key_h,
                                              fill=C.TEXT_DIM, width=1, dash=(2, 3))
                self._label_items.append(lid)
            tid = self.canvas.create_text(cx + 3, top_pad + key_h - 5, text=name,
                                          fill=C.TEXT_DIM, anchor='sw',
                                          font=('Consolas', 7))
            self._label_items.append(tid)

    def note_on(self, midi_note, velocity=1.0, duration_ms=200):
        if midi_note < self.MIDI_START or midi_note > self.MIDI_END:
            return
        v = min(1.0, velocity)
        C = ModernColors
        accent_r = int(C.ACCENT_BLUE[1:3], 16)
        accent_g = int(C.ACCENT_BLUE[3:5], 16)
        accent_b = int(C.ACCENT_BLUE[5:7], 16)
        is_white = midi_note in self._white_items
        item = self._white_items.get(midi_note) or self._black_items.get(midi_note)
        if not item:
            return
        if is_white:
            # 渐变: 白 -> accent (力度越大越蓝)
            base_r = int(C.PIANO_WHITE[1:3], 16)
            base_g = int(C.PIANO_WHITE[3:5], 16)
            base_b = int(C.PIANO_WHITE[5:7], 16)
            cr = int(base_r + (accent_r - base_r) * v * 0.85)
            cg = int(base_g + (accent_g - base_g) * v * 0.85)
            cb = int(base_b + (accent_b - base_b) * v * 0.85)
        else:
            base_r = int(C.PIANO_BLACK[1:3], 16)
            base_g = int(C.PIANO_BLACK[3:5], 16)
            base_b = int(C.PIANO_BLACK[5:7], 16)
            cr = int(base_r + (accent_r - base_r) * v * 0.8)
            cg = int(base_g + (accent_g - base_g) * v * 0.8)
            cb = int(base_b + (accent_b - base_b) * v * 0.8)
        self.canvas.itemconfig(item, fill=f"#{cr:02x}{cg:02x}{cb:02x}",
                               outline=C.ACCENT_CYAN)
        # 散光: 多层漫射辉光 - 平滑渐变边缘 (指数衰减)
        coords = self.canvas.coords(item)
        if coords and len(coords) == 4:
            x1, y1, x2, y2 = coords
            old_layers = self._glow_items.get(midi_note, [])
            for layer in old_layers:
                try:
                    self.canvas.delete(layer[0])
                except Exception:
                    pass
            # 背景色 RGB (用于 lerp 混合)
            bg_r = int(C.PIANO_BG[1:3], 16)
            bg_g = int(C.PIANO_BG[3:5], 16)
            bg_b = int(C.PIANO_BG[5:7], 16)
            glow_layers = []
            # 平滑渐变: 10层指数衰减, 外层几乎不可见, 内层明亮
            _N_GLOW = 10
            _MAX_EXP = 22
            for gi in range(_N_GLOW):
                expand = round(_MAX_EXP - gi * (_MAX_EXP - 1) / (_N_GLOW - 1))
                norm = gi / (_N_GLOW - 1)
                mix_t = 0.01 + 0.57 * (norm ** 2.2)
                t2 = min(1.0, v * mix_t)
                lr = int(bg_r + (accent_r - bg_r) * t2)
                lg = int(bg_g + (accent_g - bg_g) * t2)
                lb = int(bg_b + (accent_b - bg_b) * t2)
                gid = self.canvas.create_oval(
                    x1 - expand, y1 - expand, x2 + expand, y2 + expand,
                    fill=f"#{lr:02x}{lg:02x}{lb:02x}", outline='')
                self.canvas.tag_lower(gid)
                glow_layers.append((gid, accent_r, accent_g, accent_b, bg_r, bg_g, bg_b, mix_t))
            # 底部向下的光滴 - 多层渐变
            for d_expand, d_down, d_mix in [(12, 24, 0.04), (8, 20, 0.10), (4, 16, 0.20), (2, 12, 0.32)]:
                drip_t = min(1.0, v * d_mix)
                dr = int(bg_r + (accent_r - bg_r) * drip_t)
                dg = int(bg_g + (accent_g - bg_g) * drip_t)
                db = int(bg_b + (accent_b - bg_b) * drip_t)
                drip_end = min(y2 + d_down, self.canvas.winfo_height() or y2 + d_down)
                gid_b = self.canvas.create_oval(
                    x1 - d_expand, y2 - 2, x2 + d_expand, drip_end,
                    fill=f"#{dr:02x}{dg:02x}{db:02x}", outline='')
                self.canvas.tag_lower(gid_b)
                glow_layers.append((gid_b, accent_r, accent_g, accent_b, bg_r, bg_g, bg_b, d_mix))
            self._glow_items[midi_note] = glow_layers
        self._active[midi_note] = {
            'remaining': duration_ms, 'original': duration_ms, 'velocity': v,
            'cr': cr, 'cg': cg, 'cb': cb, 'is_white': is_white
        }
        if not self._decay_running:
            self._decay_running = True
            self.after(33, self._tick_decay)

    def _tick_decay(self):
        done = []
        C = ModernColors
        for midi, info in self._active.items():
            info['remaining'] -= 33
            if info['remaining'] <= 0:
                done.append(midi)
            else:
                # 渐变淡出: 从按压颜色插值回基础颜色
                t = info['remaining'] / info['original']  # 1.0=按压 0.0=释放
                if info['is_white']:
                    br, bg_ch, bb = 220, 220, 224
                else:
                    br, bg_ch, bb = 42, 42, 46
                fr = int(br + (info['cr'] - br) * t)
                fg = int(bg_ch + (info['cg'] - bg_ch) * t)
                fb = int(bb + (info['cb'] - bb) * t)
                item = self._white_items.get(midi) or self._black_items.get(midi)
                if item:
                    self.canvas.itemconfig(item, fill=f"#{fr:02x}{fg:02x}{fb:02x}")
                # 散光多层淡出 (与背景色混合)
                glow_layers = self._glow_items.get(midi)
                if glow_layers:
                    try:
                        for layer_data in glow_layers:
                            gid, ar2, ag2, ab2, bgr, bgg, bgb, mix_t0 = layer_data
                            fade_mix = min(1.0, info['velocity'] * mix_t0) * t
                            fr2 = int(bgr + (ar2 - bgr) * fade_mix)
                            fg2 = int(bgg + (ag2 - bgg) * fade_mix)
                            fb2 = int(bgb + (ab2 - bgb) * fade_mix)
                            self.canvas.itemconfig(gid, fill=f"#{fr2:02x}{fg2:02x}{fb2:02x}")
                    except Exception:
                        pass
        for midi in done:
            del self._active[midi]
            if midi in self._white_items:
                self.canvas.itemconfig(self._white_items[midi],
                                       fill=C.PIANO_WHITE, outline=C.BORDER)
            elif midi in self._black_items:
                self.canvas.itemconfig(self._black_items[midi],
                                       fill=C.PIANO_BLACK, outline='#1A1A1E')
            glow_layers = self._glow_items.pop(midi, None)
            if glow_layers:
                for layer in glow_layers:
                    try:
                        self.canvas.delete(layer[0])
                    except Exception:
                        pass
        if self._active:
            self.after(33, self._tick_decay)
        else:
            self._decay_running = False

    def reset(self):
        C = ModernColors
        self._active.clear()
        for item in self._white_items.values():
            self.canvas.itemconfig(item, fill=C.PIANO_WHITE, outline=C.BORDER)
        for item in self._black_items.values():
            self.canvas.itemconfig(item, fill=C.PIANO_BLACK, outline='#1A1A1E')
        for layers in self._glow_items.values():
            for layer in (layers if isinstance(layers, list) else [layers]):
                try:
                    self.canvas.delete(layer[0] if isinstance(layer, tuple) else layer)
                except Exception:
                    pass
        self._glow_items.clear()


class HotkeyButton(tk.Frame):
    """快捷键设置按钮"""
    def __init__(self, parent, label: str, current_key: str,
                 on_change: Callable[[str], None], **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.on_change = on_change
        self.current_key = current_key
        self.is_recording = False
        self._keyboard_hook = None
        self.label = tk.Label(self, text=label, width=10, anchor='w',
                              bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                              font=('Microsoft YaHei UI', 10))
        self.label.pack(side=tk.LEFT, padx=(0, 10))
        self.key_btn = tk.Button(self, text=current_key, width=8,
                                 bg=ModernColors.BG_INPUT, fg=ModernColors.ACCENT_BLUE,
                                 font=('Microsoft YaHei UI', 10, 'bold'),
                                 relief=tk.FLAT, cursor='hand2',
                                 command=self._start_recording)
        self.key_btn.pack(side=tk.LEFT)

    def _start_recording(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.key_btn.configure(text="按键...", fg=ModernColors.ACCENT_ORANGE)
        if GLOBAL_HOTKEY_AVAILABLE:
            try:
                self._keyboard_hook = kb.on_press(self._on_keyboard_press, suppress=False)
            except Exception:
                self._use_tkinter_binding()
        else:
            self._use_tkinter_binding()

    def _use_tkinter_binding(self):
        top = self.winfo_toplevel()
        top.bind('<Key>', self._on_key_press)
        top.focus_force()

    def _on_keyboard_press(self, event):
        if not self.is_recording:
            return
        key_name = event.name
        if key_name.lower() in ('shift', 'ctrl', 'alt', 'left shift', 'right shift',
                                 'left ctrl', 'right ctrl', 'left alt', 'right alt',
                                 'left windows', 'right windows'):
            return
        self._stop_recording(key_name)

    def _on_key_press(self, event):
        if not self.is_recording:
            return
        key_name = event.keysym
        if key_name in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R',
                         'Alt_L', 'Alt_R', 'Win_L', 'Win_R'):
            return
        try:
            self.winfo_toplevel().unbind('<Key>')
        except:
            pass
        self._stop_recording(key_name)

    def _stop_recording(self, key_name: str):
        self.is_recording = False
        self.current_key = key_name
        def update_ui():
            self.key_btn.configure(text=key_name, fg=ModernColors.ACCENT_BLUE)
            if self.on_change:
                self.on_change(key_name)
        if self._keyboard_hook:
            try:
                kb.unhook(self._keyboard_hook)
            except:
                pass
            self._keyboard_hook = None
        try:
            self.after(0, update_ui)
        except:
            update_ui()

    def set_key(self, key: str):
        self.current_key = key
        self.key_btn.configure(text=key)


# ==================== ThemedFilePicker ====================
class ThemedFilePicker(tk.Toplevel):
    """内置主题文件/文件夹选择器 - 避免原生 filedialog 被 topmost 主窗口遮挡"""
    def __init__(self, parent, title="选择文件", mode="file",
                 filetypes=None, initialdir=None):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        C = ModernColors
        self.configure(bg=C.BG_DARK)

        self._mode = mode            # "file" or "dir"
        self._filetypes = filetypes or [("所有文件", "*.*")]
        self._result = None
        self._entries = []           # list of (display, full_path, is_dir)

        # Parse allowed extensions
        self._exts = set()
        for _desc, pattern in self._filetypes:
            for pat in pattern.split():
                if pat.startswith("*.") and pat != "*.*":
                    self._exts.add(pat[1:].lower())  # e.g. ".mid"

        # Initial directory
        if initialdir and os.path.isdir(initialdir):
            self._cwd = initialdir
        else:
            self._cwd = os.path.expanduser("~")

        self._drag_x = 0
        self._drag_y = 0
        self._build_ui(title)
        self._populate()

        # Center on parent
        self.update_idletasks()
        W, H = 540, 440
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - W) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - H) // 2
        except Exception:
            px, py = 200, 150
        self.geometry(f"{W}x{H}+{px}+{py}")
        self.lift()

    def _build_ui(self, title):
        C = ModernColors
        # --- 标题栏 ---
        bar = tk.Frame(self, bg=C.TITLEBAR, height=34)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text=title, bg=C.TITLEBAR, fg=C.TEXT_PRIMARY,
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT, padx=12, pady=7)
        btn_x = tk.Label(bar, text='✕', bg=C.TITLEBAR, fg=C.TEXT_SECONDARY,
                         font=('Segoe UI', 11), cursor='hand2', padx=10)
        btn_x.pack(side=tk.RIGHT)
        btn_x.bind('<Button-1>', lambda e: self._cancel())
        btn_x.bind('<Enter>', lambda e: btn_x.configure(fg='#FF453A'))
        btn_x.bind('<Leave>', lambda e: btn_x.configure(fg=C.TEXT_SECONDARY))
        bar.bind('<ButtonPress-1>', self._start_drag)
        bar.bind('<B1-Motion>', self._do_drag)

        # --- 路径导航栏 ---
        nav = tk.Frame(self, bg=C.BG_CARD, height=30)
        nav.pack(fill=tk.X)
        nav.pack_propagate(False)
        btn_up = tk.Label(nav, text='↑ 上级', bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                          font=('Microsoft YaHei UI', 9), cursor='hand2', padx=10)
        btn_up.pack(side=tk.LEFT, pady=5)
        btn_up.bind('<Button-1>', lambda e: self._go_up())
        btn_up.bind('<Enter>', lambda e: btn_up.configure(fg=C.TEXT_PRIMARY))
        btn_up.bind('<Leave>', lambda e: btn_up.configure(fg=C.TEXT_SECONDARY))
        self._path_lbl = tk.Label(nav, text='', bg=C.BG_CARD, fg=C.TEXT_DIM,
                                   font=('Consolas', 8), anchor='w')
        self._path_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tk.Frame(self, bg=C.BORDER, height=1).pack(fill=tk.X)

        # --- 文件列表 ---
        list_frame = tk.Frame(self, bg=C.BG_DARK)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 4))
        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                          bg=C.BG_HOVER, troughcolor=C.BG_DARK, width=10)
        self._lb = tk.Listbox(list_frame, bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                               selectbackground=C.ACCENT_BLUE, selectforeground='#FFFFFF',
                               activestyle='none', borderwidth=0,
                               highlightthickness=1, highlightbackground=C.BORDER,
                               font=('Microsoft YaHei UI', 9),
                               yscrollcommand=sb.set)
        sb.config(command=self._lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._lb.pack(fill=tk.BOTH, expand=True)
        self._lb.bind('<Double-Button-1>', self._on_double)
        self._lb.bind('<<ListboxSelect>>', self._on_select)
        self._lb.bind('<Return>', self._on_double)

        tk.Frame(self, bg=C.BORDER, height=1).pack(fill=tk.X)

        # --- 底部操作栏 ---
        bot = tk.Frame(self, bg=C.BG_CARD)
        bot.pack(fill=tk.X)
        fname_row = tk.Frame(bot, bg=C.BG_CARD)
        fname_row.pack(fill=tk.X, padx=12, pady=(8, 4))
        tk.Label(fname_row, text='文件名:', bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                 font=('Microsoft YaHei UI', 9), width=5, anchor='w').pack(side=tk.LEFT)
        self._fname_var = tk.StringVar()
        ent = tk.Entry(fname_row, textvariable=self._fname_var,
                       bg=C.BG_HOVER, fg=C.TEXT_PRIMARY,
                       insertbackground=C.TEXT_PRIMARY, relief='flat',
                       font=('Microsoft YaHei UI', 9),
                       highlightthickness=1, highlightbackground=C.BORDER)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        btn_row = tk.Frame(bot, bg=C.BG_CARD)
        btn_row.pack(anchor='e', padx=12, pady=(2, 10))
        tk.Button(btn_row, text='取消', bg=C.BG_HOVER, fg=C.TEXT_SECONDARY,
                  relief='flat', font=('Microsoft YaHei UI', 9),
                  padx=18, pady=5, cursor='hand2',
                  activebackground=C.BORDER,
                  command=self._cancel).pack(side=tk.LEFT, padx=(0, 8))
        ok_text = '选择文件夹' if self._mode == 'dir' else '打开'
        tk.Button(btn_row, text=ok_text, bg=C.ACCENT_BLUE, fg='#FFFFFF',
                  relief='flat', font=('Microsoft YaHei UI', 9, 'bold'),
                  padx=18, pady=5, cursor='hand2',
                  activebackground=C.ACCENT_CYAN,
                  command=self._confirm).pack(side=tk.LEFT)

    def _populate(self):
        self._lb.delete(0, tk.END)
        self._entries.clear()
        self._path_lbl.configure(text=self._cwd)
        try:
            items = sorted(os.listdir(self._cwd), key=lambda x: x.lower())
        except PermissionError:
            return
        dirs, files = [], []
        for name in items:
            full = os.path.join(self._cwd, name)
            if os.path.isdir(full):
                dirs.append((name, full))
            else:
                ext = os.path.splitext(name)[1].lower()
                if self._mode == 'file' and self._exts and ext not in self._exts:
                    continue
                files.append((name, full))
        for name, full in dirs:
            self._entries.append((name, full, True))
            self._lb.insert(tk.END, f"   \U0001f4c1  {name}")
            self._lb.itemconfig(tk.END, fg=ModernColors.ACCENT_CYAN)
        for name, full in files:
            self._entries.append((name, full, False))
            self._lb.insert(tk.END, f"   \U0001f3b5  {name}")

    def _go_up(self):
        parent = os.path.dirname(self._cwd)
        if parent and parent != self._cwd:
            self._cwd = parent
            self._populate()

    def _on_double(self, event=None):
        sel = self._lb.curselection()
        if not sel:
            return
        _, fpath, is_dir = self._entries[sel[0]]
        if is_dir:
            self._cwd = fpath
            self._populate()
        else:
            self._result = fpath
            self.destroy()

    def _on_select(self, event=None):
        sel = self._lb.curselection()
        if not sel:
            return
        _, fpath, is_dir = self._entries[sel[0]]
        if not is_dir:
            self._fname_var.set(os.path.basename(fpath))
        elif self._mode == 'dir':
            self._fname_var.set(os.path.basename(fpath))

    def _confirm(self):
        if self._mode == 'dir':
            sel = self._lb.curselection()
            if sel:
                _, fpath, is_dir = self._entries[sel[0]]
                self._result = fpath if is_dir else self._cwd
            else:
                self._result = self._cwd
        else:
            fname = self._fname_var.get().strip()
            if fname:
                candidate = os.path.join(self._cwd, fname)
                self._result = candidate if os.path.isfile(candidate) else (
                    fname if os.path.isfile(fname) else None)
            if not self._result:
                sel = self._lb.curselection()
                if sel:
                    _, fpath, is_dir = self._entries[sel[0]]
                    if not is_dir:
                        self._result = fpath
        if self._result:
            self.destroy()

    def _cancel(self):
        self._result = None
        self.destroy()

    def _start_drag(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _do_drag(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def get_result(self):
        return self._result


class ControlPanel(tk.Frame):
    """控制面板"""
    def __init__(self, parent, player: MidiPlayer, settings: SettingsManager,
                 on_stop_callback=None, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.player = player
        self.settings = settings
        self.on_stop_callback = on_stop_callback
        self._folder_loop_active = False
        self._folder_loop_files = []
        self._folder_loop_index = 0
        self._create()

    def _create(self):
        # === 第一行：文件 ===
        row1 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row1.pack(fill=tk.X, padx=12, pady=(8, 4))
        self.file_label = tk.Label(row1, text="未选择文件",
                                   bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                   font=('Microsoft YaHei UI', 11), anchor='w')
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.loop_folder_btn = SmoothButton(row1, text="循环文件夹", command=self._toggle_folder_loop,
                                            width=100, height=30, bg=ModernColors.BTN_SECONDARY)
        self.loop_folder_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.open_btn = SmoothButton(row1, text="打开文件", command=self._open_file,
                                     width=80, height=30, bg=ModernColors.BTN_SECONDARY)
        self.open_btn.pack(side=tk.RIGHT)

        # === 第二行：播放控制 ===
        row2 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row2.pack(fill=tk.X, padx=12, pady=4)
        self.play_btn = SmoothButton(row2, text="播放", command=self._toggle_play,
                                     width=100, height=36, bg=ModernColors.BTN_PRIMARY)
        self.play_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.stop_btn = SmoothButton(row2, text="停止", command=self._stop,
                                     width=100, height=36, bg=ModernColors.BTN_SECONDARY)
        self.stop_btn.pack(side=tk.LEFT)
        self.status_label = tk.Label(row2, text="就绪",
                                     bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_BLUE,
                                     font=('Microsoft YaHei UI', 11))
        self.status_label.pack(side=tk.RIGHT)

        # shift_pill / sustain_pill 由外部 _create_ui 创建并注入
        self.shift_pill = None
        self.sustain_pill = None

        # === 第三行：速度 ===
        row3 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row3.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(row3, text="速度", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=self.settings.get('speed', 1.0))
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Modern.Horizontal.TScale",
                         background=ModernColors.BG_CARD,
                         troughcolor=ModernColors.BG_INPUT,
                         sliderthickness=20)
        self.speed_scale = ttk.Scale(row3, from_=0.25, to=2.0, orient=tk.HORIZONTAL,
                                     variable=self.speed_var, command=self._on_speed,
                                     style="Modern.Horizontal.TScale")
        self.speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=15)
        self.speed_label = tk.Label(row3, text=f"{self.speed_var.get():.2f}x", width=6,
                                    bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_BLUE,
                                    font=('Microsoft YaHei UI', 12, 'bold'))
        self.speed_label.pack(side=tk.LEFT)

        # === 第四行：移调 ===
        row4 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row4.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(row4, text="微调", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)
        self.transpose_var = tk.IntVar(value=self.settings.get('transpose', 0))
        self.transpose_spin = tk.Spinbox(row4, from_=-24, to=24, width=5,
                                         textvariable=self.transpose_var,
                                         command=self._on_transpose,
                                         font=('Microsoft YaHei UI', 11),
                                         bg=ModernColors.BG_INPUT, fg=ModernColors.TEXT_PRIMARY,
                                         relief=tk.FLAT, buttonbackground=ModernColors.BG_HOVER)
        self.transpose_spin.pack(side=tk.LEFT, padx=10)
        tk.Label(row4, text="半音", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
        self.auto_btn = SmoothButton(row4, text="重置", command=self._auto_transpose,
                                     width=55, height=28, bg=ModernColors.BTN_SECONDARY, font_size=9)
        self.auto_btn.pack(side=tk.LEFT, padx=15)
        self.octave_offset_label = tk.Label(row4, text="自动:调+0 8度+0", bg=ModernColors.BG_CARD,
                                            fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9))
        self.octave_offset_label.pack(side=tk.LEFT, padx=5)

        # === 第4.5行：音部控制 ===
        row4_5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row4_5.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(row4_5, text="音部", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)
        self.melody_var = tk.BooleanVar(value=True)
        self.melody_check = tk.Checkbutton(row4_5, text="主旋律", variable=self.melody_var,
                                           bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                           selectcolor=ModernColors.BG_INPUT,
                                           activebackground=ModernColors.BG_CARD,
                                           font=('Microsoft YaHei UI', 10),
                                           command=self._on_part_toggle)
        self.melody_check.pack(side=tk.LEFT, padx=(15, 5))
        self.bass_var = tk.BooleanVar(value=True)
        self.bass_check = tk.Checkbutton(row4_5, text="低音部", variable=self.bass_var,
                                         bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                         selectcolor=ModernColors.BG_INPUT,
                                         activebackground=ModernColors.BG_CARD,
                                         font=('Microsoft YaHei UI', 10),
                                         command=self._on_part_toggle)
        self.bass_check.pack(side=tk.LEFT, padx=5)
        tk.Label(row4_5, text="伴奏密度:", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(15, 5))
        self.bass_density_var = tk.DoubleVar(value=1.0)
        self.bass_density_scale = tk.Scale(row4_5, from_=0.2, to=1.0, resolution=0.1,
                                           orient=tk.HORIZONTAL, variable=self.bass_density_var,
                                           bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                           highlightthickness=0, troughcolor=ModernColors.BG_INPUT,
                                           length=80, sliderlength=15, width=12,
                                           command=self._on_bass_density_change)
        self.bass_density_scale.pack(side=tk.LEFT)
        self.bass_density_label = tk.Label(row4_5, text="100%", bg=ModernColors.BG_CARD,
                                           fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9))
        self.bass_density_label.pack(side=tk.LEFT, padx=(2, 0))
        self.part_info_label = tk.Label(row4_5, text="",
                                        bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                        font=('Microsoft YaHei UI', 9))
        self.part_info_label.pack(side=tk.RIGHT)

        # === 第五行：进度条 (GlowProgressBar) ===
        row5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row5.pack(fill=tk.X, padx=12, pady=(4, 2))
        self.progress_bar = GlowProgressBar(row5, height=8)
        self.progress_bar.pack(fill=tk.X, expand=True)
        self.time_label = tk.Label(row5, text="00:00 / 00:00",
                                   bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                   font=('Microsoft YaHei UI', 9))
        self.time_label.pack(pady=(4, 0))

        # === 第5.5行：C调直转 ===
        row5_5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row5_5.pack(fill=tk.X, padx=12, pady=4)
        self.direct_c_var = tk.BooleanVar(value=self.settings.get('direct_c_mode', False))
        self.direct_c_check = tk.Checkbutton(row5_5, text="C调直转", variable=self.direct_c_var,
                                             bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                             selectcolor=ModernColors.BG_INPUT,
                                             activebackground=ModernColors.BG_CARD,
                                             font=('Microsoft YaHei UI', 10, 'bold'),
                                             command=self._on_direct_c_toggle)
        self.direct_c_check.pack(side=tk.LEFT)
        self.direct_c_info_label = tk.Label(row5_5, text="(将任意调直接转换为C大调简谱)",
                                            bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                            font=('Microsoft YaHei UI', 9))
        self.direct_c_info_label.pack(side=tk.LEFT, padx=10)
        self.detected_key_label = tk.Label(row5_5, text="",
                                           bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_BLUE,
                                           font=('Microsoft YaHei UI', 9, 'bold'))
        self.detected_key_label.pack(side=tk.RIGHT)

        # === 第六行：通道 + 选项 ===
        row6 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row6.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.channel_btn = SmoothButton(row6, text="通道设置", command=self._show_channel_settings,
                                        width=90, height=28, bg=ModernColors.BTN_SECONDARY, font_size=9)
        self.channel_btn.pack(side=tk.LEFT)
        self.channel_info_label = tk.Label(row6, text="加载文件后可设置",
                                           bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                           font=('Microsoft YaHei UI', 9))
        self.channel_info_label.pack(side=tk.LEFT, padx=10)
        self.glissando_var = tk.BooleanVar(value=self.settings.get('glissando_enabled', False))
        self.glissando_check = tk.Checkbutton(row6, text="结尾滑奏", variable=self.glissando_var,
                                              bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                              selectcolor=ModernColors.BG_INPUT,
                                              activebackground=ModernColors.BG_CARD,
                                              font=('Microsoft YaHei UI', 9),
                                              command=self._on_glissando_toggle)
        self.glissando_check.pack(side=tk.RIGHT, padx=5)
        self.proficiency_var = tk.BooleanVar(value=self.settings.get('proficiency_enabled', True))
        self.proficiency_check = tk.Checkbutton(row6, text="熟练度", variable=self.proficiency_var,
                                                bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                                selectcolor=ModernColors.BG_INPUT,
                                                activebackground=ModernColors.BG_CARD,
                                                font=('Microsoft YaHei UI', 9),
                                                command=self._on_proficiency_toggle)
        self.proficiency_check.pack(side=tk.RIGHT, padx=5)
        self.proficiency_label = tk.Label(row6, text="熟练度: --",
                                          bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_GREEN,
                                          font=('Microsoft YaHei UI', 9))
        self.proficiency_label.pack(side=tk.RIGHT, padx=5)

        # === 初始化播放器设置 ===
        self.player._play_ending_glissando = self.glissando_var.get()
        self.player.set_proficiency_enabled(self.proficiency_var.get())
        self.player._direct_c_mode = self.direct_c_var.get()
        saved_density = self.settings.get('bass_density', 1.0)
        self.bass_density_var.set(saved_density)
        self.bass_density_label.configure(text=f"{saved_density:.0%}")
        self.player.set_bass_density(saved_density)

    def _show_channel_settings(self):
        if not self.player.parser.notes:
            ThemedDialog.showwarning(self.winfo_toplevel(), "提示", "请先加载MIDI文件")
            return
        channels_info = self.player.parser.get_channels_info()
        if not channels_info:
            ThemedDialog.showinfo(self.winfo_toplevel(), "提示", "该MIDI文件没有音符数据")
            return
        dialog = tk.Toplevel(self)
        dialog.title("通道设置")
        dialog.geometry("450x400")
        dialog.configure(bg=ModernColors.BG_DARK)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        title = tk.Label(dialog, text="分通道移调设置", bg=ModernColors.BG_DARK,
                         fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 14, 'bold'))
        title.pack(pady=15)
        hint = tk.Label(dialog, text="为每个MIDI通道单独设置移调值，可以禁用不需要的通道",
                        bg=ModernColors.BG_DARK, fg=ModernColors.TEXT_SECONDARY,
                        font=('Microsoft YaHei UI', 9))
        hint.pack(pady=(0, 10))
        canvas = tk.Canvas(dialog, bg=ModernColors.BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=ModernColors.BG_DARK)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        channel_vars = {}
        for ch in sorted(channels_info.keys()):
            info = channels_info[ch]
            frame = tk.Frame(scroll_frame, bg=ModernColors.BG_CARD)
            frame.pack(fill=tk.X, pady=5, padx=5)
            enabled_var = tk.BooleanVar(value=self.player.mapper.is_channel_enabled(ch))
            enabled_cb = tk.Checkbutton(frame, text=f"CH{ch}", variable=enabled_var,
                                        bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                        selectcolor=ModernColors.BG_INPUT,
                                        font=('Microsoft YaHei UI', 10, 'bold'), width=5)
            enabled_cb.pack(side=tk.LEFT, padx=5)
            note_range = info['note_range']
            info_text = f"音符: {info['note_count']}个  范围: {note_range[0]}-{note_range[1]}"
            info_label = tk.Label(frame, text=info_text, bg=ModernColors.BG_CARD,
                                  fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9),
                                  width=25, anchor='w')
            info_label.pack(side=tk.LEFT, padx=5)
            tk.Label(frame, text="移调:", bg=ModernColors.BG_CARD,
                     fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
            transpose_var = tk.IntVar(value=self.player.mapper.get_channel_transpose(ch))
            transpose_spin = tk.Spinbox(frame, from_=-48, to=48, width=4,
                                        textvariable=transpose_var,
                                        font=('Microsoft YaHei UI', 10),
                                        bg=ModernColors.BG_INPUT, fg=ModernColors.TEXT_PRIMARY,
                                        relief=tk.FLAT)
            transpose_spin.pack(side=tk.LEFT, padx=5)
            def auto_suggest(channel=ch, var=transpose_var, info=info):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    avg_note = info['avg_note']
                    if avg_note >= 72:
                        target = 'high'
                    elif avg_note >= 60:
                        target = 'mid'
                    else:
                        target = 'low'
                    suggested = self.player.mapper.suggest_channel_transpose(notes, target)
                    var.set(suggested)
            auto_btn = tk.Button(frame, text="自动", command=auto_suggest,
                                 bg=ModernColors.BTN_SECONDARY, fg=ModernColors.TEXT_BRIGHT,
                                 font=('Microsoft YaHei UI', 8), relief=tk.FLAT, padx=5, pady=2)
            auto_btn.pack(side=tk.LEFT, padx=5)
            def set_high(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    var.set(self.player.mapper.suggest_channel_transpose(notes, 'high'))
            def set_mid(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    var.set(self.player.mapper.suggest_channel_transpose(notes, 'mid'))
            def set_low(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    var.set(self.player.mapper.suggest_channel_transpose(notes, 'low'))
            tk.Button(frame, text="高", command=set_high, bg=ModernColors.ACCENT_RED,
                      fg=ModernColors.TEXT_BRIGHT, font=('Microsoft YaHei UI', 7),
                      relief=tk.FLAT, width=2).pack(side=tk.LEFT, padx=1)
            tk.Button(frame, text="中", command=set_mid, bg=ModernColors.ACCENT_BLUE,
                      fg=ModernColors.TEXT_BRIGHT, font=('Microsoft YaHei UI', 7),
                      relief=tk.FLAT, width=2).pack(side=tk.LEFT, padx=1)
            tk.Button(frame, text="低", command=set_low, bg=ModernColors.ACCENT_GREEN,
                      fg=ModernColors.TEXT_BRIGHT, font=('Microsoft YaHei UI', 7),
                      relief=tk.FLAT, width=2).pack(side=tk.LEFT, padx=1)
            channel_vars[ch] = {'enabled': enabled_var, 'transpose': transpose_var}
        btn_frame = tk.Frame(dialog, bg=ModernColors.BG_DARK)
        btn_frame.pack(fill=tk.X, pady=15, padx=20)
        def apply_settings():
            for ch, vars in channel_vars.items():
                self.player.mapper.set_channel_enabled(ch, vars['enabled'].get())
                self.player.mapper.set_channel_transpose(ch, vars['transpose'].get())
            ch_settings = {}
            for ch, vars in channel_vars.items():
                ch_settings[str(ch)] = {
                    'enabled': vars['enabled'].get(),
                    'transpose': vars['transpose'].get()
                }
            self.settings.set('channel_settings', ch_settings)
            enabled_count = sum(1 for ch in channel_vars if channel_vars[ch]['enabled'].get())
            total_count = len(channel_vars)
            self.channel_info_label.configure(text=f"已启用 {enabled_count}/{total_count} 个通道")
            dialog.destroy()
            ThemedDialog.showinfo(self.winfo_toplevel(), "完成", "通道设置已应用并保存")
        def reset_all():
            self.player.mapper.clear_channel_settings()
            for ch, vars in channel_vars.items():
                vars['enabled'].set(True)
                vars['transpose'].set(self.player.mapper.transpose)
        apply_btn = SmoothButton(btn_frame, text="应用", command=apply_settings,
                                 width=80, height=32, bg=ModernColors.BTN_PRIMARY, font_size=10)
        apply_btn.pack(side=tk.RIGHT, padx=5)
        reset_btn = SmoothButton(btn_frame, text="重置", command=reset_all,
                                 width=80, height=32, bg=ModernColors.BTN_SECONDARY, font_size=10)
        reset_btn.pack(side=tk.RIGHT, padx=5)

    def _ask_open_file(self):
        """内置主题文件选择器"""
        last = self.settings.get('last_file', '')
        initialdir = os.path.dirname(last) if last and os.path.exists(os.path.dirname(last)) else os.path.expanduser('~')
        picker = ThemedFilePicker(
            parent=self.winfo_toplevel(),
            title="选择 MIDI / JS 文件",
            mode="file",
            filetypes=[("支持的文件", "*.mid *.midi *.js")],
            initialdir=initialdir
        )
        self.wait_window(picker)
        return picker.get_result()

    def _ask_directory(self):
        """内置主题文件夹选择器"""
        last_folder = self.settings.get('last_folder', '')
        initialdir = last_folder if last_folder and os.path.isdir(last_folder) else os.path.expanduser('~')
        picker = ThemedFilePicker(
            parent=self.winfo_toplevel(),
            title="选择循环播放的文件夹",
            mode="dir",
            initialdir=initialdir
        )
        self.wait_window(picker)
        return picker.get_result()

    def _open_file(self):
        filepath = self._ask_open_file()
        if filepath:
            if self.player.load_midi(filepath):
                self.file_label.configure(text=os.path.basename(filepath),
                                          fg=ModernColors.TEXT_PRIMARY)
                self.transpose_var.set(0)
                self.player.set_transpose(0)
                self.settings.set('last_file', filepath)
                self.player.mapper.clear_channel_settings()
                saved_ch = self.settings.get('channel_settings', {})
                if saved_ch:
                    for ch_str, ch_cfg in saved_ch.items():
                        ch = int(ch_str)
                        self.player.mapper.set_channel_enabled(ch, ch_cfg.get('enabled', True))
                        self.player.mapper.set_channel_transpose(ch, ch_cfg.get('transpose', 0))
                coverage = self.player.get_coverage_info()
                chord_info = self.player.get_chord_info()
                if hasattr(self.player.parser, 'get_channels_info'):
                    channels_info = self.player.parser.get_channels_info()
                else:
                    channels_info = {}
                if hasattr(self.player.parser, 'get_bpm'):
                    bpm = self.player.parser.get_bpm()
                else:
                    bpm = self.player.parser.bpm
                if hasattr(self.player.parser, 'get_tempo_changes'):
                    tempo_changes = len(self.player.parser.get_tempo_changes())
                else:
                    tempo_changes = 0
                channel_count = len(channels_info)
                self.channel_info_label.configure(text=f"共 {channel_count} 个通道")
                instrument_info = self.player.parser.get_instrument_info()
                msg = f"加载成功\n\n"
                msg += f"BPM: {bpm:.1f}"
                if tempo_changes > 1:
                    msg += f" (有 {tempo_changes} 次变速)"
                msg += f"\n"
                msg += f"音符数: {coverage['total']}\n"
                msg += f"可播放: {coverage['mapped']} ({coverage['coverage']*100:.1f}%)\n"
                msg += f"和弦数: {chord_info['chord_count']}\n"
                msg += f"通道数: {channel_count}\n"
                notes = self.player.parser.notes
                if notes:
                    vels = [n.velocity for n in notes]
                    avg_vel = sum(vels) / len(vels)
                    msg += f"力度范围: {min(vels)}-{max(vels)} (均值{avg_vel:.0f})\n"
                if instrument_info:
                    msg += f"\n乐器:\n"
                    for ch, info in list(instrument_info.items())[:3]:
                        name = info.get('name', f'Program {info.get("program", 0)}') if isinstance(info, dict) else info
                        msg += f"  Ch{ch}: {name}\n"
                    if len(instrument_info) > 3:
                        msg += f"  ...等 {len(instrument_info)} 种乐器\n"
                key_transpose = getattr(self.player, '_key_transpose', 0)
                octave_offset = getattr(self.player, '_octave_offset', 0)
                msg += f"\n自动调性: {key_transpose:+d}半音, 8度偏移: {octave_offset:+d}"
                if self.direct_c_var.get():
                    self.player.set_direct_c_mode(True, save=False)
                    self._update_direct_c_display()
                    direct_c_info = self.player.get_direct_c_info()
                    key_name = direct_c_info['detected_key_name']
                    mode = '大调' if direct_c_info['detected_mode'] == 'major' else '小调'
                    msg += f"\n\nC调直转: 检测到 {key_name} {mode}\n   (传统移调已禁用)"
                else:
                    self._update_direct_c_display()
                self._update_proficiency_label()
                proficiency_info = self.player.get_proficiency_info()
                msg += f"\n熟练度: {proficiency_info['proficiency']*100:.0f}% (已弹{proficiency_info['play_count']}次)"
                self._update_pitch_analysis()
                pitch_info = self.player.parser.get_pitch_analysis()
                if pitch_info.get('melody_count', 0) > 0 or pitch_info.get('bass_count', 0) > 0:
                    msg += f"\n\n音部分析:"
                    msg += f"\n  主旋律: {pitch_info.get('melody_count', 0)} 音符"
                    msg += f"\n  低音部: {pitch_info.get('bass_count', 0)} 音符"
                    if pitch_info.get('recommend_melody_only'):
                        msg += f"\n  高低音撕裂严重，已自动关闭低音"
                ThemedDialog.showinfo(self.winfo_toplevel(), "文件信息", msg)
                if self.on_stop_callback:
                    self.winfo_toplevel().after(100, self.on_stop_callback)
            else:
                ThemedDialog.showerror(self.winfo_toplevel(), "错误", "无法加载文件")
                if self.on_stop_callback:
                    self.winfo_toplevel().after(100, self.on_stop_callback)

    def _toggle_folder_loop(self):
        if self._folder_loop_active:
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self.loop_folder_btn.set_text("循环文件夹")
            self.loop_folder_btn.set_bg(ModernColors.BTN_SECONDARY)
            self.player.stop()
            self.play_btn.set_text("播放")
            self.status_label.configure(text="已停止循环")
            if self.on_stop_callback:
                self.on_stop_callback()
        else:
            folder = self._ask_directory()
            if not folder:
                return
            self.settings.set('last_folder', folder)
            files = sorted([
                os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith(('.mid', '.midi', '.js'))
                and os.path.isfile(os.path.join(folder, f))
            ])
            if not files:
                ThemedDialog.showinfo(self.winfo_toplevel(), "提示", "该文件夹下没有 MIDI / JS 文件")
                return
            self._folder_loop_files = files
            self._folder_loop_index = 0
            self._folder_loop_active = True
            self.loop_folder_btn.set_text("停止循环")
            self.loop_folder_btn.set_bg(ModernColors.BTN_DANGER)
            self._play_next_folder_song()

    def _play_next_folder_song(self, _retries=0):
        if not self._folder_loop_active or not self._folder_loop_files:
            return
        if _retries >= len(self._folder_loop_files):
            self._toggle_folder_loop()
            ThemedDialog.showerror(self.winfo_toplevel(), "错误", "文件夹中所有文件加载失败，已停止循环")
            return
        filepath = self._folder_loop_files[self._folder_loop_index]
        self._folder_loop_index = (self._folder_loop_index + 1) % len(self._folder_loop_files)
        if self.player.load_midi(filepath):
            self.file_label.configure(text=os.path.basename(filepath), fg=ModernColors.TEXT_PRIMARY)
            self.transpose_var.set(0)
            self.player.set_transpose(0)
            self.player.mapper.clear_channel_settings()
            if self.direct_c_var.get():
                self.player.set_direct_c_mode(True, save=False)
            self.player.play()
            self.play_btn.set_text("暂停")
            self.status_label.configure(text=f"循环: {os.path.basename(filepath)}")
        else:
            self._play_next_folder_song(_retries + 1)

    def _toggle_play(self):
        state = self.player.get_state()
        if state.is_playing and not state.is_paused:
            self.player.pause()
            self.play_btn.set_text("继续")
            self.status_label.configure(text="已暂停")
        elif state.is_paused:
            self.player.resume()
            self.play_btn.set_text("暂停")
            self.status_label.configure(text="播放中")
        else:
            self.player.play()
            self.play_btn.set_text("暂停")
            self.status_label.configure(text="播放中")

    def _stop(self):
        if self._folder_loop_active:
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self.loop_folder_btn.set_text("循环文件夹")
            self.loop_folder_btn.set_bg(ModernColors.BTN_SECONDARY)
        self.player.stop()
        self.play_btn.set_text("播放")
        self.progress_bar.set(0)
        self.time_label.configure(text="00:00 / 00:00")
        self.status_label.configure(text="已停止")
        if self.on_stop_callback:
            self.on_stop_callback()

    def _on_speed(self, val):
        speed = float(val)
        self.player.set_speed(speed)
        self.speed_label.configure(text=f"{speed:.2f}x")
        self.settings.set('speed', speed)

    def _on_transpose(self):
        try:
            val = self.transpose_var.get()
            self.player.set_transpose(val)
            self.settings.set('transpose', val)
        except:
            pass

    def _auto_transpose(self):
        if not self.player.parser.notes:
            ThemedDialog.showwarning(self.winfo_toplevel(), "提示", "请先加载文件")
            return
        self.player._analyze_and_setup_mapping()
        key_transpose = getattr(self.player, '_key_transpose', 0)
        octave_offset = getattr(self.player, '_octave_offset', 0)
        self.transpose_var.set(0)
        self.player.set_transpose(0)
        self._update_octave_offset_label()
        coverage = self.player.get_coverage_info()
        ThemedDialog.showinfo(self.winfo_toplevel(), "自动调整",
            f"调性移调: {key_transpose:+d} 半音\n八度偏移: {octave_offset:+d}\n"
            f"用户移调: 0\n覆盖率: {coverage['coverage']*100:.1f}%")

    def _on_direct_c_toggle(self):
        val = self.direct_c_var.get()
        if not self.player.parser.notes:
            if val:
                ThemedDialog.showwarning(self.winfo_toplevel(), "提示", "请先加载MIDI文件")
                self.direct_c_var.set(False)
            return
        self.player.set_direct_c_mode(val)
        self.settings.set('direct_c_mode', val)
        self._update_direct_c_display()
        if val:
            info = self.player.get_direct_c_info()
            key_name = info['detected_key_name']
            mode = '大调' if info['detected_mode'] == 'major' else '小调'
            ThemedDialog.showinfo(self.winfo_toplevel(), "C调直转模式",
                f"已启用C调直转模式\n\n"
                f"检测到原曲调性: {key_name} {mode}\n"
                f"所有音符将按音级直接映射到C大调\n\n"
                f"传统移调方式已暂停\n低音部分将用和弦键替代\n微调功能仍然可用")
        else:
            self._update_octave_offset_label()

    def _update_direct_c_display(self):
        if self.player.is_direct_c_mode():
            info = self.player.get_direct_c_info()
            key_name = info['detected_key_name']
            mode = '大调' if info['detected_mode'] == 'major' else '小调'
            confidence = info.get('confidence', 0.0)
            if confidence >= 0.8:
                conf_text = "★★★"
            elif confidence >= 0.6:
                conf_text = "★★☆"
            elif confidence >= 0.4:
                conf_text = "★☆☆"
            else:
                conf_text = "☆☆☆"
            self.detected_key_label.configure(text=f"原调: {key_name} {mode} {conf_text}",
                                              fg=ModernColors.ACCENT_GREEN)
            self.direct_c_info_label.configure(text=f"(已启用 - 置信度{confidence:.1%})",
                                               fg=ModernColors.ACCENT_GREEN)
            self.octave_offset_label.configure(text="C调直转模式")
        else:
            self.detected_key_label.configure(text="")
            self.direct_c_info_label.configure(text="(将任意调直接转换为C大调简谱)",
                                               fg=ModernColors.TEXT_SECONDARY)
            self._update_octave_offset_label()

    def _on_part_toggle(self):
        play_melody = self.melody_var.get()
        play_bass = self.bass_var.get()
        if not play_melody and not play_bass:
            self.melody_var.set(True)
            play_melody = True
            ThemedDialog.showwarning(self.winfo_toplevel(), "提示", "至少需要选择一个音部")
        self.player.set_part_filter(play_melody, play_bass)
        self.player._analyze_and_setup_mapping()
        info = self.player.parser.get_pitch_analysis() if self.player.parser.notes else {}
        melody_count = info.get('melody_count', 0)
        bass_count = info.get('bass_count', 0)
        if play_melody and play_bass:
            self.part_info_label.configure(text=f"全部 (旋律{melody_count}+低音{bass_count})",
                                           fg=ModernColors.TEXT_SECONDARY)
        elif play_melody:
            self.part_info_label.configure(text=f"仅旋律 ({melody_count}音符)",
                                           fg=ModernColors.ACCENT_GREEN)
        else:
            self.part_info_label.configure(text=f"仅低音 ({bass_count}音符)",
                                           fg=ModernColors.ACCENT_ORANGE)

    def _on_bass_density_change(self, value):
        density = float(value)
        self.player.set_bass_density(density)
        self.bass_density_label.configure(text=f"{density:.0%}")
        self.settings.set('bass_density', density)

    def _on_glissando_toggle(self):
        val = self.glissando_var.get()
        self.player._play_ending_glissando = val
        self.settings.set('glissando_enabled', val)

    def _on_proficiency_toggle(self):
        val = self.proficiency_var.get()
        self.player.set_proficiency_enabled(val)
        self.settings.set('proficiency_enabled', val)

    def _update_proficiency_label(self):
        info = self.player.get_proficiency_info()
        play_count = info['play_count']
        proficiency = info['proficiency']
        if play_count == 0:
            self.proficiency_label.configure(text="熟练度: 新曲", fg=ModernColors.ACCENT_RED)
        elif proficiency >= 0.95:
            self.proficiency_label.configure(text=f"熟练度: {proficiency*100:.0f}%", fg=ModernColors.ACCENT_GREEN)
        elif proficiency >= 0.5:
            self.proficiency_label.configure(text=f"熟练度: {proficiency*100:.0f}%", fg=ModernColors.ACCENT_ORANGE)
        else:
            self.proficiency_label.configure(text=f"熟练度: {proficiency*100:.0f}%", fg=ModernColors.ACCENT_RED)

    def _update_pitch_analysis(self):
        if not self.player.parser.notes:
            self.part_info_label.configure(text="")
            return
        info = self.player.parser.get_pitch_analysis()
        melody_count = info.get('melody_count', 0)
        bass_count = info.get('bass_count', 0)
        recommend = info.get('recommend_melody_only', False)
        if recommend:
            self.part_info_label.configure(text=f"撕裂严重 推荐关低音", fg=ModernColors.ACCENT_RED)
            self.bass_var.set(False)
            self._on_part_toggle()
        else:
            self.part_info_label.configure(text=f"旋律{melody_count} 低音{bass_count}",
                                           fg=ModernColors.TEXT_SECONDARY)
            if not self.bass_var.get():
                self.bass_var.set(True)
                self._on_part_toggle()
        self._update_octave_offset_label()

    def _update_octave_offset_label(self):
        octave_offset = getattr(self.player, '_octave_offset', 0)
        key_transpose = getattr(self.player, '_key_transpose', 0)
        self.octave_offset_label.configure(text=f"自动:调{key_transpose:+d} 8度{octave_offset:+d}")

    def update_shift_state(self, is_shift: bool):
        if self.shift_pill:
            if is_shift:
                self.shift_pill.set_active(True, "SHIFT 模式")
            else:
                self.shift_pill.set_active(False, "普通模式")

    def update_sustain_state(self, is_on: bool):
        if self.sustain_pill:
            if is_on:
                self.sustain_pill.set_active(True, "延音 加长")
            else:
                self.sustain_pill.set_active(False, "延音 正常")

    def update_progress(self, current: float, total: float):
        if total > 0:
            self.progress_bar.set((current / total) * 100)
        c_str = f"{int(current // 60):02d}:{int(current % 60):02d}"
        t_str = f"{int(total // 60):02d}:{int(total % 60):02d}"
        self.time_label.configure(text=f"{c_str} / {t_str}")

    def on_playback_end(self):
        self.play_btn.set_text("播放")
        self.progress_bar.set(0)
        self.status_label.configure(text="播放完成")
        self.update_shift_state(False)
        self.update_sustain_state(False)

    def speed_up(self):
        current = self.speed_var.get()
        new_speed = min(2.0, current + 0.25)
        self.speed_var.set(new_speed)
        self._on_speed(new_speed)

    def speed_down(self):
        current = self.speed_var.get()
        new_speed = max(0.25, current - 0.25)
        self.speed_var.set(new_speed)
        self._on_speed(new_speed)


class HotkeyPanel(tk.Frame):
    """快捷键设置面板 - 使用pynput独立监控"""
    def __init__(self, parent, settings: SettingsManager,
                 callbacks: Dict[str, Callable], **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.settings = settings
        self.callbacks = callbacks
        self.hotkey_widgets = {}
        self._registered_hotkeys = {}
        self._pressed_keys = set()
        self._listener = None
        self._listener_thread = None
        self._running = True
        self._create()

    def _create(self):
        title = tk.Label(self, text="快捷键", bg=ModernColors.BG_CARD,
                         fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 11, 'bold'))
        title.pack(pady=(8, 8))
        hotkey_defs = [
            ('play_pause', '播放/暂停'),
            ('stop', '停止'),
            ('speed_up', '加速'),
            ('speed_down', '减速'),
            ('toggle_topmost', '置顶切换'),
        ]
        hotkeys = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        for key_id, label in hotkey_defs:
            current_key = hotkeys.get(key_id, DEFAULT_HOTKEYS.get(key_id, ''))
            widget = HotkeyButton(self, label, current_key,
                                  lambda k, kid=key_id: self._on_hotkey_change(kid, k))
            widget.pack(fill=tk.X, padx=15, pady=3)
            self.hotkey_widgets[key_id] = widget
        reset_btn = SmoothButton(self, text="重置默认", command=self._reset_hotkeys,
                                 width=80, height=26, bg=ModernColors.BTN_SECONDARY, font_size=8)
        reset_btn.pack(pady=6)
        tip = tk.Label(self, text="点击按键框后按下新快捷键\n全局快捷键在窗口外也有效",
                       bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                       font=('Microsoft YaHei UI', 8), justify=tk.CENTER)
        tip.pack(pady=(0, 6))
        self._register_global_hotkeys()

    def _on_hotkey_change(self, key_id: str, new_key: str):
        hotkeys = self.settings.get('hotkeys', {})
        hotkeys[key_id] = new_key
        self.settings.set('hotkeys', hotkeys)
        self._register_global_hotkeys()

    def _reset_hotkeys(self):
        self.settings.set('hotkeys', DEFAULT_HOTKEYS.copy())
        for key_id, widget in self.hotkey_widgets.items():
            widget.set_key(DEFAULT_HOTKEYS.get(key_id, ''))
        self._register_global_hotkeys()
        ThemedDialog.showinfo(self.winfo_toplevel(), "提示", "已重置为默认快捷键")

    def _normalize_key_name(self, key) -> str:
        if PYNPUT_HOTKEY_AVAILABLE:
            if isinstance(key, Key):
                key_map = {
                    Key.ctrl_l: 'ctrl', Key.ctrl_r: 'ctrl',
                    Key.alt_l: 'alt', Key.alt_r: 'alt',
                    Key.shift_l: 'shift', Key.shift_r: 'shift',
                    Key.space: 'space', Key.enter: 'enter',
                    Key.tab: 'tab', Key.esc: 'esc',
                    Key.backspace: 'backspace', Key.delete: 'delete',
                    Key.up: 'up', Key.down: 'down', Key.left: 'left', Key.right: 'right',
                    Key.home: 'home', Key.end: 'end',
                    Key.page_up: 'page up', Key.page_down: 'page down',
                    Key.f1: 'f1', Key.f2: 'f2', Key.f3: 'f3', Key.f4: 'f4',
                    Key.f5: 'f5', Key.f6: 'f6', Key.f7: 'f7', Key.f8: 'f8',
                    Key.f9: 'f9', Key.f10: 'f10', Key.f11: 'f11', Key.f12: 'f12',
                }
                return key_map.get(key, key.name if hasattr(key, 'name') else str(key))
            elif isinstance(key, KeyCode):
                if key.char:
                    return key.char.lower()
                elif key.vk:
                    return f'<{key.vk}>'
        return str(key).lower()

    def _get_current_hotkey_str(self) -> str:
        if not self._pressed_keys:
            return ''
        modifiers = []
        regular_keys = []
        for key in self._pressed_keys:
            key_lower = key.lower()
            if key_lower in ('ctrl', 'alt', 'shift'):
                modifiers.append(key_lower)
            else:
                regular_keys.append(key_lower)
        mod_order = {'ctrl': 0, 'alt': 1, 'shift': 2}
        modifiers.sort(key=lambda x: mod_order.get(x, 99))
        parts = modifiers + regular_keys
        return '+'.join(parts)

    def _on_key_press(self, key):
        if not self._running:
            return
        key_name = self._normalize_key_name(key)
        if key_name and not key_name.startswith('<'):
            self._pressed_keys.add(key_name)
            current_combo = self._get_current_hotkey_str()
            if current_combo in self._registered_hotkeys:
                callback = self._registered_hotkeys[current_combo]
                try:
                    self.after(0, callback)
                except:
                    pass

    def _on_key_release(self, key):
        if not self._running:
            return
        key_name = self._normalize_key_name(key)
        self._pressed_keys.discard(key_name)

    def _register_global_hotkeys(self):
        if not GLOBAL_HOTKEY_AVAILABLE:
            return
        self._registered_hotkeys = {}
        hotkeys = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        for key_id, key in hotkeys.items():
            if key and key_id in self.callbacks:
                normalized = '+'.join(sorted(key.lower().split('+'),
                    key=lambda x: {'ctrl': 0, 'alt': 1, 'shift': 2}.get(x, 99)))
                self._registered_hotkeys[normalized] = self.callbacks[key_id]
        if PYNPUT_HOTKEY_AVAILABLE and self._listener is None:
            self._start_pynput_listener()

    def _start_pynput_listener(self):
        if not PYNPUT_HOTKEY_AVAILABLE:
            return
        self._stop_pynput_listener()
        self._running = True
        self._pressed_keys = set()
        try:
            self._listener = pynput_kb.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release
            )
            self._listener.start()
        except Exception as e:
            print(f"[快捷键] pynput监听器启动失败: {e}")
            self._listener = None

    def _stop_pynput_listener(self):
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except:
                pass
            self._listener = None

    def _unregister_global_hotkeys(self):
        self._stop_pynput_listener()
        self._registered_hotkeys = {}

    def cleanup(self):
        self._unregister_global_hotkeys()


# ==================== MidiVisualizer 增强版 ====================
class MidiVisualizer(tk.Frame):
    """MIDI可视化 - 竖向柱状图 + 镜像波形 + 背景网格"""
    NUM_BARS = 36
    BAR_DECAY = 0.90
    UPDATE_INTERVAL = 33

    KEY_TO_BAR = {
        'z': 0, '1': 1, 'x': 2, '2': 3, 'c': 4, 'v': 5,
        '3': 6, 'b': 7, '4': 8, 'n': 9, '5': 10, 'm': 11,
        'a': 12, '6': 13, 's': 14, '7': 15, 'd': 16, 'f': 17,
        '8': 18, 'g': 19, '9': 20, 'h': 21, '0': 22, 'j': 23,
        'q': 24, 'i': 25, 'w': 26, 'o': 27, 'e': 28, 'r': 29,
        'p': 30, 't': 31, '[': 32, 'y': 33, ']': 34, 'u': 35,
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self._bar_values = [0.0] * self.NUM_BARS
        self._bar_peaks = [0.0] * self.NUM_BARS
        self._wave_history = []
        self._running = False
        self._mode = 'bar'
        self._colors = self._generate_colors()       # fallback static colors
        self._glow_colors = self._generate_glow_colors()
        # --- 色彩动画 ---
        self._hue_offset = 0.0        # 慢速旋转色调 (0-360)
        self._beat_bright = 0.0       # 节拍亮度脉冲 (0-1)
        self._bpm = 0.0               # 当前BPM估算
        self._bpm_times: list = []    # 最近音符时间戳
        self._history_tick = 0        # 用于限速捕捉历史帧

        top_bar = tk.Frame(self, bg=ModernColors.BG_CARD)
        top_bar.pack(fill=tk.X, padx=8, pady=(6, 2))
        tk.Label(top_bar, text="可视化", bg=ModernColors.BG_CARD,
                 fg=ModernColors.TEXT_DIM, font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT)
        self._mode_btn = SmoothButton(top_bar, text="柱状图", width=56, height=22,
                                       bg=ModernColors.BG_HOVER,
                                       font_size=8, command=self._toggle_mode)
        self._mode_btn.pack(side=tk.RIGHT)
        self._note_label = tk.Label(top_bar, text="", bg=ModernColors.BG_CARD,
                                    fg=ModernColors.ACCENT_CYAN, font=('Consolas', 9))
        self._note_label.pack(side=tk.RIGHT, padx=(0, 8))

        self.canvas = tk.Canvas(self, bg=ModernColors.VIZ_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))

    def _generate_colors(self):
        colors = []
        for i in range(self.NUM_BARS):
            ratio = i / (self.NUM_BARS - 1) if self.NUM_BARS > 1 else 0
            if ratio < 0.33:
                t = ratio / 0.33
                r = int(0x30 + (0x32 - 0x30) * t)
                g = int(0xD1 + (0xD2 - 0xD1) * t)
                b = int(0x58 + (0xFF - 0x58) * t)
            elif ratio < 0.66:
                t = (ratio - 0.33) / 0.33
                r = int(0x32 + (0x0A - 0x32) * t)
                g = int(0xD2 + (0x84 - 0xD2) * t)
                b = 0xFF
            else:
                t = (ratio - 0.66) / 0.34
                r = int(0x0A + (0xBF - 0x0A) * t)
                g = int(0x84 + (0x5A - 0x84) * t)
                b = int(0xFF + (0xF2 - 0xFF) * t)
            r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
        return colors

    def _generate_glow_colors(self):
        glow = []
        for c in self._colors:
            r = min(255, int(c[1:3], 16) + 60)
            g = min(255, int(c[3:5], 16) + 60)
            b = min(255, int(c[5:7], 16) + 60)
            glow.append(f"#{r:02x}{g:02x}{b:02x}")
        return glow

    # ---- 动态色彩系统 ----
    def _hsv_to_hex(self, h: float, s: float, v: float) -> str:
        """HSV (h=0-360, s/v=0-1) → '#rrggbb'"""
        h = h % 360
        hi = int(h / 60) % 6
        f = h / 60 - int(h / 60)
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        rgb = [(v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q)][hi]
        return f"#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}"

    def _get_bar_color(self, i: int, bright_mul: float = 1.0,
                       hue_shift: float = 0.0) -> str:
        """获取第i条bar的动态颜色 (低音暖→高音冷 + 全局色调旋转 + 节拍脉冲)"""
        ratio = i / (self.NUM_BARS - 1) if self.NUM_BARS > 1 else 0
        base_hue = 15 + ratio * 220   # 15°(红橙=低音) → 235°(蓝紫=高音)
        hue = (base_hue + self._hue_offset + hue_shift) % 360
        sat = 0.88
        val = max(0.05, min(1.0, (0.60 + 0.35 * self._beat_bright) * bright_mul))
        return self._hsv_to_hex(hue, sat, val)

    def _get_bar_glow_color(self, i: int, hue_shift: float = 0.0) -> str:
        """高亮辉光色 (同色相但更亮更白)"""
        ratio = i / (self.NUM_BARS - 1) if self.NUM_BARS > 1 else 0
        base_hue = 15 + ratio * 220
        hue = (base_hue + self._hue_offset + hue_shift) % 360
        return self._hsv_to_hex(hue, 0.55, 1.0)

    def _toggle_mode(self):
        modes = ['bar', 'grid', 'curve']
        mode_labels = {'bar': '柱状图', 'grid': '网格', 'curve': '曲线'}
        idx = modes.index(self._mode) if self._mode in modes else 0
        self._mode = modes[(idx + 1) % len(modes)]
        self._mode_btn.set_text(mode_labels.get(self._mode, self._mode))
        self._draw()

    def trigger_note(self, key: str, velocity: float = 1.0):
        key_lower = key.lower()
        if key_lower in self.KEY_TO_BAR:
            idx = self.KEY_TO_BAR[key_lower]
            self._bar_values[idx] = min(1.0, velocity)
            self._bar_peaks[idx] = min(1.0, velocity)
            self._note_label.configure(text=f"♪ {key.upper()}")
            # BPM 估算 + 节拍闪光
            now = time.monotonic()
            self._bpm_times.append(now)
            self._bpm_times = [t for t in self._bpm_times if now - t < 4.0]
            if len(self._bpm_times) >= 3:
                intervals = [self._bpm_times[j+1] - self._bpm_times[j]
                             for j in range(len(self._bpm_times) - 1)]
                avg = sum(intervals) / len(intervals)
                self._bpm = 60.0 / avg if avg > 0 else 0.0
            self._beat_bright = min(1.0, self._beat_bright + 0.40)

    def start(self):
        if not self._running:
            self._running = True
            self._animate()

    def stop(self):
        self._running = False
        self._bar_values = [0.0] * self.NUM_BARS
        self._bar_peaks = [0.0] * self.NUM_BARS
        self._wave_history.clear()
        self._draw()

    def _animate(self):
        if not self._running:
            return
        for i in range(self.NUM_BARS):
            self._bar_values[i] *= self.BAR_DECAY
            if self._bar_values[i] < 0.008:
                self._bar_values[i] = 0.0
            self._bar_peaks[i] *= 0.97
            if self._bar_peaks[i] < self._bar_values[i]:
                self._bar_peaks[i] = self._bar_values[i]
        # 色调慢速旋转 (BPM越高旋转越快, 无音乐时极慢)
        hue_speed = 0.25 + (self._bpm / 180.0) * 0.8
        self._hue_offset = (self._hue_offset + hue_speed) % 360.0
        # 节拍亮度衰减
        if self._beat_bright > 0:
            self._beat_bright = max(0.0, self._beat_bright - 0.04)
        self._draw()
        self.canvas.after(self.UPDATE_INTERVAL, self._animate)

    def _draw(self):
        if self._mode == 'bar':
            self._draw_bars_vertical()
        elif self._mode == 'grid':
            self._draw_grid()
        elif self._mode == 'curve':
            self._draw_curve()
        else:
            self._draw_bars_vertical()

    def _draw_bars_vertical(self):
        """双层叠加柱状图 - 暗影层(peak) + 亮层(current) + 细腻渐变"""
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        pad_l, pad_r, pad_t, pad_b = 4, 4, 2, 2
        usable_h = h - pad_t - pad_b
        usable_w = w - pad_l - pad_r
        bar_h = max(3, usable_h / self.NUM_BARS)
        max_bar_w = usable_w - 2

        for i in range(self.NUM_BARS):
            y  = int(pad_t + (self.NUM_BARS - 1 - i) * bar_h)
            y2 = int(pad_t + (self.NUM_BARS - i) * bar_h) - 1
            if y2 <= y:
                y2 = y + 1
            val  = self._bar_values[i]
            peak = self._bar_peaks[i]
            color      = self._get_bar_color(i)
            glow_color = self._get_bar_glow_color(i)
            cr,  cg,  cb  = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            gcr, gcg, gcb = int(glow_color[1:3], 16), int(glow_color[3:5], 16), int(glow_color[5:7], 16)

            # 暗槽
            bg_hex = ModernColors.VIZ_BG
            bg_r = int(bg_hex[1:3], 16)
            bg_g = int(bg_hex[3:5], 16)
            bg_b = int(bg_hex[5:7], 16)
            self.canvas.create_rectangle(pad_l, y, pad_l + max_bar_w, y2,
                                         fill=bg_hex, outline='')

            # 层一: 峰值暗影 (6段细腻)
            if peak >= 0.015:
                pw = int(peak * max_bar_w)
                SEGS_S = min(8, max(3, pw // 6))
                sw = pw / SEGS_S
                for s in range(SEGS_S):
                    sx  = pad_l + int(s * sw)
                    sex = pad_l + int((s + 1) * sw) + 1
                    t_s = s / max(1, SEGS_S - 1)
                    br = 0.06 + 0.18 * (t_s ** 1.3)
                    sr = int(bg_r + (cr - bg_r) * br)
                    sg = int(bg_g + (cg - bg_g) * br)
                    sb = int(bg_b + (cb - bg_b) * br)
                    self.canvas.create_rectangle(
                        sx, y, sex, y2,
                        fill=f"#{max(0,min(255,sr)):02x}{max(0,min(255,sg)):02x}{max(0,min(255,sb)):02x}",
                        outline='')

            # 层二: 当前亮条 (12段细腻渐变 + 辉光尖端)
            if val >= 0.008:
                bw = int(val * max_bar_w)
                if bw < 1:
                    continue
                SEGS = min(16, max(6, bw // 4))
                sw = bw / SEGS
                for s in range(SEGS):
                    sx  = pad_l + int(s * sw)
                    sex = pad_l + int((s + 1) * sw) + 1
                    t_s = s / max(1, SEGS - 1)
                    br = 0.12 + 0.88 * (t_s ** 1.6)
                    sr = int(bg_r + (cr - bg_r) * br)
                    sg = int(bg_g + (cg - bg_g) * br)
                    sb = int(bg_b + (cb - bg_b) * br)
                    self.canvas.create_rectangle(
                        sx, y, sex, y2,
                        fill=f"#{max(0,min(255,sr)):02x}{max(0,min(255,sg)):02x}{max(0,min(255,sb)):02x}",
                        outline='')
                # 辉光尖端: 4段由中到白
                tip = pad_l + bw
                g1  = min(18, max(4, bw // 5))
                for gi in range(4):
                    t_g = gi / 3
                    gx0 = tip - g1 + int(gi * g1 / 4)
                    gx1 = tip - g1 + int((gi + 1) * g1 / 4) + 1
                    if gx0 < pad_l:
                        continue
                    gr2 = min(255, int(cr + (gcr - cr) * t_g))
                    gg2 = min(255, int(cg + (gcg - cg) * t_g))
                    gb2 = min(255, int(cb + (gcb - cb) * t_g))
                    self.canvas.create_rectangle(gx0, y, gx1, y2,
                        fill=f"#{gr2:02x}{gg2:02x}{gb2:02x}", outline='')

    def _draw_grid(self):
        """双层叠加网格 - 暗影像素(peak) + 亮像素(current) 同向叠加 + RGB渐变"""
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        pad_l, pad_r, pad_t, pad_b = 4, 4, 2, 2
        usable_h = h - pad_t - pad_b
        usable_w = w - pad_l - pad_r
        bar_h  = max(3, usable_h / self.NUM_BARS)
        max_bar_w = usable_w - 2
        cell_w, cell_gap = 4, 1

        for i in range(self.NUM_BARS):
            y    = pad_t + (self.NUM_BARS - 1 - i) * bar_h
            val  = self._bar_values[i]
            peak = self._bar_peaks[i]
            color = self._get_bar_color(i)
            cr, cg, cb = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            bg_hex = ModernColors.VIZ_BG
            br2 = int(bg_hex[1:3], 16)
            bg2 = int(bg_hex[3:5], 16)
            bb2 = int(bg_hex[5:7], 16)

            # ---- 第一层: 峰值暗影像素 ----
            if peak >= 0.01:
                max_cells = max(1, int(peak * max_bar_w) // (cell_w + cell_gap))
                for c in range(max_cells):
                    cx = pad_l + c * (cell_w + cell_gap)
                    if cx + cell_w > pad_l + max_bar_w:
                        break
                    t_c = c / max(1, max_cells - 1)
                    bright = 0.08 + 0.14 * (t_c ** 1.3)
                    sr = int(br2 + (cr - br2) * bright)
                    sg = int(bg2 + (cg - bg2) * bright)
                    sb = int(bb2 + (cb - bb2) * bright)
                    self.canvas.create_rectangle(
                        cx, y, cx + cell_w, y + bar_h - 1,
                        fill=f"#{max(0,min(255,sr)):02x}"
                             f"{max(0,min(255,sg)):02x}"
                             f"{max(0,min(255,sb)):02x}",
                        outline='')

            # ---- 第二层: 当前值亮像素 (叠在上面) ----
            if val >= 0.008:
                num_cells = max(1, int(val * max_bar_w) // (cell_w + cell_gap))
                for c in range(num_cells):
                    cx = pad_l + c * (cell_w + cell_gap)
                    if cx + cell_w > pad_l + max_bar_w:
                        break
                    t_c = c / max(1, num_cells - 1)
                    bright = 0.22 + 0.78 * (t_c ** 1.4)
                    sr = int(br2 + (cr - br2) * bright)
                    sg = int(bg2 + (cg - bg2) * bright)
                    sb = int(bb2 + (cb - bb2) * bright)
                    self.canvas.create_rectangle(
                        cx, y, cx + cell_w, y + bar_h - 1,
                        fill=f"#{max(0,min(255,sr)):02x}"
                             f"{max(0,min(255,sg)):02x}"
                             f"{max(0,min(255,sb)):02x}",
                        outline='')

    def _draw_curve(self):
        """多重拖尾平滑曲线 - 最大分散保持峰值高度, 历史帧可见"""
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        pad_l, pad_r, pad_t, pad_b = 4, 4, 2, 2
        usable_h = h - pad_t - pad_b
        usable_w = w - pad_l - pad_r
        cx = pad_l + usable_w / 2
        bar_h = max(3, usable_h / self.NUM_BARS)
        max_half_w = (usable_w - 8) / 2

        # 中心竖线
        self.canvas.create_line(cx, pad_t, cx, h - pad_b,
                                fill=ModernColors.BORDER, width=1, dash=(2, 5))

        def _max_spread(vals, spread=6, sigma=2.2):
            """最大分散: 每个尖峰保持原来高度并将高斯补丁展开到邻音
            → 形成圆弧而不是尖锥, 且峰值不被平均稀释"""
            N = len(vals)
            out = list(vals)          # 先保留原始峰值
            for i in range(N):
                v = vals[i]
                if v < 0.01:
                    continue
                for k in range(1, spread + 1):
                    influence = v * math.exp(-0.5 * (k / sigma) ** 2)
                    if influence < 0.005:
                        break
                    if i - k >= 0 and out[i - k] < influence:
                        out[i - k] = influence
                    if i + k < N  and out[i + k] < influence:
                        out[i + k] = influence
            return out

        # 所有帧: 历史帧在前(暗), 当前帧在后(亮)
        frames = list(self._wave_history) + [list(self._bar_values)]
        n_frames = len(frames)
        if n_frames == 0:
            return

        N = self.NUM_BARS
        ys = [pad_t + (N - 1 - i) * bar_h + bar_h / 2 for i in range(N)]

        for fi, frame_vals in enumerate(frames):
            age = fi / max(1, n_frames - 1)  # 0=最旧, 1=最新

            # 历史帧明显可见: 最旧帧亮度至少 0.08
            fill_bright = 0.08 + 0.28 * age            # 0.08 ~ 0.36
            line_bright = 0.35 + 0.65 * (age ** 0.8)   # 0.35 ~ 1.00
            lw = 1 if age < 0.85 else 2
            hue_shift = (1.0 - age) * 30               # 历史帧色调偏移

            # 最大分散后的半宽 (峰值高度完全保留)
            spread_vals = _max_spread(frame_vals, spread=6, sigma=2.2)
            hbs = [spread_vals[i] * max_half_w for i in range(N)]

            if max(hbs) < 0.8:
                continue

            # ---- 单一平滑闭合填充多边形 (右侧下行 + 左侧上行) ----
            poly = []
            for i in range(N):
                poly.extend([cx + hbs[i], ys[i]])
            for i in range(N - 1, -1, -1):
                poly.extend([cx - hbs[i], ys[i]])

            mid_i = N // 2
            fc = self._get_bar_color(mid_i, bright_mul=fill_bright,
                                     hue_shift=hue_shift)
            self.canvas.create_polygon(poly, fill=fc, outline='', smooth=True)

            # ---- 全宽平滑边缘曲线, 分4段染色 ----
            stride = max(3, N // 4)
            for side in (1, -1):
                for start in range(0, N - 1, stride):
                    end = min(start + stride + 1, N)
                    seg = []
                    for k in range(start, end):
                        seg.extend([cx + side * hbs[k], ys[k]])
                    if len(seg) < 4:
                        continue
                    bar_i = min(start + stride // 2, N - 1)
                    lc = self._get_bar_color(bar_i, bright_mul=line_bright,
                                             hue_shift=hue_shift)
                    self.canvas.create_line(*seg, fill=lc,
                                            width=lw, smooth=True)

    def reset(self):
        self._bar_values = [0.0] * self.NUM_BARS
        self._bar_peaks = [0.0] * self.NUM_BARS
        self._wave_history.clear()
        self._note_label.configure(text="")
        self._draw()


class InfoPanel(tk.Frame):
    """信息面板"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self._recent_notes = []
        self._create()
    def _create(self):
        title = tk.Label(self, text="音符记录", bg=ModernColors.BG_CARD,
                         fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 12, 'bold'))
        title.pack(pady=(10, 5))
        self.notes_frame = tk.Frame(self, bg=ModernColors.BG_INPUT)
        self.notes_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.note_labels = []
        for i in range(10):
            lbl = tk.Label(self.notes_frame, text="", bg=ModernColors.BG_INPUT,
                           fg=ModernColors.TEXT_SECONDARY, font=('Consolas', 9), anchor='w')
            lbl.pack(fill=tk.X, padx=8, pady=1)
            self.note_labels.append(lbl)
    def update_note(self, key: str, note: NoteEvent, is_chord: bool = False):
        if is_chord:
            text = f"♫ {key.upper():2s}  和弦"
        else:
            duration_str = f"{note.duration:.2f}s" if note.duration < 10 else f"{note.duration:.1f}s"
            text = f"♪ {key.upper():2s}  MIDI:{note.note:3d}  {duration_str}"
        self._recent_notes.insert(0, text)
        if len(self._recent_notes) > 10:
            self._recent_notes.pop()
        for i, lbl in enumerate(self.note_labels):
            if i < len(self._recent_notes):
                lbl.configure(text=self._recent_notes[i],
                              fg=ModernColors.ACCENT_BLUE if i == 0 else ModernColors.TEXT_SECONDARY)
            else:
                lbl.configure(text="")
    def clear(self):
        self._recent_notes.clear()
        for lbl in self.note_labels:
            lbl.configure(text="")


class _DummyInfoPanel:
    def update_note(self, key, note, is_chord=False):
        pass
    def clear(self):
        pass


# ==================== 主应用 ====================
class MidiPlayerGUI:
    """主应用 - 自定义无边框窗口 + Apple 风格深色主题"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=ModernColors.BG_DARK)
        self.root.resizable(True, True)

        # 无边框
        self.root.overrideredirect(True)
        self.root._app_ref = self  # ControlPanel 引用

        # 窗口大小并居中
        win_w, win_h = 930, 940
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(860, 750)

        # 让无边框窗口出现在任务栏
        self.root.update_idletasks()
        self._setup_taskbar_icon()

        self.is_topmost = False
        self.settings = SettingsManager()
        self.player = MidiPlayer()
        self._set_icon()
        self._create_ui()
        self._bind_callbacks()
        self._check_hotkey_status()

    def _setup_taskbar_icon(self):
        """让overrideredirect窗口显示在任务栏 + DWM圆角"""
        self._apply_window_style()

    def _apply_window_style(self):
        """应用任务栏 + DWM圆角样式 (可重复调用)"""
        try:
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            try:
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND))
            except Exception:
                pass
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
        except Exception as e:
            print(f"设置任务栏失败: {e}")

    def _check_hotkey_status(self):
        if not GLOBAL_HOTKEY_AVAILABLE:
            msg = f"全局快捷键功能不可用"
            if KEYBOARD_ERROR_MSG:
                msg += f"\n原因: {KEYBOARD_ERROR_MSG}"
            if not is_admin():
                msg += f"\n\n解决方案: 请以管理员身份运行程序"
            self.root.after(500, lambda: ThemedDialog.showwarning(self.root, "快捷键提示", msg))

    def _set_icon(self):
        icon_path = get_icon_path()
        if icon_path:
            try:
                self.root.iconbitmap(default=icon_path)
                self.root.iconbitmap(icon_path)
            except:
                pass
        try:
            myappid = 'midi.28keys.player.2.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass

    def _create_ui(self):
        """创建界面 - 自定义窗口框架 + 扁平布局"""
        # ===== 窗口边框容器 =====
        border = tk.Frame(self.root, bg=ModernColors.BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=ModernColors.BG_DARK)
        inner.pack(fill=tk.BOTH, expand=True)

        # ===== 自定义标题栏 =====
        self.title_bar = CustomTitleBar(inner, self.root,
                                        title="咲 Midi Player", version="v2.0.1+2001",
                                        on_close=self._on_close)
        self.title_bar.pack(fill=tk.X)

        # ===== 标题栏下方工具条 =====
        toolbar = tk.Frame(inner, bg=ModernColors.BG_DARK, height=28)
        toolbar.pack(fill=tk.X, padx=12, pady=(2, 0))
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="透明度", bg=ModernColors.BG_DARK,
                 fg=ModernColors.TEXT_DIM, font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT, padx=(0, 3))
        self.opacity_var = tk.DoubleVar(value=1.0)
        self.opacity_scale = tk.Scale(toolbar, from_=0.3, to=1.0, resolution=0.05,
                                      orient=tk.HORIZONTAL, variable=self.opacity_var,
                                      bg=ModernColors.BG_DARK, fg=ModernColors.TEXT_DIM,
                                      highlightthickness=0, troughcolor=ModernColors.BG_HOVER,
                                      length=60, sliderlength=12, width=10,
                                      showvalue=False, command=self._on_opacity_change)
        self.opacity_scale.pack(side=tk.LEFT, padx=(0, 4))
        self.opacity_label = tk.Label(toolbar, text="100%", bg=ModernColors.BG_DARK,
                                      fg=ModernColors.TEXT_DIM, font=('Microsoft YaHei UI', 8), width=4)
        self.opacity_label.pack(side=tk.LEFT, padx=(0, 12))
        self.topmost_btn = SmoothButton(toolbar, text="置顶", command=self._toggle_topmost,
                                        width=55, height=22, bg=ModernColors.BTN_SECONDARY, font_size=8)
        self.topmost_btn.pack(side=tk.RIGHT)

        self.theme_btn = SmoothButton(toolbar, text="Light SE", command=self._toggle_theme,
                                      width=70, height=22, bg=ModernColors.BTN_SECONDARY, font_size=8)
        self.theme_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ===== 分隔线 =====
        tk.Frame(inner, bg=ModernColors.BORDER, height=1).pack(fill=tk.X, padx=12, pady=(4, 0))

        # ===== 主内容区 =====
        main = tk.Frame(inner, bg=ModernColors.BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # --- 左侧 ---
        left = tk.Frame(main, bg=ModernColors.BG_DARK)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 状态指示器行 (延音 + 模式) 放在键盘上方
        status_row = tk.Frame(left, bg=ModernColors.BG_DARK, bd=0)
        status_row.pack(fill=tk.X, pady=(0, 2))
        self._shift_pill = StatusPill(status_row, text="普通模式",
                                      active_color=ModernColors.ACCENT_BLUE,
                                      width=100, height=20)
        self._shift_pill.pack(side=tk.LEFT, padx=(12, 10), pady=4)
        self._sustain_pill = StatusPill(status_row, text="延音 正常",
                                        active_color=ModernColors.ACCENT_GREEN,
                                        width=100, height=20)
        self._sustain_pill.pack(side=tk.LEFT, pady=4)

        # 键盘卡片
        kb_card = tk.Frame(left, bg=ModernColors.BG_CARD, bd=0)
        kb_card.pack(fill=tk.X, pady=(0, 3))
        self.piano = PianoKeyboard(kb_card)
        self.piano.pack(padx=8, pady=8)

        # 控制面板
        ctrl_card = tk.Frame(left, bg=ModernColors.BG_CARD, bd=0)
        ctrl_card.pack(fill=tk.X, pady=2)
        self.control = ControlPanel(ctrl_card, self.player, self.settings,
                                    on_stop_callback=lambda: self.root.after(100, self._restore_focus_and_hotkeys))
        self.control.pack(fill=tk.X)
        # 注入 StatusPill 引用
        self.control.shift_pill = self._shift_pill
        self.control.sustain_pill = self._sustain_pill

        # 60键可视化钢琴 (填满左侧剩余空间)
        piano_card = tk.Frame(left, bg=ModernColors.BG_CARD, bd=0)
        piano_card.pack(fill=tk.BOTH, expand=True, pady=(3, 0))
        self.mini_piano = MiniPianoBar(piano_card)
        self.mini_piano.pack(fill=tk.BOTH, expand=True)

        # --- 右侧 ---
        right = tk.Frame(main, bg=ModernColors.BG_DARK, width=240)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        right.pack_propagate(False)

        # 快捷键卡片 (紧凑)
        hk_card = tk.Frame(right, bg=ModernColors.BG_CARD, bd=0)
        hk_card.pack(fill=tk.X, pady=(0, 3))

        def stop_and_restore():
            self.control._stop()
            self.root.after(100, self._restore_focus_and_hotkeys)

        self.hotkey_panel = HotkeyPanel(hk_card, self.settings, {
            'play_pause': lambda: self.root.after(0, self.control._toggle_play),
            'stop': lambda: self.root.after(0, stop_and_restore),
            'speed_up': lambda: self.root.after(0, self.control.speed_up),
            'speed_down': lambda: self.root.after(0, self.control.speed_down),
            'toggle_topmost': lambda: self.root.after(0, self._toggle_topmost),
        })
        self.hotkey_panel.pack(fill=tk.X)

        # 可视化卡片 (填满剩余空间)
        self.viz_card = tk.Frame(right, bg=ModernColors.BG_CARD, bd=0)
        self.viz_card.pack(fill=tk.BOTH, expand=True)
        self.visualizer = MidiVisualizer(self.viz_card)
        self.visualizer.pack(fill=tk.BOTH, expand=True)

        self.info = _DummyInfoPanel()

        # ===== 状态栏 + 拖拽手柄 =====
        status_frame = tk.Frame(inner, bg=ModernColors.BG_PANEL)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar = tk.Label(status_frame, text="就绪  |  F5 播放/暂停  |  F9 置顶",
                                   bg=ModernColors.BG_PANEL, fg=ModernColors.TEXT_DIM,
                                   font=('Microsoft YaHei UI', 8), anchor='w', padx=12)
        self.status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        self.resize_grip = ResizeGrip(status_frame, self.root, size=14)
        self.resize_grip.pack(side=tk.RIGHT)

    def _on_opacity_change(self, val):
        opacity = float(val)
        self.opacity_label.configure(text=f"{int(opacity * 100)}%")
        try:
            self.root.attributes('-alpha', opacity)
        except:
            pass

    def _toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.root.attributes('-topmost', self.is_topmost)
        if self.is_topmost:
            self.topmost_btn.set_text("已置顶")
            self.topmost_btn.set_bg(ModernColors.BTN_PRIMARY)
            self.status_bar.configure(text="窗口已置顶")
            self.visualizer.start()
        else:
            self.topmost_btn.set_text("置顶")
            self.topmost_btn.set_bg(ModernColors.BTN_SECONDARY)
            self.status_bar.configure(text="已取消置顶")
            self.visualizer.stop()
            self.opacity_var.set(1.0)
            self.root.attributes('-alpha', 1.0)
            self.opacity_label.configure(text="100%")

    def _bind_callbacks(self):
        def on_note(key, note, is_chord=False):
            duration_ms = int(min(2000, max(100, note.duration * 1000)))
            self.root.after(0, lambda: self.piano.highlight_key(key, duration_ms))
            self.root.after(0, lambda: self.info.update_note(key, note, is_chord))
            vel = note.velocity / 127.0 if hasattr(note, 'velocity') else 0.8
            self.root.after(0, lambda: self.visualizer.trigger_note(key, vel))
            # 触发48键可视化钢琴
            midi_note = note.note
            self.root.after(0, lambda: self.mini_piano.note_on(midi_note, vel, duration_ms))
            if not self.visualizer._running:
                self.root.after(0, self.visualizer.start)

        def on_progress(current, total):
            self.root.after(0, lambda: self.control.update_progress(current, total))

        def on_end():
            self.root.after(0, self.control.on_playback_end)
            self.root.after(0, lambda: self.status_bar.configure(text="播放完成"))
            self.root.after(0, self.piano.reset_all)
            self.root.after(0, self.info.clear)
            self.root.after(0, self.visualizer.reset)
            self.root.after(0, self.mini_piano.reset)
            if self.control._folder_loop_active:
                self.root.after(500, self.control._play_next_folder_song)
            else:
                self.root.after(100, self._restore_focus_and_hotkeys)

        self.player.on_note_play = on_note
        self.player.on_progress = on_progress
        self.player.on_playback_end = on_end

        def on_shift(is_shift):
            self.root.after(0, lambda: self.control.update_shift_state(is_shift))

        def on_sustain(is_on):
            self.root.after(0, lambda: self.control.update_sustain_state(is_on))

        self.player.on_shift_change = on_shift
        self.player.on_sustain_change = on_sustain

        def on_click(event):
            self.root.after(100, self._restore_focus_and_hotkeys)
        self.root.bind('<Button-1>', on_click)

        def on_focus_in(event):
            if event.widget == self.root:
                self.root.after(50, self._restore_focus_and_hotkeys)
        self.root.bind('<FocusIn>', on_focus_in)

    def _restore_focus_and_hotkeys(self):
        try:
            self.root.focus_force()
            if hasattr(self, 'player') and self.player:
                self.player.simulator.release_all()
            if hasattr(self, 'hotkey_panel') and self.hotkey_panel:
                self.hotkey_panel._pressed_keys.clear()
        except Exception as e:
            print(f"恢复状态失败: {e}")

    def _toggle_theme(self):
        """切换 Dark SE / Light SE 主题"""
        new_theme = ModernColors.toggle_theme()
        label = "Dark SE" if new_theme == 'light' else "Light SE"
        self.theme_btn.set_text(label)
        self._refresh_all_colors()

    def _refresh_all_colors(self):
        """刷新全部控件颜色 (主题切换后)"""
        C = ModernColors
        # 旧→新 背景映射 (dark 全部值 + light 全部值)
        bg_map = {
            '#1c1c1e': C.BG_DARK, '#f2f2f7': C.BG_DARK,
            '#2c2c2e': C.BG_CARD, '#ffffff': C.BG_CARD,
            '#3a3a3c': C.BG_HOVER, '#e5e5ea': C.BG_HOVER,
            '#161618': C.TITLEBAR, '#ebebf0': C.TITLEBAR,
            '#38383a': C.BORDER, '#d1d1d6': C.BORDER,
            '#48484a': C.BORDER_BRIGHT, '#c7c7cc': C.BORDER_BRIGHT,
            '#131315': C.VIZ_BG, '#f8f8fa': C.VIZ_BG,
            '#1a1a1c': C.PIANO_BG, '#e8e8ed': C.PIANO_BG,
            '#252528': C.BG_HOVER,
        }
        fg_map = {
            '#f5f5f7': C.TEXT_PRIMARY, '#1c1c1e': C.TEXT_PRIMARY,
            '#98989d': C.TEXT_SECONDARY, '#8e8e93': C.TEXT_SECONDARY,
            '#636366': C.TEXT_DIM, '#aeaeb2': C.TEXT_DIM,
            '#48484a': C.TEXT_DIM, '#e5e5e7': C.TEXT_PRIMARY,
            '#6e6e73': C.TEXT_DIM,
        }
        self.root.configure(bg=C.BG_DARK)
        def refresh_widget(w):
            try:
                cls_name = w.winfo_class()
                if cls_name in ('Frame', 'Labelframe'):
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        w.configure(bg=bg_map[bg])
                elif cls_name == 'Label':
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        w.configure(bg=bg_map[bg])
                    fg = str(w.cget('fg')).lower()
                    if fg in fg_map:
                        w.configure(fg=fg_map[fg])
                elif cls_name == 'Button':
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        w.configure(bg=bg_map[bg])
                    fg = str(w.cget('fg')).lower()
                    if fg in fg_map:
                        w.configure(fg=fg_map[fg])
                elif cls_name == 'Checkbutton':
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        w.configure(bg=bg_map[bg], selectcolor=bg_map.get(bg, C.BG_INPUT))
                    fg = str(w.cget('fg')).lower()
                    if fg in fg_map:
                        w.configure(fg=fg_map[fg])
                elif cls_name in ('Scale', 'TScale'):
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        try:
                            w.configure(bg=bg_map[bg], troughcolor=C.BG_HOVER)
                        except Exception:
                            pass
                    fg = str(w.cget('fg')).lower()
                    if fg in fg_map:
                        try:
                            w.configure(fg=fg_map[fg])
                        except Exception:
                            pass
                elif cls_name == 'Spinbox':
                    bg = str(w.cget('bg')).lower()
                    if bg in bg_map:
                        w.configure(bg=bg_map[bg])
                    fg = str(w.cget('fg')).lower()
                    if fg in fg_map:
                        w.configure(fg=fg_map[fg])
                elif cls_name == 'Canvas':
                    # SmoothButton 和 PianoKey 也是 Canvas
                    if isinstance(w, SmoothButton):
                        try:
                            parent_bg = w.master.cget('bg')
                        except:
                            parent_bg = C.BG_CARD
                        # 更新按钮底色随主题
                        _btn_bg_map = {
                            '#0a84ff': C.BTN_PRIMARY,  '#007aff': C.BTN_PRIMARY,
                            '#48484a': C.BTN_SECONDARY, '#e5e5ea': C.BTN_SECONDARY,
                            '#3a3a3c': C.BG_HOVER,      '#d1d1d6': C.BG_HOVER,
                            '#ff453a': C.BTN_DANGER,   '#ff3b30': C.BTN_DANGER,
                        }
                        old_base = w.base_bg.lower()
                        if old_base in _btn_bg_map:
                            w.base_bg = _btn_bg_map[old_base]
                            w.current_bg = w.base_bg
                        w.configure(bg=parent_bg)
                        w._draw()
                    elif isinstance(w, PianoKey):
                        w.configure(bg=C.BG_CARD)
                        w.reset_theme()
                    elif isinstance(w, GlowProgressBar):
                        try:
                            pbg = w.master.cget('bg')
                        except:
                            pbg = C.BG_CARD
                        w.configure(bg=pbg)
                        w._draw()
                    elif isinstance(w, StatusPill):
                        try:
                            pbg = w.master.cget('bg')
                        except:
                            pbg = C.BG_DARK
                        w.configure(bg=pbg)
                        w._draw()
                    else:
                        bg = str(w.cget('bg')).lower()
                        if bg in bg_map:
                            w.configure(bg=bg_map[bg])
            except Exception:
                pass
            for child in w.winfo_children():
                refresh_widget(child)
        refresh_widget(self.root)
        # 特殊控件直接刷新
        try:
            self.visualizer.canvas.configure(bg=C.VIZ_BG)
            self.visualizer.configure(bg=C.BG_CARD)
            self.viz_card.configure(bg=C.BG_CARD)
            self.visualizer._draw()
            self.mini_piano.canvas.configure(bg=C.PIANO_BG)
            self.mini_piano._build_keys()
            self.status_bar.configure(bg=C.BG_PANEL, fg=C.TEXT_DIM)
            # ttk.Scale 速度条主题
            try:
                import tkinter.ttk as _ttk
                _s = _ttk.Style()
                _s.configure('Modern.Horizontal.TScale',
                             background=C.BG_CARD,
                             troughcolor=C.BG_INPUT,
                             sliderthickness=20)
            except Exception:
                pass
            # 标题栏: 按钮重绘 + 文字更新
            for cv, txt in self.title_bar._ctrl_btns:
                cv.configure(bg=C.TITLEBAR)
                self.title_bar._draw_ctrl_btn(cv, txt, C.TITLEBAR, C.TEXT_DIM)
            self.title_bar.configure(bg=C.TITLEBAR)
            self.title_bar._title_lbl.configure(bg=C.TITLEBAR, fg=C.TEXT_PRIMARY)
            self.title_bar._version_lbl.configure(bg=C.TITLEBAR, fg=C.TEXT_DIM)
            # 标题栏图标 canvas
            for child in self.title_bar.winfo_children():
                if isinstance(child, tk.Canvas) and child not in [cv for cv, _ in self.title_bar._ctrl_btns]:
                    child.configure(bg=C.TITLEBAR)
            # 工具栏按钮
            self.topmost_btn._draw()
            self.theme_btn._draw()
        except Exception:
            pass

    def _on_close(self):
        """关闭窗口"""
        self.hotkey_panel.cleanup()
        self.player.stop()
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()


def main():
    app = MidiPlayerGUI()
    app.run()


if __name__ == "__main__":
    main()
