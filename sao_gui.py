# -*- coding: utf-8 -*-
"""
SAO Utils 风格完整 GUI — 独立 UI 壳
包含 SAO PopUpMenu 菜单系统, SAO Alert 对话框, HP 血条进度条,
LINK START 入场动画, SAO 风格文件选择器

所有播放功能复用 MidiPlayer 后端, 与 gui.py (Old UI) 完全独立
"""

import tkinter as tk
from tkinter import ttk
import os
import sys
import json
import ctypes
import math
import time
import threading
from typing import Optional

from PIL import Image, ImageDraw, ImageTk, ImageFilter, ImageFont
import numpy as np

from player import MidiPlayer
from midi_parser import NoteEvent
from config import (
    WINDOW_TITLE, WINDOW_SIZE,
    KEYBOARD_LAYOUT, NOTE_NAMES, BLACK_KEY_LAYOUT, BLACK_KEY_NAMES,
    NOTE_NAMES_EXTENDED, BLACK_KEY_NAMES_EXTENDED,
    DEFAULT_HOTKEYS, CONFIG_FILE,
    KEY_TO_MIDI
)
from sao_theme import (
    SAOColors, SAOButton, SAOProgressBar, SAOTitleBar, SAODialog,
    SAOLeaderboardDialog,
    SAOStatusPill, SAOResizeGrip, SAOFilePicker, SAOSeparator,
    SAOPopUpMenu, SAOHPBar, SAOLinkStart, SAOCircleButton,
    Animator, lerp, lerp_color, ease_out, ease_in_out
)
from gui import MidiVisualizer, ModernColors, SmoothButton
from character_profile import (
    load_profile, save_profile, get_or_ask_profile,
    show_welcome_dialog, PROFESSION_LIST,
    calc_level, add_song_xp
)
from sao_sound import play_sound, LevelUpEffect, load_sao_fonts, get_sao_font, get_cjk_font

# pyglet Link Start 渲染器 (已弃用, 保留文件但不再使用)
# OpenGL 上下文要求主线程, 与 tkinter 冲突, 改用 Canvas SAO-UI 隧道模型
HAS_PYGLET = False

# ── 全局快捷键检测 (复用 gui.py 逻辑) ──
def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

KEYBOARD_HOTKEY_AVAILABLE = False
KEYBOARD_ERROR_MSG = None
try:
    import keyboard as kb
    try:
        _tc = lambda: None
        kb.add_hotkey('ctrl+alt+shift+f12', _tc, suppress=False)
        kb.remove_hotkey('ctrl+alt+shift+f12')
        KEYBOARD_HOTKEY_AVAILABLE = True
    except Exception as e:
        KEYBOARD_ERROR_MSG = str(e)
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


# ══════════════════════════════════════════════════════════
#  Settings Manager (与 gui.py 共享 settings.json)
# ══════════════════════════════════════════════════════════
class SettingsManager:
    def __init__(self):
        self.settings = {
            'hotkeys': DEFAULT_HOTKEYS.copy(),
            'last_file': '', 'speed': 1.0, 'transpose': 0,
            'chord_mode': False, 'ui_mode': 'sao',
        }
        self.load()

    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.settings.update(json.load(f))
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


def _get_icon_path():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, 'icon.ico')
    return p if os.path.exists(p) else None


def _apply_panel_style(panel):
    """为浮动 Toplevel 面板添加 DWM 圆角 + 系统阴影 — 增强浮动质感"""
    try:
        panel.update_idletasks()
        hwnd = int(_user32.GetParent(ctypes.c_void_p(panel.winfo_id())))
        # DWM 圆角 (Win11+)
        val = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        # 系统阴影 (CS_DROPSHADOW)
        GCL_STYLE = -26
        CS_DROPSHADOW = 0x00020000
        cls = ctypes.windll.user32.GetClassLongW(hwnd, GCL_STYLE)
        ctypes.windll.user32.SetClassLongW(hwnd, GCL_STYLE, cls | CS_DROPSHADOW)
    except Exception:
        pass


# ── SAO HUD 面板样式常量 ──
_SAO_PANEL_BG = '#fafafa'          # 面板主背景
_SAO_PANEL_HEADER_BG = '#1a2030'   # 深色标题栏
_SAO_PANEL_HEADER_FG = '#e8f4f8'   # 标题文字
_SAO_PANEL_BORDER = '#d1d1d6'      # 外边框
_SAO_PANEL_ACCENT = '#86dfff'      # 青色强调
_SAO_PANEL_GOLD = '#f3af12'        # 金色强调
_SAO_PANEL_SEP = '#e0e0e0'         # 分隔线
_SAO_PANEL_BODY_BG = '#ffffff'     # 内容区背景
_SAO_PANEL_LABEL_FG = '#999999'    # 标签文字
_SAO_PANEL_VALUE_FG = '#333333'    # 数值文字


def _sao_panel_header(parent, title_icon, title_text, close_cmd):
    """创建 SAO 风格深色标题栏，返回 (header_frame, close_label)"""
    hdr = tk.Frame(parent, bg=_SAO_PANEL_HEADER_BG, height=28)
    hdr.pack(fill=tk.X)
    hdr.pack_propagate(False)
    # 左侧角标 + 标题
    accent = tk.Frame(hdr, bg=_SAO_PANEL_ACCENT, width=3, height=16)
    accent.pack(side=tk.LEFT, padx=(6, 0), pady=6)
    tk.Label(hdr, text=f'{title_icon} {title_text}',
             bg=_SAO_PANEL_HEADER_BG, fg=_SAO_PANEL_HEADER_FG,
             font=get_sao_font(8, True)).pack(side=tk.LEFT, padx=6)
    # 右侧系统标记
    tk.Label(hdr, text='◇', bg=_SAO_PANEL_HEADER_BG, fg='#4a5a6a',
             font=get_sao_font(7)).pack(side=tk.RIGHT, padx=(0, 2))
    close_lbl = _make_panel_close_button(hdr, close_cmd, bg=_SAO_PANEL_HEADER_BG)
    close_lbl.pack(side=tk.RIGHT, padx=6)
    return hdr, close_lbl


def _sao_panel_body(parent):
    """创建 SAO 风格面板内容区 (带角标装饰)"""
    # 分隔线
    tk.Frame(parent, bg=_SAO_PANEL_ACCENT, height=1).pack(fill=tk.X)
    body = tk.Frame(parent, bg=_SAO_PANEL_BODY_BG)
    body.pack(fill=tk.BOTH, expand=True, padx=1, pady=(0, 1))
    return body


def _sao_panel_hud_canvas(parent):
    """在面板底部添加一个 HUD 装饰画布层"""
    cv = tk.Canvas(parent, height=16, bg=_SAO_PANEL_BODY_BG,
                   highlightthickness=0, bd=0)
    cv.pack(fill=tk.X, side=tk.BOTTOM)
    return cv


def _sao_row(parent, label_text, value_text='', value_fg=None, value_font=None):
    """创建 SAO 风格的 标签: 值 行"""
    row = tk.Frame(parent, bg=_SAO_PANEL_BODY_BG)
    row.pack(fill=tk.X, pady=2)
    tk.Label(row, text=label_text, bg=_SAO_PANEL_BODY_BG,
             fg=_SAO_PANEL_LABEL_FG, font=get_sao_font(8),
             anchor='w').pack(side=tk.LEFT)
    val_lbl = tk.Label(row, text=value_text, bg=_SAO_PANEL_BODY_BG,
                        fg=value_fg or _SAO_PANEL_VALUE_FG,
                        font=value_font or get_sao_font(9, True))
    val_lbl.pack(side=tk.RIGHT)
    return val_lbl


def _sao_pill(parent, text, active, command):
    """创建 SAO 风格切换按钮"""
    bg = _SAO_PANEL_GOLD if active else '#1a2030'
    fg = '#ffffff' if active else '#8a9aaa'
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=get_cjk_font(8, True),
                   padx=8, pady=2, cursor='hand2', relief=tk.FLAT)
    lbl.bind('<Button-1>', lambda e: command())
    return lbl


def _apply_viz_light_theme(viz):
    """将 MidiVisualizer 内部深色 ModernColors 覆盖为白色 SAO 配色"""
    # ── 关键: 同步更新类属性, 否则渲染代码里的 lerp 仍用暗色底 ──
    _VIZ_LIGHT = '#f0f2f8'
    ModernColors.VIZ_BG = _VIZ_LIGHT

    _bg_map = {
        '#2c2c2e': '#ffffff',   # ModernColors.BG_CARD
        '#3a3a3c': '#f0f0f0',   # ModernColors.BG_HOVER
        '#131315': _VIZ_LIGHT,  # ModernColors.VIZ_BG
        '#060a10': _VIZ_LIGHT,  # SAO 模式 VIZ_BG 备用值
        '#1c1c1e': '#ffffff',   # ModernColors.BG_DARK / BG_INPUT
    }
    _fg_map = {
        '#636366': '#999999',   # ModernColors.TEXT_DIM
        '#64d2ff': '#f3af12',   # ModernColors.ACCENT_CYAN → SAO gold
        '#f5f5f7': '#333333',   # ModernColors.TEXT_PRIMARY
        '#98989d': '#999999',   # ModernColors.TEXT_SECONDARY
    }
    def _patch(w):
        try:
            bg = w.cget('bg').lower()
            if bg in _bg_map:
                w.configure(bg=_bg_map[bg])
        except Exception:
            pass
        try:
            fg = w.cget('fg').lower()
            if fg in _fg_map:
                w.configure(fg=_fg_map[fg])
        except Exception:
            pass
        for child in w.winfo_children():
            _patch(child)
    _patch(viz)


def _set_clickthrough_style(win):
    """给装饰/条带窗口设置 Win32 透明点击穿透样式。"""
    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


def _disable_native_window_shadow(win):
    """关闭透明/异形窗口的系统矩形阴影，避免阴影落到错误区域。"""
    try:
        win.update_idletasks()
        hwnd = int(_user32.GetParent(ctypes.c_void_p(win.winfo_id())) or win.winfo_id())
        policy = ctypes.c_int(1)  # DWMNCRP_DISABLED
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(policy), 4)
    except Exception:
        pass


def _make_sao_panel_hud(parent, width: int, height: int, alpha: float = 0.18):
    """生成一个轻量 SAO HUD 画布，提供左右错层飘移装饰。"""
    cv = tk.Canvas(parent, width=width, height=height, bg=parent.cget('bg'),
                   highlightthickness=0, bd=0)
    cv.place(x=0, y=0, relwidth=1, relheight=1)
    cv.tk.call('lower', cv._w)
    return cv


def _hex_rgba(hex_color: str, alpha: int = 255):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(ch * 2 for ch in hex_color)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)


def _make_panel_close_button(parent, command, bg=_SAO_PANEL_HEADER_BG):
    size = 18
    scale = 4
    sw = size * scale
    img = Image.new('RGBA', (sw, sw), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def S(v):
        return int(round(v * scale))

    draw.line((S(4), S(4), S(14), S(14)), fill=_hex_rgba('#ff707a'), width=max(1, S(2)))
    draw.line((S(4), S(14), S(14), S(4)), fill=_hex_rgba('#ff707a'), width=max(1, S(2)))
    normal = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))

    img_h = Image.new('RGBA', (sw, sw), (0, 0, 0, 0))
    draw_h = ImageDraw.Draw(img_h)
    draw_h.ellipse((S(1), S(1), S(17), S(17)), outline=_hex_rgba('#ff707a', 210), width=max(1, S(1)))
    draw_h.line((S(4), S(4), S(14), S(14)), fill=_hex_rgba('#ffffff'), width=max(1, S(2)))
    draw_h.line((S(4), S(14), S(14), S(4)), fill=_hex_rgba('#ffffff'), width=max(1, S(2)))
    hover = ImageTk.PhotoImage(img_h.resize((size, size), Image.LANCZOS))

    lbl = tk.Label(parent, bg=bg, image=normal, cursor='hand2', bd=0, highlightthickness=0)
    lbl._img_normal = normal
    lbl._img_hover = hover
    lbl.configure(image=normal)
    lbl.bind('<Enter>', lambda e: lbl.configure(image=lbl._img_hover))
    lbl.bind('<Leave>', lambda e: lbl.configure(image=lbl._img_normal))
    lbl.bind('<Button-1>', lambda e: command())
    return lbl


# ══════════════════════════════════════════════════════════
#  Win32 per-pixel alpha 分层窗口 (UpdateLayeredWindow)
# ══════════════════════════════════════════════════════════

class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_byte), ('BlendFlags', ctypes.c_byte),
                ('SourceConstantAlpha', ctypes.c_byte), ('AlphaFormat', ctypes.c_byte)]

class _ULW_SIZE(ctypes.Structure):
    _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]

class _ULW_POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', ctypes.c_ulong), ('biWidth', ctypes.c_long),
        ('biHeight', ctypes.c_long), ('biPlanes', ctypes.c_ushort),
        ('biBitCount', ctypes.c_ushort), ('biCompression', ctypes.c_ulong),
        ('biSizeImage', ctypes.c_ulong), ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', ctypes.c_ulong),
        ('biClrImportant', ctypes.c_ulong),
    ]


# Win32 函数签名 (64-bit 安全, 防止 HWND/HDC 截断)
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
for _fn, _res, _args in [
    (_user32.GetDC, ctypes.c_void_p, [ctypes.c_void_p]),
    (_user32.ReleaseDC, ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p]),
    (_user32.GetParent, ctypes.c_void_p, [ctypes.c_void_p]),
    (_user32.GetWindowLongW, ctypes.c_long, [ctypes.c_void_p, ctypes.c_int]),
    (_user32.SetWindowLongW, ctypes.c_long, [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]),
    (_user32.UpdateLayeredWindow, ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]),
    (_gdi32.CreateCompatibleDC, ctypes.c_void_p, [ctypes.c_void_p]),
    (_gdi32.CreateDIBSection, ctypes.c_void_p,
        [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
         ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]),
    (_gdi32.SelectObject, ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]),
    (_gdi32.DeleteObject, ctypes.c_int, [ctypes.c_void_p]),
    (_gdi32.DeleteDC, ctypes.c_int, [ctypes.c_void_p]),
]:
    _fn.restype = _res
    _fn.argtypes = _args
del _fn, _res, _args


def _update_layered_win(hwnd, rgba_image, overall_alpha=255, dst_pos=None):
    """使用 Win32 UpdateLayeredWindow 实现真正的逐像素 alpha 透明窗口。
    rgba_image: PIL RGBA Image;  overall_alpha: 0-255 整体 alpha。"""
    if not hwnd:
        return False
    w, h = rgba_image.size
    # RGBA -> 预乘 BGRA (ULW 要求预乘 alpha)
    arr = np.array(rgba_image, dtype=np.float32)
    a = arr[:, :, 3:4] / 255.0
    bgra = np.empty((h, w, 4), dtype=np.uint8)
    bgra[:, :, 0] = np.clip(arr[:, :, 2] * a[:, :, 0], 0, 255)  # B
    bgra[:, :, 1] = np.clip(arr[:, :, 1] * a[:, :, 0], 0, 255)  # G
    bgra[:, :, 2] = np.clip(arr[:, :, 0] * a[:, :, 0], 0, 255)  # R
    bgra[:, :, 3] = arr[:, :, 3].astype(np.uint8)

    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(bmi)
    bmi.biWidth = w
    bmi.biHeight = -h   # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32

    hdcS = _user32.GetDC(None)
    hdcM = _gdi32.CreateCompatibleDC(hdcS)
    bits = ctypes.c_void_p()
    hbmp = _gdi32.CreateDIBSection(hdcM, ctypes.byref(bmi), 0,
                                    ctypes.byref(bits), None, 0)
    if not hbmp:
        _gdi32.DeleteDC(hdcM)
        _user32.ReleaseDC(None, hdcS)
        return False
    old = _gdi32.SelectObject(hdcM, hbmp)
    raw = bgra.tobytes()
    ctypes.memmove(bits, raw, len(raw))

    pt = _ULW_POINT(0, 0)
    sz = _ULW_SIZE(w, h)
    bf = _BLENDFUNCTION(0, 0, min(255, max(0, int(overall_alpha))), 1)
    dst = None
    if dst_pos is not None:
        try:
            dx, dy = dst_pos
            dst = _ULW_POINT(int(dx), int(dy))
        except Exception:
            dst = None
    ok = _user32.UpdateLayeredWindow(
        ctypes.c_void_p(hwnd), hdcS, ctypes.byref(dst) if dst is not None else None, ctypes.byref(sz),
        hdcM, ctypes.byref(pt), 0, ctypes.byref(bf), 2)

    _gdi32.SelectObject(hdcM, old)
    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdcM)
    _user32.ReleaseDC(None, hdcS)
    return bool(ok)


def _get_hp_pil_font(size, family='sao', _cache={}):
    """加载 PIL 字体用于 HP 条渲染 (带缓存)。"""
    key = (family, size)
    if key in _cache:
        return _cache[key]
    base = os.path.dirname(os.path.abspath(__file__))
    fname = 'SAOUI.ttf' if family == 'sao' else 'ZhuZiAYuanJWD.ttf'
    fp = os.path.join(base, 'assets', 'fonts', fname)
    try:
        font = ImageFont.truetype(fp, size=size)
    except Exception:
        font = ImageFont.load_default()
    _cache[key] = font
    return font


