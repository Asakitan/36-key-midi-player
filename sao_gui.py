# -*- coding: utf-8 -*-
"""
SAO Utils 风格完整 GUI — 独立 UI 壳
包含 SAO PopUpMenu 菜单系统, SAO Alert 对话框, HP 血条进度条,
LINK START 入场动画, SAO 风格文件选择器

所有播放功能复用 MidiPlayer 后端, 与 gui.py (Old UI) 完全独立
"""

import tkinter as tk
from tkinter import ttk
import threading
import os
import sys
import json
import ctypes
import math
import time
from typing import Optional

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
    SAOStatusPill, SAOResizeGrip, SAOFilePicker, SAOSeparator,
    SAOPopUpMenu, SAOHPBar, SAOLinkStart, SAOCircleButton,
    Animator, lerp, lerp_color, ease_out
)
from gui import MidiVisualizer, ModernColors, SmoothButton

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
        hwnd = ctypes.windll.user32.GetParent(panel.winfo_id())
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
# ══════════════════════════════════════════════════════════
class SAOPlayerPanel(tk.Frame):
    """
    SAO 风格左侧信息面板 — 显示播放器状态
    替代默认的 SAOLeftInfo，集成 HP 进度条、文件信息、播放状态
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=parent.cget('bg'), highlightthickness=0, **kw)
        self._active = False
        self._anim = Animator(self)
        self._target_w = 280
        self._top_h = 220
        self._bottom_h = 80

        # 数据
        self._file_name = "未选择文件"
        self._status = "就绪"
        self._time_current = 0
        self._time_total = 0
        self._speed = 1.0
        self._transpose = 0
        self._hp_percent = 1.0
        self._mode = "经典60键"
        self._shift_mode = "普通模式"     # 演奏中模式
        self._bpm = 0
        self._is_playing = False
        self._sustain = False

        self._build()

    def _build(self):
        self._top = tk.Canvas(self, width=0, height=0,
                              bg='#ffffff', highlightthickness=0)
        self._top.pack(anchor='nw')
        self._bottom = tk.Canvas(self, width=0, height=0,
                                 bg='#f5f5f7', highlightthickness=0)
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
            self._redraw_top(self._target_w, self._top_h)

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
        self._top.delete('all')
        if w < 40 or h < 40:
            return

        # 右三角指示器 (白色)
        self._top.create_polygon(w, h * 0.75, w + 16, h * 0.75 + 7, w, h * 0.75 + 14,
                                 fill='#ffffff', outline='')

        # 分隔线 (SAO 白色主题)
        self._top.create_line(10, 35, w - 10, 35, fill='#d1d1d6', width=1)
        # 金色发光分隔线
        self._top.create_line(10, 34, int(w * 0.5), 34, fill='#f3af12', width=1)

        # 文件名
        display_name = self._file_name
        if len(display_name) > 26:
            display_name = display_name[:23] + '...'
        self._top.create_text(w // 2, 20, text=display_name,
                              font=('Microsoft YaHei UI', 9, 'bold'), fill='#333333')

        if h < 80:
            return

        # HP 进度条
        bar_x, bar_w = 15, w - 30
        bar_y, bar_h = 46, 16

        # 边框 (polygon 风格)
        pts = [bar_x, bar_y,
               bar_x + bar_w, bar_y,
               bar_x + bar_w - 3, bar_y + bar_h,
               bar_x, bar_y + bar_h]
        self._top.create_polygon(pts, outline='#d1d1d6', fill='#f0f0f0', width=1)

        fill_w = int(bar_w * self._hp_percent)
        if fill_w > 0:
            if self._hp_percent > 0.5:
                fc = '#9ad334'
            elif self._hp_percent > 0.25:
                fc = '#f4fa49'
            else:
                fc = '#ef684e'
            self._top.create_rectangle(bar_x + 1, bar_y + 1,
                                       bar_x + 1 + fill_w, bar_y + bar_h - 1,
                                       fill=fc, outline='')

        # 百分比
        self._top.create_text(bar_x + bar_w // 2, bar_y + bar_h // 2,
                              text=f'{int(self._hp_percent * 100)}%',
                              fill='#999999', font=('Segoe UI', 7))

        if h < 120:
            return

        # 时间
        c_min, c_sec = divmod(int(self._time_current), 60)
        t_min, t_sec = divmod(int(self._time_total), 60)
        self._top.create_text(w // 2, bar_y + bar_h + 16,
                              text=f"{c_min:02d}:{c_sec:02d} / {t_min:02d}:{t_sec:02d}",
                              fill='#646364', font=('Consolas', 10))

        if h < 160:
            return

        # BPM
        if self._bpm > 0:
            self._top.create_text(w // 2, bar_y + bar_h + 38,
                                  text=f'BPM  {self._bpm:.0f}',
                                  fill='#f3af12', font=('Segoe UI', 9))

        # 速度 / 移调
        y_info = bar_y + bar_h + 58
        self._top.create_text(w // 2, y_info,
                              text=f'x{self._speed:.2f}  ·  {self._transpose:+d}半音',
                              fill='#999999', font=('Segoe UI', 8))

        # 模式 (SAO 金色)
        if h > 190:
            self._top.create_text(w // 2, y_info + 22,
                                  text=self._mode,
                                  fill='#f3af12', font=('Microsoft YaHei UI', 8, 'bold'))

    def _redraw_bottom(self, w, h):
        self._bottom.delete('all')
        if w < 40 or h < 15:
            return

        # 上三角 (连接两块 canvas)
        self._bottom.create_polygon(30, 0, 37, -10, 44, 0,
                                    fill='#f5f5f7', outline='')

        # 小分隔线
        self._bottom.create_line(0, 1, w, 1, fill='#d1d1d6', width=1)

        # 状态指示灯
        dot_color = '#3ad86c' if self._is_playing else '#d1d1d6'
        self._bottom.create_oval(14, 17, 23, 26, fill=dot_color, outline='')

        status_color = '#333333' if self._is_playing else '#999999'
        self._bottom.create_text(29, 22, text=self._status,
                                 font=('Microsoft YaHei UI', 10), fill=status_color,
                                 anchor='w')

        if h > 50:
            # 模式标签 (左下) — SAO 金色
            self._bottom.create_text(14, 54, text=self._mode,
                                     font=('Microsoft YaHei UI', 8), fill='#f3af12',
                                     anchor='w')
            # 演奏模式 (中间) — SHIFT/CTRL 等
            _sm = self._shift_mode
            _smc = '#428ce6' if _sm == '普通模式' else ('#1565c0' if 'SHIFT' in _sm else '#e65100')
            self._bottom.create_text(w // 2, 54, text=_sm,
                                     font=('Segoe UI', 7), fill=_smc, anchor='center')
            # 延音踏板指示 (右下)
            sus_color = '#3ad86c' if self._sustain else '#cccccc'
            sus_text  = 'SUS ●' if self._sustain else 'SUS ○'
            self._bottom.create_text(w - 12, 54, text=sus_text,
                                     font=('Segoe UI', 8), fill=sus_color,
                                     anchor='e')


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
        self.player = MidiPlayer()
        saved_mode = self.settings.get('mode_system', 'classic')
        self.player.set_mode_system(saved_mode)

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
        self._proficiency_enabled = True
        self._player_panel = None  # 当 SAO 菜单打开时设置
        self._picker = None        # SAOFilePicker 引用 (防止 GC)
        self._piano_panel = None   # 浮动钢琴面板
        self._viz_panel = None     # 浮动可视化面板
        self._status_panel = None  # 浮动状态面板
        self._control_panel = None # 浮动控制面板
        self._mini_piano = None
        self._visualizer = None
        self._lift_loop_active = False
        self._skip_canvas_click = False
        self._float_progress_pct = 0.0
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

    # ══════════════════════════════════════════════
    #  悬浮触发按钮 (常驻小部件)
    # ══════════════════════════════════════════════
    def _create_floating_widget(self):
        """创建高质感常驻悬浮小条 — 点击打开 SAO 菜单"""
        FW, FH = 310, 70
        self._fw, self._fh = FW, FH

        self._float = tk.Toplevel(self.root)
        self._float.overrideredirect(True)
        self._float.attributes('-topmost', True)
        self._float.attributes('-alpha', 0.95)
        self._float.configure(bg='#ffffff')

        # Win32: 任务栏 + 圆角 + 阴影 (与 SAO 对话框相同格式)
        try:
            self._float.update_idletasks()
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd = ctypes.windll.user32.GetParent(self._float.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            # CS_DROPSHADOW — 和 SAO 对话框相同的系统阴影
            cls_style = ctypes.windll.user32.GetClassLongW(hwnd, -26)
            ctypes.windll.user32.SetClassLongW(hwnd, -26, cls_style | 0x00020000)
            try:
                val = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
            except:
                pass
        except:
            pass

        cv = tk.Canvas(self._float, width=FW, height=FH,
                       bg='#ffffff', highlightthickness=0)
        cv.pack(fill=tk.BOTH, expand=True)
        self._float_cv = cv

        # ── 静态装饰 (SAO Utils 白色风格) ──
        # 白底微灰渐变 (top → bottom)
        for i in range(0, FH, 2):
            t = i / FH
            gv = int(255 - 8 * t)
            cv.create_line(0, i, FW, i, fill=f'#{gv:02x}{gv:02x}{gv:02x}')

        # 左侧金色高光条 (SAO 特征)
        cv.create_rectangle(0, 0, 3, FH, fill='#f3d49a', outline='')
        cv.create_rectangle(0, 0, 1, FH, fill='#f3af12', outline='')

        # 外边框: 浅灰, 底部金色线
        cv.create_rectangle(0, 0, FW - 1, FH - 1, outline='#d1d1d6', width=1)
        cv.create_line(1, FH - 2, FW - 1, FH - 2, fill='#f3af12', width=1)
        cv.create_line(1, FH - 3, FW - 1, FH - 3, fill='#e8e4dc', width=1)

        # 菱形图标 (带外发光)
        ix, iy = 22, 33
        # 外发光 (模拟 AA)
        cv.create_polygon(ix, iy - 10, ix + 10, iy, ix, iy + 10, ix - 10, iy,
                          fill='#f8f0e0', outline='#e8d8b0', width=1, smooth=True)
        cv.create_polygon(ix, iy - 9, ix + 9, iy, ix, iy + 9, ix - 9, iy,
                          fill='#f5e8c8', outline='#d4a820', width=1, smooth=False)
        cv.create_polygon(ix, iy - 7, ix + 7, iy, ix, iy + 7, ix - 7, iy,
                          fill='#f3af12', outline='')

        # 标题
        cv.create_text(40, 19, text='咲 Midi Player',
                       fill='#333333', font=('Segoe UI', 10, 'bold'), anchor='w')

        # 内容分隔线
        cv.create_line(40, 33, FW - 72, 33, fill='#e0e0e0', width=1)

        # SAO 菜单按钮 (金色圆) — 点击区域
        bx, by = FW - 26, 30
        # 外环发光层
        cv.create_oval(bx - 17, by - 17, bx + 17, by + 17,
                       fill='', outline='#f5e0a0', width=1)
        cv.create_oval(bx - 16, by - 16, bx + 16, by + 16,
                       fill='', outline='#e8c860', width=1)
        cv.create_oval(bx - 15, by - 15, bx + 15, by + 15,
                       fill='#f9f5ee', outline='#f3af12', width=2, tags='sao_ring')
        cv.create_oval(bx - 9, by - 9, bx + 9, by + 9,
                       fill='#f3af12', outline='', tags='sao_dot')
        # 三条横线 (menu icon)
        for yi in [-3, 0, 3]:
            cv.create_line(bx - 5, by + yi, bx + 5, by + yi,
                           fill='#ffffff', width=1, tags='sao_lines')

        # ── 动态元素 (存 item id) ──
        # 文件名/副标题
        self._float_fname_id = cv.create_text(
            40, 46, text='未选择文件  |  Alt+A 打开菜单',
            fill='#999999', font=('Microsoft YaHei UI', 7), anchor='w', tags='fname')

        # 进度条背景
        pb_x0, pb_y0, pb_x1, pb_y1 = 40, 59, FW - 72, 63
        cv.create_rectangle(pb_x0, pb_y0, pb_x1, pb_y1,
                            fill='#e8e8e8', outline='#d1d1d6')
        self._float_pbar_id = cv.create_rectangle(
            pb_x0, pb_y0, pb_x0, pb_y1, fill='#f3af12', outline='', tags='pbar')
        self._float_pb_coords = (pb_x0, pb_y0, pb_x1, pb_y1)

        # 状态指示灯
        self._float_status_dot = cv.create_oval(
            FW - 64, 26, FW - 54, 36,
            fill='#e0e0e0', outline='#d1d1d6', width=1)

        # ── 浮动按钮: ▶ 播放/暂停 和 ■ 停止 ──
        btn_y0, btn_y1 = FH - 20, FH - 4        # y: 50 – 66
        # ▶ 播放/暂停
        cv.create_rectangle(FW - 72, btn_y0, FW - 50, btn_y1,
                            fill='#f5f5f5', outline='#d1d1d6', tags='play_bg')
        self._float_play_icon = cv.create_text(
            FW - 61, (btn_y0 + btn_y1) // 2,
            text='▶', fill='#2a9040',
            font=('Segoe UI', 8), tags='play_txt')
        # ■ 停止
        cv.create_rectangle(FW - 48, btn_y0, FW - 26, btn_y1,
                            fill='#f5f5f5', outline='#d1d1d6', tags='stop_bg')
        cv.create_text(FW - 37, (btn_y0 + btn_y1) // 2,
                       text='■', fill='#c04040',
                       font=('Segoe UI', 8), tags='stop_txt')

        # 按钮交互绑定
        def _on_play_enter(e):
            cv.itemconfig('play_bg', outline='#40a060')
            cv.itemconfig('play_txt', fill='#3ad86c')
        def _on_play_leave(e):
            cv.itemconfig('play_bg', outline='#d1d1d6')
            cv.itemconfig('play_txt', fill='#2a9040')
        def _on_play_click(e):
            self._skip_canvas_click = True
            self.root.after(0, self._toggle_play)
        def _on_stop_enter(e):
            cv.itemconfig('stop_bg', outline='#c04040')
            cv.itemconfig('stop_txt', fill='#e04040')
        def _on_stop_leave(e):
            cv.itemconfig('stop_bg', outline='#d1d1d6')
            cv.itemconfig('stop_txt', fill='#c04040')
        def _on_stop_click(e):
            self._skip_canvas_click = True
            self.root.after(0, self._stop)
        for tag in ('play_bg', 'play_txt'):
            cv.tag_bind(tag, '<Enter>', _on_play_enter)
            cv.tag_bind(tag, '<Leave>', _on_play_leave)
            cv.tag_bind(tag, '<ButtonRelease-1>', _on_play_click)
        for tag in ('stop_bg', 'stop_txt'):
            cv.tag_bind(tag, '<Enter>', _on_stop_enter)
            cv.tag_bind(tag, '<Leave>', _on_stop_leave)
            cv.tag_bind(tag, '<ButtonRelease-1>', _on_stop_click)

        # ── 拖拽 / 点击 交互 ──
        self._drag = {'x': 0, 'y': 0, 'dragging': False}
        cv.bind('<Button-1>', self._float_click)
        cv.bind('<B1-Motion>', self._float_drag)
        cv.bind('<ButtonRelease-1>', self._float_release)
        cv.bind('<Enter>', self._float_enter)
        cv.bind('<Leave>', self._float_leave)

        # 右键菜单
        self._float_ctx = tk.Menu(self._float, tearoff=0, bg='#ffffff',
                                  fg='#333333', activebackground='#f3af12',
                                  activeforeground='#ffffff',
                                  font=('Microsoft YaHei UI', 9))
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
        self._float_ctx.add_command(label='↺ 切换到 Old UI', command=self._switch_to_old_ui)
        self._float_ctx.add_command(label='✕ 退出', command=self._on_close)
        cv.bind('<Button-3>', lambda e: self._float_ctx.tk_popup(e.x_root, e.y_root))

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
        if not self._breath_active:
            return
        if self._drag.get('dragging', False):
            self.root.after(80, self._breath_step)
            return
        try:
            if not self._float.winfo_exists():
                return
            elapsed = time.time() - self._breath_t0
            # SAO Utils 呼吸: 8s 周期, 4 waypoints (0,0)→(0,4)→(-4,0)→(-4,4)→(0,0)
            phase = (elapsed % 8.0) / 8.0
            waypoints = [(0, 0), (0, 4), (-4, 0), (-4, 4), (0, 0)]
            idx = min(int(phase * 4), 3)
            local_t = (phase * 4) - idx
            x0, y0 = waypoints[idx]
            x1, y1 = waypoints[idx + 1]
            dx = int(x0 + (x1 - x0) * local_t)
            dy = int(y0 + (y1 - y0) * local_t)
            self._float.geometry(f'+{self._breath_base_x + dx}+{self._breath_base_y + dy}')
        except Exception:
            pass
        self.root.after(50, self._breath_step)

    def _stop_float_breath(self):
        self._breath_active = False
        # 恢复到基准位置
        try:
            if self._float.winfo_exists():
                self._float.geometry(f'+{self._breath_base_x}+{self._breath_base_y}')
        except Exception:
            pass

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
            # 拖拽结束 — 记住位置, 从新位置重启呼吸
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
        cv = self._float_cv
        cv.itemconfig('sao_ring', outline='#ffd700')
        cv.itemconfig('sao_dot', fill='#ffd700')
        cv.itemconfig('fname', fill='#555555')
        # 微升透明度 = 浮动感
        try:
            self._float.attributes('-alpha', 1.0)
        except Exception:
            pass

    def _float_leave(self, e):
        cv = self._float_cv
        cv.itemconfig('sao_ring', outline='#f3af12')
        cv.itemconfig('sao_dot', fill='#f3af12')
        cv.itemconfig('fname', fill='#999999')
        try:
            self._float.attributes('-alpha', 0.95)
        except Exception:
            pass

    def _update_float_display(self):
        """更新悬浮按钮的文件名 + 进度条 + 状态灯 + 播放按钮图标"""
        cv = self._float_cv
        if not cv.winfo_exists():
            return
        # 状态灯
        if self._playing and not self._paused:
            dot_fill, dot_outline = '#3ad86c', '#2a9040'
        elif self._paused:
            dot_fill, dot_outline = '#f0a030', '#c08020'
        else:
            dot_fill, dot_outline = '#e0e0e0', '#d1d1d6'
        cv.itemconfig(self._float_status_dot, fill=dot_fill, outline=dot_outline)
        # 播放/暂停按钮图标 + 颜色
        if self._playing and not self._paused:
            cv.itemconfig(self._float_play_icon, text='⏸', fill='#f0a030')
        else:
            cv.itemconfig(self._float_play_icon, text='▶', fill='#2a9040')
        # 进度条
        x0, y0, x1, y1 = self._float_pb_coords
        fill_x = x0 + int((x1 - x0) * self._float_progress_pct)
        cv.coords(self._float_pbar_id, x0, y0, max(x0, fill_x), y1)

    def _update_float_status(self):
        self._update_float_display()

    def _update_float_fname(self, name=''):
        cv = self._float_cv
        if not cv.winfo_exists():
            return
        if name:
            display = name if len(name) <= 32 else name[:29] + '...'
            cv.itemconfig(self._float_fname_id, text=display, fill='#666666')
        else:
            cv.itemconfig(self._float_fname_id,
                          text='未选择文件  |  Alt+A 打开菜单', fill='#999999')

    def _animate_float_to(self, x0, y0, x1, y1, ms=700):
        """将悬浮窗口从 (x0,y0) 平滑动画到 (x1,y1)"""
        steps = max(1, ms // 16)
        step = [0]
        def tick():
            if not self._float.winfo_exists():
                return
            step[0] += 1
            t = min(1.0, step[0] / steps)
            et = ease_out(t)
            x = int(x0 + (x1 - x0) * et)
            y = int(y0 + (y1 - y0) * et)
            self._float.geometry(f'+{x}+{y}')
            if t < 1.0:
                self.root.after(16, tick)
        tick()

    def _lift_float_loop(self):
        """SAO 菜单开启时持续将悬浮按钮保持在最上层"""
        if not self._lift_loop_active:
            return
        try:
            if self._float.winfo_exists():
                self._float.lift()
        except Exception:
            pass
        self.root.after(150, self._lift_float_loop)

    # ══════════════════════════════════════════════
    #  SAO 菜单 = 主界面
    # ══════════════════════════════════════════════
    def _make_player_panel(self, parent):
        """工厂: 为 SAO 菜单创建左侧玩家信息面板"""
        panel = SAOPlayerPanel(parent)
        self._player_panel = panel

        # 同步当前状态
        if self._current_file:
            panel._file_name = os.path.basename(self._current_file)
        panel._speed = self._speed
        panel._transpose = self._transpose
        panel._is_playing = self._playing
        panel._status = "播放中" if self._playing else ("已暂停" if self._paused else "就绪")
        mode = self.settings.get('mode_system', 'classic')
        panel._mode = '经典60键' if mode == 'classic' else '扩展88键'
        panel._sustain = self._sustain_active

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
            ],
            '关于': [
                {'icon': '◇', 'label': '关于本程序', 'command': self._show_about},
                {'icon': '↺', 'label': '切换到 Old UI', 'command': self._switch_to_old_ui},
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
            username='Player',
            description='咲 Midi Player SAO Edition',
            on_close=self._on_sao_menu_close,
            on_open=self._on_sao_menu_open,
            key_code='a',
            slide_down=False,
            left_widget_factory=self._make_player_panel,
            anchor_widget=self._float,
        )
        self._sao_menu.bind_events()

    def _fade_panel_in(self, panel, target=0.92, duration_ms=350):
        """浮动面板淡入 — 平滑 ease-out 动画"""
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
                self.root.after(16, _step)

        _step()

    def _toggle_sao_menu(self):
        if self._sao_menu.visible:
            self._sao_menu.close()
        else:
            self._sao_menu.child_menus = self._build_menu_children()
            self._sao_menu.open()
            # 立即将悬浮按钮浮到 overlay 之上 (避免撕裂)
            self._float.lift()

    def _on_sao_menu_open(self):
        """SAO 菜单打开时 — 停止呼吸, 启动 float 保持最顶循环"""
        self._stop_float_breath()
        self._lift_loop_active = True
        self._lift_float_loop()

    def _on_sao_menu_close(self):
        """SAO 菜单关闭时 — 重启呼吸动画"""
        self._lift_loop_active = False
        self._player_panel = None
        self._restore_focus()
        self.root.after(400, self._start_float_breath)

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
            return

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
        self._piano_panel.attributes('-alpha', 0.0)  # 淡入动画起点
        self._piano_panel.geometry(f'{pw}x{ph}+{fx}+{fy}')
        self._piano_panel.configure(bg='#ffffff')

        # DWM 圆角 + 系统阴影
        _apply_panel_style(self._piano_panel)

        # 边框
        border = tk.Frame(self._piano_panel, bg='#d1d1d6', padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg='#ffffff')
        inner.pack(fill=tk.BOTH, expand=True)

        # 标题行
        hdr = tk.Frame(inner, bg='#f5f5f7', height=20)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text='◆ Piano', bg='#f5f5f7', fg='#646364',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=8)
        close_lbl = tk.Label(hdr, text='×', bg='#f5f5f7', fg='#999999',
                             font=('Consolas', 11), cursor='hand2')
        close_lbl.pack(side=tk.RIGHT, padx=6)
        close_lbl.bind('<Button-1>', lambda e: self._toggle_piano_panel())

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

        self._mini_piano = SAOMiniPiano(inner, octaves=5)
        self._mini_piano.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._fade_panel_in(self._piano_panel, target=0.90)
        self.settings.set('show_piano', True)
        self.settings.save()

    def _toggle_status_panel(self):
        """浮动状态面板 — 显示延音踏板状态 + 模式"""
        if self._status_panel and self._status_panel.winfo_exists():
            self._status_panel.destroy()
            self._status_panel = None
            self.settings.set('show_status', False)
            self.settings.save()
            return

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
        self._status_panel.attributes('-alpha', 0.0)  # 淡入动画起点
        self._status_panel.geometry(f'{sw}x{sh}+{fx}+{fy}')
        self._status_panel.configure(bg='#ffffff')
        _apply_panel_style(self._status_panel)

        border = tk.Frame(self._status_panel, bg='#d1d1d6', padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg='#ffffff')
        inner.pack(fill=tk.BOTH, expand=True)

        # 标题行
        hdr = tk.Frame(inner, bg='#f5f5f7', height=22)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text='◉ 状态', bg='#f5f5f7', fg='#646364',
                 font=('Segoe UI', 8, 'bold')).pack(side=tk.LEFT, padx=8)
        close_lbl = tk.Label(hdr, text='×', bg='#f5f5f7', fg='#999999',
                             font=('Consolas', 11), cursor='hand2')
        close_lbl.pack(side=tk.RIGHT, padx=6)
        close_lbl.bind('<Button-1>', lambda e: self._toggle_status_panel())

        # 分隔线
        tk.Frame(inner, bg='#e0e0e0', height=1).pack(fill=tk.X)

        body = tk.Frame(inner, bg='#ffffff')
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # 模式行
        mode_row = tk.Frame(body, bg='#ffffff')
        mode_row.pack(fill=tk.X, pady=3)
        tk.Label(mode_row, text='模式', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)
        self._status_mode_lbl = tk.Label(mode_row, text=self._get_mode_text(),
                                          bg='#ffffff', fg='#f3af12',
                                          font=('Microsoft YaHei UI', 9, 'bold'))
        self._status_mode_lbl.pack(side=tk.RIGHT)

        # 键位模式行 (normal/shift/ctrl)
        shift_row = tk.Frame(body, bg='#ffffff')
        shift_row.pack(fill=tk.X, pady=3)
        tk.Label(shift_row, text='键位切换', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)
        _sm_labels = {'normal': '普通模式', 'shift': 'SHIFT 高音',
                      'ctrl': 'CTRL 低音', 'lt': 'LT 极低', 'gt': 'GT 极高'}
        _sm_text = _sm_labels.get(self._shift_mode, self._shift_mode)
        self._status_shift_lbl = tk.Label(shift_row, text=_sm_text,
                                           bg='#ffffff', fg='#2196f3',
                                           font=('Segoe UI', 9, 'bold'))
        self._status_shift_lbl.pack(side=tk.RIGHT)

        # 延音行
        sus_row = tk.Frame(body, bg='#ffffff')
        sus_row.pack(fill=tk.X, pady=3)
        tk.Label(sus_row, text='延音踏板', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)
        self._status_sus_dot = tk.Canvas(sus_row, width=12, height=12,
                                          bg='#ffffff', highlightthickness=0)
        self._status_sus_dot.pack(side=tk.RIGHT, padx=(4, 0))
        self._status_sus_lbl = tk.Label(sus_row, text='OFF',
                                         bg='#ffffff', fg='#bbbbbb',
                                         font=('Segoe UI', 8, 'bold'))
        self._status_sus_lbl.pack(side=tk.RIGHT)

        # BPM行
        bpm_row = tk.Frame(body, bg='#ffffff')
        bpm_row.pack(fill=tk.X, pady=3)
        tk.Label(bpm_row, text='BPM', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)
        bpm_val = getattr(getattr(self.player, 'parser', None), 'bpm', 0)
        self._status_bpm_lbl = tk.Label(bpm_row,
                                         text=f'{bpm_val:.0f}' if bpm_val else '—',
                                         bg='#ffffff', fg='#333333',
                                         font=('Consolas', 10))
        self._status_bpm_lbl.pack(side=tk.RIGHT)

        # 速度行
        spd_row = tk.Frame(body, bg='#ffffff')
        spd_row.pack(fill=tk.X, pady=3)
        tk.Label(spd_row, text='速度', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT)
        self._status_spd_lbl = tk.Label(spd_row, text=f'{self._speed:.2f}×',
                                         bg='#ffffff', fg='#333333',
                                         font=('Consolas', 10))
        self._status_spd_lbl.pack(side=tk.RIGHT)

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
            self._status_sus_lbl.configure(text='OFF', fg='#bbbbbb')
            self._status_sus_dot.delete('all')
            self._status_sus_dot.create_oval(1, 1, 11, 11, fill='#e0e0e0', outline='#d1d1d6')
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
            return

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
        self._viz_panel.attributes('-alpha', 0.0)  # 淡入动画起点
        self._viz_panel.geometry(f'{vw}x{vh}+{fx}+{fy}')
        self._viz_panel.configure(bg='#ffffff')

        _apply_panel_style(self._viz_panel)

        border = tk.Frame(self._viz_panel, bg='#d1d1d6', padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg='#ffffff')
        inner.pack(fill=tk.BOTH, expand=True)

        hdr = tk.Frame(inner, bg='#f5f5f7', height=20)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text='◆ Visualizer', bg='#f5f5f7', fg='#646364',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=8)
        close_lbl = tk.Label(hdr, text='×', bg='#f5f5f7', fg='#999999',
                             font=('Consolas', 11), cursor='hand2')
        close_lbl.pack(side=tk.RIGHT, padx=6)
        close_lbl.bind('<Button-1>', lambda e: self._toggle_viz_panel())

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

        self._visualizer = MidiVisualizer(inner, settings=self.settings)
        self._visualizer.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        _apply_viz_light_theme(self._visualizer)
        if self._playing:
            self._visualizer.start()
        self._fade_panel_in(self._viz_panel, target=0.90)
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
            return

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
        self._control_panel.configure(bg='#ffffff')
        _apply_panel_style(self._control_panel)

        border = tk.Frame(self._control_panel, bg='#d1d1d6', padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg='#ffffff')
        inner.pack(fill=tk.BOTH, expand=True)

        # 标题栏
        hdr = tk.Frame(inner, bg='#f5f5f7', height=24)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text='⚙ 控制面板', bg='#f5f5f7', fg='#646364',
                 font=('Segoe UI', 8, 'bold')).pack(side=tk.LEFT, padx=8)
        close_lbl = tk.Label(hdr, text='×', bg='#f5f5f7', fg='#999999',
                              font=('Consolas', 11), cursor='hand2')
        close_lbl.pack(side=tk.RIGHT, padx=6)
        close_lbl.bind('<Button-1>', lambda e: self._toggle_control_panel())
        _cd = {'x': 0, 'y': 0}
        def cdstart(e): _cd['x'], _cd['y'] = e.x_root, e.y_root
        def cdmove(e):
            dx, dy = e.x_root - _cd['x'], e.y_root - _cd['y']
            nx, ny = self._control_panel.winfo_x()+dx, self._control_panel.winfo_y()+dy
            self._control_panel.geometry(f'+{nx}+{ny}')
            _cd['x'], _cd['y'] = e.x_root, e.y_root
            self.settings.set('ctrl_x', nx); self.settings.set('ctrl_y', ny)
        hdr.bind('<Button-1>', cdstart); hdr.bind('<B1-Motion>', cdmove)

        tk.Frame(inner, bg='#e0e0e0', height=1).pack(fill=tk.X)
        body = tk.Frame(inner, bg='#ffffff')
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # ── pill 切换按钮辅助 ──
        def pill(parent, text, active, command):
            lbl = tk.Label(parent, text=text,
                           bg='#f3af12' if active else '#eeeeee',
                           fg='#ffffff' if active else '#999999',
                           font=('Microsoft YaHei UI', 8, 'bold'),
                           padx=8, pady=2, cursor='hand2', relief=tk.FLAT)
            lbl.bind('<Button-1>', lambda e: command())
            return lbl

        # ── 键位模式 ──
        row_mode = tk.Frame(body, bg='#ffffff')
        row_mode.pack(fill=tk.X, pady=(2, 3))
        tk.Label(row_mode, text='键位', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8), width=5, anchor='w').pack(side=tk.LEFT)
        cur_mode = self.settings.get('mode_system', 'classic')
        p60 = pill(row_mode, '60键 CTRL/SHIFT', cur_mode == 'classic',  lambda: self._set_mode('classic'))
        p60.pack(side=tk.LEFT, padx=(0, 4))
        p88 = pill(row_mode, '88键 </>',        cur_mode == 'extended', lambda: self._set_mode('extended'))
        p88.pack(side=tk.LEFT)
        self._control_panel._mode_pills = (p60, p88)

        tk.Frame(body, bg='#eeeeee', height=1).pack(fill=tk.X, pady=4)

        # ── 音部控制 ──
        row_part = tk.Frame(body, bg='#ffffff')
        row_part.pack(fill=tk.X, pady=2)
        tk.Label(row_part, text='音部', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8), width=5, anchor='w').pack(side=tk.LEFT)
        pm = pill(row_part, '✓ 主旋律' if self._melody_on else '✗ 主旋律', self._melody_on, self._toggle_melody)
        pm.pack(side=tk.LEFT, padx=(0, 4))
        pb = pill(row_part, '✓ 低音部' if self._bass_on else '✗ 低音部', self._bass_on, self._toggle_bass)
        pb.pack(side=tk.LEFT)
        self._control_panel._part_pills = (pm, pb)

        # ── 伴奏密度 ──
        row_dens = tk.Frame(body, bg='#ffffff')
        row_dens.pack(fill=tk.X, pady=2)
        tk.Label(row_dens, text='伴奏密度', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8), anchor='w').pack(side=tk.LEFT)
        dens_var = tk.DoubleVar(value=self._bass_density)
        dens_scale = tk.Scale(row_dens, from_=0.2, to=1.0, resolution=0.1,
                              orient=tk.HORIZONTAL, variable=dens_var,
                              bg='#ffffff', fg='#646364', troughcolor='#e8e8e8',
                              highlightthickness=0, bd=0, length=100, sliderlength=14,
                              width=10, showvalue=False,
                              command=lambda v: self._set_bass_density_direct(float(v)))
        dens_scale.pack(side=tk.LEFT, padx=(6, 2))
        dens_lbl = tk.Label(row_dens, text=f'{self._bass_density:.0%}', bg='#ffffff',
                             fg='#333333', font=('Consolas', 9), width=4)
        dens_lbl.pack(side=tk.LEFT)
        self._control_panel._dens_var = dens_var
        self._control_panel._dens_lbl = dens_lbl

        tk.Frame(body, bg='#eeeeee', height=1).pack(fill=tk.X, pady=4)

        # ── 速度 ──
        row_spd = tk.Frame(body, bg='#ffffff')
        row_spd.pack(fill=tk.X, pady=2)
        tk.Label(row_spd, text='速度', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8), width=5, anchor='w').pack(side=tk.LEFT)
        btn_sm = tk.Label(row_spd, text='−', bg='#eeeeee', fg='#646364',
                          font=('Consolas', 11, 'bold'), padx=7, pady=1, cursor='hand2')
        btn_sm.pack(side=tk.LEFT)
        btn_sm.bind('<Button-1>', lambda e: self._speed_down())
        spd_lbl = tk.Label(row_spd, text=f'{self._speed:.2f}×', bg='#ffffff',
                            fg='#333333', font=('Consolas', 10), width=6)
        spd_lbl.pack(side=tk.LEFT, padx=4)
        btn_sp = tk.Label(row_spd, text='+', bg='#eeeeee', fg='#646364',
                          font=('Consolas', 11, 'bold'), padx=7, pady=1, cursor='hand2')
        btn_sp.pack(side=tk.LEFT)
        btn_sp.bind('<Button-1>', lambda e: self._speed_up())
        self._control_panel._spd_lbl = spd_lbl

        # ── 移调 ──
        row_tr = tk.Frame(body, bg='#ffffff')
        row_tr.pack(fill=tk.X, pady=2)
        tk.Label(row_tr, text='移调', bg='#ffffff', fg='#999999',
                 font=('Segoe UI', 8), width=5, anchor='w').pack(side=tk.LEFT)
        btn_tm = tk.Label(row_tr, text='−', bg='#eeeeee', fg='#646364',
                          font=('Consolas', 11, 'bold'), padx=7, pady=1, cursor='hand2')
        btn_tm.pack(side=tk.LEFT)
        btn_tm.bind('<Button-1>', lambda e: self._transpose_down())
        tr_lbl = tk.Label(row_tr, text=f'{self._transpose:+d} 半音', bg='#ffffff',
                           fg='#333333', font=('Consolas', 10), width=7)
        tr_lbl.pack(side=tk.LEFT, padx=4)
        btn_tp = tk.Label(row_tr, text='+', bg='#eeeeee', fg='#646364',
                          font=('Consolas', 11, 'bold'), padx=7, pady=1, cursor='hand2')
        btn_tp.pack(side=tk.LEFT)
        btn_tp.bind('<Button-1>', lambda e: self._transpose_up())
        btn_rst = tk.Label(row_tr, text='重置', bg='#eeeeee', fg='#646364',
                           font=('Segoe UI', 8), padx=6, pady=2, cursor='hand2')
        btn_rst.pack(side=tk.LEFT, padx=(6, 0))
        btn_rst.bind('<Button-1>', lambda e: self._auto_transpose())
        self._control_panel._tr_lbl = tr_lbl

        tk.Frame(body, bg='#eeeeee', height=1).pack(fill=tk.X, pady=4)

        # ── 选项行 1 ──
        row_opt1 = tk.Frame(body, bg='#ffffff')
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
        row_opt2 = tk.Frame(body, bg='#ffffff')
        row_opt2.pack(fill=tk.X, pady=2)
        gl_lbl = pill(row_opt2, '结尾滑奏 ✓' if self._glissando else '结尾滑奏',
                      self._glissando, self._toggle_glissando)
        gl_lbl.pack(side=tk.LEFT, padx=(0, 6))
        midi_btn = tk.Label(row_opt2, text='MIDI通道…', bg='#eeeeee', fg='#646364',
                            font=('Segoe UI', 8), padx=8, pady=2, cursor='hand2')
        midi_btn.pack(side=tk.LEFT)
        midi_btn.bind('<Button-1>', lambda e: self._show_channel_settings())
        self._control_panel._gl_lbl = gl_lbl

        self._fade_panel_in(self._control_panel, target=0.95)
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
            pm.configure(bg='#f3af12' if self._melody_on else '#eeeeee',
                         fg='#ffffff' if self._melody_on else '#999999',
                         text='✓ 主旋律' if self._melody_on else '✗ 主旋律')
            pb.configure(bg='#f3af12' if self._bass_on else '#eeeeee',
                         fg='#ffffff' if self._bass_on else '#999999',
                         text='✓ 低音部' if self._bass_on else '✗ 低音部')
        if hasattr(p, '_mode_pills'):
            p60, p88 = p._mode_pills
            cur = self.settings.get('mode_system', 'classic')
            p60.configure(bg='#f3af12' if cur == 'classic' else '#eeeeee',
                          fg='#ffffff' if cur == 'classic' else '#999999')
            p88.configure(bg='#f3af12' if cur == 'extended' else '#eeeeee',
                          fg='#ffffff' if cur == 'extended' else '#999999')
        if hasattr(p, '_dc_lbl'):
            p._dc_lbl.configure(
                text='C调直转 ✓' if self._direct_c else 'C调直转',
                bg='#f3af12' if self._direct_c else '#eeeeee',
                fg='#ffffff' if self._direct_c else '#999999')
        if hasattr(p, '_pf_lbl'):
            p._pf_lbl.configure(
                text='熟练度 ✓' if self._proficiency_enabled else '熟练度',
                bg='#f3af12' if self._proficiency_enabled else '#eeeeee',
                fg='#ffffff' if self._proficiency_enabled else '#999999')
        if hasattr(p, '_gl_lbl'):
            p._gl_lbl.configure(
                text='结尾滑奏 ✓' if self._glissando else '结尾滑奏',
                bg='#f3af12' if self._glissando else '#eeeeee',
                fg='#ffffff' if self._glissando else '#999999')

    def _set_bass_density_direct(self, val: float):
        """直接设置伴奏密度 (由控制面板滑块调用)"""
        self._bass_density = round(val, 1)
        self.player.set_bass_density(self._bass_density)
        if self._control_panel and self._control_panel.winfo_exists():
            if hasattr(self._control_panel, '_dens_lbl'):
                self._control_panel._dens_lbl.configure(text=f'{self._bass_density:.0%}')
        self._refresh_menu_if_open()

    def _restore_panels(self):
        """恢复上次会话中打开的浮动面板"""
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
            # 定位到中央, 显示, 然后滑动到目标位置
            self._float.geometry(f'{self._fw}x{self._fh}+{fx_start}+{fy_start}')
            self._float.deiconify()
            self._float.lift()
            self._animate_float_to(fx_start, fy_start, fx_final, fy_final, ms=750)
            # 滑动完成后启动呼吸, 再自动打开菜单
            self._breath_base_x = fx_final
            self._breath_base_y = fy_final
            self.root.after(800, self._start_float_breath)
            self.root.after(1150, self._toggle_sao_menu)
            # 恢复上次打开的浮动面板
            self.root.after(1600, self._restore_panels)

        ls = SAOLinkStart(self.root, on_done=on_done)
        ls.play()

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
        if self._player_panel:
            self._player_panel.update_mode('经典60键' if mode == 'classic' else '扩展88键')
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
        if self._folder_loop_active:
            self._folder_loop_active = False
            self._refresh_menu_if_open()
            return

        if not self._current_file:
            SAODialog.showwarning(self._float, "提示", "请先打开一个MIDI文件")
            return

        folder = os.path.dirname(self._current_file)
        files = sorted([os.path.join(folder, f) for f in os.listdir(folder)
                        if f.lower().endswith(('.mid', '.midi'))])
        if not files:
            SAODialog.showwarning(self._float, "提示", "当前文件夹中没有MIDI文件")
            return

        self._folder_loop_active = True
        self._folder_loop_files = files
        try:
            self._folder_loop_index = files.index(self._current_file)
        except ValueError:
            self._folder_loop_index = 0
        self._refresh_menu_if_open()

    def _play_next_folder_song(self):
        if not self._folder_loop_active or not self._folder_loop_files:
            return
        self._folder_loop_index = (self._folder_loop_index + 1) % len(self._folder_loop_files)
        next_file = self._folder_loop_files[self._folder_loop_index]
        self._on_file_selected(next_file)
        self.root.after(500, self._toggle_play)

    # ══════════════════════════════════════════════
    #  回调绑定
    # ══════════════════════════════════════════════
    def _bind_callbacks(self):
        def on_note(key, note, is_chord=False):
            dur = int(min(2000, max(100, note.duration * 1000)))
            vel = note.velocity / 127.0 if hasattr(note, 'velocity') else 0.8
            midi_note = note.note
            if self._mini_piano:
                self.root.after(0, lambda: self._mini_piano.note_on(midi_note, vel, dur))
            if self._visualizer:
                self.root.after(0, lambda k=key, v=vel: self._visualizer.trigger_note(k, v))

        def on_progress(current, total):
            self.root.after(0, lambda: self._update_progress(current, total))

        def on_end():
            self.root.after(0, self._on_playback_end)

        def on_sustain(active: bool):
            self._sustain_active = active
            if self._player_panel:
                self.root.after(0, lambda: self._player_panel.update_sustain(active))
            self.root.after(0, self._update_status_panel)

        def on_shift(mode):
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
        if self._player_panel:
            self._player_panel.update_status("播放完成", False)
            self._player_panel.update_progress(0, 0)
        if self._mini_piano:
            self._mini_piano.reset()
        if self._visualizer:
            self._visualizer.stop()
        self._refresh_menu_if_open()
        if self._folder_loop_active:
            self.root.after(500, self._play_next_folder_song)

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

    def _switch_to_old_ui(self):
        self.settings.set('ui_mode', 'old')
        if self._sao_menu.visible:
            self._sao_menu.close()
        SAODialog.showinfo(self._float, "切换 UI",
                           "将切换到经典 UI 模式。\n请重新启动程序。")

    def _show_about(self):
        if self._sao_menu.visible:
            self._sao_menu.close()
        self.root.after(600, lambda: SAODialog.showinfo(
            self._float, "关于",
            "咲 Midi Player  SAO Edition\nv2.2.0\n\n"
            "Alt+A 打开 SAO 菜单\n"
            "右键悬浮按钮查看更多选项"))

    def _on_close(self):
        if hasattr(self, '_hotkey_mgr'):
            self._hotkey_mgr.cleanup()
        try:
            self._sao_menu.unbind_events()
            if self._sao_menu.visible:
                self._sao_menu.close()
        except Exception:
            pass
        self.player.stop()
        # 销毁所有浮动面板
        for panel in [self._piano_panel, self._viz_panel, self._status_panel]:
            try:
                if panel and panel.winfo_exists():
                    panel.destroy()
            except Exception:
                pass
        try:
            if self._float and self._float.winfo_exists():
                self._float.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
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