# ══════════════════════════════════════════════════════════
#  迷你钢琴 (60键可视化) — 精简版
# ══════════════════════════════════════════════════════════
class SAOMiniPiano(tk.Canvas):
    """SAO 风格 60 键可视化钢琴 (白色主题 + 渐变衰减)"""

    WHITE_KEY_COLOR = '#f0f0f0'
    BLACK_KEY_COLOR = '#444444'
    WHITE_KEY_BRIGHT = '#f3af12'   # SAO 金色
    BLACK_KEY_BRIGHT = '#dea620'

    def __init__(self, parent, octaves=5, **kw):
        self._octaves = octaves
        self._total_whites = octaves * 7
        self._key_w = 0
        self._key_h = 0
        super().__init__(parent, height=80, highlightthickness=0, **kw)
        self.configure(bg='#ffffff')
        self._active: dict = {}  # midi_note → after_id
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, e=None):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10:
            return
        self._key_w = w / self._total_whites
        self._key_h = h
        self._draw_keys()

    def _draw_keys(self):
        self.delete('all')
        kw, kh = self._key_w, self._key_h
        if kw < 1 or kh < 1:
            return
        # 白键 (浅灰色, SAO 风格)
        for i in range(self._total_whites):
            x = i * kw
            self.create_rectangle(x, 0, x + kw - 1, kh,
                                  fill=self.WHITE_KEY_COLOR, outline='#dddddd', width=1,
                                  tags=f'w{i}')
        # 黑键
        black_pattern = [1, 1, 0, 1, 1, 1, 0]
        bw = kw * 0.6
        bh = kh * 0.6
        for oct in range(self._octaves):
            for j, has_black in enumerate(black_pattern):
                if has_black:
                    wi = oct * 7 + j
                    x = (wi + 1) * kw - bw / 2
                    self.create_rectangle(x, 0, x + bw, bh,
                                          fill=self.BLACK_KEY_COLOR, outline='#555555', width=1,
                                          tags=f'b{oct}_{j}')

    def note_on(self, midi_note: int, velocity: float = 0.8, duration_ms: int = 500):
        """高亮键 — 带渐变衰减 (SAO 金色 → 正常色)"""
        note_offset = midi_note - 36
        if note_offset < 0 or note_offset >= self._octaves * 12:
            return
        octave = note_offset // 12
        semitone = note_offset % 12
        white_map = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}
        black_map = {1: 0, 3: 1, 6: 3, 8: 4, 10: 5}

        is_white = semitone in white_map
        if is_white:
            wi = octave * 7 + white_map[semitone]
            tag = f'w{wi}'
            bright = self.WHITE_KEY_BRIGHT
            normal = self.WHITE_KEY_COLOR
        elif semitone in black_map:
            bj = black_map[semitone]
            tag = f'b{octave}_{bj}'
            bright = self.BLACK_KEY_BRIGHT
            normal = self.BLACK_KEY_COLOR
        else:
            return

        if midi_note in self._active:
            self.after_cancel(self._active[midi_note])
        self.itemconfig(tag, fill=bright)

        # 渐变衰减: 8 步从亮色平滑过渡回正常色
        FADE_STEPS = 8
        interval = max(25, duration_ms // FADE_STEPS)

        def _fade(step=1):
            if step > FADE_STEPS:
                self._active.pop(midi_note, None)
                return
            t = step / FADE_STEPS
            color = lerp_color(bright, normal, t)
            try:
                self.itemconfig(tag, fill=color)
            except Exception:
                self._active.pop(midi_note, None)
                return
            self._active[midi_note] = self.after(interval, lambda s=step + 1: _fade(s))

        self._active[midi_note] = self.after(interval, _fade)

    def reset(self):
        for aid in self._active.values():
            try:
                self.after_cancel(aid)
            except:
                pass
        self._active.clear()
        self._draw_keys()


# ══════════════════════════════════════════════════════════
#  可视化柱状图 — SAO 风格
# ══════════════════════════════════════════════════════════
# SAOVisualizer replaced by MidiVisualizer (from gui.py) for richer visuals


# ══════════════════════════════════════════════════════════
#  SAO 全局快捷键面板 — pynput 版
# ══════════════════════════════════════════════════════════
class SAOHotkeyManager:
    """全局快捷键管理 (与 gui.py HotkeyPanel 逻辑一致)"""

    # F键虚拟键码表 (Windows VK codes)
    _FKEY_VK = {
        'F1': 112, 'F2': 113, 'F3': 114, 'F4': 115,
        'F5': 116, 'F6': 117, 'F7': 118, 'F8': 119,
        'F9': 120, 'F10': 121, 'F11': 122, 'F12': 123,
    }

    def __init__(self, settings: SettingsManager, actions: dict):
        self.settings = settings
        self.actions = actions
        self._listener = None
        self._pressed_keys = set()
        self._start()

    def _start(self):
        if not PYNPUT_HOTKEY_AVAILABLE:
            return
        try:
            self._listener = pynput_kb.Listener(
                on_press=self._on_press, on_release=self._on_release)
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            pass

    def _on_press(self, key):
        try:
            if isinstance(key, KeyCode) and key.vk:
                self._pressed_keys.add(key.vk)
            elif isinstance(key, Key):
                self._pressed_keys.add(key.value.vk if hasattr(key.value, 'vk') else str(key))
        except:
            pass
        self._check_combos()

    def _on_release(self, key):
        try:
            if isinstance(key, KeyCode) and key.vk:
                self._pressed_keys.discard(key.vk)
            elif isinstance(key, Key):
                self._pressed_keys.discard(key.value.vk if hasattr(key.value, 'vk') else str(key))
        except:
            pass

    def _check_combos(self):
        saved = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        for action, info in saved.items():
            vk = None
            if isinstance(info, dict):
                vk = info.get('vk')
            elif isinstance(info, str) and info:
                vk = self._FKEY_VK.get(info.upper())
            if vk and vk in self._pressed_keys:
                cb = self.actions.get(action)
                if cb:
                    cb()
                    self._pressed_keys.clear()
                    return

    def cleanup(self):
        if self._listener:
            try:
                self._listener.stop()
            except:
                pass


# ══════════════════════════════════════════════════════════
#  SAO Player GUI — 完整独立 UI
# ══════════════════════════════════════════════════════════
#  SAO 左侧玩家信息面板 (替代 SAOLeftInfo)
#  对标 SAO-UI HP 组件 + LeftInfo 组件
# ══════════════════════════════════════════════════════════
class SAOPlayerPanel(tk.Frame):
    """
    SAO 风格左侧信息面板 — 对标 SAO-UI LeftInfo + HP 组件
    
    结构:
    - Top 区 (白色, 240×280): 用户名/分隔线/HP条/等级/文件信息
    - Bottom 区 (灰色, 240×120): 描述 + 状态信息
    - 右三角指示器 (连接 MenuBar)
    - 下三角装饰 (连接 top/bottom)
    """

    def __init__(self, parent, username='Player', profession='', **kw):
        super().__init__(parent, bg=parent.cget('bg'), highlightthickness=0, **kw)
        self._active = False
        self._anim = Animator(self)
        self._target_w = 240
        self._top_h = 240
        self._bottom_h = 80

        # 用户资料
        self._username = username
        self._profession = profession

        # 等级数据
        self._level = 1
        self._xp_percent = 0.0  # 当前经验百分比 (0~1)
        self._xp_total = 0  # 累计 XP (用于 calc_level)

        # 播放数据
        self._file_name = "未选择文件"
        self._status = "就绪"
        self._time_current = 0
        self._time_total = 0
        self._speed = 1.0
        self._transpose = 0
        self._hp_percent = 1.0
        self._hp_current = 1000
        self._hp_total = 1000
        self._mode = "经典60键"
        self._shift_mode = "普通模式"
        self._bpm = 0
        self._is_playing = False
        self._sustain = False

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

    def update_file(self, name):
        self._file_name = name
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

    def update_progress(self, current, total):
        self._time_current = current
        self._time_total = total
        if total > 0:
            self._hp_percent = current / total
            self._hp_current = int(current)
            self._hp_total = int(total)
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

    def update_status(self, status, is_playing=None):
        self._status = status
        if is_playing is not None:
            self._is_playing = is_playing
        if self._active:
            self._redraw_bottom(self._target_w, self._bottom_h)

    def update_speed(self, speed):
        self._speed = speed
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

    def update_transpose(self, t):
        self._transpose = t
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

    def update_mode(self, mode_text):
        self._mode = mode_text
        if self._active:
            self._redraw_bottom(self._target_w, self._bottom_h)

    def update_bpm(self, bpm):
        self._bpm = bpm
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

    def update_sustain(self, on: bool):
        self._sustain = on
        if self._active:
            self._redraw_bottom(self._target_w, self._bottom_h)

    def update_shift_mode(self, mode_text: str):
        self._shift_mode = mode_text
        if self._active:
            self._redraw_bottom(self._target_w, self._bottom_h)

    def update_level(self, level: int, xp_pct: float, xp_total: int = 0):
        """更新等级信息"""
        self._level = level
        self._xp_percent = xp_pct
        self._xp_total = xp_total
        if self._active:
            self._redraw_top(self._target_w, self._top_h)

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
                           on_done=lambda: self._anim.animate('bottom_open', 400, phase2))

    def _animate_close(self):
        def fade(t):
            inv = 1 - t
            w = max(1, int(self._target_w * inv))
            self._top.configure(width=w, height=max(1, int(self._top_h * inv)))
            self._bottom.configure(width=w, height=max(1, int(self._bottom_h * inv)))

        self._anim.animate('close', 200, fade)

    def _redraw_top(self, w, h):
        """SAO 系统信息面板 .top — HUD 风格"""
        self._top.delete('all')
        if w < 40 or h < 40:
            return

        GOLD = '#f3af12'
        CYAN = '#86dfff'
        DIM = '#c8c8c8'
        LABEL = '#aaaaaa'
        TITLE_FG = '#646364'

        # ── 背景 ──
        self._top.create_rectangle(0, 0, w, h, fill='#ffffff', outline='')

        # ── HUD 角标 (四角 L 型边框) ──
        bk = 14  # bracket length
        self._top.create_line(2, 2, 2 + bk, 2, fill=CYAN, width=1)
        self._top.create_line(2, 2, 2, 2 + bk, fill=CYAN, width=1)
        self._top.create_line(w - 2 - bk, 2, w - 2, 2, fill=GOLD, width=1)
        self._top.create_line(w - 2, 2, w - 2, 2 + bk, fill=GOLD, width=1)
        self._top.create_line(2, h - 2, 2 + bk, h - 2, fill=CYAN, width=1)
        self._top.create_line(2, h - 2 - bk, 2, h - 2, fill=CYAN, width=1)
        self._top.create_line(w - 2 - bk, h - 2, w - 2, h - 2, fill=GOLD, width=1)
        self._top.create_line(w - 2, h - 2 - bk, w - 2, h - 2, fill=GOLD, width=1)

        # ── 右三角指示器 (连接 MenuBar) ──
        tri_y = int(h * 0.6)
        self._top.create_polygon(w, tri_y, w + 18, tri_y + 7, w, tri_y + 14,
                                 fill='#ffffff', outline='')

        # ── 系统编号标签 ──
        self._top.create_text(w - 8, 12, text='SYS:PLAYER', anchor='e',
                              font=get_sao_font(6), fill=DIM)

        # ── 用户名 ──
        title_y = 26
        display_name = self._username
        if len(display_name) > 18:
            display_name = display_name[:16] + '…'
        self._top.create_text(w // 2, title_y, text=display_name,
                              font=get_sao_font(13, True), fill=TITLE_FG)

        # 分隔线 (对标 .title border-bottom)
        sep_y = 44
        self._top.create_line(10, sep_y, w - 10, sep_y, fill='#aaaaaa', width=2)
        # 微型扫描点
        for i in range(5):
            dot_x = 14 + i * 8
            self._top.create_rectangle(dot_x, sep_y - 1, dot_x + 3, sep_y,
                                       fill=CYAN, outline='')

        if h < 60:
            return

        # ── 等级区域 ──
        # 等级标签
        self._top.create_text(20, 62, text='LEVEL', anchor='w',
                              font=get_sao_font(7), fill=LABEL)
        self._top.create_text(w // 2, 84,
                              text=f'Lv. {self._level}',
                              font=get_sao_font(20, True), fill=GOLD)

        if h < 120:
            return

        # ── 经验值条 ──
        from character_profile import calc_level as _cl
        _lv, _cur_xp, _need_xp = _cl(
            getattr(self, '_xp_total', 0) if hasattr(self, '_xp_total') else 0)

        # EXP 标签
        self._top.create_text(20, 108, text='EXP', anchor='w',
                              font=get_sao_font(7), fill=LABEL)
        self._top.create_text(w - 20, 108, text=f'{_cur_xp} / {_need_xp}',
                              anchor='e', font=get_sao_font(8), fill='#999999')

        # 经验条 (带边框)
        if h > 124:
            xp_y = 122
            xp_x = 20
            xp_w = w - 40
            xp_h = 6
            # 底色
            self._top.create_rectangle(xp_x, xp_y, xp_x + xp_w, xp_y + xp_h,
                                       fill='#e8e8e8', outline='#d8d8d8', width=1)
            xp_fill = int(xp_w * self._xp_percent)
            if xp_fill > 0:
                self._top.create_rectangle(xp_x + 1, xp_y + 1,
                                           xp_x + xp_fill, xp_y + xp_h - 1,
                                           fill=GOLD, outline='')
                # 光泽高亮
                self._top.create_rectangle(xp_x + 1, xp_y + 1,
                                           xp_x + xp_fill, xp_y + 3,
                                           fill='#f5c644', outline='')

        # ── 状态标签行 ──
        if h > 150:
            info_y = 140
            # HP 状态
            self._top.create_text(20, info_y, text='HP', anchor='w',
                                  font=get_sao_font(7, True), fill=CYAN)
            hp_text = f'{self._hp_current}/{self._hp_total}' if self._hp_total > 0 else '—'
            self._top.create_text(w - 20, info_y, text=hp_text, anchor='e',
                                  font=get_sao_font(8), fill='#777777')

        if h > 170:
            info_y2 = 158
            self._top.create_text(20, info_y2, text='SPD', anchor='w',
                                  font=get_sao_font(7, True), fill=CYAN)
            self._top.create_text(w - 20, info_y2, text=f'{self._speed:.2f}x', anchor='e',
                                  font=get_sao_font(8), fill='#777777')

        if h > 190:
            info_y3 = 176
            self._top.create_text(20, info_y3, text='KEY', anchor='w',
                                  font=get_sao_font(7, True), fill=CYAN)
            self._top.create_text(w - 20, info_y3, text=f'{self._transpose:+d}', anchor='e',
                                  font=get_sao_font(8), fill='#777777')

        if h > 210:
            info_y4 = 194
            self._top.create_text(20, info_y4, text='BPM', anchor='w',
                                  font=get_sao_font(7, True), fill=GOLD)
            self._top.create_text(w - 20, info_y4, text=f'{self._bpm}' if self._bpm else '—',
                                  anchor='e', font=get_sao_font(8), fill='#777777')

        # ── 底部微型扫描线 ──
        if h > 220:
            scan_y = h - 16
            self._top.create_line(10, scan_y, w - 10, scan_y, fill='#e8e8e8', width=1)
            t = time.time()
            scan_x = 10 + int((w - 20) * ((math.sin(t * 1.5) + 1) / 2))
            self._top.create_rectangle(scan_x - 12, scan_y - 1, scan_x + 12, scan_y + 1,
                                       fill=CYAN, outline='')

    def _redraw_bottom(self, w, h):
        """SAO 系统信息面板 .bottom — 状态描述区"""
        self._bottom.delete('all')
        if w < 40 or h < 15:
            return

        # 背景
        self._bottom.create_rectangle(0, 0, w, h, fill='#e5e3e3', outline='')

        # 下三角装饰 (连接 top/bottom)
        self._bottom.create_polygon(30, 0, 37.5, -10, 45, 0,
                                    fill='#e5e3e3', outline='')

        # 顶部微渐变阴影
        for i in range(3):
            av = int(220 + i * 8)
            self._bottom.create_line(0, i, w, i,
                                     fill=f'#{av:02x}{av:02x}{av:02x}', width=1)

        # 角标
        self._bottom.create_line(3, 3, 12, 3, fill='#86dfff', width=1)
        self._bottom.create_line(3, 3, 3, 12, fill='#86dfff', width=1)
        self._bottom.create_line(w - 12, h - 3, w - 3, h - 3, fill='#f3af12', width=1)
        self._bottom.create_line(w - 3, h - 12, w - 3, h - 3, fill='#f3af12', width=1)

        # 状态标签
        self._bottom.create_text(12, 12, text='STATUS', anchor='w',
                                 font=get_sao_font(6), fill='#b0b0b0')

        # 描述/职业
        desc = self._profession if self._profession else '咲 Midi Player SAO Edition'
        self._bottom.create_text(15, h // 2 + 2, text=desc,
                                 font=get_cjk_font(10), fill='#777777',
                                 anchor='w')

        # 底部系统标签
        if h > 50:
            self._bottom.create_text(w - 8, h - 10, text='SAO://SYSTEM',
                                     anchor='e', font=get_sao_font(5), fill='#c8c8c8')



# ══════════════════════════════════════════════════════════
#  SAO Player GUI — 纯悬浮 SAO Menu 架构
# ══════════════════════════════════════════════════════════
class SAOPlayerGUI:
    """
    纯悬浮 SAO Utils 风格 GUI — 没有传统窗口！
    - 常驻: 小型悬浮触发按钮 (Toplevel)
    - 展开: SAO PopUpMenu 全屏菜单 = 主界面
    - 左面板: SAOPlayerPanel (文件/进度/状态)
    - 菜单按钮: 5 类 (文件/播放/设置/控制/关于)
    - 子菜单: 所有播放控制
    - 可选: 浮动钢琴/可视化面板
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # root 永远隐藏, 只作为 Tk 事件循环
        self.root.title("咲 Midi Player SAO Edition")

        self.settings = SettingsManager()
        # 记录当前 UI 模式 — 下次启动时使用
        self.settings.set('ui_mode', 'sao')
        self.settings.save()
        self.player = MidiPlayer()
        saved_mode = self.settings.get('mode_system', 'classic')
        self.player.set_mode_system(saved_mode)

        # ── 角色配置 ──
        profile = load_profile()
        self._username = profile.get('username', '')
        self._profession = profile.get('profession', '')
        self._level = profile.get('level', 1)
        self._xp = profile.get('xp', 0)
        self._songs_played = profile.get('songs_played', 0)
        self._play_time = profile.get('play_time', 0)

        # 加载 SAO 字体
        load_sao_fonts()

        self._current_file = None
        self._playing = False
        self._paused = False
        self._folder_loop_active = False
        self._folder_loop_files = []
        self._folder_loop_index = 0
        self._speed = self.settings.get('speed', 1.0)
        self._transpose = self.settings.get('transpose', 0)
        self._melody_on = True
        self._bass_on = True
        self._bass_density = 0.6
        self._glissando = False
        self._direct_c = False
        self._sustain_active = False
        self._shift_mode = 'normal'     # 当前演奏模式: normal/shift/ctrl/lt/gt
        self._proficiency_enabled = False
        self._panels_hidden = False  # 一键隐藏所有面板
        self._hidden_panels_snapshot = []  # 隐藏前记录哪些面板是开的
        self._player_panel = None  # 当 SAO 菜单打开时设置
        self._picker = None        # SAOFilePicker 引用 (防止 GC)
        self._piano_panel = None   # 浮动钢琴面板
        self._viz_panel = None     # 浮动可视化面板
        self._status_panel = None  # 浮动状态面板
        self._control_panel = None # 浮动控制面板
        self._fisheye_ov = None    # 菜单开启时的持久鱼眼叠加层
        self._ctx_menu_open = False  # 右键菜单弹出中, 暂停 z-order 置顶
        self._mini_piano = None
        self._visualizer = None
        self._lift_loop_active = False
        self._skip_canvas_click = False
        self._float_progress_pct = 0.0
        self._hp_alpha_windows = []
        self._hp_alpha_photos = []
        self._float_hud_ids = []
        self._float_hud_text = []
        self._destroyed = False  # hot-switch 守卫: 阻止 after() 回调在 root 销毁后执行
        self._exit_animating = False
        self._close_finalized = False
        self._entry_overlay = None
        self._exit_overlay = None
        # 浮动呼吸动画
        self._breath_active = False
        self._breath_base_x = 0
        self._breath_base_y = 0
        self._breath_t0 = 0.0

        self._set_icon()
        self._create_floating_widget()
        self._setup_sao_menu()
        self._bind_callbacks()
        self._setup_hotkeys()

        # LINK START 入场
        self.root.after(100, self._play_link_start)

    def _set_icon(self):
        icon_path = _get_icon_path()
        if icon_path:
            try:
                self.root.iconbitmap(default=icon_path)
            except:
                pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('midi.28keys.player.sao')
        except:
            pass

    def _create_hp_alpha_strip_windows(self):
        """(ULW 模式下 HP 填充已由 PIL alpha 梯度渲染, 不再需要条带窗口)"""
        self._hp_alpha_windows = []
        self._hp_alpha_photos = []

    def _destroy_hp_alpha_strip_windows(self):
        for item in getattr(self, '_hp_alpha_windows', []):
            try:
                item['win'].destroy()
            except Exception:
                pass
        self._hp_alpha_windows = []
        self._hp_alpha_photos = []

    def _render_hp_strip_image(self, *a, **kw):
        return None

    def _sync_hp_alpha_strip_windows(self):
        """(ULW 模式下不需要同步条带窗口)"""
        pass

    def _build_float_hud_items(self):
        """(ULW 模式下 HUD 已统一由 PIL 渲染, 此方法保留接口兼容)"""
        pass

    def _render_hp_shell(self, hover=False, scale=4):
        """渲染静态 HP 外壳为 RGBA PIL Image (4× 超采样 + LANCZOS)。"""
        FW, FH = self._fw, self._fh
        ox, oy = 6, 4
        BW, BH = 400, 40
        xt_w = 22
        xr_x = ox + xt_w + 3
        xr_w = BW - xt_w - 3
        bar_x = ox + 100
        bar_y = oy + 8
        PW, PT, PH, PS = 260, 16, 23, 124
        num_x = ox + int(BW * 0.60)
        num_y = oy + int(BH * 0.90)
        xp_w = int(150 * 0.69)
        lv_x = num_x + xp_w + 3
        lv_w = int(150 * 0.30)

        bg = '#b5cde0' if hover else '#9db5d0'
        border = '#e7e4e4' if hover else '#dad7d7'
        glow_cyan = '#9cecff' if hover else '#86dfff'
        glow_gold = '#ffd06a' if hover else '#f3af12'

        sw, sh = FW * scale, FH * scale
        img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def S(v):
            return int(round(v * scale))

        def P(pts):
            return [(S(x), S(y)) for x, y in pts]

        # ── xt_left 方块 ──
        draw.rectangle((S(ox), S(oy), S(ox + xt_w), S(oy + BH)), fill=_hex_rgba(bg, 248))
        draw.rectangle((S(ox), S(oy + BH / 4), S(ox + xt_w / 2), S(oy + BH * 3 / 4)),
                        fill=(0, 0, 0, 0))

        # ── xt_right 异形多边形 ──
        xr_pts = [
            (xr_x + 75, oy + int(BH * 0.22)),
            (xr_x + xr_w, oy + int(BH * 0.22)),
            (xr_x + xr_w, oy),
            (xr_x, oy), (xr_x, oy + BH),
            (xr_x + 210, oy + BH),
            (xr_x + 210, oy + int(BH * 0.80)),
            (xr_x + xr_w, oy + int(BH * 0.80)),
            (xr_x + xr_w, oy + int(BH * 0.60)),
            (xr_x + 200, oy + int(BH * 0.60)),
            (xr_x + 195, oy + int(BH * 0.77)),
            (xr_x + 75, oy + int(BH * 0.77)),
        ]
        draw.polygon(P(xr_pts), fill=_hex_rgba(bg, 242))

        # ── 右侧渐隐条纹 ──
        fade_start = xr_x + int(xr_w * 0.40)
        fade_end = xr_x + xr_w
        n_strips = 72
        bg_rgb = _hex_rgba(bg, 255)
        for i in range(n_strips):
            t = i / max(1, n_strips - 1)
            alpha = int(210 * (1.0 - t * t))
            sx = fade_start + (fade_end - fade_start) * i / n_strips
            ex = fade_start + (fade_end - fade_start) * (i + 1) / n_strips + 1
            fill = (bg_rgb[0], bg_rgb[1], bg_rgb[2], alpha)
            draw.rectangle((S(sx), S(oy), S(ex), S(oy + BH * 0.22)), fill=fill)
            draw.rectangle((S(sx), S(oy + BH * 0.60), S(ex), S(oy + BH * 0.80)), fill=fill)

        # ── HP 条边框 ──
        bar_pts = [
            (bar_x, bar_y), (bar_x + PW, bar_y),
            (bar_x + PW - 5, bar_y + PT), (bar_x + PS, bar_y + PT),
            (bar_x + PS - 4, bar_y + PH), (bar_x, bar_y + PH),
        ]
        draw.polygon(P(bar_pts), fill=(92, 114, 140, 118 if not hover else 138))
        draw.line(P(bar_pts + [bar_pts[0]]),
                  fill=_hex_rgba(border, 255), width=max(1, scale))
        draw.line(P([(bar_x + 2, bar_y + 1), (bar_x + PW - 2, bar_y + 1)]),
                  fill=_hex_rgba(border, 220), width=max(1, scale))
        draw.line(P([(bar_x + 2, bar_y + PH - 1), (bar_x + PS - 5, bar_y + PH - 1)]),
                  fill=_hex_rgba(border, 220), width=max(1, scale))
        draw.polygon(P([
            (bar_x + 2, bar_y + 2), (bar_x + PW - 3, bar_y + 2),
            (bar_x + PW - 8, bar_y + PT - 1), (bar_x + PS + 1, bar_y + PT - 1),
            (bar_x + PS - 6, bar_y + PH - 3), (bar_x + 2, bar_y + PH - 3),
        ]), fill=(176, 202, 226, 32 if not hover else 42))

        # ── 数值底框 ──
        draw.rectangle((S(num_x), S(num_y), S(num_x + xp_w), S(num_y + 18)),
                        fill=_hex_rgba(bg, 236))
        draw.rectangle((S(lv_x), S(num_y), S(lv_x + lv_w), S(num_y + 18)),
                        fill=_hex_rgba(bg, 236))

        return img.resize((FW, FH), Image.LANCZOS)

    def _render_hp_dynamic(self):
        """合成完整 HP 帧: 静态外壳 + HP 填充 + 文字 + HUD 呼吸光点。"""
        FW, FH = self._fw, self._fh
        shell = self._hp_shell_hover.copy() if self._hp_hover else self._hp_shell_normal.copy()
        draw = ImageDraw.Draw(shell)

        # ── HP 填充 (带从左到右的 alpha 梯度) ──
        pct = self._float_progress_pct
        if pct > 0:
            if pct >= 0.60:
                c = (154, 211, 52)
            elif pct >= 0.25:
                c = (244, 250, 73)
            else:
                c = (239, 104, 78)
            top_max_w = self._hp_bar_right - self._hp_bar_x
            top_fill_w = max(1, int(top_max_w * pct))
            bot_max_w = self._hp_bar_step_x - self._hp_bar_x
            bot_fill_w = min(top_fill_w, bot_max_w)
            alpha_base = 0.96 if self._playing and not self._paused else 0.86

            # 上层
            h_top = max(1, self._hp_bar_bot_top - self._hp_bar_y)
            grad_top = np.zeros((h_top, top_fill_w, 4), dtype=np.uint8)
            grad_top[:, :, :3] = c
            ts = np.linspace(0, 1, top_fill_w)
            alphas = (255 * alpha_base * (0.18 + (1.0 - ts) * 0.74)).clip(0, 255).astype(np.uint8)
            grad_top[:, :, 3] = alphas[np.newaxis, :]
            fill_top_img = Image.fromarray(grad_top)
            shell.paste(fill_top_img, (self._hp_bar_x, self._hp_bar_y), fill_top_img)

            # 下层
            if bot_fill_w > 0:
                h_bot = max(1, self._hp_bar_bot_full - self._hp_bar_bot_top)
                grad_bot = np.zeros((h_bot, bot_fill_w, 4), dtype=np.uint8)
                grad_bot[:, :, :3] = c
                ts_b = np.linspace(0, 1, bot_fill_w)
                alphas_b = (255 * alpha_base * (0.18 + (1.0 - ts_b) * 0.74)).clip(0, 255).astype(np.uint8)
                grad_bot[:, :, 3] = alphas_b[np.newaxis, :]
                fill_bot_img = Image.fromarray(grad_bot)
                shell.paste(fill_bot_img, (self._hp_bar_x, self._hp_bar_bot_top), fill_bot_img)

        # ── 文字: 用户名 ──
        name = getattr(self, '_hp_display_name', 'Player')
        ox, oy = 6, 4
        BW, BH = 400, 40
        xr_x = ox + 22 + 3
        name_cx = (xr_x + xr_x + 75) // 2
        name_cy = oy + BH // 2
        try:
            fn = _get_hp_pil_font(14, 'cjk')
            draw.text((name_cx, name_cy), name, fill=(225, 222, 222, 255),
                      font=fn, anchor='mm')
        except Exception:
            draw.text((name_cx - 10, name_cy - 6), name, fill=(225, 222, 222, 255))

        # ── 文字: XP / 等级 ──
        num_x = ox + int(BW * 0.60)
        num_y = oy + int(BH * 0.90)
        xp_w = int(150 * 0.69)
        lv_x = num_x + xp_w + 3
        lv_w = int(150 * 0.30)
        _lv, _cur_xp, _need_xp = calc_level(self._xp)
        try:
            fn_num = _get_hp_pil_font(12, 'sao')
            draw.text((num_x + xp_w - 5, num_y + 9),
                      f'{_cur_xp}/{_need_xp}', fill=(225, 222, 222, 255),
                      font=fn_num, anchor='rm')
            draw.text((lv_x + lv_w - 5, num_y + 9),
                      f'lv.{self._level}', fill=(225, 222, 222, 255),
                      font=fn_num, anchor='rm')
        except Exception:
            pass

        return shell

    def _refresh_hp_layered(self):
        """重新渲染并更新分层 HP 窗口。"""
        if self._destroyed:
            return
        try:
            if not self._float or not self._float.winfo_exists():
                return
        except Exception:
            return
        if not self._float_hwnd:
            return
        alpha = getattr(self, '_float_alpha', 0.82)
        try:
            if alpha <= 0.01:
                # alpha ≈ 0: 仍然调用 ULW (全透明), 防止 Tk 黑底暴露
                _blank = Image.new('RGBA', (self._fw, self._fh), (0, 0, 0, 0))
                _update_layered_win(self._float_hwnd, _blank, 0)
                return
            img = self._render_hp_dynamic()
            dst_pos = None
            try:
                dst_pos = (self._float.winfo_rootx(), self._float.winfo_rooty())
            except Exception:
                pass
            ok = _update_layered_win(self._float_hwnd, img, int(255 * alpha), dst_pos=dst_pos)
            if not ok and not getattr(self, '_ulw_warned', False):
                self._ulw_warned = True
                print(f'[SAO-HP] UpdateLayeredWindow FAILED, hwnd=0x{self._float_hwnd:X}')
        except Exception as e:
            if not getattr(self, '_ulw_warned', False):
                self._ulw_warned = True
                print(f'[SAO-HP] _refresh_hp_layered error: {e}')
                import traceback; traceback.print_exc()

    def _set_float_alpha(self, alpha):
        """设置 HP 窗口整体透明度并刷新。"""
        self._float_alpha = alpha
        self._refresh_hp_layered()

    def _animate_float_hud(self):
        """30fps HUD 呼吸动画循环 — 每帧重新渲染分层窗口。"""
        if self._destroyed:
            return
        try:
            if not self._float.winfo_exists():
                return
        except Exception:
            return
        self._refresh_hp_layered()
        try:
            self.root.after(33, self._animate_float_hud)
        except Exception:
            pass

    def _attach_sao_panel_fx(self, panel, header, inner, accent='#86dfff'):
        """给 Tk 浮动面板附加 SAO 风格 HUD 背景和左右错层漂移。"""
        try:
            panel.update_idletasks()
            pw = max(80, panel.winfo_width())
            ph = max(60, panel.winfo_height())
        except Exception:
            return

        if getattr(panel, '_sao_fx_inited', False):
            return
        panel._sao_fx_inited = True
        header_cv = _make_sao_panel_hud(header, pw, 24)
        body_cv = _make_sao_panel_hud(inner, pw, ph)
        panel._sao_header_hud = header_cv
        panel._sao_body_hud = body_cv

        def _tick():
            try:
                if self._destroyed or not panel.winfo_exists():
                    return
            except Exception:
                return
            tt = time.time() + (hash(str(panel)) % 17) * 0.13
            header_cv.delete('all')
            body_cv.delete('all')
            cyan = '#86dfff'
            gold = '#f3af12'

            left_far = int(10 + 5 * math.sin(tt * 0.66))
            left_near = int(20 + 12 * math.sin(tt * 1.35 + 0.8))
            right_far = int(pw - 18 + 7 * math.sin(tt * 0.72 + 1.1))
            right_near = int(pw - 34 + 12 * math.sin(tt * 1.45 + 2.1))
            body_cv.create_line(left_far, 30, left_far + 78, 30, fill=cyan, width=1)
            body_cv.create_line(left_near, ph - 44, left_near + 102, ph - 44, fill=gold, width=1)
            body_cv.create_line(right_far - 88, 42, right_far, 42, fill=cyan, width=1)
            body_cv.create_line(right_near - 110, ph - 58, right_near, ph - 58, fill=gold, width=1)
            for i in range(5):
                lx = left_far + i * 12
                rx2 = right_far - i * 13
                body_cv.create_line(lx, 48, lx, 54 + (i % 2) * 3, fill=cyan, width=1)
                body_cv.create_line(rx2, ph - 74, rx2, ph - 68 - (i % 2) * 3, fill=gold, width=1)
            body_cv.create_rectangle(left_near + 8, ph - 36, left_near + 66, ph - 24, outline=cyan, width=1)
            body_cv.create_rectangle(right_near - 74, 22, right_near - 12, 34, outline=gold, width=1)
            try:
                self.root.after(33, _tick)
            except Exception:
                pass

        _tick()

    # ══════════════════════════════════════════════
    #  悬浮触发按钮 — 纯 SAO-UI HP 组件 (对标 HP/src/index.vue)
    # ══════════════════════════════════════════════
    def _create_floating_widget(self):
        """SAO-UI HP 组件 — Win32 分层窗口 (per-pixel alpha) 版本。
        使用 UpdateLayeredWindow 实现真正的逐像素 alpha 透明，
        所有内容(外壳/HP填充/文字/HUD)统一由 PIL 渲染后一次性刷新。
        """
        # ── 尺寸 ──
        FW, FH = 420, 64
        self._fw, self._fh = FW, FH
        self._float_alpha = 0.0
        self._hp_hover = False

        self._float = tk.Toplevel(self.root)
        self._float.overrideredirect(True)
        self._float.attributes('-topmost', True)
        self._float.geometry(f'{FW}x{FH}')
        self._float.configure(bg='#000000')

        # Win32: 设为分层窗口 + 任务栏可见
        self._float_hwnd = 0
        try:
            self._float.update_idletasks()
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_LAYERED = 0x00080000
            hwnd = int(_user32.GetParent(ctypes.c_void_p(self._float.winfo_id())))
            self._float_hwnd = hwnd
            style = _user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW | WS_EX_LAYERED) & ~WS_EX_TOOLWINDOW
            _user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE, style)
            _disable_native_window_shadow(self._float)
            # 立即绘制一帧全透明 ULW, 让 Win32 接管渲染 (Tk 黑底永不显示)
            try:
                _blank = Image.new('RGBA', (FW, FH), (0, 0, 0, 0))
                _update_layered_win(hwnd, _blank, 0)
            except Exception:
                pass
            print(f'[SAO-HP] ULW hwnd=0x{hwnd:X}, layered OK')
        except Exception as e:
            print(f'[SAO-HP] ULW init FAILED: {e}')
            import traceback; traceback.print_exc()
            self._float_hwnd = 0

        # ── 预渲染静态外壳 (normal / hover) ──
        self._hp_shell_normal = self._render_hp_shell(hover=False)
        self._hp_shell_hover = self._render_hp_shell(hover=True)

        # ── HP 布局常量 ──
        ox, oy = 6, 4
        bar_x = ox + 100; bar_y = oy + 8
        PW, PT, PH, PS = 260, 16, 23, 124
        self._hp_bar_x        = bar_x + 2
        self._hp_bar_y        = bar_y + 2
        self._hp_bar_right    = bar_x + PW - 7
        self._hp_bar_bot_top  = bar_y + PT - 1
        self._hp_bar_bot_full = bar_y + PH - 2
        self._hp_bar_step_x   = bar_x + PS - 6

        # ── 显示名 ──
        display_name = self._username if self._username else 'Player'
        if len(display_name) > 8:
            display_name = display_name[:7] + '…'
        self._hp_display_name = display_name

        # ── 拖拽 / 点击 交互 (绑定到 Toplevel) ──
        self._drag = {'x': 0, 'y': 0, 'dragging': False}
        self._float.bind('<Button-1>', self._float_click)
        self._float.bind('<B1-Motion>', self._float_drag)
        self._float.bind('<ButtonRelease-1>', self._float_release)
        self._float.bind('<Enter>', self._float_enter)
        self._float.bind('<Leave>', self._float_leave)

        # 右键菜单
        self._float_ctx = tk.Menu(self._float, tearoff=0, bg='#ffffff',
                                  fg='#333333', activebackground='#f3af12',
                                  activeforeground='#ffffff',
                                  font=get_cjk_font(9))
        self._float_ctx.add_command(label='◆ 打开 SAO 菜单', command=self._toggle_sao_menu)
        self._float_ctx.add_separator()
        self._float_ctx.add_command(label='▶ 播放/暂停', command=self._toggle_play)
        self._float_ctx.add_command(label='■ 停止', command=self._stop)
        self._float_ctx.add_command(label='▸ 打开文件', command=self._open_file)
        self._float_ctx.add_separator()
        self._float_ctx.add_command(label='⌨ 钢琴面板', command=self._toggle_piano_panel)
        self._float_ctx.add_command(label='≡ 可视化', command=self._toggle_viz_panel)
        self._float_ctx.add_command(label='◉ 状态面板', command=self._toggle_status_panel)
        self._float_ctx.add_command(label='⚙ 控制面板', command=self._toggle_control_panel)
        self._float_ctx.add_separator()
        self._float_ctx.add_command(label='◈ 隐藏/显示面板', command=self._toggle_hide_all_panels)
        self._float_ctx.add_command(label='◇ WebView UI', command=self._switch_to_webview_ui)
        self._float_ctx.add_command(label='↺ Old UI', command=self._switch_to_old_ui)
        self._float_ctx.add_command(label='✕ 退出', command=self._on_close)
        def _show_ctx_menu(e):
            self._ctx_menu_open = True
            try:
                self._float_ctx.tk_popup(e.x_root, e.y_root)
            finally:
                self._ctx_menu_open = False
        self._float.bind('<Button-3>', _show_ctx_menu)

        # 初始渲染一次 (alpha=0，不可见)
        try:
            self._refresh_hp_layered()
        except Exception:
            pass

        # 初始隐藏 — LinkStart 完成后才显示
        self._float.withdraw()

    # ──────── 浮动呼吸动画 ────────
    def _start_float_breath(self):
        """idle 状态下轻微上下浮动 (模仿 SAO 菜单呼吸动画)"""
        if self._breath_active:
            return
        self._breath_active = True
        try:
            self._float.update_idletasks()
            self._breath_base_x = self._float.winfo_x()
            self._breath_base_y = self._float.winfo_y()
        except Exception:
            pass
        self._breath_t0 = time.time()
        self._breath_step()

    def _breath_step(self):
        if self._destroyed or not self._breath_active:
            return
        try:
            t = time.time() - self._breath_t0
            new_dx = int(round(math.sin(t * 1.25) * 3.0))
            new_dy = int(round(math.sin(t * 2.1) * 2.0))
            fx = self._breath_base_x + new_dx
            fy = self._breath_base_y + new_dy
            if self._float and self._float.winfo_exists():
                self._float.geometry(f'+{fx}+{fy}')
            self.root.after(16, self._breath_step)
        except Exception:
            pass

    def _stop_float_breath(self):
        self._breath_active = False
        try:
            if self._float and self._float.winfo_exists():
                self._float.geometry(f'+{self._breath_base_x}+{self._breath_base_y}')
        except Exception:
            pass

    def _attach_panel_float(self, panel, phase: float = 0.0, amp: float = 2.5):
        """给浮动面板附加轻微漂浮动画，且不再叠加额外 HUD 小条。"""
        t0 = time.time()

        def _step():
            if self._destroyed:
                return
            try:
                if not panel.winfo_exists():
                    return
            except Exception:
                return

            now = time.time() - t0
            new_dx = int(amp * math.sin(now * 0.82 + phase))
            new_dy = int(amp * math.sin(now * 0.61 + phase + 1.2))
            old_dx = getattr(panel, '_fdx', 0)
            old_dy = getattr(panel, '_fdy', 0)
            dd_x, dd_y = new_dx - old_dx, new_dy - old_dy
            if dd_x != 0 or dd_y != 0:
                try:
                    cx = panel.winfo_x()
                    cy = panel.winfo_y()
                    panel.geometry(f'+{cx + dd_x}+{cy + dd_y}')
                except Exception:
                    pass
            panel._fdx = new_dx
            panel._fdy = new_dy
            try:
                self.root.after(16, _step)
            except Exception:
                pass

        panel._fdx = 0
        panel._fdy = 0
        _step()

    def _float_click(self, e):
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root
        self._drag['dragging'] = False
        self._stop_float_breath()

    def _float_drag(self, e):
        dx = abs(e.x_root - self._drag['x'])
        dy = abs(e.y_root - self._drag['y'])
        if dx > 5 or dy > 5:
            self._drag['dragging'] = True
        if self._drag['dragging']:
            mx = e.x_root - self._fw // 2
            my = e.y_root - self._fh // 2
            self._float.geometry(f'+{mx}+{my}')

    def _float_release(self, e):
        if self._skip_canvas_click:
            self._skip_canvas_click = False
            return
        if self._drag['dragging']:
            try:
                self._breath_base_x = self._float.winfo_x()
                self._breath_base_y = self._float.winfo_y()
                self.settings.set('float_x', self._breath_base_x)
                self.settings.set('float_y', self._breath_base_y)
                self.settings.save()
            except Exception:
                pass
            self._breath_t0 = time.time()
            self._breath_active = True
            self._breath_step()
        else:
            self._toggle_sao_menu()

    def _float_enter(self, e):
        """高亮悬浮 HP 组件"""
        try:
            self._hp_hover = True
            self._float_alpha = 0.93
            self._refresh_hp_layered()
        except Exception:
            pass

    def _float_leave(self, e):
        """恢复默认色"""
        try:
            self._hp_hover = False
            self._float_alpha = 0.82
            self._refresh_hp_layered()
        except Exception:
            pass

    def _update_float_display(self):
        """更新悬浮 HP 组件 — 由 _render_hp_dynamic 统一处理，仅触发刷新。"""
        self._refresh_hp_layered()

    def _update_float_status(self):
        self._update_float_display()

    def _update_float_fname(self, name=''):
        """HP 组件风格: 无文件名显示, 保留接口兼容"""
        pass

    def _animate_float_to(self, x0, y0, x1, y1, ms=700):
        """将悬浮窗口从 (x0,y0) 平滑动画到 (x1,y1)"""
        steps = max(1, ms // 16)
        step = [0]
        def tick():
            if self._destroyed:
                return
            if not self._float.winfo_exists():
                return
            step[0] += 1
            t = min(1.0, step[0] / steps)
            et = ease_out(t)
            x = int(x0 + (x1 - x0) * et)
            y = int(y0 + (y1 - y0) * et)
            self._float.geometry(f'+{x}+{y}')
            try:
                self._refresh_hp_layered()
            except Exception:
                pass
            if t < 1.0:
                try:
                    self.root.after(16, tick)
                except Exception:
                    pass
        tick()

    def _lift_float_loop(self):
        """SAO 菜单开启时持续将悬浮按钮保持在最上层"""
        if self._destroyed or not self._lift_loop_active:
            return
        try:
            if self._float.winfo_exists():
                self._float.lift()
        except Exception:
            pass
        try:
            self.root.after(150, self._lift_float_loop)
        except Exception:
            pass

    # ══════════════════════════════════════════════
    #  SAO 菜单 = 主界面
    # ══════════════════════════════════════════════
    def _make_player_panel(self, parent):
        """工厂: 为 SAO 菜单创建左侧信息面板"""
        panel = SAOPlayerPanel(parent,
                               username=self._username or 'Player',
                               profession=self._profession or '')
        self._player_panel = panel

        # 等级信息
        panel._level = self._level
        try:
            lv, cur_xp, need_xp = calc_level(self._xp)
            panel._xp_percent = cur_xp / max(1, need_xp)
            panel._xp_total = self._xp
        except Exception:
            panel._xp_percent = 0.0
            panel._xp_total = 0

        return panel

    def _build_menu_children(self):
        """动态构建子菜单 (支持状态反映)"""
        play_icon = '⏸' if (self._playing and not self._paused) else '▶'
        play_label = '暂停' if (self._playing and not self._paused) else ('继续' if self._paused else '播放')
        mode = self.settings.get('mode_system', 'classic')
        mode_60 = '● 经典60键' if mode == 'classic' else '○ 经典60键'
        mode_88 = '● 扩展88键' if mode == 'extended' else '○ 扩展88键'
        melody_state = '✓' if self._melody_on else '✗'
        bass_state = '✓' if self._bass_on else '✗'
        folder_label = '停止循环' if self._folder_loop_active else '循环文件夹'

        # 读取快捷键配置
        hk = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        def _k(key_id):
            v = hk.get(key_id, DEFAULT_HOTKEYS.get(key_id, ''))
            return f'  [{v}]' if v else ''

        return {
            '文件': [
                {'icon': '▸', 'label': '打开 MIDI 文件', 'command': self._open_file},
                {'icon': '↻', 'label': folder_label, 'command': self._toggle_folder_loop},
                {'icon': '✓', 'label': '保存设置', 'command': lambda: self.settings.save()},
            ],
            '播放': [
                {'icon': play_icon, 'label': play_label + _k('play_pause'), 'command': self._toggle_play},
                {'icon': '■', 'label': '停止' + _k('stop'), 'command': self._stop},
                {'icon': '⊕', 'label': f'加速  ({self._speed:.2f}x)' + _k('speed_up'), 'command': self._speed_up},
                {'icon': '⊖', 'label': f'减速  ({self._speed:.2f}x)' + _k('speed_down'), 'command': self._speed_down},
            ],
            '设置': [
                {'icon': '♪', 'label': mode_60, 'command': lambda: self._set_mode('classic')},
                {'icon': '♫', 'label': mode_88, 'command': lambda: self._set_mode('extended')},
                {'icon': '▲', 'label': f'移调 +1  (当前 {self._transpose:+d})', 'command': self._transpose_up},
                {'icon': '▼', 'label': f'移调 -1  (当前 {self._transpose:+d})', 'command': self._transpose_down},
                {'icon': '↺', 'label': '重置移调 / 自动检测', 'command': self._auto_transpose},
                {'icon': 'C', 'label': 'C调直转' + (' ✓' if self._direct_c else ''), 'command': self._toggle_direct_c},
                {'icon': melody_state, 'label': '旋律', 'command': self._toggle_melody},
                {'icon': bass_state, 'label': '伴奏', 'command': self._toggle_bass},
                {'icon': '♩', 'label': f'伴奏密度  ({self._bass_density:.0%})', 'command': self._cycle_bass_density},
                {'icon': '⊕', 'label': '熟练度模拟' + (' ✓' if self._proficiency_enabled else ''), 'command': self._toggle_proficiency},
            ],
            '控制': [
                {'icon': '⊞', 'label': 'MIDI 通道控制', 'command': self._show_channel_settings},
                {'icon': '⌨', 'label': '钢琴面板', 'command': self._toggle_piano_panel},
                {'icon': '≡', 'label': '可视化面板', 'command': self._toggle_viz_panel},
                {'icon': '◉', 'label': '状态面板  (延音/模式)', 'command': self._toggle_status_panel},
                {'icon': '⚙', 'label': '控制面板  (音部/速度/移调)', 'command': self._toggle_control_panel},
                {'icon': '⊤', 'label': '滑音: ' + ('ON' if self._glissando else 'OFF'), 'command': self._toggle_glissando},
                {'icon': '◈', 'label': '一键隐藏面板' + (' ✓' if self._panels_hidden else ''), 'command': self._toggle_hide_all_panels},
            ],
            '关于': [
                {'icon': '◇', 'label': '关于本程序', 'command': self._show_about},
                {'icon': '✎', 'label': '修改角色资料', 'command': self._edit_profile},
                {'icon': '◆', 'label': '排行榜', 'command': self._show_leaderboard},
                {'icon': '◇', 'label': '切换到 WebView UI', 'command': self._switch_to_webview_ui},
                {'icon': '↺', 'label': '切换到 Old School UI', 'command': self._switch_to_old_ui},
            ],
        }

    def _setup_sao_menu(self):
        """构建 SAO PopUpMenu 菜单 = 主界面"""
        self._menu_icons = [
            {'name': '文件', 'icon': '☰', 'can_active': True},
            {'name': '播放', 'icon': '▶', 'can_active': True},
            {'name': '设置', 'icon': '⚙', 'can_active': True},
            {'name': '控制', 'icon': '◆', 'can_active': True},
            {'name': '关于', 'icon': 'ℹ', 'can_active': True},
        ]

        self._sao_menu = SAOPopUpMenu(
            self.root, self._menu_icons, self._build_menu_children(),
            username=self._username or 'Player',
            description=self._profession or '咲 Midi Player SAO Edition',
            on_close=self._on_sao_menu_close,
            on_open=self._on_sao_menu_open,
            key_code='a',
            slide_down=False,
            left_widget_factory=self._make_player_panel,
            anchor_widget=self._float,
        )
        self._sao_menu.bind_events()

    def _fade_panel_in(self, panel, target=0.92, duration_ms=350):
        """浮动面板淡入 — 平滑 ease-out 动画, 并确保鱼眼叠加层运行"""
        # 面板打开时, 如果鱼眼尚未启动则启动
        if self._fisheye_ov is None:
            try:
                self.root.after(100, self._start_fisheye_overlay)
            except Exception:
                pass

        t0 = time.time()
        dur = duration_ms / 1000.0

        def _step():
            try:
                if not panel.winfo_exists():
                    return
            except Exception:
                return
            elapsed = time.time() - t0
            t = min(1.0, elapsed / dur)
            et = 1 - (1 - t) ** 3  # ease_out
            panel.attributes('-alpha', target * et)
            if t < 1.0:
                try:
                    self.root.after(16, _step)
                except Exception:
                    pass

        _step()

    def _toggle_sao_menu(self):
        if self._sao_menu.visible:
            try:
                play_sound('menu_close')
            except Exception:
                pass
            self._play_motion_blur(closing=True)
            self._sao_menu.close()
        else:
            try:
                play_sound('menu_open')
            except Exception:
                pass
            self._play_motion_blur(closing=False)
            self._sao_menu.child_menus = self._build_menu_children()
            self._sao_menu.open()
            # 立即将悬浮按钮浮到 overlay 之上 (避免撕裂)
            self._float.lift()

    def _on_sao_menu_open(self):
        """SAO 菜单打开时 — 停止呼吸, 启动持久鱼眼 (Win32 z-order 接管)"""
        self._stop_float_breath()
        # 不启动 _lift_float_loop (tkinter .lift() 会引起闪烁);
        # z-order 完全由 _start_fisheye_overlay 内的 Win32 SetWindowPos 管理
        self._lift_loop_active = False
        # 延迟启动鱼眼叠加 (等菜单渲染完再截图), 带重试确保首次也能生效
        self._start_fisheye_with_retry(retries=5, delay=80)

    def _start_fisheye_with_retry(self, retries=5, delay=80):
        """带重试的鱼眼启动 — 首次进入时菜单可能还未完成渲染"""
        if self._destroyed:
            return
        if self._fisheye_ov is not None:
            return  # 已在运行
        if retries <= 0:
            return
        if self._sao_menu.visible or self._any_panel_open():
            self._start_fisheye_overlay()
        else:
            try:
                self.root.after(delay, lambda: self._start_fisheye_with_retry(retries - 1, delay))
            except Exception:
                pass

    def _any_panel_open(self):
        """检查是否有任何浮动面板处于打开且可见状态"""
        if self._panels_hidden:
            return False
        for p in (self._piano_panel, self._viz_panel,
                  self._status_panel, self._control_panel):
            try:
                if p and p.winfo_exists():
                    return True
            except Exception:
                pass
        return False

    def _maybe_stop_fisheye(self):
        """仅当 SAO 菜单和所有面板都关闭时才销毁鱼眼叠加层"""
        if self._sao_menu.visible:
            return
        if self._any_panel_open():
            return
        self._stop_fisheye_overlay()

    def _on_sao_menu_close(self):
        """SAO 菜单关闭时 — 重启呼吸动画; 面板仍开时保持鱼眼, 否则渐隐销毁"""
        self._lift_loop_active = False
        self._player_panel = None
        self._maybe_stop_fisheye()
        if not self._destroyed:
            self._restore_focus()
            try:
                self.root.after(400, self._start_float_breath)
            except Exception:
                pass

    def _refresh_menu_if_open(self):
        """如果菜单打开, 刷新子菜单和面板"""
        if self._sao_menu.visible:
            children = self._build_menu_children()
            for name, items in children.items():
                self._sao_menu.refresh_child_menu(name, items)
        self._update_float_status()
        self._update_control_panel()

    # ══════════════════════════════════════════════
    #  浮动面板: 钢琴 / 可视化
    # ══════════════════════════════════════════════
    def _toggle_piano_panel(self):
        if self._piano_panel and self._piano_panel.winfo_exists():
            self._piano_panel.destroy()
            self._piano_panel = None
            self._mini_piano = None
            self.settings.set('show_piano', False)
            self.settings.save()
            self._maybe_stop_fisheye()
            try: play_sound('alert_close')
            except: pass
            return

        try: play_sound('panel')
        except: pass

        pw, ph = 500, 100
        _dfx = self._float.winfo_x()
        _dfy = self._float.winfo_y() - ph - 10
        fx = int(self.settings.get('piano_x', _dfx))
        fy = int(self.settings.get('piano_y', _dfy))
        # 防止超出屏幕
        sw2, sh2 = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        fx = max(0, min(fx, sw2 - pw)); fy = max(0, min(fy, sh2 - ph))

        self._piano_panel = tk.Toplevel(self.root)
        self._piano_panel.overrideredirect(True)
        self._piano_panel.attributes('-topmost', True)
        self._piano_panel.attributes('-alpha', 0.0)
        self._piano_panel.geometry(f'{pw}x{ph}+{fx}+{fy}')
        self._piano_panel.configure(bg=_SAO_PANEL_HEADER_BG)

        _apply_panel_style(self._piano_panel)

        # SAO 标题栏
        border = tk.Frame(self._piano_panel, bg=_SAO_PANEL_BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=_SAO_PANEL_BODY_BG)
        inner.pack(fill=tk.BOTH, expand=True)

        hdr, close_lbl = _sao_panel_header(inner, '⌨', 'PIANO', self._toggle_piano_panel)

        # 拖拽
        _pd = {'x': 0, 'y': 0}
        def pdstart(e): _pd['x'], _pd['y'] = e.x_root, e.y_root
        def pdmove(e):
            dx, dy = e.x_root - _pd['x'], e.y_root - _pd['y']
            nx, ny = self._piano_panel.winfo_x()+dx, self._piano_panel.winfo_y()+dy
            self._piano_panel.geometry(f'+{nx}+{ny}')
            _pd['x'], _pd['y'] = e.x_root, e.y_root
            self.settings.set('piano_x', nx); self.settings.set('piano_y', ny)
        for w in [hdr, hdr.winfo_children()[0] if hdr.winfo_children() else hdr]:
            w.bind('<Button-1>', pdstart)
            w.bind('<B1-Motion>', pdmove)

        # 分隔线
        tk.Frame(inner, bg=_SAO_PANEL_ACCENT, height=1).pack(fill=tk.X)

        self._mini_piano = SAOMiniPiano(inner, octaves=5)
        self._mini_piano.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._fade_panel_in(self._piano_panel, target=0.90)
        self._attach_sao_panel_fx(self._piano_panel, hdr, inner)
        self._attach_panel_float(self._piano_panel, phase=0.0)
        self.settings.set('show_piano', True)
        self.settings.save()

    def _toggle_status_panel(self):
        """浮动状态面板 — 显示延音踏板状态 + 模式"""
        if self._status_panel and self._status_panel.winfo_exists():
            self._status_panel.destroy()
            self._status_panel = None
            self.settings.set('show_status', False)
            self.settings.save()
            self._maybe_stop_fisheye()
            try: play_sound('alert_close')
            except: pass
            return

        try: play_sound('panel')
        except: pass
        sw, sh = 220, 200
        saved_sx = self.settings.get('status_x', None)
        saved_sy = self.settings.get('status_y', None)
        if saved_sx is not None:
            fx, fy = int(saved_sx), int(saved_sy)
        else:
            fx = self._float.winfo_x() + self._fw + 10
            fy = self._float.winfo_y()
            if fx + sw > self._float.winfo_screenwidth() - 10:
                fx = self._float.winfo_x() - sw - 10

        self._status_panel = tk.Toplevel(self.root)
        self._status_panel.overrideredirect(True)
        self._status_panel.attributes('-topmost', True)
        self._status_panel.attributes('-alpha', 0.0)
        self._status_panel.geometry(f'{sw}x{sh}+{fx}+{fy}')
        self._status_panel.configure(bg=_SAO_PANEL_HEADER_BG)
        _apply_panel_style(self._status_panel)

        border = tk.Frame(self._status_panel, bg=_SAO_PANEL_BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=_SAO_PANEL_BODY_BG)
        inner.pack(fill=tk.BOTH, expand=True)

        hdr, close_lbl = _sao_panel_header(inner, '◉', 'STATUS', self._toggle_status_panel)

        body = _sao_panel_body(inner)
        body_pad = tk.Frame(body, bg=_SAO_PANEL_BODY_BG)
        body_pad.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # 模式行
        self._status_mode_lbl = _sao_row(body_pad, '模式', self._get_mode_text(),
                                          value_fg=_SAO_PANEL_GOLD,
                                          value_font=get_cjk_font(9, True))

        # 键位模式行
        _sm_labels = {'normal': '普通模式', 'shift': 'SHIFT 高音',
                      'ctrl': 'CTRL 低音', 'lt': 'LT 极低', 'gt': 'GT 极高'}
        _sm_text = _sm_labels.get(self._shift_mode, self._shift_mode)
        self._status_shift_lbl = _sao_row(body_pad, '键位切换', _sm_text,
                                           value_fg='#2196f3')

        # 分隔线
        tk.Frame(body_pad, bg=_SAO_PANEL_SEP, height=1).pack(fill=tk.X, pady=3)

        # 延音行
        sus_row = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        sus_row.pack(fill=tk.X, pady=2)
        tk.Label(sus_row, text='延音踏板', bg=_SAO_PANEL_BODY_BG,
                 fg=_SAO_PANEL_LABEL_FG, font=get_sao_font(8)).pack(side=tk.LEFT)
        self._status_sus_dot = tk.Canvas(sus_row, width=12, height=12,
                                          bg=_SAO_PANEL_BODY_BG, highlightthickness=0)
        self._status_sus_dot.pack(side=tk.RIGHT, padx=(4, 0))
        self._status_sus_lbl = tk.Label(sus_row, text='OFF',
                                         bg=_SAO_PANEL_BODY_BG, fg='#556677',
                                         font=get_sao_font(8, True))
        self._status_sus_lbl.pack(side=tk.RIGHT)

        # BPM行
        bpm_val = getattr(getattr(self.player, 'parser', None), 'bpm', 0)
        self._status_bpm_lbl = _sao_row(body_pad, 'BPM',
                                         f'{bpm_val:.0f}' if bpm_val else '—')

        # 速度行
        self._status_spd_lbl = _sao_row(body_pad, '速度', f'{self._speed:.2f}×')

        # 底部 HUD 装饰
        hud_cv = _sao_panel_hud_canvas(body)
        hud_cv.create_text(4, 8, text='SYS:STATUS', anchor='w',
                           font=('Consolas', 6), fill='#d0d0d0')
        hud_cv.create_line(80, 8, sw - 10, 8, fill='#e8e8e8', width=1)

        # 拖拽
        _sd = {'x': 0, 'y': 0}
        def sdstart(e): _sd['x'], _sd['y'] = e.x_root, e.y_root
        def sdmove(e):
            dx, dy = e.x_root - _sd['x'], e.y_root - _sd['y']
            nx, ny = self._status_panel.winfo_x()+dx, self._status_panel.winfo_y()+dy
            self._status_panel.geometry(f'+{nx}+{ny}')
            _sd['x'], _sd['y'] = e.x_root, e.y_root
            self.settings.set('status_x', nx); self.settings.set('status_y', ny)
        hdr.bind('<Button-1>', sdstart)
        hdr.bind('<B1-Motion>', sdmove)

        self._fade_panel_in(self._status_panel, target=0.92)
        self._attach_sao_panel_fx(self._status_panel, hdr, inner)
        self._attach_panel_float(self._status_panel, phase=2.0)
        self._update_status_panel()
        self.settings.set('show_status', True)
        self.settings.save()

    def _get_mode_text(self):
        mode = self.settings.get('mode_system', 'classic')
        return '经典 60 键' if mode == 'classic' else '扩展 88 键'

    def _update_status_panel(self):
        """刷新状态面板内容 (sustain / speed / bpm)"""
        if not (self._status_panel and self._status_panel.winfo_exists()):
            return
        # 延音
        if self._sustain_active:
            self._status_sus_lbl.configure(text='ON', fg='#3ad86c')
            self._status_sus_dot.delete('all')
            self._status_sus_dot.create_oval(1, 1, 11, 11, fill='#3ad86c', outline='')
        else:
            self._status_sus_lbl.configure(text='OFF', fg='#556677')
            self._status_sus_dot.delete('all')
            self._status_sus_dot.create_oval(1, 1, 11, 11, fill='#2a3545', outline='#3a4a5a')
        # 模式
        if hasattr(self, '_status_mode_lbl'):
            self._status_mode_lbl.configure(text=self._get_mode_text())
        # 速度
        if hasattr(self, '_status_spd_lbl'):
            self._status_spd_lbl.configure(text=f'{self._speed:.2f}×')
        # BPM
        if hasattr(self, '_status_bpm_lbl'):
            bpm_val = getattr(getattr(self.player, 'parser', None), 'bpm', 0)
            self._status_bpm_lbl.configure(text=f'{bpm_val:.0f}' if bpm_val else '—')
        # 键位切换
        if hasattr(self, '_status_shift_lbl'):
            _sm_labels = {'normal': '普通模式', 'shift': 'SHIFT 高音',
                          'ctrl': 'CTRL 低音', 'lt': 'LT 极低', 'gt': 'GT 极高'}
            _sm_text = _sm_labels.get(self._shift_mode, self._shift_mode)
            _sm_color = '#2196f3' if self._shift_mode == 'normal' else ('#1565c0' if self._shift_mode == 'shift' else '#e65100')
            self._status_shift_lbl.configure(text=_sm_text, fg=_sm_color)

    def _toggle_viz_panel(self):
        if self._viz_panel and self._viz_panel.winfo_exists():
            self._viz_panel.destroy()
            self._viz_panel = None
            self._visualizer = None
            self.settings.set('show_viz', False)
            self.settings.save()
            self._maybe_stop_fisheye()
            try: play_sound('alert_close')
            except: pass
            return

        try: play_sound('panel')
        except: pass
        vw, vh = 200, 300
        _dfx = self._float.winfo_x() - vw - 10
        _dfy = self._float.winfo_y() - vh + 50
        fx = int(self.settings.get('viz_x', _dfx))
        fy = int(self.settings.get('viz_y', _dfy))
        sw2, sh2 = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        fx = max(0, min(fx, sw2 - vw)); fy = max(0, min(fy, sh2 - vh))

        self._viz_panel = tk.Toplevel(self.root)
        self._viz_panel.overrideredirect(True)
        self._viz_panel.attributes('-topmost', True)
        self._viz_panel.attributes('-alpha', 0.0)
        self._viz_panel.geometry(f'{vw}x{vh}+{fx}+{fy}')
        self._viz_panel.configure(bg=_SAO_PANEL_HEADER_BG)

        _apply_panel_style(self._viz_panel)

        border = tk.Frame(self._viz_panel, bg=_SAO_PANEL_BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=_SAO_PANEL_BODY_BG)
        inner.pack(fill=tk.BOTH, expand=True)

        hdr, close_lbl = _sao_panel_header(inner, '≡', 'VISUALIZER', self._toggle_viz_panel)

        _vd = {'x': 0, 'y': 0}
        def vdstart(e): _vd['x'], _vd['y'] = e.x_root, e.y_root
        def vdmove(e):
            dx, dy = e.x_root - _vd['x'], e.y_root - _vd['y']
            nx, ny = self._viz_panel.winfo_x()+dx, self._viz_panel.winfo_y()+dy
            self._viz_panel.geometry(f'+{nx}+{ny}')
            _vd['x'], _vd['y'] = e.x_root, e.y_root
            self.settings.set('viz_x', nx); self.settings.set('viz_y', ny)
        for w in [hdr]:
            w.bind('<Button-1>', vdstart)
            w.bind('<B1-Motion>', vdmove)

        # 分隔线
        tk.Frame(inner, bg=_SAO_PANEL_ACCENT, height=1).pack(fill=tk.X)

        self._visualizer = MidiVisualizer(inner, settings=self.settings)
        self._visualizer.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        _apply_viz_light_theme(self._visualizer)
        if self._playing:
            self._visualizer.start()
        self._fade_panel_in(self._viz_panel, target=0.90)
        self._attach_sao_panel_fx(self._viz_panel, hdr, inner)
        self._attach_panel_float(self._viz_panel, phase=1.0)
        self.settings.set('show_viz', True)
        self.settings.save()

    # ══════════════════════════════════════════════
    #  LINK START 入场
    # ══════════════════════════════════════════════
    def _toggle_control_panel(self):
        """浮动控制面板 — 音部/速度/移调/选项全览"""
        if self._control_panel and self._control_panel.winfo_exists():
            self._control_panel.destroy()
            self._control_panel = None
            self.settings.set('show_control', False)
            self.settings.save()
            self._maybe_stop_fisheye()
            try: play_sound('alert_close')
            except: pass
            return

        try: play_sound('panel')
        except: pass
        PW, PH = 295, 305
        _dfx = self._float.winfo_x() - PW - 10
        _dfy = self._float.winfo_y()
        fx = int(self.settings.get('ctrl_x', _dfx))
        fy = int(self.settings.get('ctrl_y', _dfy))
        sw2, sh2 = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        fx = max(0, min(fx, sw2 - PW))
        fy = max(0, min(fy, sh2 - PH))

        self._control_panel = tk.Toplevel(self.root)
        self._control_panel.overrideredirect(True)
        self._control_panel.attributes('-topmost', True)
        self._control_panel.attributes('-alpha', 0.0)
        self._control_panel.geometry(f'{PW}x{PH}+{fx}+{fy}')
        self._control_panel.configure(bg=_SAO_PANEL_HEADER_BG)
        _apply_panel_style(self._control_panel)

        border = tk.Frame(self._control_panel, bg=_SAO_PANEL_BORDER, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=_SAO_PANEL_BODY_BG)
        inner.pack(fill=tk.BOTH, expand=True)

        # SAO 标题栏
        hdr, close_lbl = _sao_panel_header(inner, '⚙', 'CONTROL', self._toggle_control_panel)
        _cd = {'x': 0, 'y': 0}
        def cdstart(e): _cd['x'], _cd['y'] = e.x_root, e.y_root
        def cdmove(e):
            dx, dy = e.x_root - _cd['x'], e.y_root - _cd['y']
            nx, ny = self._control_panel.winfo_x()+dx, self._control_panel.winfo_y()+dy
            self._control_panel.geometry(f'+{nx}+{ny}')
            _cd['x'], _cd['y'] = e.x_root, e.y_root
            self.settings.set('ctrl_x', nx); self.settings.set('ctrl_y', ny)
        hdr.bind('<Button-1>', cdstart); hdr.bind('<B1-Motion>', cdmove)

        body = _sao_panel_body(inner)
        body_pad = tk.Frame(body, bg=_SAO_PANEL_BODY_BG)
        body_pad.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # ── pill 切换按钮辅助 (使用 SAO 风格) ──
        pill = _sao_pill

        # ── 键位模式 ──
        row_mode = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_mode.pack(fill=tk.X, pady=(2, 3))
        tk.Label(row_mode, text='键位', bg=_SAO_PANEL_BODY_BG,
                 fg=_SAO_PANEL_LABEL_FG,
                 font=get_sao_font(8), width=5, anchor='w').pack(side=tk.LEFT)
        cur_mode = self.settings.get('mode_system', 'classic')
        p60 = pill(row_mode, '60键 CTRL/SHIFT', cur_mode == 'classic',  lambda: self._set_mode('classic'))
        p60.pack(side=tk.LEFT, padx=(0, 4))
        p88 = pill(row_mode, '88键 </>',        cur_mode == 'extended', lambda: self._set_mode('extended'))
        p88.pack(side=tk.LEFT)
        self._control_panel._mode_pills = (p60, p88)

        tk.Frame(body_pad, bg=_SAO_PANEL_SEP, height=1).pack(fill=tk.X, pady=4)

        # ── 音部控制 ──
        row_part = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_part.pack(fill=tk.X, pady=2)
        tk.Label(row_part, text='音部', bg=_SAO_PANEL_BODY_BG, fg=_SAO_PANEL_LABEL_FG,
                 font=get_sao_font(8), width=5, anchor='w').pack(side=tk.LEFT)
        pm = pill(row_part, '✓ 主旋律' if self._melody_on else '✗ 主旋律', self._melody_on, self._toggle_melody)
        pm.pack(side=tk.LEFT, padx=(0, 4))
        pb = pill(row_part, '✓ 低音部' if self._bass_on else '✗ 低音部', self._bass_on, self._toggle_bass)
        pb.pack(side=tk.LEFT)
        self._control_panel._part_pills = (pm, pb)

        # ── 伴奏密度 ──
        row_dens = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_dens.pack(fill=tk.X, pady=2)
        tk.Label(row_dens, text='伴奏密度', bg=_SAO_PANEL_BODY_BG, fg=_SAO_PANEL_LABEL_FG,
                 font=get_sao_font(8), anchor='w').pack(side=tk.LEFT)
        dens_var = tk.DoubleVar(value=self._bass_density)
        dens_scale = tk.Scale(row_dens, from_=0.2, to=1.0, resolution=0.1,
                              orient=tk.HORIZONTAL, variable=dens_var,
                              bg=_SAO_PANEL_BODY_BG, fg=_SAO_PANEL_LABEL_FG,
                              troughcolor='#1a2a3a',
                              highlightthickness=0, bd=0, length=100, sliderlength=14,
                              width=10, showvalue=False,
                              command=lambda v: self._set_bass_density_direct(float(v)))
        dens_scale.pack(side=tk.LEFT, padx=(6, 2))
        dens_lbl = tk.Label(row_dens, text=f'{self._bass_density:.0%}', bg=_SAO_PANEL_BODY_BG,
                             fg=_SAO_PANEL_VALUE_FG, font=get_sao_font(8, True), width=4)
        dens_lbl.pack(side=tk.LEFT)
        self._control_panel._dens_var = dens_var
        self._control_panel._dens_lbl = dens_lbl

        tk.Frame(body_pad, bg=_SAO_PANEL_SEP, height=1).pack(fill=tk.X, pady=4)

        # ── 速度 ──
        row_spd = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_spd.pack(fill=tk.X, pady=2)
        tk.Label(row_spd, text='速度', bg=_SAO_PANEL_BODY_BG, fg=_SAO_PANEL_LABEL_FG,
                 font=get_sao_font(8), width=5, anchor='w').pack(side=tk.LEFT)
        btn_sm = tk.Label(row_spd, text='−', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                          font=get_sao_font(10, True), padx=7, pady=1, cursor='hand2')
        btn_sm.pack(side=tk.LEFT)
        btn_sm.bind('<Button-1>', lambda e: self._speed_down())
        spd_lbl = tk.Label(row_spd, text=f'{self._speed:.2f}×', bg=_SAO_PANEL_BODY_BG,
                            fg=_SAO_PANEL_VALUE_FG, font=get_sao_font(9, True), width=6)
        spd_lbl.pack(side=tk.LEFT, padx=4)
        btn_sp = tk.Label(row_spd, text='+', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                          font=get_sao_font(10, True), padx=7, pady=1, cursor='hand2')
        btn_sp.pack(side=tk.LEFT)
        btn_sp.bind('<Button-1>', lambda e: self._speed_up())
        self._control_panel._spd_lbl = spd_lbl

        # ── 移调 ──
        row_tr = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_tr.pack(fill=tk.X, pady=2)
        tk.Label(row_tr, text='移调', bg=_SAO_PANEL_BODY_BG, fg=_SAO_PANEL_LABEL_FG,
                 font=get_sao_font(8), width=5, anchor='w').pack(side=tk.LEFT)
        btn_tm = tk.Label(row_tr, text='−', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                          font=get_sao_font(10, True), padx=7, pady=1, cursor='hand2')
        btn_tm.pack(side=tk.LEFT)
        btn_tm.bind('<Button-1>', lambda e: self._transpose_down())
        tr_lbl = tk.Label(row_tr, text=f'{self._transpose:+d} 半音', bg=_SAO_PANEL_BODY_BG,
                           fg=_SAO_PANEL_VALUE_FG, font=get_sao_font(9, True), width=7)
        tr_lbl.pack(side=tk.LEFT, padx=4)
        btn_tp = tk.Label(row_tr, text='+', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                          font=get_sao_font(10, True), padx=7, pady=1, cursor='hand2')
        btn_tp.pack(side=tk.LEFT)
        btn_tp.bind('<Button-1>', lambda e: self._transpose_up())
        btn_rst = tk.Label(row_tr, text='重置', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                           font=get_sao_font(8), padx=6, pady=2, cursor='hand2')
        btn_rst.pack(side=tk.LEFT, padx=(6, 0))
        btn_rst.bind('<Button-1>', lambda e: self._auto_transpose())
        self._control_panel._tr_lbl = tr_lbl

        tk.Frame(body_pad, bg=_SAO_PANEL_SEP, height=1).pack(fill=tk.X, pady=4)

        # ── 选项行 1 ──
        row_opt1 = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_opt1.pack(fill=tk.X, pady=2)
        dc_lbl = pill(row_opt1, 'C调直转 ✓' if self._direct_c else 'C调直转',
                      self._direct_c, self._toggle_direct_c)
        dc_lbl.pack(side=tk.LEFT, padx=(0, 6))
        pf_lbl = pill(row_opt1, '熟练度 ✓' if self._proficiency_enabled else '熟练度',
                      self._proficiency_enabled, self._toggle_proficiency)
        pf_lbl.pack(side=tk.LEFT)
        self._control_panel._dc_lbl = dc_lbl
        self._control_panel._pf_lbl = pf_lbl

        # ── 选项行 2 ──
        row_opt2 = tk.Frame(body_pad, bg=_SAO_PANEL_BODY_BG)
        row_opt2.pack(fill=tk.X, pady=2)
        gl_lbl = pill(row_opt2, '结尾滑奏 ✓' if self._glissando else '结尾滑奏',
                      self._glissando, self._toggle_glissando)
        gl_lbl.pack(side=tk.LEFT, padx=(0, 6))
        midi_btn = tk.Label(row_opt2, text='MIDI通道…', bg='#1a2030', fg=_SAO_PANEL_LABEL_FG,
                            font=get_sao_font(8), padx=8, pady=2, cursor='hand2')
        midi_btn.pack(side=tk.LEFT)
        midi_btn.bind('<Button-1>', lambda e: self._show_channel_settings())
        self._control_panel._gl_lbl = gl_lbl

        self._fade_panel_in(self._control_panel, target=0.95)
        self._attach_sao_panel_fx(self._control_panel, hdr, inner)
        self._attach_panel_float(self._control_panel, phase=3.0)
        self.settings.set('show_control', True)
        self.settings.save()

    def _update_control_panel(self):
        """刷新控制面板所有动态显示"""
        p = self._control_panel
        if p is None or not p.winfo_exists():
            return
        if hasattr(p, '_spd_lbl'):
            p._spd_lbl.configure(text=f'{self._speed:.2f}×')
        if hasattr(p, '_tr_lbl'):
            p._tr_lbl.configure(text=f'{self._transpose:+d} 半音')
        if hasattr(p, '_dens_lbl'):
            p._dens_lbl.configure(text=f'{self._bass_density:.0%}')
        if hasattr(p, '_dens_var'):
            p._dens_var.set(self._bass_density)
        if hasattr(p, '_part_pills'):
            pm, pb = p._part_pills
            pm.configure(bg='#f3af12' if self._melody_on else '#1a2030',
                         fg='#ffffff' if self._melody_on else '#8a9aaa',
                         text='✓ 主旋律' if self._melody_on else '✗ 主旋律')
            pb.configure(bg='#f3af12' if self._bass_on else '#1a2030',
                         fg='#ffffff' if self._bass_on else '#8a9aaa',
                         text='✓ 低音部' if self._bass_on else '✗ 低音部')
        if hasattr(p, '_mode_pills'):
            p60, p88 = p._mode_pills
            cur = self.settings.get('mode_system', 'classic')
            p60.configure(bg='#f3af12' if cur == 'classic' else '#1a2030',
                          fg='#ffffff' if cur == 'classic' else '#8a9aaa')
            p88.configure(bg='#f3af12' if cur == 'extended' else '#1a2030',
                          fg='#ffffff' if cur == 'extended' else '#8a9aaa')
        if hasattr(p, '_dc_lbl'):
            p._dc_lbl.configure(
                text='C调直转 ✓' if self._direct_c else 'C调直转',
                bg='#f3af12' if self._direct_c else '#1a2030',
                fg='#ffffff' if self._direct_c else '#8a9aaa')
        if hasattr(p, '_pf_lbl'):
            p._pf_lbl.configure(
                text='熟练度 ✓' if self._proficiency_enabled else '熟练度',
                bg='#f3af12' if self._proficiency_enabled else '#1a2030',
                fg='#ffffff' if self._proficiency_enabled else '#8a9aaa')
        if hasattr(p, '_gl_lbl'):
            p._gl_lbl.configure(
                text='结尾滑奏 ✓' if self._glissando else '结尾滑奏',
                bg='#f3af12' if self._glissando else '#1a2030',
                fg='#ffffff' if self._glissando else '#8a9aaa')

    def _set_bass_density_direct(self, val: float):
        """直接设置伴奏密度 (由控制面板滑块调用)"""
        self._bass_density = round(val, 1)
        self.player.set_bass_density(self._bass_density)
        if self._control_panel and self._control_panel.winfo_exists():
            if hasattr(self._control_panel, '_dens_lbl'):
                self._control_panel._dens_lbl.configure(text=f'{self._bass_density:.0%}')
        self._refresh_menu_if_open()

    def _toggle_hide_all_panels(self):
        """一键隐藏/显示所有浮动面板 (不销毁, 只是 withdraw/deiconify)"""
        panels = [
            ('piano',   self._piano_panel),
            ('viz',     self._viz_panel),
            ('status',  self._status_panel),
            ('control', self._control_panel),
        ]

        if not self._panels_hidden:
            # ── 隐藏 ──
            self._hidden_panels_snapshot = []
            for name, p in panels:
                try:
                    if p and p.winfo_exists():
                        self._hidden_panels_snapshot.append(name)
                        p.withdraw()
                except Exception:
                    pass
            self._panels_hidden = True
            self._maybe_stop_fisheye()
        else:
            # ── 恢复 ──
            for name, p in panels:
                try:
                    if name in self._hidden_panels_snapshot and p and p.winfo_exists():
                        p.deiconify()
                        p.lift()
                except Exception:
                    pass
            self._hidden_panels_snapshot = []
            self._panels_hidden = False
            # 面板恢复后确保鱼眼也恢复
            if self._fisheye_ov is None and self._any_panel_open():
                self.root.after(100, self._start_fisheye_overlay)

        self._refresh_menu_if_open()

    def _restore_panels(self):
        """恢复上次会话中打开的浮动面板"""
        # 如果面板处于隐藏状态则跳过恢复
        if self._panels_hidden:
            return
        if self.settings.get('show_piano', False):
            if not (self._piano_panel and self._piano_panel.winfo_exists()):
                self._toggle_piano_panel()
        if self.settings.get('show_viz', False):
            if not (self._viz_panel and self._viz_panel.winfo_exists()):
                self._toggle_viz_panel()
        if self.settings.get('show_status', False):
            if not (self._status_panel and self._status_panel.winfo_exists()):
                self._toggle_status_panel()
        if self.settings.get('show_control', False):
            if not (self._control_panel and self._control_panel.winfo_exists()):
                self._toggle_control_panel()

    # ══════════════════════════════════════════════════════════════
    #  点击悬浮按钮 → 径向运动模糊闪现
    # ══════════════════════════════════════════════════════════════
    def _play_motion_blur(self, closing=False):
        """
        悬浮按钮点击时的径向运动模糊效果 (SAO 菜单展开/收起).

        以悬浮按钮为中心, 截取屏幕 → 径向缩放模糊 → 叠加层渐隐.
        • 后台线程: 截屏 + 径向模糊
        • 主线程: 显示结果 + 渐隐动画
        • WDA_EXCLUDEFROMCAPTURE: 防止鱼眼层捕获到此叠加层 (消除撕裂)
        • BILINEAR 缩放: 减少锯齿/马赛克感
        """
        try:
            from PIL import ImageGrab, Image, ImageTk, ImageFilter
        except ImportError:
            return

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        # 悬浮按钮中心作为模糊焦点
        try:
            fx = self._float.winfo_x() + self._fw // 2
            fy = self._float.winfo_y() + self._fh // 2
        except Exception:
            fx, fy = sw // 2, sh // 2

        def _build_and_show():
            """后台: 截屏 + 径向模糊 → 主线程显示."""
            # 截屏
            shot = None
            try:
                import mss as _mss_mod
                _sct = _mss_mod.mss()
                _mon = {"top": 0, "left": 0, "width": sw, "height": sh}
                s = _sct.grab(_mon)
                shot = Image.frombytes('RGB', s.size, s.rgb)
            except Exception:
                pass
            if shot is None:
                for _g in (
                    lambda: ImageGrab.grab(bbox=(0, 0, sw, sh), all_screens=True),
                    lambda: ImageGrab.grab(bbox=(0, 0, sw, sh)),
                    lambda: ImageGrab.grab(),
                ):
                    try:
                        shot = _g()
                        break
                    except Exception:
                        continue
            if shot is None:
                return

            # 半分辨率处理 (1/2 而非 1/3, 提升清晰度)
            hw, hh = sw // 2, sh // 2
            small = shot.resize((hw, hh), Image.BILINEAR)
            cx, cy = fx / 2.0, fy / 2.0

            # 径向缩放模糊: 多次微缩放叠加
            import numpy as np
            acc = np.array(small, dtype=np.float32)
            n_layers = 5
            for i in range(1, n_layers + 1):
                scale = 1.0 + i * 0.012
                nw = int(hw * scale)
                nh = int(hh * scale)
                zoomed = small.resize((nw, nh), Image.BILINEAR)
                ox = int(cx * scale - cx)
                oy = int(cy * scale - cy)
                ox = max(0, min(ox, nw - hw))
                oy = max(0, min(oy, nh - hh))
                crop = zoomed.crop((ox, oy, ox + hw, oy + hh))
                acc += np.array(crop, dtype=np.float32)
            blurred = Image.fromarray(
                (acc / (n_layers + 1)).clip(0, 255).astype(np.uint8))

            from PIL import ImageEnhance
            if closing:
                blurred = ImageEnhance.Brightness(blurred).enhance(0.85)
            else:
                blurred = ImageEnhance.Brightness(blurred).enhance(1.12)

            full = blurred.resize((sw, sh), Image.BILINEAR)

            try:
                self.root.after(0, lambda img=full: _display(img))
            except Exception:
                pass

        def _display(pil_img):
            """主线程: 显示模糊图 + 350ms ease-out 渐隐."""
            try:
                mb_ov = tk.Toplevel(self.root)
                mb_ov.overrideredirect(True)
                mb_ov.attributes('-topmost', True)
                mb_ov.attributes('-alpha', 0.0)
                mb_ov.geometry(f'{sw}x{sh}+0+0')
                cv = tk.Canvas(mb_ov, width=sw, height=sh,
                               highlightthickness=0, bg='black')
                cv.pack(fill=tk.BOTH, expand=True)
                photo = ImageTk.PhotoImage(pil_img)
                cv.create_image(0, 0, image=photo, anchor='nw')
                cv._photo = photo

                # WDA_EXCLUDEFROMCAPTURE: 鱼眼截屏不会捕获到此 overlay
                try:
                    import ctypes as _ct
                    _u32 = _ct.windll.user32
                    mb_ov.update_idletasks()
                    hwnd = _u32.GetParent(mb_ov.winfo_id()) or mb_ov.winfo_id()
                    _u32.SetWindowDisplayAffinity(hwnd, 0x00000011)
                except Exception:
                    pass
            except Exception:
                return

            # 快速渐入 (50ms) → 缓慢渐隐 (350ms), 消除突然出现的闪烁感
            _t0 = time.time()
            _fadein_dur = 0.05
            _fadeout_dur = 0.35
            _peak = 0.72

            def _mblur_anim():
                dt = time.time() - _t0
                if dt < _fadein_dur:
                    # 渐入阶段
                    a = _peak * (dt / _fadein_dur)
                elif dt < _fadein_dur + _fadeout_dur:
                    # 渐隐阶段
                    t = (dt - _fadein_dur) / _fadeout_dur
                    a = _peak * (1.0 - t ** 0.6)
                else:
                    try: mb_ov.destroy()
                    except Exception: pass
                    return
                try: mb_ov.attributes('-alpha', max(0.0, a))
                except Exception: pass
                try: mb_ov.after(16, _mblur_anim)
                except Exception: pass

            mb_ov.after(1, _mblur_anim)

        import threading as _th
        _th.Thread(target=_build_and_show, daemon=True).start()

    # ══════════════════════════════════════════════════════════════
    #  持久鱼眼叠加层 (菜单开启时常驻, 关闭时销毁)
    # ══════════════════════════════════════════════════════════════
    def _start_fisheye_overlay(self):
        """
        SAO 菜单开启期间的持久鱼眼叠加层 (实时 60fps 双缓冲).

        架构:
          • 后台 _worker 线程: 截屏 + GPU/numpy 畸变 + 缩放 → _latest_frame
          • 主线程 16ms _tick 状态机: 从 _latest_frame 读 → PhotoImage → canvas
          • 保证 60fps 显示 (alpha 动画 + 内容), 捕获帧率按硬件自适应
          • _tick: init→fadein→active→fadeout→销毁
          • 菜单关闭 16ms 内检测 → 同步渐隐, 无需二次点击
        """
        self._stop_fisheye_overlay()
        if not self._sao_menu.visible and not self._any_panel_open():
            return
        self._lift_loop_active = False

        try:
            from PIL import ImageGrab, Image, ImageTk
        except ImportError:
            return

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        hw, hh = int(sw * 0.85), int(sh * 0.85)   # 85% 分辨率 (清晰度提升)

        # ── 创建叠加层窗口 (不设 topmost, 自然低于 topmost UI) ──
        # GPU/numpy 初始化已移至后台 _worker 线程 (消除主线程阻塞)
        try:
            ov = tk.Toplevel(self.root)
            ov.overrideredirect(True)
            # 不设 -topmost: overlay 位于所有 topmost 窗口下方
            ov.attributes('-alpha', 0.0)
            ov.geometry(f'{sw}x{sh}+0+0')
            cv_ov = tk.Canvas(ov, width=sw, height=sh,
                              highlightthickness=0, bg='black')
            cv_ov.pack(fill=tk.BOTH, expand=True)
            ov._cv = cv_ov
            ov._img_id = None
            self._fisheye_ov = ov
        except Exception:
            return

        # ── Win32 API (64-bit safe) ──
        _hwnd_ref = [0]
        try:
            import ctypes as _ct
            _u32 = _ct.windll.user32
            _vp = _ct.c_void_p
            _u32.GetParent.argtypes                 = [_vp]
            _u32.GetParent.restype                  = _vp
            _u32.GetWindowLongW.argtypes            = [_vp, _ct.c_int]
            _u32.GetWindowLongW.restype             = _ct.c_long
            _u32.SetWindowLongW.argtypes            = [_vp, _ct.c_int, _ct.c_long]
            _u32.SetWindowLongW.restype             = _ct.c_long
            _u32.SetLayeredWindowAttributes.argtypes = [_vp, _ct.c_uint,
                                                        _ct.c_ubyte, _ct.c_uint]
            _u32.SetLayeredWindowAttributes.restype  = _ct.c_int
            # SetWindowDisplayAffinity (Win10 2004+): 排除屏幕捕获
            _u32.SetWindowDisplayAffinity.argtypes  = [_vp, _ct.c_uint]
            _u32.SetWindowDisplayAffinity.restype   = _ct.c_int
        except Exception:
            _u32 = None

        _GWL_EXSTYLE       = -20
        _WS_EX_TRANSPARENT = 0x00000020
        _LWA_ALPHA         = 0x00000002
        _WDA_EXCLUDEFROMCAPTURE = 0x00000011

        def _set_alpha(bv):
            if _hwnd_ref[0] and _u32:
                try:
                    _u32.SetLayeredWindowAttributes(
                        _hwnd_ref[0], 0, bv, _LWA_ALPHA)
                except Exception:
                    pass

        def _init_layered():
            if not _u32:
                return
            try:
                ov.update_idletasks()
                hwnd = _u32.GetParent(ov.winfo_id()) or ov.winfo_id()
                _hwnd_ref[0] = hwnd
                cur = _u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
                _u32.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                                    cur | _WS_EX_TRANSPARENT)
                _u32.SetLayeredWindowAttributes(hwnd, 0, 0, _LWA_ALPHA)
                # WDA_EXCLUDEFROMCAPTURE: 叠加层对 ImageGrab 不可见
                try:
                    _u32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)
                except Exception:
                    pass
            except Exception:
                pass

        # ── 60fps 双缓冲状态机 ──
        _ALPHA_MAX = 255
        _alpha_cur = [0.0]
        _FADEIN_STEP = _ALPHA_MAX / 38.0     # 38 × 16ms ≈ 600ms 渐显
        _FADEOUT_STEP = _ALPHA_MAX / 25.0    # 25 × 16ms ≈ 400ms 渐隐
        _running = [True]
        _latest_frame = [None]   # 后台线程写, 主线程读 (GIL 原子)
        _state = ['init']        # init → fadein → active → fadeout → 销毁
        _last_shown = [None]     # 去重: 同帧不重建 PhotoImage

        def _show(frame):
            """仅在新帧到达时创建 PhotoImage (跳过重复帧)."""
            if frame is None or frame is _last_shown[0]:
                return
            _last_shown[0] = frame
            try:
                photo = ImageTk.PhotoImage(frame)
                if ov._img_id is None:
                    ov._img_id = cv_ov.create_image(
                        0, 0, image=photo, anchor='nw')
                else:
                    cv_ov.itemconfig(ov._img_id, image=photo)
                cv_ov._photo = photo
            except Exception:
                pass

        def _tick():
            """主线程 60fps 状态机: fadein / display / fadeout 全在此."""
            if self._fisheye_ov is None:
                return
            s = _state[0]
            if s == 'init':
                f = _latest_frame[0]
                if f is not None:
                    _show(f)
                    _state[0] = 'fadein'
            elif s == 'fadein':
                if not self._sao_menu.visible:
                    _state[0] = 'fadeout'
                    _running[0] = False
                else:
                    _alpha_cur[0] = min(_ALPHA_MAX,
                                        _alpha_cur[0] + _FADEIN_STEP)
                    _set_alpha(int(_alpha_cur[0]))
                    _show(_latest_frame[0])
                    if _alpha_cur[0] >= _ALPHA_MAX:
                        _state[0] = 'active'
            elif s == 'active':
                if not self._sao_menu.visible:
                    _state[0] = 'fadeout'
                    _running[0] = False
                else:
                    _show(_latest_frame[0])
            elif s == 'fadeout':
                _alpha_cur[0] = max(0, _alpha_cur[0] - _FADEOUT_STEP)
                _set_alpha(int(_alpha_cur[0]))
                if _alpha_cur[0] <= 0:
                    self._stop_fisheye_overlay()
                    return
            try: ov.after(16, _tick)
            except Exception: pass

        if self._destroyed:
            return
        ov.after(30, _init_layered)
        ov.after(50, _tick)

        # ── 后台 worker: 截屏 + 畸变 + 缩放 → _latest_frame ──
        def _worker():
            """后台线程: 全部重活在此, 主线程仅 PhotoImage."""
            import time as _time

            # ── 优先 mss 快速截屏 (DXGI, ~5ms), fallback ImageGrab (~30ms) ──
            _cap_fn = None
            try:
                import mss as _mss_mod
                _sct = _mss_mod.mss()
                _mon = {"top": 0, "left": 0, "width": sw, "height": sh}
                def _cap_mss():
                    s = _sct.grab(_mon)
                    return Image.frombytes('RGB', s.size, s.rgb)
                _cap_fn = _cap_mss
            except Exception:
                pass
            if _cap_fn is None:
                def _cap_ig():
                    for _g in (
                        lambda: ImageGrab.grab(bbox=(0, 0, sw, sh),
                                               all_screens=True),
                        lambda: ImageGrab.grab(bbox=(0, 0, sw, sh)),
                        lambda: ImageGrab.grab(),
                    ):
                        try: return _g()
                        except Exception: continue
                    return None
                _cap_fn = _cap_ig

            # ── GPU 初始化 (GL 上下文在本线程创建 & 使用, 线程安全) ──
            _gl_ok = False
            _ctx = _prog = _vbo = _vao = _tex = _fbo = None
            try:
                import moderngl
                _ctx = moderngl.create_standalone_context()
                _prog = _ctx.program(
                    vertex_shader='''
                        #version 330
                        in vec2 in_pos;
                        out vec2 uv;
                        void main() {
                            gl_Position = vec4(in_pos, 0.0, 1.0);
                            uv = in_pos * 0.5 + 0.5;
                        }
                    ''',
                    fragment_shader='''
                        #version 330
                        uniform sampler2D tex;
                        uniform float strength;
                        in vec2 uv;
                        out vec4 fragColor;
                        void main() {
                            vec2 c = uv - 0.5;
                            float r2 = dot(c, c);
                            vec2 d = uv + c * strength * r2;
                            fragColor = texture(tex, d);
                        }
                    '''
                )
                import numpy as _np
                _verts = _np.array([-1, -1, 3, -1, -1, 3], dtype='f4')
                _vbo = _ctx.buffer(_verts)
                _vao = _ctx.simple_vertex_array(_prog, _vbo, 'in_pos')
                _tex = _ctx.texture((hw, hh), 3)
                _tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                _fbo = _ctx.framebuffer(
                    color_attachments=[_ctx.texture((hw, hh), 3)])
                _prog['strength'].value = 0.55
                _prog['tex'].value = 0
                _gl_ok = True
            except Exception:
                _ctx = None

            # ── numpy 后备 ──
            qw, qh = (hw, hh) if _gl_ok else (int(sw * 0.5), int(sh * 0.5))
            _np_maps = None
            if not _gl_ok:
                try:
                    import numpy as _np
                except ImportError:
                    return
                cx_, cy_ = qw / 2.0, qh / 2.0
                _yy, _xx = _np.mgrid[0:qh, 0:qw].astype(_np.float32)
                _nx = (_xx - cx_) / cx_;  _ny = (_yy - cy_) / cy_
                _r2 = _nx * _nx + _ny * _ny; _f = 1.0 + 0.55 * _r2
                _sx = _np.clip(cx_ + _nx * _f * cx_, 0.0, qw - 1.0001)
                _sy = _np.clip(cy_ + _ny * _f * cy_, 0.0, qh - 1.0001)
                _x0 = _sx.astype(_np.int32); _x1 = _x0 + 1
                _y0 = _sy.astype(_np.int32); _y1 = _y0 + 1
                _wfx = (_sx - _x0).astype(_np.float32)[..., _np.newaxis]
                _wfy = (_sy - _y0).astype(_np.float32)[..., _np.newaxis]
                _np_maps = (_x0, _x1, _y0, _y1, _wfx, _wfy)

            # ── 主循环: 持续产出帧 → _latest_frame ──
            _frame_interval = 0.033  # 目标 ~30fps (降低 CPU 占用)
            while _running[0]:
                _t_start = _time.time()
                shot = _cap_fn()
                if shot is None or not _running[0]:
                    _time.sleep(0.05)
                    continue
                try:
                    if _gl_ok:
                        small = shot.resize((hw, hh), Image.BILINEAR)
                        _tex.write(small.tobytes())
                        _fbo.use()
                        _ctx.clear()
                        _tex.use(0)
                        _vao.render(moderngl.TRIANGLES)
                        raw = _fbo.color_attachments[0].read()
                        dist = Image.frombytes('RGB', (hw, hh), raw)
                    else:
                        tiny = shot.resize((qw, qh), Image.BILINEAR)
                        _x0, _x1, _y0, _y1, _wfx, _wfy = _np_maps
                        a = _np.array(tiny, dtype=_np.float32)
                        t = a[_y0, _x0] * (1 - _wfx) + a[_y0, _x1] * _wfx
                        b = a[_y1, _x0] * (1 - _wfx) + a[_y1, _x1] * _wfx
                        dist = Image.fromarray(
                            (t * (1 - _wfy) + b * _wfy)
                            .clip(0, 255).astype(_np.uint8))
                except Exception:
                    _time.sleep(0.02)
                    continue
                if not _running[0]:
                    break
                full = dist.resize((sw, sh), Image.BILINEAR)
                _latest_frame[0] = full
                # 限制帧率, 释放 CPU 给主线程
                _elapsed = _time.time() - _t_start
                _sleep = max(0.001, _frame_interval - _elapsed)
                _time.sleep(_sleep)

            # ── 线程退出, 释放 GPU ──
            if _ctx:
                try: _ctx.release()
                except Exception: pass

        import threading as _th
        _th.Thread(target=_worker, daemon=True).start()
        ov._running_ref = _running

    def _stop_fisheye_overlay(self):
        """销毁持久鱼眼叠加层 (GPU 由后台线程自行释放)."""
        ov = self._fisheye_ov
        self._fisheye_ov = None
        if ov is not None:
            running = getattr(ov, '_running_ref', None)
            if running:
                running[0] = False
            try:
                ov.destroy()
            except Exception:
                pass

    # ══════════════════════════════════════════════
    #  LinkStart 入场鱼眼镜头畅变
    # ══════════════════════════════════════════════
    def _run_fisheye_entry(self):
        """
        LinkStart 结束后短暂鱼眼镜头畟变过渡 — 屏幕从弯曲收缩至正常.

        流程: 抓取当前屏幕 → 应用桶形型畟变 (MESH变换) →
                全屏覆盖层显示畟变图 → 0.9s内渐隐 →
                真实 UI 从底层透出 (SAO 镜头对焦效果).
        """
        try:
            from PIL import ImageGrab, Image, ImageTk
        except ImportError:
            return

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        img = None
        for _grab in (
            lambda: ImageGrab.grab(bbox=(0, 0, sw, sh), all_screens=True),
            lambda: ImageGrab.grab(bbox=(0, 0, sw, sh)),
            lambda: ImageGrab.grab(),
        ):
            try:
                img = _grab()
                break
            except Exception:
                continue
        if img is None:
            return

        # 半分辨率处理 (MESH 运算量 1/4)
        half_w, half_h = sw // 2, sh // 2
        small = img.resize((half_w, half_h), Image.BILINEAR)

        def _barrel(src, strength):
            cx_, cy_ = half_w / 2.0, half_h / 2.0
            grid = 18
            mesh_data = []
            for gy in range(0, half_h, grid):
                for gx in range(0, half_w, grid):
                    x1, y1 = gx, gy
                    x2, y2 = min(gx + grid, half_w), min(gy + grid, half_h)
                    src_pts = []
                    for px, py in [(x1, y1), (x1, y2), (x2, y2), (x2, y1)]:
                        nx_ = (px - cx_) / cx_
                        ny_ = (py - cy_) / cy_
                        r2 = nx_ * nx_ + ny_ * ny_
                        f = 1.0 + strength * r2
                        sx = cx_ + nx_ * f * cx_
                        sy = cy_ + ny_ * f * cy_
                        src_pts.extend([
                            max(0.0, min(half_w - 1.0, sx)),
                            max(0.0, min(half_h - 1.0, sy)),
                        ])
                    mesh_data.append(((x1, y1, x2, y2), src_pts))
            return src.transform(src.size, Image.MESH, mesh_data, Image.BILINEAR)

        try:
            dist_half = _barrel(small, 0.50)
            distorted = dist_half.resize((sw, sh), Image.BILINEAR)
        except Exception:
            return

        # 全屏 overlay
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.attributes('-alpha', 1.0)
        ov.geometry(f'{sw}x{sh}+0+0')
        cv_ov = tk.Canvas(ov, width=sw, height=sh,
                          highlightthickness=0, bg='black')
        cv_ov.pack(fill=tk.BOTH, expand=True)
        photo = ImageTk.PhotoImage(distorted)
        cv_ov.create_image(0, 0, image=photo, anchor='nw')
        cv_ov._photo = photo  # 防止 GC

        # ease-in 渐隐: 开始快, 收尾慢 (0.9s 内全透明)
        t0 = time.time()
        dur = 0.90

        def _fade():
            if self._destroyed:
                try: ov.destroy()
                except: pass
                return
            elapsed = time.time() - t0
            if elapsed >= dur:
                try:
                    ov.destroy()
                except Exception:
                    pass
                return
            a = max(0.0, 1.0 - (elapsed / dur) ** 0.6)
            try:
                ov.attributes('-alpha', a)
            except Exception:
                pass
            try:
                self.root.after(16, _fade)
            except Exception:
                pass

        _fade()

    def _play_link_start(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 目标位置: 上次保存的位置, 否则右下角
        saved_x = self.settings.get('float_x', None)
        saved_y = self.settings.get('float_y', None)
        if saved_x is not None and saved_y is not None:
            fx_final = max(0, min(int(saved_x), sw - self._fw))
            fy_final = max(0, min(int(saved_y), sh - self._fh))
        else:
            fx_final = sw - self._fw - 50
            fy_final = sh - 180
        # 起始位置: 屏幕正中央 (LinkStart 动画中心)
        fx_start = sw // 2 - self._fw // 2
        fy_start = sh // 2 + 80   # 略低于中心 (文字下方)

        def on_done():
            self._float.geometry(f'{self._fw}x{self._fh}+{fx_start}+{fy_start}')
            self._set_float_alpha(0.0)
            self._float.deiconify()
            self._float.lift()
            # Re-assert WS_EX_LAYERED (withdraw/deiconify 可能重置)
            try:
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                h = self._float_hwnd
                if h:
                    ex = _user32.GetWindowLongW(ctypes.c_void_p(h), GWL_EXSTYLE)
                    if not (ex & WS_EX_LAYERED):
                        _user32.SetWindowLongW(ctypes.c_void_p(h), GWL_EXSTYLE,
                                               ex | WS_EX_LAYERED)
                        print('[SAO-HP] Re-asserted WS_EX_LAYERED after deiconify')
            except Exception:
                pass
            # 立即绘制全透明 ULW 帧, 防止 deiconify 后暴露 Tk 黑底
            try:
                _blank = Image.new('RGBA', (self._fw, self._fh), (0, 0, 0, 0))
                _update_layered_win(self._float_hwnd, _blank, 0)
            except Exception:
                pass
            self._play_motion_blur(closing=False)
            self._run_entry_animation(fx_start, fy_start, fx_final, fy_final)

        # Canvas 渲染 (SAO-UI 隧道模型)
        ls = SAOLinkStart(self.root, on_done=on_done)
        ls.play()

    def _show_welcome_then_menu(self):
        """首次启动: 显示欢迎对话框, 完成后再打开菜单"""
        def on_profile_done(username, profession):
            self._username = username
            self._profession = profession
            self._update_float_title()
            # 更新 SAO 菜单的用户信息
            if self._sao_menu:
                self._sao_menu.username = username
                self._sao_menu.description = profession or '咲 Midi Player SAO Edition'
            self.root.after(300, self._toggle_sao_menu)

        show_welcome_dialog(self._float, on_done=on_profile_done)

    def _update_float_title(self):
        """更新 HP 组件的用户名"""
        try:
            name = self._username if self._username else 'Player'
            if len(name) > 8:
                name = name[:7] + '…'
            self._hp_display_name = name
            self._refresh_hp_layered()
        except Exception:
            pass

    # ══════════════════════════════════════════════
    #  文件操作
    # ══════════════════════════════════════════════
    def _open_file(self):
        if self._sao_menu.visible:
            self._sao_menu.close()

        last = self.settings.get('last_file', '')
        init_dir = os.path.dirname(last) if last else os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'Midi')
        if not os.path.isdir(init_dir):
            init_dir = os.path.dirname(os.path.abspath(__file__))

        def do_open():
            # 保留引用防止 GC 销毁窗口
            self._picker = SAOFilePicker(
                self._float,
                title='选择 MIDI 文件',
                initial_dir=init_dir,
                filetypes=[('MIDI Files', '*.mid;*.midi'), ('All Files', '*.*')],
                callback=self._on_file_selected,
            )

        # 等 SAO 菜单关闭动画完成再打开文件选择器
        self.root.after(600, do_open)

    def _on_file_selected(self, filepath):
        self._picker = None   # 释放 picker 引用
        if not filepath:
            return
        self._current_file = filepath
        self.settings.set('last_file', filepath)
        fname = os.path.basename(filepath)
        self._update_float_fname(fname)

        # 解析文件
        try:
            from midi_parser import analyze_midi
            info = analyze_midi(filepath)
            if info:
                n_notes = info.get('total_notes', 0)
                bpm    = info.get('bpm', 0)
                total  = info.get('total_time', 0)
                SAODialog.showinfo(
                    self._float, "文件信息",
                    f"文件: {fname}\n音符数: {n_notes}\nBPM: {bpm:.0f}\n时长: {total:.1f}s")
        except Exception as e:
            SAODialog.showerror(self._float, "错误", f"解析失败: {e}")

    # ══════════════════════════════════════════════
    #  播放控制
    # ══════════════════════════════════════════════
    def _toggle_play(self):
        if self._playing and not self._paused:
            self.player.pause()
            self._paused = True
            self._update_float_status()
            self._refresh_menu_if_open()
            if self._player_panel:
                self._player_panel.update_status("已暂停", False)
            return

        if self._paused:
            self.player.resume()
            self._paused = False
            self._update_float_status()
            self._refresh_menu_if_open()
            if self._player_panel:
                self._player_panel.update_status("播放中", True)
            return

        if not self._current_file:
            SAODialog.showwarning(self._float, "提示", "请先打开 MIDI 文件\n(右键悬浮按钮 → 打开文件)")
            return

        try:
            ok = self.player.load_midi(self._current_file)
        except Exception as e:
            SAODialog.showerror(self._float, "错误", f"载入失败:\n{e}")
            return

        if not ok:
            SAODialog.showwarning(self._float, "提示", "文件中没有可用音符")
            return

        self.player.set_speed(self._speed)
        self.player.set_transpose(self._transpose)
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self.player.stop()
        self.player.play()
        bpm = getattr(getattr(self.player, 'parser', None), 'bpm', 120)
        self._playing = True
        self._paused = False
        self._update_float_status()
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_status("播放中", True)
            self._player_panel.update_bpm(bpm)
        if self._visualizer:
            self._visualizer.start()
        self._update_status_panel()

    def _stop(self):
        # 停止循环文件夹
        if self._folder_loop_active:
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
        self.player.stop()
        self._playing = False
        self._paused = False
        self._update_float_status()
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_status("已停止", False)
            self._player_panel.update_progress(0, 0)
        if self._mini_piano:
            self._mini_piano.reset()
        if self._visualizer:
            self._visualizer.stop()

    def _speed_up(self):
        self._speed = min(2.0, round(self._speed + 0.1, 2))
        self.player.set_speed(self._speed)
        self.settings.set('speed', self._speed)
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_speed(self._speed)
        self._update_status_panel()

    def _speed_down(self):
        self._speed = max(0.25, round(self._speed - 0.1, 2))
        self.player.set_speed(self._speed)
        self.settings.set('speed', self._speed)
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_speed(self._speed)
        self._update_status_panel()

    def _transpose_up(self):
        self._transpose = min(24, self._transpose + 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_transpose(self._transpose)

    def _transpose_down(self):
        self._transpose = max(-24, self._transpose - 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_transpose(self._transpose)

    def _auto_transpose(self):
        self._transpose = 0
        self.player.set_transpose(0)
        self.settings.set('transpose', 0)
        if self._current_file:
            try:
                from analyze_transpose import analyze_key
                key_info = analyze_key(self._current_file)
                if key_info:
                    SAODialog.showinfo(self._float, "调性检测",
                                       f"检测到: {key_info.get('key', '?')}")
            except:
                pass
        self._refresh_menu_if_open()
        if self._player_panel:
            self._player_panel.update_transpose(0)

    def _toggle_direct_c(self):
        self._direct_c = not self._direct_c
        self.player.set_direct_c_mode(self._direct_c)
        if not self._direct_c:
            self._transpose = 0
            self.player.set_transpose(0)
            if self._player_panel:
                self._player_panel.update_transpose(0)
        self._refresh_menu_if_open()

    def _toggle_melody(self):
        self._melody_on = not self._melody_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._refresh_menu_if_open()

    def _toggle_bass(self):
        self._bass_on = not self._bass_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._refresh_menu_if_open()

    def _toggle_glissando(self):
        self._glissando = not self._glissando
        self.player._play_ending_glissando = self._glissando
        self._refresh_menu_if_open()

    def _cycle_bass_density(self):
        """循环伴奏密度: 0.3 → 0.6 → 1.0 → 0.3"""
        levels = [0.3, 0.6, 1.0]
        try:
            idx = levels.index(self._bass_density)
            self._bass_density = levels[(idx + 1) % len(levels)]
        except ValueError:
            self._bass_density = 0.6
        self.player.set_bass_density(self._bass_density)
        self._refresh_menu_if_open()

    def _toggle_proficiency(self):
        self._proficiency_enabled = not self._proficiency_enabled
        self.player.set_proficiency_enabled(self._proficiency_enabled)
        self._refresh_menu_if_open()

    def _set_mode(self, mode):
        self.player.set_mode_system(mode)
        self.settings.set('mode_system', mode)
        mode_text = '经典60键' if mode == 'classic' else '扩展88键'
        if self._player_panel:
            self._player_panel.update_mode(mode_text)
        # 更新悬浮面板上的模式
        try:
            pass  # 模式文字已通过 _render_hp_dynamic 统一渲染
        except Exception:
            pass
        self._refresh_menu_if_open()
        self._update_status_panel()

    def _show_channel_settings(self):
        if self._sao_menu.visible:
            self._sao_menu.close()
        self.root.after(600, self._do_show_channel_settings)

    def _do_show_channel_settings(self):
        try:
            from midi_controller import MIDIControllerDialog
            MIDIControllerDialog(self._float, self.player, self.settings,
                                midi_path=self._current_file or '')
        except ImportError:
            SAODialog.showerror(self._float, "错误", "MIDI控制器模块不可用")

    def _toggle_folder_loop(self):
        """切换循环文件夹 — 移植自 Old UI"""
        if self._folder_loop_active:
            # 停止循环
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self.player.stop()
            self._playing = False
            self._paused = False
            self._update_float_status()
            self._refresh_menu_if_open()
            if self._player_panel:
                self._player_panel.update_status("已停止循环", False)
                self._player_panel.update_progress(0, 0)
            if self._mini_piano:
                self._mini_piano.reset()
            if self._visualizer:
                self._visualizer.stop()
            return

        # 关闭 SAO 菜单, 延迟打开文件夹选择器
        if self._sao_menu.visible:
            self._sao_menu.close()
        self.root.after(600, self._do_open_folder_picker)

    def _do_open_folder_picker(self):
        """打开文件夹选择器 (SAOFilePicker dir 模式)"""
        last_folder = self.settings.get('last_folder', '')
        if self._current_file:
            init_dir = os.path.dirname(self._current_file)
        elif last_folder and os.path.isdir(last_folder):
            init_dir = last_folder
        else:
            init_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Midi')
        if not os.path.isdir(init_dir):
            init_dir = os.path.dirname(os.path.abspath(__file__))

        self._picker = SAOFilePicker(
            self._float,
            title='选择循环播放的文件夹',
            initial_dir=init_dir,
            mode='dir',
            callback=self._on_folder_selected,
        )

    def _on_folder_selected(self, folder):
        """文件夹选中回调 — 扫描 MIDI 并开始循环"""
        self._picker = None
        if not folder or not os.path.isdir(folder):
            return

        self.settings.set('last_folder', folder)
        files = sorted([
            os.path.join(folder, f) for f in os.listdir(folder)
            if f.lower().endswith(('.mid', '.midi'))
            and os.path.isfile(os.path.join(folder, f))
        ])
        if not files:
            SAODialog.showwarning(self._float, "提示", "该文件夹下没有 MIDI 文件")
            return

        self._folder_loop_files = files
        self._folder_loop_index = 0
        self._folder_loop_active = True
        self._refresh_menu_if_open()
        self._play_next_folder_song()

    def _play_next_folder_song(self, _retries=0):
        """播放下一首循环文件 — 含重试逻辑"""
        if not self._folder_loop_active or not self._folder_loop_files:
            return
        if _retries >= len(self._folder_loop_files):
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self._refresh_menu_if_open()
            SAODialog.showerror(self._float, "错误", "文件夹中所有文件加载失败，已停止循环")
            return

        filepath = self._folder_loop_files[self._folder_loop_index]
        self._folder_loop_index = (self._folder_loop_index + 1) % len(self._folder_loop_files)

        if self.player.load_midi(filepath):
            self._current_file = filepath
            self.settings.set('last_file', filepath)
            fname = os.path.basename(filepath)
            self._update_float_fname(fname)
            self._transpose = 0
            self.player.set_transpose(0)
            self.player.mapper.clear_channel_settings()
            if self._direct_c:
                self.player.set_direct_c_mode(True, save=False)
            self.player.set_part_filter(self._melody_on, self._bass_on)
            self.player.set_speed(self._speed)
            self.player.play()
            self._playing = True
            self._paused = False
            self._update_float_status()
            self._refresh_menu_if_open()
            if self._player_panel:
                self._player_panel.update_status(f"循环: {fname}", True)
            # 启动可视化面板
            if self._visualizer:
                self._visualizer.start()
            # 更新BPM
            bpm = getattr(getattr(self.player, 'parser', None), 'bpm', 120)
            if self._player_panel:
                self._player_panel.update_bpm(bpm)
            self._update_status_panel()
        else:
            self._play_next_folder_song(_retries + 1)

    # ══════════════════════════════════════════════
    #  回调绑定
    # ══════════════════════════════════════════════
    def _bind_callbacks(self):
        def on_note(key, note, is_chord=False):
            if self._destroyed:
                return
            dur = int(min(2000, max(100, note.duration * 1000)))
            vel = note.velocity / 127.0 if hasattr(note, 'velocity') else 0.8
            midi_note = note.note
            if self._mini_piano:
                self.root.after(0, lambda: self._mini_piano.note_on(midi_note, vel, dur))
            if self._visualizer:
                self.root.after(0, lambda k=key, v=vel: self._visualizer.trigger_note(k, v))

        def on_progress(current, total):
            if self._destroyed:
                return
            self.root.after(0, lambda: self._update_progress(current, total))

        def on_end():
            if self._destroyed:
                return
            self.root.after(0, self._on_playback_end)

        def on_sustain(active: bool):
            if self._destroyed:
                return
            self._sustain_active = active
            if self._player_panel:
                self.root.after(0, lambda: self._player_panel.update_sustain(active))
            self.root.after(0, self._update_status_panel)

        def on_shift(mode):
            if self._destroyed:
                return
            _labels = {'normal': '普通模式', 'shift': 'SHIFT 高音',
                       'ctrl': 'CTRL 低音', 'lt': 'LT 极低', 'gt': 'GT 极高'}
            text = _labels.get(mode, mode)
            self._shift_mode = mode
            if self._player_panel:
                self.root.after(0, lambda: self._player_panel.update_shift_mode(text))
            self.root.after(0, self._update_status_panel)

        self.player.on_note_play = on_note
        self.player.on_progress = on_progress
        self.player.on_playback_end = on_end
        self.player.on_sustain_change = on_sustain
        self.player.on_shift_change = on_shift

    def _update_progress(self, current, total):
        # 更新悬浮进度条
        if total > 0:
            self._float_progress_pct = current / total
        else:
            self._float_progress_pct = 0.0
        try:
            self._update_float_display()
            # HP 数值已通过 _render_hp_dynamic 统一渲染
        except Exception:
            pass
        # 更新 SAO 菜单左面板
        if self._player_panel:
            try:
                self._player_panel.update_progress(current, total)
            except:
                pass

    def _on_playback_end(self):
        self._playing = False
        self._paused = False
        self._update_float_status()

        # ── 经验值 & 升级 ──
        _leveled_up = False
        song_dur = self._float_progress_pct * self.player._total_time if hasattr(self.player, '_total_time') else 0
        try:
            profile = load_profile()
            profile, leveled_up, old_lv, new_lv = add_song_xp(profile, song_dur)
            _leveled_up = leveled_up
            self._level = new_lv
            self._xp = profile.get('xp', 0)
            self._songs_played = profile.get('songs_played', 0)
            # 更新面板等级
            lv, cur_xp, need_xp = calc_level(self._xp)
            xp_pct = cur_xp / max(1, need_xp)
            if self._player_panel:
                self._player_panel.update_level(new_lv, xp_pct, self._xp)
            # 升级特效
            if leveled_up:
                self.root.after(300, lambda: LevelUpEffect.show(self.root, old_lv, new_lv))
            # 更新悬浮面板上的等级和 XP
            try:
                self._refresh_hp_layered()
            except Exception:
                pass
        except Exception:
            pass

        # 排行榜上传 (后台, 不阻塞)
        try:
            import threading as _thr
            from leaderboard import upload_stats
            from character_profile import load_profile as _lp
            _prof = _lp()
            _thr.Thread(target=upload_stats, kwargs={
                'username': _prof.get('username', 'Player'),
                'level': _prof.get('level', 1),
                'xp': _prof.get('xp', 0),
                'songs_played': _prof.get('songs_played', 0),
                'play_time': _prof.get('play_time', 0),
                'profession': _prof.get('profession', ''),
            }, daemon=True).start()
        except Exception:
            pass

        if self._player_panel:
            self._player_panel.update_status("播放完成", False)
            self._player_panel.update_progress(0, 0)
        if self._mini_piano:
            self._mini_piano.reset()
        if self._visualizer:
            self._visualizer.stop()
        self._refresh_menu_if_open()
        if self._folder_loop_active:
            # 升级时等动画结束 (2.5s) + 1s 再继续，否则 0.5s
            delay = 3500 if _leveled_up else 500
            self.root.after(delay, self._play_next_folder_song)

    def _restore_focus(self):
        try:
            if hasattr(self, 'player') and self.player:
                self.player.simulator.release_all()
        except:
            pass

    # ══════════════════════════════════════════════
    #  快捷键
    # ══════════════════════════════════════════════
    def _setup_hotkeys(self):
        self._hotkey_mgr = SAOHotkeyManager(self.settings, {
            'play_pause': lambda: self.root.after(0, self._toggle_play),
            'stop': lambda: self.root.after(0, self._stop),
            'speed_up': lambda: self.root.after(0, self._speed_up),
            'speed_down': lambda: self.root.after(0, self._speed_down),
            'toggle_topmost': lambda: self.root.after(0, self._toggle_topmost),
            'hide_panels': lambda: self.root.after(0, self._toggle_hide_all_panels),
        })

    # ══════════════════════════════════════════════
    #  其他功能
    # ══════════════════════════════════════════════
    def _toggle_topmost(self):
        current = self._float.attributes('-topmost')
        new_val = not current
        self._float.attributes('-topmost', new_val)
        for panel in [self._piano_panel, self._viz_panel, self._status_panel]:
            try:
                if panel and panel.winfo_exists():
                    panel.attributes('-topmost', new_val)
            except Exception:
                pass
        self._refresh_menu_if_open()

    def _switch_to_webview_ui(self):
        """切换到 WebView UI (sao_webview.py) — 热切换"""
        def _do_switch():
            self.settings.set('ui_mode', 'webview')
            self.settings.save()

            def _launch_next():
                from sao_webview import SAOWebViewGUI
                app = SAOWebViewGUI()
                app.run()

            self._run_exit_animation(after_shutdown=_launch_next,
                                     mode='switch', target_label='SAO WEBVIEW UI')

        SAODialog.ask(self._float, "切换 UI",
                      "将切换到 SAO WebView UI。\n确定继续吗？",
                      on_ok=_do_switch)

    def _switch_to_old_ui(self):
        """切换到 Old School UI (gui.py) — 在进程内热切换, 无需重启"""
        def _do_switch():
            self.settings.set('ui_mode', 'old')
            self.settings.save()

            def _launch_next():
                from gui import MidiPlayerGUI
                app = MidiPlayerGUI()
                app.run()

            self._run_exit_animation(after_shutdown=_launch_next,
                                     mode='switch', target_label='CLASSIC UI')

        SAODialog.ask(self._float, "切换 UI",
                      "将切换到经典 UI 模式。\n确定继续吗？",
                      on_ok=_do_switch)

    def _show_about(self):
        if self._sao_menu.visible:
            self._sao_menu.close()
        self.root.after(600, lambda: SAODialog.showinfo(
            self._float, "关于",
            "咲 Midi Player  SAO Edition\nv3.4.18+3418\n\n"
            "Alt+A 打开 SAO 菜单\n"
            "右键悬浮按钮查看更多选项"))

    def _edit_profile(self):
        """打开角色资料编辑对话框"""
        if self._sao_menu.visible:
            self._sao_menu.close()

        def on_profile_done(username, profession):
            self._username = username
            self._profession = profession
            self._update_float_title()
            if self._sao_menu:
                self._sao_menu.username = username
                self._sao_menu.description = profession or '咲 Midi Player SAO Edition'
            if self._player_panel:
                self._player_panel._username = username
                self._player_panel._profession = profession
                if self._player_panel._active:
                    self._player_panel._redraw_top(
                        self._player_panel._target_w,
                        self._player_panel._top_h)

        self.root.after(600, lambda: show_welcome_dialog(
            self._float, on_done=on_profile_done))

    def _show_leaderboard(self):
        """打开排行榜对话框 (SAO_GUI tkinter 版)."""
        if self._sao_menu.visible:
            self._sao_menu.close()

        holder = {'dlg': None}

        def _ensure_dialog():
            if holder['dlg'] is None:
                holder['dlg'] = SAOLeaderboardDialog(self._float, '排行榜', sort_by='xp')
            return holder['dlg']

        self.root.after(0, lambda: _ensure_dialog().set_loading('正在获取排行榜...'))

        def _do():
            try:
                from leaderboard import fetch_leaderboard, get_local_identity
                data = fetch_leaderboard(sort_by='xp', limit=50)
                if data is None:
                    self.root.after(0, lambda: _ensure_dialog().set_error('无法连接服务器，请稍后再试'))
                    return
                identity = get_local_identity()
                rows = data if isinstance(data, list) else data.get('players', [])
                for i, r in enumerate(rows):
                    r['rank'] = i + 1
                self.root.after(0, lambda: _ensure_dialog().set_entries(rows, identity['device_id'], identity.get('player_id', identity.get('device_name', '')), 'xp'))
            except Exception as e:
                print(f"[SAO] leaderboard: {e}")
                self.root.after(0, lambda: _ensure_dialog().set_error(f'加载失败: {e}'))

        self.root.after(600, lambda: threading.Thread(target=_do, daemon=True).start())

    def _cleanup_exit_overlay(self):
        ov = getattr(self, '_exit_overlay', None)
        if not ov:
            return
        try:
            gl = ov.get('gl')
            if gl:
                for key in ('pulse_tex', 'pulse_fbo', 'pulse_prog', 'pulse_vao', 'ctx'):
                    try:
                        obj = gl.get(key)
                        if obj is not None:
                            obj.release()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            win = ov.get('win')
            if win and win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        self._exit_overlay = None

    def _cleanup_entry_overlay(self):
        ov = getattr(self, '_entry_overlay', None)
        if not ov:
            return
        try:
            win = ov.get('win')
            if win and win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        self._entry_overlay = None

    def _create_entry_overlay(self, start_x, start_y, end_x, end_y):
        self._cleanup_entry_overlay()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.geometry(f'{sw}x{sh}+0+0')
        ov.configure(bg='#060a10')
        ov.attributes('-alpha', 0.0)
        try:
            _disable_native_window_shadow(ov)
        except Exception:
            pass
        cv = tk.Canvas(ov, width=sw, height=sh, bg='#060a10', highlightthickness=0, bd=0)
        cv.pack(fill=tk.BOTH, expand=True)
        self._entry_overlay = {
            'win': ov,
            'cv': cv,
            'sw': sw,
            'sh': sh,
            'start_x': start_x + self._fw // 2,
            'start_y': start_y + self._fh // 2,
            'end_x': end_x + self._fw // 2,
            'end_y': end_y + self._fh // 2,
        }
        return self._entry_overlay

    def _draw_entry_overlay(self, progress):
        ov = getattr(self, '_entry_overlay', None)
        if not ov:
            return
        try:
            win = ov['win']
            cv = ov['cv']
            if not win.winfo_exists() or not cv.winfo_exists():
                return
        except Exception:
            return

        sw, sh = ov['sw'], ov['sh']
        stage1 = min(1.0, progress / 0.34)
        stage2 = max(0.0, min(1.0, (progress - 0.24) / 0.76))
        bloom = ease_out(stage1)
        deploy = ease_in_out(stage2)
        cx = int(lerp(ov['start_x'], ov['end_x'], deploy))
        cy = int(lerp(ov['start_y'], ov['end_y'], deploy))
        cyan = '#86dfff'
        gold = '#f3af12'
        white = '#edf7ff'
        dim_cyan = '#173746'
        dim_gold = '#5e4211'

        try:
            win.attributes('-alpha', max(0.0, min(0.92, (1.0 - progress) ** 0.42 * 0.88)))
        except Exception:
            pass

        cv.delete('all')
        scan_pitch = 24
        scan_shift = int((progress * 240) % scan_pitch)
        for y in range(-scan_pitch, sh + scan_pitch, scan_pitch):
            yy = y + scan_shift
            col = dim_cyan if ((y // scan_pitch) % 2 == 0) else '#101823'
            cv.create_line(0, yy, sw, yy, fill=col, width=1)

        span = int(lerp(min(sw * 0.42, 520), min(sw * 0.22, 260), deploy))
        aperture = int(lerp(172, 28, deploy))
        for off, col in [(-54, cyan), (-24, dim_cyan), (24, dim_gold), (54, gold)]:
            cv.create_line(cx - span, cy + off, cx - aperture, cy + off, fill=col, width=1)
            cv.create_line(cx + aperture, cy + off, cx + span, cy + off, fill=col, width=1)

        ring_r = int(lerp(220, 64, deploy))
        for extra, col in [(0, cyan), (24, gold)]:
            r = ring_r + extra
            arm = 22 + extra // 4
            for sx in (-1, 1):
                for sy in (-1, 1):
                    px = cx + sx * r
                    py = cy + sy * r
                    cv.create_line(px, py, px - sx * arm, py, fill=col, width=1)
                    cv.create_line(px, py, px, py - sy * arm, fill=col, width=1)

        diamond = int(lerp(28, 10, deploy))
        cv.create_polygon(cx, cy - diamond, cx + diamond, cy,
                          cx, cy + diamond, cx - diamond, cy,
                          outline=white, fill='')
        cv.create_line(cx - 46, cy, cx + 46, cy, fill=white, width=1)
        cv.create_line(cx, cy - 22, cx, cy + 22, fill=white, width=1)

        pulse_y = int(lerp(cy - 160, cy + 88, bloom))
        cv.create_line(max(0, cx - span - 150), pulse_y,
                       min(sw, cx + span + 150), pulse_y,
                       fill=cyan, width=1)
        cv.create_line(max(0, cx - span - 110), pulse_y + 3,
                       min(sw, cx + span + 110), pulse_y + 3,
                       fill=dim_cyan, width=1)

        label_x1 = max(30, cx - span - 70)
        label_x2 = min(sw - 30, cx + span + 70)
        cv.create_text(label_x1, max(24, cy - 164), text='SYS:ENTITY',
                       anchor='w', fill=cyan, font=('Consolas', 9))
        cv.create_text(label_x2, max(24, cy - 164), text='SEQ:ENTRY',
                       anchor='e', fill=gold, font=('Consolas', 9))
        cv.create_text(label_x1, min(sh - 24, cy + 174), text='STATUS:DEPLOY',
                       anchor='w', fill=dim_cyan, font=('Consolas', 9))
        cv.create_text(label_x2, min(sh - 24, cy + 174), text=time.strftime('%H:%M:%S'),
                       anchor='e', fill=dim_gold, font=('Consolas', 9))

        text_y = cy + 92
        cv.create_text(cx, text_y, text='LINK START', fill=white,
                       font=get_sao_font(16, True))
        cv.create_text(cx, text_y + 26, text='ENTITY DEPLOYMENT', fill=gold,
                       font=('Consolas', 11, 'bold'))
        cv.create_text(cx, text_y + 48, text='INITIALIZING VISUAL SHELL',
                       fill='#8aaec0', font=('Consolas', 9))

    def _run_entry_animation(self, fx_start, fy_start, fx_final, fy_final):
        self._create_entry_overlay(fx_start, fy_start, fx_final, fy_final)
        anim_start = time.time()
        total = 1.18
        phase1 = 0.36

        def _done():
            self._cleanup_entry_overlay()
            self._breath_base_x = fx_final
            self._breath_base_y = fy_final
            self.root.after(120, self._start_float_breath)
            self.root.after(160, self._animate_float_hud)
            if not self._username:
                self.root.after(420, self._show_welcome_then_menu)
            else:
                self.root.after(420, self._toggle_sao_menu)
            self.root.after(900, self._restore_panels)

        def _tick():
            if self._destroyed:
                self._cleanup_entry_overlay()
                return
            try:
                if not self._float.winfo_exists():
                    self._cleanup_entry_overlay()
                    return
            except Exception:
                self._cleanup_entry_overlay()
                return

            elapsed = time.time() - anim_start
            t = min(1.0, elapsed / total)
            self._draw_entry_overlay(t)

            if elapsed < phase1:
                hold = ease_out(elapsed / phase1)
                self._set_float_alpha(0.12 * hold)
                try:
                    self.root.after(16, _tick)
                except Exception:
                    self._cleanup_entry_overlay()
                return

            deploy = min(1.0, (elapsed - phase1) / max(0.001, total - phase1))
            deploy_e = ease_out(deploy)
            fx = int(lerp(fx_start, fx_final, deploy_e))
            fy = int(lerp(fy_start, fy_final, deploy_e))
            self._float.geometry(f'+{fx}+{fy}')
            self._set_float_alpha(0.82 * ease_in_out(deploy))

            if elapsed < total:
                try:
                    self.root.after(16, _tick)
                except Exception:
                    self._cleanup_entry_overlay()
            else:
                self._float.geometry(f'+{fx_final}+{fy_final}')
                self._set_float_alpha(0.82)
                _done()

        _tick()

    def _get_exit_banner(self, mode='exit', target_label=None):
        if mode == 'switch':
            return {
                'primary': 'INTERFACE SHIFT',
                'secondary': (target_label or 'NEXT UI').upper(),
                'tertiary': 'TRANSFERRING CONTROL TO NEXT LAYER',
                'accent': '#f3af12',
                'accent_dim': '#5e4211',
            }
        return {
            'primary': 'SYSTEM LOG OUT',
            'secondary': 'SAO ENTITY',
            'tertiary': 'PERSISTING SESSION STATE',
            'accent': '#86dfff',
            'accent_dim': '#173746',
        }

    def _init_exit_pulse_gl(self, width, height):
        try:
            import moderngl
        except Exception:
            return None
        try:
            ctx = moderngl.create_standalone_context()
            prog = ctx.program(
                vertex_shader='''
#version 330
out vec2 uv;
vec2 pos[3] = vec2[](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() {
    vec2 p = pos[gl_VertexID];
    uv = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
''',
                fragment_shader='''
#version 330
in vec2 uv;
uniform vec2 u_resolution;
uniform vec2 u_center;
uniform float u_progress;
out vec4 fragColor;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float band(float x, float center, float width) {
    return exp(-pow((x - center) / max(0.0001, width), 2.0));
}

float gridLine(vec2 q, vec2 dir, float scale, float width) {
    float v = abs(fract(dot(q, dir) * scale) - 0.5);
    return 1.0 - smoothstep(width, width + 0.018, v);
}

void main() {
    vec2 center = u_center / u_resolution;
    vec2 p = uv - center;
    p.x *= u_resolution.x / max(1.0, u_resolution.y);
    float r = length(p);
    float progress = clamp(u_progress, 0.0, 1.0);

    float bluePulse = smoothstep(0.00, 0.09, progress) * (1.0 - smoothstep(0.12, 0.29, progress));
    float whitePulse = smoothstep(0.15, 0.23, progress) * (1.0 - smoothstep(0.28, 0.45, progress));
    float exposure = smoothstep(0.01, 0.08, progress) * (1.0 - smoothstep(0.15, 0.32, progress));
    float dualFlash = bluePulse * 0.95 + whitePulse * 1.24 + exposure * 0.82;

    vec2 radialDir = normalize(p + vec2(0.0001, 0.0));
    float ringRadius = mix(0.012, 0.74, progress);
    float ringWidth = mix(0.038, 0.014, progress);
    float refractBand = band(r, ringRadius - mix(0.015, 0.060, progress), ringWidth * 3.4)
                      * smoothstep(0.06, 0.74, progress);
    vec2 distort = radialDir * refractBand * (0.020 + whitePulse * 0.018)
                 + vec2(sin(uv.y * u_resolution.y * 0.090 + progress * 28.0),
                        cos(uv.x * u_resolution.x * 0.052 - progress * 21.0)) * refractBand * 0.0045;

    vec2 rp = p + distort;
    float rr = length(rp);
    float rang = atan(rp.y, rp.x);

    float fringe = (0.010 + bluePulse * 0.010 + whitePulse * 0.016) * (0.40 + rr * 1.9);
    float segmentA = smoothstep(0.12, 0.94, 0.5 + 0.5 * sin(rang * 16.0 + progress * 18.0 + rr * 34.0));
    float segmentB = smoothstep(0.20, 0.97, 0.5 + 0.5 * cos(rang * 11.0 - progress * 15.0 - rr * 26.0));
    float segmentMask = clamp(segmentA * 0.65 + segmentB * 0.95, 0.0, 1.0);

    float ringR = band(rr, ringRadius + fringe * 1.05, ringWidth * 1.10) * (0.45 + 0.55 * segmentMask);
    float ringG = band(rr, ringRadius, ringWidth) * (0.28 + 0.72 * segmentMask);
    float ringB = band(rr, max(0.0, ringRadius - fringe), ringWidth * 0.90) * (0.38 + 0.62 * segmentMask);

    float echoR = band(rr, ringRadius + 0.026, ringWidth * 1.7) * (1.0 - smoothstep(0.24, 0.78, progress));
    float echoC = band(rr, max(0.0, ringRadius - 0.070), ringWidth * 2.8) * (1.0 - smoothstep(0.16, 0.58, progress));
    float echoB = band(rr, max(0.0, ringRadius - 0.128), ringWidth * 3.5) * (1.0 - smoothstep(0.10, 0.48, progress));

    vec2 dirA = normalize(vec2(1.0, 0.0));
    vec2 dirB = normalize(vec2(0.5, 0.8660254));
    vec2 dirC = normalize(vec2(-0.5, 0.8660254));
    float hexScale = mix(20.0, 31.0, smoothstep(0.08, 0.80, progress));
    float lineA = gridLine(rp, dirA, hexScale, 0.035);
    float lineB = gridLine(rp, dirB, hexScale, 0.033);
    float lineC = gridLine(rp, dirC, hexScale, 0.033);
    float hexWire = max(lineA, max(lineB, lineC));
    float hexNode = max(lineA * lineB, max(lineB * lineC, lineC * lineA));
    float hexMask = band(rr, ringRadius + 0.020, ringWidth * 4.8)
                  + band(rr, ringRadius - 0.090, ringWidth * 6.2) * 0.6;
    float circuitry = clamp((hexWire * 0.60 + hexNode * 1.10) * hexMask, 0.0, 1.0);

    float core = exp(-rr * mix(60.0, 24.0, progress)) * (0.72 + 0.28 * whitePulse);
    float bloom = exp(-rr * 7.2) * (bluePulse * 0.95 + whitePulse * 1.10 + exposure * 0.55);
    float halo = exp(-rr * 3.1) * smoothstep(0.04, 0.24, progress) * (1.0 - smoothstep(0.60, 1.0, progress));

    float edgeWave = band(rr, mix(0.18, 1.04, progress), mix(0.10, 0.022, progress));
    vec2 edgeUv = abs(uv - 0.5) * 2.0;
    float edgeMask = pow(max(edgeUv.x, edgeUv.y), 3.6);
    float edgeSweep = edgeWave * edgeMask * smoothstep(0.10, 0.92, progress);

    float scanlines = 0.90 + 0.10 * sin((uv.y * u_resolution.y + progress * 2900.0) * 1.14);
    float scanMicro = 0.95 + 0.05 * sin((uv.y * u_resolution.y) * 4.2 + progress * 970.0);
    float lensSweep = band(uv.y, 0.28 + progress * 0.50, 0.040) + band(uv.y, 0.60 + progress * 0.24, 0.055) * 0.6;

    float tearCenter1 = 0.33 + 0.09 * sin(progress * 12.0);
    float tearCenter2 = 0.61 + 0.06 * cos(progress * 10.0 + 0.7);
    float tearBand1 = band(uv.y, tearCenter1, 0.010 + whitePulse * 0.008);
    float tearBand2 = band(uv.y, tearCenter2, 0.014 + bluePulse * 0.010);
    float tearPattern1 = step(0.38, hash21(vec2(floor((uv.x + distort.x * 9.0) * 220.0), floor(progress * 90.0) + 13.0)));
    float tearPattern2 = step(0.32, hash21(vec2(floor((uv.x - distort.x * 7.0) * 180.0) + 7.0, floor(progress * 126.0) + 27.0)));
    float tear = tearBand1 * tearPattern1 + tearBand2 * tearPattern2;

    float chromaGlint = smoothstep(0.76, 1.0, sin(rang * 24.0 + rr * 80.0 - progress * 18.0) * 0.5 + 0.5)
                      * band(rr, ringRadius, ringWidth * 2.2);
    float grain = hash21(gl_FragCoord.xy * 0.05 + progress * 31.0) * 0.045;

    vec3 cyan = vec3(0.60, 0.95, 1.0);
    vec3 blue = vec3(0.06, 0.48, 1.0);
    vec3 white = vec3(1.0, 1.0, 1.0);
    vec3 ghost = vec3(0.34, 0.88, 1.0);
    vec3 color = vec3(0.0);

    color += mix(blue, cyan, 0.42) * exposure * (0.50 + 0.50 * exp(-rr * 2.0));
    color += vec3(0.82, 0.96, 1.0) * lensSweep * (0.10 + exposure * 0.24);
    color += white * whitePulse * (0.26 + 0.74 * exp(-rr * 3.2));
    color.r += ringR * 0.92 + echoR * 0.44 + whitePulse * 0.18;
    color.g += ringG * 1.04 + echoC * 0.38 + circuitry * 0.24;
    color.b += ringB * 1.82 + echoC * 0.62 + echoB * 0.54 + edgeSweep * 0.90 + circuitry * 0.36;
    color += cyan * bloom * 0.98;
    color += ghost * (echoC * 0.62 + echoB * 0.44 + halo * 0.58);
    color += vec3(0.44, 0.92, 1.0) * edgeSweep;
    color += vec3(0.52, 0.94, 1.0) * circuitry * (0.50 + bluePulse * 0.55);
    color += vec3(0.86, 1.0, 1.0) * hexNode * hexMask * 0.34;
    color += vec3(0.78, 0.98, 1.0) * tear * (0.50 + dualFlash * 0.46);
    color += vec3(0.94, 0.40, 0.50) * chromaGlint * 0.20;
    color += vec3(0.18, 0.84, 1.0) * chromaGlint * 0.48;
    color += white * core * (0.22 + whitePulse * 0.42);
    color += vec3(grain) * (dualFlash * 0.20 + tear * 0.24 + circuitry * 0.08);

    color *= scanlines * scanMicro;
    color += vec3(0.07, 0.18, 0.36) * tear * 0.28;
    color = clamp(color, 0.0, 1.0);
    fragColor = vec4(color, 1.0);
}
''')
            vao = ctx.vertex_array(prog, [])
            tex = ctx.texture((width, height), 3)
            fbo = ctx.framebuffer(color_attachments=[tex])
            prog['u_resolution'].value = (float(width), float(height))
            return {
                'ctx': ctx,
                'pulse_prog': prog,
                'pulse_vao': vao,
                'pulse_tex': tex,
                'pulse_fbo': fbo,
            }
        except Exception:
            try:
                ctx.release()
            except Exception:
                pass
            return None

    def _draw_exit_pulse_gl(self, cv, ov, cx, cy, purge_t):
        gl = ov.get('gl')
        if not gl:
            return False
        try:
            prog = gl['pulse_prog']
            fbo = gl['pulse_fbo']
            vao = gl['pulse_vao']
            fbo.use()
            gl['ctx'].clear(0.0, 0.0, 0.0, 1.0)
            prog['u_center'].value = (float(cx), float(cy))
            prog['u_progress'].value = float(max(0.0, min(1.0, purge_t)))
            vao.render()
            raw = fbo.read(components=3)
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(ov['sh'], ov['sw'], 3)
            photo = ImageTk.PhotoImage(Image.fromarray(arr[::-1], 'RGB'))
            ov['gl_photo'] = photo
            cv.create_image(0, 0, image=photo, anchor='nw')
            return True
        except Exception:
            return False

    def _create_exit_overlay(self, mode='exit', target_label=None):
        self._cleanup_exit_overlay()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.geometry(f'{sw}x{sh}+0+0')
        ov.configure(bg='#060a10')
        ov.attributes('-alpha', 0.0)
        try:
            _disable_native_window_shadow(ov)
        except Exception:
            pass
        cv = tk.Canvas(ov, width=sw, height=sh, bg='#060a10', highlightthickness=0, bd=0)
        cv.pack(fill=tk.BOTH, expand=True)
        try:
            fx = self._float.winfo_rootx() + self._fw // 2
            fy = self._float.winfo_rooty() + self._fh // 2
        except Exception:
            fx, fy = sw // 2, sh // 2
        self._exit_overlay = {
            'win': ov,
            'cv': cv,
            'sw': sw,
            'sh': sh,
            'fx': fx,
            'fy': fy,
            'banner': self._get_exit_banner(mode, target_label),
            'mode': mode,
            'gl': self._init_exit_pulse_gl(sw, sh),
            'gl_photo': None,
        }
        return self._exit_overlay

    def _draw_exit_overlay(self, progress):
        ov = getattr(self, '_exit_overlay', None)
        if not ov:
            return
        try:
            win = ov['win']
            cv = ov['cv']
            if not win.winfo_exists() or not cv.winfo_exists():
                return
        except Exception:
            return

        sw, sh = ov['sw'], ov['sh']
        cx, cy = ov['fx'], ov['fy']
        lock_t = min(1.0, progress / 0.34)
        purge_t = max(0.0, min(1.0, (progress - 0.34) / 0.66))
        lock_e = ease_out(lock_t)
        purge_e = ease_in_out(purge_t)
        cyan = '#86dfff'
        gold = ov['banner']['accent']
        dim_cyan = '#173746'
        dim_gold = ov['banner']['accent_dim']
        white = '#edf7ff'

        wash = 0.22 + 0.78 * lock_e
        sweep = ((lock_t * 0.45) + purge_t * 1.2) % 1.0

        try:
            win.attributes('-alpha', min(0.95, 0.10 + 0.56 * lock_e + 0.24 * purge_e))
        except Exception:
            pass

        cv.delete('all')
        if purge_t < 0.02 or not ov.get('gl'):
            scan_pitch = 26
            scan_shift = int((progress * 280) % scan_pitch)
            for y in range(-scan_pitch, sh + scan_pitch, scan_pitch):
                yy = y + scan_shift
                col = dim_cyan if ((y // scan_pitch) % 2 == 0) else '#101823'
                cv.create_line(0, yy, sw, yy, fill=col, width=1)

        pulse_gl_drawn = False
        if purge_t > 0.0:
            pulse_gl_drawn = self._draw_exit_pulse_gl(cv, ov, cx, cy, purge_t)
            if not pulse_gl_drawn:
                pulse = max(0.0, 1.0 - abs(purge_t - 0.18) / 0.18)
                if pulse > 0.01:
                    if pulse > 0.72:
                        flash_fill = '#eefbff'
                        flash_stipple = 'gray25'
                    elif pulse > 0.38:
                        flash_fill = '#c8efff'
                        flash_stipple = 'gray25'
                    else:
                        flash_fill = '#8edfff'
                        flash_stipple = 'gray50'
                    cv.create_rectangle(0, 0, sw, sh, fill=flash_fill, outline='', stipple=flash_stipple)
                    bloom_r = int(lerp(40, min(sw, sh) * 0.32, pulse))
                    core_r = max(10, int(bloom_r * 0.26))
                    cv.create_oval(cx - bloom_r, cy - bloom_r,
                                   cx + bloom_r, cy + bloom_r,
                                   outline='#dff8ff', width=max(1, int(2 + pulse * 3)),
                                   stipple='gray25')
                    cv.create_oval(cx - core_r, cy - core_r,
                                   cx + core_r, cy + core_r,
                                   fill='#f8feff', outline='', stipple='gray25')

        span = int(lerp(min(sw * 0.30, 360), min(sw * 0.38, 460), lock_e))
        aperture = int(lerp(146, 22, purge_e))
        for off, col in [(-60, cyan), (-28, dim_cyan), (28, dim_gold), (60, gold)]:
            cv.create_line(cx - span, cy + off, cx - aperture, cy + off, fill=col, width=1)
            cv.create_line(cx + aperture, cy + off, cx + span, cy + off, fill=col, width=1)

        base_r = int(lerp(34, 194, lock_e * (1.0 - purge_e * 0.20)))
        for extra, col in [(0, cyan), (20, gold)]:
            r = max(22, int((base_r + extra) * (1.0 - 0.58 * purge_e)))
            arm = 18 + extra // 3
            for sx in (-1, 1):
                for sy in (-1, 1):
                    px = cx + sx * r
                    py = cy + sy * r
                    cv.create_line(px, py, px - sx * arm, py, fill=col, width=1)
                    cv.create_line(px, py, px, py - sy * arm, fill=col, width=1)

        diamond = int(lerp(24, 9, purge_e))
        cv.create_polygon(cx, cy - diamond, cx + diamond, cy,
                          cx, cy + diamond, cx - diamond, cy,
                          outline=white, fill='')
        cv.create_line(cx - 38, cy, cx + 38, cy, fill=white, width=1)
        cv.create_line(cx, cy - 18, cx, cy + 18, fill=white, width=1)

        if purge_t > 0.0 and not pulse_gl_drawn:
            burst = int(lerp(18, 220, purge_e))
            flash = '#d7f7ff' if purge_t < 0.7 else gold
            cv.create_line(cx - burst, cy, cx + burst, cy, fill=flash, width=2)
            cv.create_line(cx, cy - int(burst * 0.42), cx, cy + int(burst * 0.42), fill=flash, width=1)

        scan_y = int(lerp(cy - 140, cy + 120, sweep))
        cv.create_line(max(0, cx - span - 140), scan_y,
                       min(sw, cx + span + 140), scan_y,
                       fill=cyan, width=1)
        cv.create_line(max(0, cx - span - 120), scan_y + 3,
                       min(sw, cx + span + 120), scan_y + 3,
                       fill=dim_cyan, width=1)

        banner_x1 = max(30, cx - span - 60)
        banner_x2 = min(sw - 30, cx + span + 60)
        seq_label = 'SEQ:SHIFT' if ov.get('mode') == 'switch' else 'SEQ:EXIT'
        status_label = 'STATUS:LOCK' if purge_t < 0.08 else ('STATUS:TRANSFER' if ov.get('mode') == 'switch' else 'STATUS:PURGE')
        cv.create_text(banner_x1, max(24, cy - 150), text='SYS:ENTITY',
                       anchor='w', fill=cyan, font=('Consolas', 9))
        cv.create_text(banner_x2, max(24, cy - 150), text=seq_label,
                       anchor='e', fill=gold, font=('Consolas', 9))
        cv.create_text(banner_x1, min(sh - 24, cy + 164), text=status_label,
                       anchor='w', fill=dim_cyan, font=('Consolas', 9))
        cv.create_text(banner_x2, min(sh - 24, cy + 164), text=time.strftime('%H:%M:%S'),
                       anchor='e', fill=dim_gold, font=('Consolas', 9))

        text_y = cy + 86
        primary = 'ENTITY LOCK' if purge_t < 0.12 else ov['banner']['primary']
        tertiary = 'FREEZING UI STATE' if purge_t < 0.12 else ov['banner']['tertiary']
        cv.create_text(cx, text_y, text=primary,
                       fill=white, font=get_sao_font(16, True))
        cv.create_text(cx, text_y + 26, text=ov['banner']['secondary'],
                       fill=gold, font=('Consolas', 11, 'bold'))
        cv.create_text(cx, text_y + 48, text=tertiary,
                       fill='#8aaec0', font=('Consolas', 9))

    def _collect_exit_windows(self):
        wins = []
        seen = set()

        try:
            focus_x = self._float.winfo_x() + self._fw // 2
            focus_y = self._float.winfo_y() + self._fh // 2
        except Exception:
            focus_x = self.root.winfo_screenwidth() // 2
            focus_y = self.root.winfo_screenheight() // 2

        def _profile(x, y, role, order):
            dx = x - focus_x
            dy = y - focus_y
            dist = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / dist, dy / dist
            if role == 'float':
                return {'delay': 0.28, 'duration': 0.52, 'travel': 86,
                        'ux': 1.0, 'uy': -0.25, 'movable': True}
            if role == 'panel':
                return {'delay': 0.12 + order * 0.085, 'duration': 0.40,
                        'travel': 48 + order * 12, 'ux': ux, 'uy': uy + 0.24, 'movable': True}
            if role == 'menu':
                return {'delay': 0.00, 'duration': 0.32, 'travel': 0,
                        'ux': 0.0, 'uy': 0.0, 'movable': False}
            if role == 'fisheye':
                return {'delay': 0.00, 'duration': 0.24, 'travel': 0,
                        'ux': 0.0, 'uy': 0.0, 'movable': False}
            return {'delay': 0.06, 'duration': 0.32, 'travel': 22,
                    'ux': ux, 'uy': uy, 'movable': True}

        def _add(win, role, order=0, ulw=False):
            if not win:
                return
            try:
                if not win.winfo_exists():
                    return
                wid = win.winfo_id()
                if wid in seen:
                    return
                seen.add(wid)
                try:
                    alpha = float(win.attributes('-alpha'))
                except Exception:
                    alpha = 1.0
                profile = _profile(win.winfo_x(), win.winfo_y(), role, order)
                wins.append({
                    'win': win,
                    'alpha': max(0.0, min(1.0, alpha)),
                    'x': win.winfo_x(),
                    'y': win.winfo_y(),
                    'role': role,
                    'ulw': ulw,
                    **profile,
                })
            except Exception:
                pass

        # HP float 使用 ULW，不能用 attributes('-alpha') 读写
        _float = getattr(self, '_float', None)
        if _float:
            try:
                if _float.winfo_exists():
                    wid = _float.winfo_id()
                    if wid not in seen:
                        seen.add(wid)
                        profile = _profile(_float.winfo_x(), _float.winfo_y(), 'float', 0)
                        wins.append({
                            'win': _float,
                            'alpha': getattr(self, '_float_alpha', 1.0),
                            'x': _float.winfo_x(),
                            'y': _float.winfo_y(),
                            'role': 'float',
                            'ulw': True,
                            **profile,
                        })
            except Exception:
                pass
        for idx, panel in enumerate([self._piano_panel, self._viz_panel, self._status_panel, self._control_panel]):
            _add(panel, 'panel', order=idx)
        _add(getattr(getattr(self, '_sao_menu', None), '_overlay', None), 'menu')
        _add(getattr(self, '_fisheye_ov', None), 'fisheye')
        # _hp_alpha_windows 已废弃 (ULW 内部渲染)
        return wins

    def _finalize_close(self):
        if self._close_finalized:
            return
        self._close_finalized = True
        self._destroyed = True
        self._breath_active = False
        self._lift_loop_active = False
        self._cleanup_entry_overlay()
        self._cleanup_exit_overlay()
        if hasattr(self, '_hotkey_mgr'):
            self._hotkey_mgr.cleanup()
        self._stop_fisheye_overlay()
        try:
            self._sao_menu.unbind_events()
            if self._sao_menu.visible:
                self._sao_menu.close()
        except Exception:
            pass
        self.player.stop()
        # 销毁所有浮动面板
        for panel in [self._piano_panel, self._viz_panel, self._status_panel, self._control_panel]:
            try:
                if panel and panel.winfo_exists():
                    panel.destroy()
            except Exception:
                pass
        self._destroy_hp_alpha_strip_windows()
        try:
            if self._float and self._float.winfo_exists():
                self._float.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _run_exit_animation(self, after_shutdown=None, mode='exit', target_label=None):
        if self._close_finalized or self._exit_animating:
            return
        self._exit_animating = True
        self._destroyed = True
        self._breath_active = False
        self._lift_loop_active = False
        try:
            play_sound('menu_close')
        except Exception:
            pass
        try:
            self._play_motion_blur(closing=True)
        except Exception:
            pass
        try:
            if self._sao_menu.visible:
                self._sao_menu.close()
        except Exception:
            pass

        wins = self._collect_exit_windows()
        self._create_exit_overlay(mode=mode, target_label=target_label)
        if not wins:
            self._draw_exit_overlay(1.0)
            self._finalize_close()
            if after_shutdown:
                try:
                    after_shutdown()
                except Exception:
                    pass
            return

        t0 = time.time()
        stage1 = 0.42
        stage2 = 0.96
        duration = stage1 + stage2

        def _finish():
            self._finalize_close()
            if after_shutdown:
                try:
                    after_shutdown()
                except Exception:
                    pass

        def _step():
            if self._close_finalized:
                return
            elapsed = time.time() - t0
            t = min(1.0, elapsed / duration)
            self._draw_exit_overlay(t)
            for item in wins:
                try:
                    win = item['win']
                    if not win.winfo_exists():
                        continue
                    if elapsed < stage1:
                        hold = ease_out(min(1.0, elapsed / stage1))
                        new_alpha = item['alpha'] * (1.0 - 0.16 * hold)
                        if item.get('movable'):
                            dx = int(item['ux'] * item['travel'] * 0.10 * hold)
                            dy = int(item['uy'] * item['travel'] * 0.10 * hold)
                            if item.get('role') == 'float':
                                dy -= int(8 * hold)
                            try:
                                win.geometry(f'+{item["x"] + dx}+{item["y"] + dy}')
                            except Exception:
                                pass
                    else:
                        local = min(1.0, max(0.0, (elapsed - stage1 - item['delay']) / max(0.001, item['duration'])))
                        fade = ease_in_out(local)
                        base_alpha = item['alpha'] * 0.84
                        new_alpha = max(0.0, base_alpha * (1.0 - fade))
                        if item.get('movable'):
                            dx = int(item['ux'] * item['travel'] * (0.10 + 0.90 * fade))
                            dy = int(item['uy'] * item['travel'] * (0.10 + 0.90 * fade))
                            if item.get('role') == 'float':
                                dy -= int(18 + 18 * fade)
                            try:
                                win.geometry(f'+{item["x"] + dx}+{item["y"] + dy}')
                            except Exception:
                                pass
                    if item.get('ulw'):
                        self._set_float_alpha(new_alpha)
                    else:
                        win.attributes('-alpha', new_alpha)
                except Exception:
                    pass
            if elapsed < duration:
                try:
                    self.root.after(16, _step)
                except Exception:
                    _finish()
            else:
                _finish()

        try:
            self.root.after(1, _step)
        except Exception:
            _finish()

    def _on_close(self):
        self._run_exit_animation(mode='exit', target_label='Desktop')

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()


def main():
    # 设置 DPI 感知 — 减少 Tkinter 控件锯齿 / 模糊
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    app = SAOPlayerGUI()
    app.run()


if __name__ == "__main__":
    main()
