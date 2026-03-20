# -*- coding: utf-8 -*-
"""
GUI模块 - 现代扁平风格图形用户界面
支持自定义快捷键、窗口置顶、平滑动画
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import json
import ctypes
from typing import Optional, Dict, Callable

from player import MidiPlayer
from midi_parser import NoteEvent
from config import (
    WINDOW_TITLE, WINDOW_SIZE, 
    KEYBOARD_LAYOUT, NOTE_NAMES, BLACK_KEY_LAYOUT, BLACK_KEY_NAMES,
    DEFAULT_HOTKEYS, CONFIG_FILE
)

# 检查是否有管理员权限（Windows）
def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# 尝试导入keyboard用于全局快捷键（备用）
KEYBOARD_HOTKEY_AVAILABLE = False
KEYBOARD_ERROR_MSG = None

try:
    import keyboard as kb
    # 测试keyboard是否能正常工作
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

# 使用pynput监控快捷键（与按键模拟分离，避免阻塞）
PYNPUT_HOTKEY_AVAILABLE = False
try:
    from pynput import keyboard as pynput_kb
    from pynput.keyboard import Key, KeyCode
    PYNPUT_HOTKEY_AVAILABLE = True
except ImportError:
    pass

# 最终确定使用哪个库
GLOBAL_HOTKEY_AVAILABLE = PYNPUT_HOTKEY_AVAILABLE or KEYBOARD_HOTKEY_AVAILABLE


# ==================== 现代配色方案 ====================
class ModernColors:
    """现代扁平配色"""
    # 背景
    BG_DARK = "#1E1E2E"          # 深色背景
    BG_CARD = "#2D2D3F"          # 卡片背景
    BG_HOVER = "#3D3D4F"         # 悬停背景
    BG_INPUT = "#252535"         # 输入框背景
    
    # 强调色
    ACCENT_BLUE = "#7AA2F7"      # 柔和蓝
    ACCENT_GREEN = "#9ECE6A"     # 柔和绿
    ACCENT_RED = "#F7768E"       # 柔和红
    ACCENT_ORANGE = "#FF9E64"    # 柔和橙
    ACCENT_PURPLE = "#BB9AF7"    # 柔和紫
    ACCENT_CYAN = "#7DCFFF"      # 柔和青
    
    # 文字
    TEXT_PRIMARY = "#C0CAF5"     # 主文字
    TEXT_SECONDARY = "#565F89"   # 次级文字
    TEXT_BRIGHT = "#FFFFFF"      # 亮色文字
    
    # 按键行颜色
    ROW_HIGH = "#3B2D3D"         # 高音 - 暗红
    ROW_MID_HIGH = "#3D3528"     # 中高音 - 暗橙
    ROW_MID = "#283545"          # 中音 - 暗蓝
    ROW_CHORD = "#352D45"        # 和弦 - 暗紫
    
    # 按键
    KEY_NORMAL = "#3D3D4F"
    KEY_PRESSED = "#9ECE6A"
    KEY_BORDER = "#4D4D5F"


class SettingsManager:
    """设置管理器"""
    
    def __init__(self):
        self.settings = {
            'hotkeys': DEFAULT_HOTKEYS.copy(),
            'last_file': '',
            'speed': 1.0,
            'transpose': 0,
            'chord_mode': False,  # 36键模式下默认关闭和弦识别
        }
        self.load()
        
    def load(self):
        """加载设置"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    self.settings.update(saved)
        except:
            pass
            
    def save(self):
        """保存设置"""
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
    """获取图标路径"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, 'icon.ico')
    return icon_path if os.path.exists(icon_path) else None


class SmoothButton(tk.Canvas):
    """平滑动画按钮"""
    
    def __init__(self, parent, text="", command=None, width=100, height=40,
                 bg="#7AA2F7", fg="#FFFFFF", radius=10, font_size=11, **kwargs):
        # 获取父容器背景色
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
        self._animating = False
        
        self._draw()
        
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)
        
    def _lerp_color(self, c1, c2, t):
        """颜色插值"""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _brighten(self, color, amount=25):
        """使颜色变亮"""
        r = min(255, int(color[1:3], 16) + amount)
        g = min(255, int(color[3:5], 16) + amount)
        b = min(255, int(color[5:7], 16) + amount)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _darken(self, color, amount=25):
        """使颜色变暗"""
        r = max(0, int(color[1:3], 16) - amount)
        g = max(0, int(color[3:5], 16) - amount)
        b = max(0, int(color[5:7], 16) - amount)
        return f"#{r:02x}{g:02x}{b:02x}"
        
    def _draw(self, color=None):
        """绘制按钮"""
        self.delete("all")
        color = color or self.current_bg
        w, h, r = self.winfo_reqwidth(), self.winfo_reqheight(), self.radius
        
        # 圆角矩形
        points = [
            r, 0, w-r, 0,
            w, 0, w, r,
            w, h-r, w, h,
            w-r, h, r, h,
            0, h, 0, h-r,
            0, r, 0, 0,
            r, 0
        ]
        self.create_polygon(points, fill=color, smooth=True)
        
        # 文字
        self.create_text(w/2, h/2, text=self.text, fill=self.fg,
                        font=('Microsoft YaHei UI', self.font_size, 'bold'))
        
    def _animate_to(self, target_color, steps=5):
        """平滑动画到目标颜色"""
        if self._animating:
            return
        self._animating = True
        
        def step(i):
            if i >= steps:
                self._animating = False
                return
            t = i / steps
            color = self._lerp_color(self.current_bg, target_color, t)
            self.current_bg = color
            self._draw()
            self.after(16, lambda: step(i + 1))
        
        step(0)
        
    def _on_enter(self, e):
        self._draw(self._brighten(self.base_bg, 20))
        
    def _on_leave(self, e):
        self._draw(self.base_bg)
        self.current_bg = self.base_bg
        
    def _on_click(self, e):
        self._draw(self._darken(self.base_bg, 20))
        
    def _on_release(self, e):
        self._draw(self.base_bg)
        if self.command:
            self.command()
            
    def set_text(self, text):
        self.text = text
        self._draw()
        
    def set_bg(self, color):
        self.base_bg = color
        self.current_bg = color
        self._draw()


class PianoKey(tk.Canvas):
    """钢琴按键 - 支持渐亮渐暗动画"""
    
    # 动画参数
    FADE_IN_STEPS = 3       # 渐亮步数（快速亮起）
    FADE_OUT_STEPS = 8      # 渐暗步数（缓慢熄灭）
    FRAME_DELAY = 16        # 每帧延迟(ms)，约60fps
    
    def __init__(self, parent, note_name: str, key_char: str,
                 row_color: str = ModernColors.KEY_NORMAL, is_black: bool = False, **kwargs):
        self._is_black_key = is_black
        if is_black:
            super().__init__(parent, width=52, height=46,
                            bg=ModernColors.BG_CARD, highlightthickness=0, **kwargs)
        else:
            super().__init__(parent, width=72, height=68,
                            bg=ModernColors.BG_CARD, highlightthickness=0, **kwargs)
        
        self.note_name = note_name
        self.key_char = key_char
        self.base_color = row_color
        self.current_color = row_color
        self._highlight_id = None
        self._fade_animation_id = None
        self._is_pressed = False
        
        self._draw()
    
    def _lerp_color(self, c1, c2, t):
        """颜色插值"""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
        
    def _draw(self):
        """绘制按键"""
        self.delete("all")
        if self._is_black_key:
            w, h = 52, 46
            r = 8
            # 阴影
            self._draw_rounded_rect(2, 2, w-1, h-1, r, '#0A0A0F')
            # 主体
            self._draw_rounded_rect(0, 0, w-3, h-3, r, self.current_color)
            # 边框
            self._draw_rounded_rect_outline(0, 0, w-3, h-3, r, '#555566')
            # 音符名
            self.create_text(24, 14, text=self.note_name,
                            fill='#CCCCDD',
                            font=('Microsoft YaHei UI', 10, 'bold'))
            # 按键提示
            self.create_text(24, 32, text=f"[{self.key_char.upper()}]",
                            fill='#888899',
                            font=('Microsoft YaHei UI', 8))
        else:
            w, h = 72, 68
            r = 12
            # 阴影
            self._draw_rounded_rect(3, 3, w-1, h-1, r, ModernColors.BG_DARK)
            # 主体
            self._draw_rounded_rect(0, 0, w-4, h-4, r, self.current_color)
            # 边框高光
            self._draw_rounded_rect_outline(0, 0, w-4, h-4, r, ModernColors.KEY_BORDER)
            # 音符名
            self.create_text(34, 24, text=self.note_name,
                            fill=ModernColors.TEXT_PRIMARY,
                            font=('Microsoft YaHei UI', 14, 'bold'))
            # 按键提示
            self.create_text(34, 48, text=f"[{self.key_char.upper()}]",
                            fill=ModernColors.TEXT_SECONDARY,
                            font=('Microsoft YaHei UI', 9))
        
    def _draw_rounded_rect(self, x, y, w, h, r, color):
        """绘制圆角矩形"""
        points = [
            x+r, y, w-r, y,
            w, y, w, y+r,
            w, h-r, w, h,
            w-r, h, x+r, h,
            x, h, x, h-r,
            x, y+r, x, y,
            x+r, y
        ]
        self.create_polygon(points, fill=color, smooth=True)
        
    def _draw_rounded_rect_outline(self, x, y, w, h, r, color):
        """绘制圆角矩形边框"""
        points = [
            x+r, y, w-r, y,
            w, y, w, y+r,
            w, h-r, w, h,
            w-r, h, x+r, h,
            x, h, x, h-r,
            x, y+r, x, y,
            x+r, y
        ]
        self.create_line(points, fill=color, smooth=True, width=1)
    
    def _cancel_animations(self):
        """取消所有动画"""
        if self._highlight_id:
            self.after_cancel(self._highlight_id)
            self._highlight_id = None
        if self._fade_animation_id:
            self.after_cancel(self._fade_animation_id)
            self._fade_animation_id = None
    
    def highlight(self, duration_ms: int = 180):
        """高亮按键 - 带渐亮渐暗效果"""
        self._cancel_animations()
        self._is_pressed = True
        
        # 渐亮动画
        self._fade_in(duration_ms)
    
    def _fade_in(self, hold_duration_ms: int):
        """渐亮动画"""
        start_color = self.current_color
        target_color = ModernColors.KEY_PRESSED
        step = [0]
        
        def animate():
            if step[0] >= self.FADE_IN_STEPS:
                # 渐亮完成，保持高亮状态一段时间后开始渐暗
                self.current_color = target_color
                self._draw()
                # 计算保持时间（总时长 - 渐亮时间 - 渐暗时间）
                fade_in_time = self.FADE_IN_STEPS * self.FRAME_DELAY
                fade_out_time = self.FADE_OUT_STEPS * self.FRAME_DELAY
                hold_time = max(0, hold_duration_ms - fade_in_time - fade_out_time)
                self._highlight_id = self.after(hold_time, self._fade_out)
                return
            
            t = (step[0] + 1) / self.FADE_IN_STEPS
            # 使用ease-out曲线使动画更自然
            t = 1 - (1 - t) ** 2
            self.current_color = self._lerp_color(start_color, target_color, t)
            self._draw()
            step[0] += 1
            self._fade_animation_id = self.after(self.FRAME_DELAY, animate)
        
        animate()
    
    def _fade_out(self):
        """渐暗动画"""
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
            # 使用ease-in-out曲线
            t = t * t * (3 - 2 * t)
            self.current_color = self._lerp_color(start_color, target_color, t)
            self._draw()
            step[0] += 1
            self._fade_animation_id = self.after(self.FRAME_DELAY, animate)
        
        animate()
        
    def _restore(self):
        """恢复（兼容旧接口）"""
        self._fade_out()
        
    def reset(self):
        """重置"""
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
        """创建键盘"""
        row_labels = ['高音', '中音', '低音']
        row_colors = [
            ModernColors.ROW_HIGH,
            ModernColors.ROW_MID_HIGH,
            ModernColors.ROW_MID,
        ]
        
        for row_idx, (row_name, keys) in enumerate(KEYBOARD_LAYOUT.items()):
            # 行标签
            lbl = tk.Label(self, text=row_labels[row_idx], width=5,
                          bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                          font=('Microsoft YaHei UI', 10))
            lbl.grid(row=row_idx*2, column=0, padx=8, pady=2, rowspan=2)
            
            # 白键
            for col_idx, key in enumerate(keys):
                note_name = NOTE_NAMES[row_name][col_idx]
                piano_key = PianoKey(self, note_name, key, row_colors[row_idx])
                piano_key.grid(row=row_idx*2+1, column=col_idx+1, padx=2, pady=2)
                self.keys[key] = piano_key
            
            # 黑键（如果有）
            black_row_name = f'{row_name}_black'
            if black_row_name in BLACK_KEY_LAYOUT:
                black_keys = BLACK_KEY_LAYOUT[black_row_name]
                black_names = BLACK_KEY_NAMES[black_row_name]
                for col_idx, bkey in enumerate(black_keys):
                    if bkey is not None:
                        bname = black_names[col_idx] if black_names[col_idx] else '♯'
                        piano_key = PianoKey(self, bname, bkey, '#2D2D3F', is_black=True)
                        piano_key.grid(row=row_idx*2, column=col_idx+1, padx=2, pady=1)
                        self.keys[bkey] = piano_key
                
    def highlight_key(self, key: str, duration_ms: int = 180):
        key = key.lower()
        if key in self.keys:
            self.keys[key].highlight(duration_ms)
            
    def reset_all(self):
        for k in self.keys.values():
            k.reset()


class HotkeyButton(tk.Frame):
    """快捷键设置按钮"""
    
    def __init__(self, parent, label: str, current_key: str,
                 on_change: Callable[[str], None], **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        
        self.on_change = on_change
        self.current_key = current_key
        self.is_recording = False
        self._keyboard_hook = None
        
        # 标签
        self.label = tk.Label(self, text=label, width=10, anchor='w',
                             bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                             font=('Microsoft YaHei UI', 10))
        self.label.pack(side=tk.LEFT, padx=(0, 10))
        
        # 按键显示/录制按钮
        self.key_btn = tk.Button(self, text=current_key, width=8,
                                bg=ModernColors.BG_INPUT, fg=ModernColors.ACCENT_CYAN,
                                font=('Microsoft YaHei UI', 10, 'bold'),
                                relief=tk.FLAT, cursor='hand2',
                                command=self._start_recording)
        self.key_btn.pack(side=tk.LEFT)
        
    def _start_recording(self):
        """开始录制快捷键"""
        if self.is_recording:
            return
        self.is_recording = True
        self.key_btn.configure(text="按键...", fg=ModernColors.ACCENT_ORANGE)
        
        # 使用keyboard库监听全局按键（更可靠）
        if GLOBAL_HOTKEY_AVAILABLE:
            try:
                self._keyboard_hook = kb.on_press(self._on_keyboard_press, suppress=False)
            except Exception as e:
                print(f"无法启动键盘监听: {e}")
                # 回退到Tkinter绑定
                self._use_tkinter_binding()
        else:
            self._use_tkinter_binding()
    
    def _use_tkinter_binding(self):
        """使用Tkinter绑定（备用方案）"""
        # 绑定到顶层窗口以确保能接收按键
        top = self.winfo_toplevel()
        top.bind('<Key>', self._on_key_press)
        top.focus_force()
    
    def _on_keyboard_press(self, event):
        """keyboard库的按键回调"""
        if not self.is_recording:
            return
        
        # 获取按键名称
        key_name = event.name
        
        # 忽略修饰键本身
        if key_name.lower() in ('shift', 'ctrl', 'alt', 'left shift', 'right shift',
                                 'left ctrl', 'right ctrl', 'left alt', 'right alt',
                                 'left windows', 'right windows'):
            return
        
        # 停止监听
        self._stop_recording(key_name)
        
    def _on_key_press(self, event):
        """Tkinter的按键回调（备用）"""
        if not self.is_recording:
            return
            
        # 获取按键名称
        key_name = event.keysym
        
        # 忽略修饰键本身
        if key_name in ('Shift_L', 'Shift_R', 'Control_L', 'Control_R', 
                       'Alt_L', 'Alt_R', 'Win_L', 'Win_R'):
            return
        
        # 解绑Tkinter事件
        try:
            self.winfo_toplevel().unbind('<Key>')
        except:
            pass
            
        self._stop_recording(key_name)
    
    def _stop_recording(self, key_name: str):
        """停止录制并保存按键"""
        self.is_recording = False
        self.current_key = key_name
        
        # 在主线程中更新UI
        def update_ui():
            self.key_btn.configure(text=key_name, fg=ModernColors.ACCENT_CYAN)
            if self.on_change:
                self.on_change(key_name)
        
        # 移除keyboard库的钩子
        if self._keyboard_hook:
            try:
                kb.unhook(self._keyboard_hook)
            except:
                pass
            self._keyboard_hook = None
        
        # 确保在主线程更新UI
        try:
            self.after(0, update_ui)
        except:
            update_ui()
            
    def set_key(self, key: str):
        """设置显示的按键"""
        self.current_key = key
        self.key_btn.configure(text=key)


class ControlPanel(tk.Frame):
    """控制面板"""
    
    def __init__(self, parent, player: MidiPlayer, settings: SettingsManager, 
                 on_stop_callback=None, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.player = player
        self.settings = settings
        self.on_stop_callback = on_stop_callback  # 停止后的回调
        # 文件夹循环状态
        self._folder_loop_active = False
        self._folder_loop_files = []
        self._folder_loop_index = 0
        self._create()
        
    def _create(self):
        """创建控件"""
        # === 第一行：文件 ===
        row1 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row1.pack(fill=tk.X, padx=20, pady=(15, 8))
        
        self.file_label = tk.Label(row1, text="未选择文件",
                                  bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                  font=('Microsoft YaHei UI', 11), anchor='w')
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.loop_folder_btn = SmoothButton(row1, text="🔁 循环文件夹", command=self._toggle_folder_loop,
                                           width=115, height=34, bg=ModernColors.ACCENT_PURPLE)
        self.loop_folder_btn.pack(side=tk.RIGHT, padx=(0, 8))
        
        self.open_btn = SmoothButton(row1, text="📂 打开", command=self._open_file,
                                    width=90, height=34, bg=ModernColors.ACCENT_BLUE)
        self.open_btn.pack(side=tk.RIGHT)
        
        # === 第二行：播放控制 ===
        row2 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row2.pack(fill=tk.X, padx=20, pady=8)
        
        self.play_btn = SmoothButton(row2, text="▶ 播放", command=self._toggle_play,
                                    width=100, height=40, bg=ModernColors.ACCENT_GREEN)
        self.play_btn.pack(side=tk.LEFT, padx=(0, 12))
        
        self.stop_btn = SmoothButton(row2, text="⏹ 停止", command=self._stop,
                                    width=100, height=40, bg=ModernColors.ACCENT_RED)
        self.stop_btn.pack(side=tk.LEFT)
        
        # 状态显示
        self.status_label = tk.Label(row2, text="就绪",
                                    bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_CYAN,
                                    font=('Microsoft YaHei UI', 11, 'bold'))
        self.status_label.pack(side=tk.RIGHT)
        
        # === 状态指示器行：SHIFT模式 + 延音踏板 ===
        row2_5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row2_5.pack(fill=tk.X, padx=20, pady=(0, 4))
        
        self.shift_indicator = tk.Label(row2_5, text="🎹 普通模式",
                                       bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                       font=('Microsoft YaHei UI', 9))
        self.shift_indicator.pack(side=tk.LEFT, padx=(0, 15))
        
        self.sustain_indicator = tk.Label(row2_5, text="♫ 延音 正常",
                                         bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                         font=('Microsoft YaHei UI', 9))
        self.sustain_indicator.pack(side=tk.LEFT)
        
        # === 第三行：速度 ===
        row3 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row3.pack(fill=tk.X, padx=20, pady=8)
        
        tk.Label(row3, text="速度", bg=ModernColors.BG_CARD, 
                fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)
        
        self.speed_var = tk.DoubleVar(value=self.settings.get('speed', 1.0))
        
        # 自定义滑块
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
                                   bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_ORANGE,
                                   font=('Microsoft YaHei UI', 12, 'bold'))
        self.speed_label.pack(side=tk.LEFT)
        
        # === 第四行：移调和和弦 ===
        row4 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row4.pack(fill=tk.X, padx=20, pady=8)
        
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
                                    width=60, height=30, bg=ModernColors.ACCENT_ORANGE,
                                    font_size=9)
        self.auto_btn.pack(side=tk.LEFT, padx=15)
        
        # 自动移调信息显示
        self.octave_offset_label = tk.Label(row4, text="自动:调+0 8度+0", bg=ModernColors.BG_CARD,
                                           fg=ModernColors.ACCENT_PURPLE, font=('Microsoft YaHei UI', 9))
        self.octave_offset_label.pack(side=tk.LEFT, padx=5)
        
        # === 第4.5行：音部控制 ===
        row4_5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row4_5.pack(fill=tk.X, padx=20, pady=8)
        
        tk.Label(row4_5, text="音部", bg=ModernColors.BG_CARD,
                fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)
        
        # 主旋律开关
        self.melody_var = tk.BooleanVar(value=True)
        self.melody_check = tk.Checkbutton(row4_5, text="🎵主旋律",
                                          variable=self.melody_var,
                                          bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                          selectcolor=ModernColors.BG_INPUT,
                                          activebackground=ModernColors.BG_CARD,
                                          font=('Microsoft YaHei UI', 10),
                                          command=self._on_part_toggle)
        self.melody_check.pack(side=tk.LEFT, padx=(15, 5))
        
        # 低音部开关
        self.bass_var = tk.BooleanVar(value=True)
        self.bass_check = tk.Checkbutton(row4_5, text="🎸低音部",
                                        variable=self.bass_var,
                                        bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                        selectcolor=ModernColors.BG_INPUT,
                                        activebackground=ModernColors.BG_CARD,
                                        font=('Microsoft YaHei UI', 10),
                                        command=self._on_part_toggle)
        self.bass_check.pack(side=tk.LEFT, padx=5)
        
        # 伴奏密度控制
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
        
        # 音部信息标签
        self.part_info_label = tk.Label(row4_5, text="",
                                       bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                       font=('Microsoft YaHei UI', 9))
        self.part_info_label.pack(side=tk.RIGHT)
        
        # === 第五行：进度 ===
        row5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row5.pack(fill=tk.X, padx=20, pady=(8, 15))
        
        style.configure("Modern.Horizontal.TProgressbar",
                       troughcolor=ModernColors.BG_INPUT,
                       background=ModernColors.ACCENT_BLUE)
        
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(row5, variable=self.progress_var,
                                           maximum=100, style="Modern.Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, expand=True)
        
        self.time_label = tk.Label(row5, text="00:00 / 00:00",
                                  bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                  font=('Microsoft YaHei UI', 9))
        self.time_label.pack(pady=(5, 0))
        
        # === 第5.5行：C调直转模式 ===
        row5_5 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row5_5.pack(fill=tk.X, padx=20, pady=8)
        
        # C调直转模式开关
        self.direct_c_var = tk.BooleanVar(value=self.settings.get('direct_c_mode', False))
        self.direct_c_check = tk.Checkbutton(row5_5, text="🎹 C调直转",
                                            variable=self.direct_c_var,
                                            bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                            selectcolor=ModernColors.BG_INPUT,
                                            activebackground=ModernColors.BG_CARD,
                                            font=('Microsoft YaHei UI', 10, 'bold'),
                                            command=self._on_direct_c_toggle)
        self.direct_c_check.pack(side=tk.LEFT)
        
        # C调直转模式说明
        self.direct_c_info_label = tk.Label(row5_5, text="(将任意调直接转换为C大调简谱)",
                                           bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                           font=('Microsoft YaHei UI', 9))
        self.direct_c_info_label.pack(side=tk.LEFT, padx=10)
        
        # 检测到的调性显示
        self.detected_key_label = tk.Label(row5_5, text="",
                                          bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_CYAN,
                                          font=('Microsoft YaHei UI', 9, 'bold'))
        self.detected_key_label.pack(side=tk.RIGHT)
        
        # === 第六行：通道设置按钮 + Glissando开关 ===
        row6 = tk.Frame(self, bg=ModernColors.BG_CARD)
        row6.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        self.channel_btn = SmoothButton(row6, text="🎹 通道设置", command=self._show_channel_settings,
                                       width=100, height=30, bg=ModernColors.ACCENT_PURPLE,
                                       font_size=9)
        self.channel_btn.pack(side=tk.LEFT)
        
        self.channel_info_label = tk.Label(row6, text="加载文件后可设置",
                                          bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                          font=('Microsoft YaHei UI', 9))
        self.channel_info_label.pack(side=tk.LEFT, padx=10)
        
        # Glissando结尾滑奏开关（默认关闭）
        self.glissando_var = tk.BooleanVar(value=self.settings.get('glissando_enabled', False))
        self.glissando_check = tk.Checkbutton(row6, text="🎵结尾滑奏",
                                             variable=self.glissando_var,
                                             bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                             selectcolor=ModernColors.BG_INPUT,
                                             activebackground=ModernColors.BG_CARD,
                                             font=('Microsoft YaHei UI', 9),
                                             command=self._on_glissando_toggle)
        self.glissando_check.pack(side=tk.RIGHT, padx=5)
        
        # 熟练度模拟开关
        self.proficiency_var = tk.BooleanVar(value=self.settings.get('proficiency_enabled', True))
        self.proficiency_check = tk.Checkbutton(row6, text="🎯熟练度",
                                               variable=self.proficiency_var,
                                               bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                               selectcolor=ModernColors.BG_INPUT,
                                               activebackground=ModernColors.BG_CARD,
                                               font=('Microsoft YaHei UI', 9),
                                               command=self._on_proficiency_toggle)
        self.proficiency_check.pack(side=tk.RIGHT, padx=5)
        
        # 熟练度显示标签
        self.proficiency_label = tk.Label(row6, text="熟练度: --",
                                         bg=ModernColors.BG_CARD, fg=ModernColors.ACCENT_GREEN,
                                         font=('Microsoft YaHei UI', 9))
        self.proficiency_label.pack(side=tk.RIGHT, padx=5)
        
        # === 初始化播放器设置 ===
        # 同步结尾滑奏设置
        self.player._play_ending_glissando = self.glissando_var.get()
        
        # 同步熟练度设置
        self.player.set_proficiency_enabled(self.proficiency_var.get())
        
        # 同步C调直转模式（仅设置标志，实际映射在加载文件时建立）
        self.player._direct_c_mode = self.direct_c_var.get()
        
        # 加载伴奏密度设置
        saved_density = self.settings.get('bass_density', 1.0)
        self.bass_density_var.set(saved_density)
        self.bass_density_label.configure(text=f"{saved_density:.0%}")
        self.player.set_bass_density(saved_density)
    
    def _show_channel_settings(self):
        """显示通道设置对话框"""
        if not self.player.parser.notes:
            messagebox.showwarning("提示", "请先加载MIDI文件")
            return
        
        # 获取通道信息
        channels_info = self.player.parser.get_channels_info()
        if not channels_info:
            messagebox.showinfo("提示", "该MIDI文件没有音符数据")
            return
        
        # 创建对话框
        dialog = tk.Toplevel(self)
        dialog.title("通道设置")
        dialog.geometry("450x400")
        dialog.configure(bg=ModernColors.BG_DARK)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        # 标题
        title = tk.Label(dialog, text="🎹 分通道移调设置", bg=ModernColors.BG_DARK,
                        fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 14, 'bold'))
        title.pack(pady=15)
        
        # 说明
        hint = tk.Label(dialog, text="为每个MIDI通道单独设置移调值，可以禁用不需要的通道",
                       bg=ModernColors.BG_DARK, fg=ModernColors.TEXT_SECONDARY,
                       font=('Microsoft YaHei UI', 9))
        hint.pack(pady=(0, 10))
        
        # 滚动框架
        canvas = tk.Canvas(dialog, bg=ModernColors.BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=ModernColors.BG_DARK)
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 存储控件引用
        channel_vars = {}
        
        for ch in sorted(channels_info.keys()):
            info = channels_info[ch]
            
            frame = tk.Frame(scroll_frame, bg=ModernColors.BG_CARD)
            frame.pack(fill=tk.X, pady=5, padx=5)
            
            # 启用复选框
            enabled_var = tk.BooleanVar(value=self.player.mapper.is_channel_enabled(ch))
            enabled_cb = tk.Checkbutton(frame, text=f"CH{ch}", variable=enabled_var,
                                       bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                                       selectcolor=ModernColors.BG_INPUT,
                                       font=('Microsoft YaHei UI', 10, 'bold'),
                                       width=5)
            enabled_cb.pack(side=tk.LEFT, padx=5)
            
            # 音符信息
            note_range = info['note_range']
            info_text = f"音符: {info['note_count']}个  范围: {note_range[0]}-{note_range[1]}"
            info_label = tk.Label(frame, text=info_text, bg=ModernColors.BG_CARD,
                                 fg=ModernColors.TEXT_SECONDARY, font=('Microsoft YaHei UI', 9),
                                 width=25, anchor='w')
            info_label.pack(side=tk.LEFT, padx=5)
            
            # 移调设置
            tk.Label(frame, text="移调:", bg=ModernColors.BG_CARD,
                    fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
            
            transpose_var = tk.IntVar(value=self.player.mapper.get_channel_transpose(ch))
            transpose_spin = tk.Spinbox(frame, from_=-48, to=48, width=4,
                                       textvariable=transpose_var,
                                       font=('Microsoft YaHei UI', 10),
                                       bg=ModernColors.BG_INPUT, fg=ModernColors.TEXT_PRIMARY,
                                       relief=tk.FLAT)
            transpose_spin.pack(side=tk.LEFT, padx=5)
            
            # 自动建议按钮（使用通道专用的建议方法）
            def auto_suggest(channel=ch, var=transpose_var, info=info):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    # 根据音符范围判断目标音区
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
                               bg=ModernColors.ACCENT_ORANGE, fg=ModernColors.TEXT_BRIGHT,
                               font=('Microsoft YaHei UI', 8), relief=tk.FLAT,
                               padx=5, pady=2)
            auto_btn.pack(side=tk.LEFT, padx=5)
            
            # 添加音区选择按钮
            def set_high(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    suggested = self.player.mapper.suggest_channel_transpose(notes, 'high')
                    var.set(suggested)
            
            def set_mid(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    suggested = self.player.mapper.suggest_channel_transpose(notes, 'mid')
                    var.set(suggested)
            
            def set_low(channel=ch, var=transpose_var):
                notes = [n.note for n in self.player.parser.get_notes_by_channel(channel)]
                if notes:
                    suggested = self.player.mapper.suggest_channel_transpose(notes, 'low')
                    var.set(suggested)
            
            tk.Button(frame, text="高", command=set_high,
                     bg=ModernColors.ACCENT_RED, fg=ModernColors.TEXT_BRIGHT,
                     font=('Microsoft YaHei UI', 7), relief=tk.FLAT,
                     width=2).pack(side=tk.LEFT, padx=1)
            tk.Button(frame, text="中", command=set_mid,
                     bg=ModernColors.ACCENT_BLUE, fg=ModernColors.TEXT_BRIGHT,
                     font=('Microsoft YaHei UI', 7), relief=tk.FLAT,
                     width=2).pack(side=tk.LEFT, padx=1)
            tk.Button(frame, text="低", command=set_low,
                     bg=ModernColors.ACCENT_GREEN, fg=ModernColors.TEXT_BRIGHT,
                     font=('Microsoft YaHei UI', 7), relief=tk.FLAT,
                     width=2).pack(side=tk.LEFT, padx=1)
            
            channel_vars[ch] = {'enabled': enabled_var, 'transpose': transpose_var}
        
        # 按钮区域
        btn_frame = tk.Frame(dialog, bg=ModernColors.BG_DARK)
        btn_frame.pack(fill=tk.X, pady=15, padx=20)
        
        def apply_settings():
            for ch, vars in channel_vars.items():
                self.player.mapper.set_channel_enabled(ch, vars['enabled'].get())
                self.player.mapper.set_channel_transpose(ch, vars['transpose'].get())
            
            # 更新通道信息显示
            enabled_count = sum(1 for ch in channel_vars if channel_vars[ch]['enabled'].get())
            total_count = len(channel_vars)
            self.channel_info_label.configure(text=f"已启用 {enabled_count}/{total_count} 个通道")
            
            dialog.destroy()
            messagebox.showinfo("完成", "通道设置已应用")
        
        def reset_all():
            self.player.mapper.clear_channel_settings()
            for ch, vars in channel_vars.items():
                vars['enabled'].set(True)
                vars['transpose'].set(self.player.mapper.transpose)
        
        apply_btn = SmoothButton(btn_frame, text="✓ 应用", command=apply_settings,
                                width=80, height=32, bg=ModernColors.ACCENT_GREEN, font_size=10)
        apply_btn.pack(side=tk.RIGHT, padx=5)
        
        reset_btn = SmoothButton(btn_frame, text="重置", command=reset_all,
                                width=80, height=32, bg=ModernColors.ACCENT_PURPLE, font_size=10)
        reset_btn.pack(side=tk.RIGHT, padx=5)
        
    def _open_file(self):
        filepath = filedialog.askopenfilename(
            title="选择MIDI/JS文件",
            filetypes=[
                ("支持的文件", "*.mid *.midi *.js"),
                ("MIDI文件", "*.mid *.midi"),
                ("JS谱面", "*.js"),
                ("所有文件", "*.*")
            ]
        )
        if filepath:
            if self.player.load_midi(filepath):
                self.file_label.configure(text=os.path.basename(filepath),
                                         fg=ModernColors.TEXT_PRIMARY)
                # 加载新文件时，用户额外移调归零
                self.transpose_var.set(0)
                self.player.set_transpose(0)
                self.settings.set('last_file', filepath)
                
                # 清除之前的通道设置
                self.player.mapper.clear_channel_settings()
                
                coverage = self.player.get_coverage_info()
                chord_info = self.player.get_chord_info()
                
                # JS文件没有通道信息
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
                
                # 更新通道信息显示
                channel_count = len(channels_info)
                self.channel_info_label.configure(text=f"共 {channel_count} 个通道")
                
                # 获取乐器信息
                instrument_info = self.player.parser.get_instrument_info()
                
                msg = f"✓ 加载成功\n\n"
                msg += f"BPM: {bpm:.1f}"
                if tempo_changes > 1:
                    msg += f" (有 {tempo_changes} 次变速)"
                msg += f"\n"
                msg += f"音符数: {coverage['total']}\n"
                msg += f"可播放: {coverage['mapped']} ({coverage['coverage']*100:.1f}%)\n"
                msg += f"和弦数: {chord_info['chord_count']}\n"
                msg += f"通道数: {channel_count}\n"
                
                # 显示力度信息
                notes = self.player.parser.notes
                if notes:
                    vels = [n.velocity for n in notes]
                    avg_vel = sum(vels) / len(vels)
                    msg += f"力度范围: {min(vels)}-{max(vels)} (均值{avg_vel:.0f})\n"
                
                # 显示乐器信息
                if instrument_info:
                    msg += f"\n乐器:\n"
                    for ch, info in list(instrument_info.items())[:3]:
                        name = info.get('name', f'Program {info.get("program", 0)}') if isinstance(info, dict) else info
                        msg += f"  Ch{ch}: {name}\n"
                    if len(instrument_info) > 3:
                        msg += f"  ...等 {len(instrument_info)} 种乐器\n"
                
                # 显示自动调性移调信息
                key_transpose = getattr(self.player, '_key_transpose', 0)
                octave_offset = getattr(self.player, '_octave_offset', 0)
                msg += f"\n自动调性: {key_transpose:+d}半音, 8度偏移: {octave_offset:+d}"
                
                # 同步C调直转模式状态（如果已开启，重新建立映射）
                if self.direct_c_var.get():
                    self.player.set_direct_c_mode(True, save=False)  # 不重复保存
                    self._update_direct_c_display()
                    direct_c_info = self.player.get_direct_c_info()
                    key_name = direct_c_info['detected_key_name']
                    mode = '大调' if direct_c_info['detected_mode'] == 'major' else '小调'
                    msg += f"\n\n🎹 C调直转: 检测到 {key_name} {mode}\n   (传统移调已禁用)"
                else:
                    self._update_direct_c_display()
                
                # 更新熟练度显示
                self._update_proficiency_label()
                proficiency_info = self.player.get_proficiency_info()
                msg += f"\n熟练度: {proficiency_info['proficiency']*100:.0f}% (已弹{proficiency_info['play_count']}次)"
                
                # 更新音部分析信息并自动推荐
                self._update_pitch_analysis()
                
                # 显示音部信息
                pitch_info = self.player.parser.get_pitch_analysis()
                if pitch_info.get('melody_count', 0) > 0 or pitch_info.get('bass_count', 0) > 0:
                    msg += f"\n\n音部分析:"
                    msg += f"\n  主旋律: {pitch_info.get('melody_count', 0)} 音符"
                    msg += f"\n  低音部: {pitch_info.get('bass_count', 0)} 音符"
                    if pitch_info.get('recommend_melody_only'):
                        msg += f"\n  ⚠ 高低音撕裂严重，已自动关闭低音"
                
                messagebox.showinfo("文件信息", msg)
                
                # 加载文件后恢复焦点和快捷键
                if self.on_stop_callback:
                    self.winfo_toplevel().after(100, self.on_stop_callback)
            else:
                messagebox.showerror("错误", "无法加载文件")
                if self.on_stop_callback:
                    self.winfo_toplevel().after(100, self.on_stop_callback)
                
    def _toggle_folder_loop(self):
        """一键循环选定文件夹下的所有MIDI/JS文件（不含子文件夹）"""
        if self._folder_loop_active:
            # 停止循环
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self.loop_folder_btn.set_text("🔁 循环文件夹")
            self.loop_folder_btn.set_bg(ModernColors.ACCENT_PURPLE)
            self.player.stop()
            self.play_btn.set_text("▶ 播放")
            self.status_label.configure(text="已停止循环")
            if self.on_stop_callback:
                self.on_stop_callback()
        else:
            # 选择文件夹
            folder = filedialog.askdirectory(title="选择循环播放的文件夹")
            if not folder:
                return
            files = sorted([
                os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith(('.mid', '.midi', '.js'))
                and os.path.isfile(os.path.join(folder, f))
            ])
            if not files:
                messagebox.showinfo("提示", "该文件夹下没有 MIDI / JS 文件")
                return
            self._folder_loop_files = files
            self._folder_loop_index = 0
            self._folder_loop_active = True
            self.loop_folder_btn.set_text("⏹ 停止循环")
            self.loop_folder_btn.set_bg(ModernColors.ACCENT_RED)
            self._play_next_folder_song()

    def _play_next_folder_song(self, _retries=0):
        """加载并播放文件夹循环中的下一首"""
        if not self._folder_loop_active or not self._folder_loop_files:
            return
        if _retries >= len(self._folder_loop_files):
            # 所有文件都加载失败，停止循环
            self._toggle_folder_loop()
            messagebox.showerror("错误", "文件夹中所有文件加载失败，已停止循环")
            return
        filepath = self._folder_loop_files[self._folder_loop_index]
        self._folder_loop_index = (self._folder_loop_index + 1) % len(self._folder_loop_files)
        if self.player.load_midi(filepath):
            self.file_label.configure(text=os.path.basename(filepath),
                                      fg=ModernColors.TEXT_PRIMARY)
            self.transpose_var.set(0)
            self.player.set_transpose(0)
            self.player.mapper.clear_channel_settings()
            # 同步C调直转模式
            if self.direct_c_var.get():
                self.player.set_direct_c_mode(True, save=False)
            self.player.play()
            self.play_btn.set_text("⏸ 暂停")
            self.status_label.configure(text=f"🔁 {os.path.basename(filepath)}")
        else:
            # 加载失败，跳过这首
            self._play_next_folder_song(_retries + 1)

    def _toggle_play(self):
        state = self.player.get_state()
        if state.is_playing and not state.is_paused:
            self.player.pause()
            self.play_btn.set_text("▶ 继续")
            self.status_label.configure(text="已暂停")
        elif state.is_paused:
            self.player.resume()
            self.play_btn.set_text("⏸ 暂停")
            self.status_label.configure(text="播放中")
        else:
            self.player.play()
            self.play_btn.set_text("⏸ 暂停")
            self.status_label.configure(text="播放中")
            
    def _stop(self):
        # 停止时也取消文件夹循环
        if self._folder_loop_active:
            self._folder_loop_active = False
            self._folder_loop_files = []
            self._folder_loop_index = 0
            self.loop_folder_btn.set_text("🔁 循环文件夹")
            self.loop_folder_btn.set_bg(ModernColors.ACCENT_PURPLE)
        self.player.stop()
        self.play_btn.set_text("▶ 播放")
        self.progress_var.set(0)
        self.time_label.configure(text="00:00 / 00:00")
        self.status_label.configure(text="已停止")
        # 调用停止回调（仅释放按键，不影响快捷键）
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
        """自动移调 - 重新分析并应用最佳移调"""
        if not self.player.parser.notes:
            messagebox.showwarning("提示", "请先加载文件")
            return
        
        # 重新分析并获取最佳移调
        self.player._analyze_and_setup_mapping()
        # 获取调性移调值（存储在 _key_transpose 中）
        key_transpose = getattr(self.player, '_key_transpose', 0)
        octave_offset = getattr(self.player, '_octave_offset', 0)
        
        # 自动移调后，用户额外移调归零
        self.transpose_var.set(0)
        self.player.set_transpose(0)
        self._update_octave_offset_label()
        coverage = self.player.get_coverage_info()
        messagebox.showinfo("自动调整", f"调性移调: {key_transpose:+d} 半音\n八度偏移: {octave_offset:+d}\n用户移调: 0\n覆盖率: {coverage['coverage']*100:.1f}%")
        
    def _on_direct_c_toggle(self):
        """C调直转模式开关切换"""
        val = self.direct_c_var.get()
        
        if not self.player.parser.notes:
            if val:
                messagebox.showwarning("提示", "请先加载MIDI文件")
                self.direct_c_var.set(False)
            return
        
        self.player.set_direct_c_mode(val)
        self.settings.set('direct_c_mode', val)
        
        # 更新界面显示
        self._update_direct_c_display()
        
        if val:
            # 开启C调直转时，提示用户
            info = self.player.get_direct_c_info()
            key_name = info['detected_key_name']
            mode = '大调' if info['detected_mode'] == 'major' else '小调'
            messagebox.showinfo("C调直转模式", 
                f"已启用C调直转模式\n\n"
                f"检测到原曲调性: {key_name} {mode}\n"
                f"所有音符将按音级直接映射到C大调\n\n"
                f"• 传统移调方式已暂停\n"
                f"• 低音部分将用和弦键替代\n"
                f"• 微调功能仍然可用")
        else:
            # 关闭时恢复传统映射
            self._update_octave_offset_label()
    
    def _update_direct_c_display(self):
        """更新C调直转模式的显示"""
        if self.player.is_direct_c_mode():
            info = self.player.get_direct_c_info()
            key_name = info['detected_key_name']
            mode = '大调' if info['detected_mode'] == 'major' else '小调'
            confidence = info.get('confidence', 0.0)
            # 置信度评级
            if confidence >= 0.8:
                conf_text = "★★★"
            elif confidence >= 0.6:
                conf_text = "★★☆"
            elif confidence >= 0.4:
                conf_text = "★☆☆"
            else:
                conf_text = "☆☆☆"
            self.detected_key_label.configure(
                text=f"原调: {key_name} {mode} {conf_text}",
                fg=ModernColors.ACCENT_GREEN
            )
            self.direct_c_info_label.configure(
                text=f"(已启用 - 置信度{confidence:.1%})",
                fg=ModernColors.ACCENT_GREEN
            )
            # 隐藏传统移调信息
            self.octave_offset_label.configure(text="C调直转模式")
        else:
            self.detected_key_label.configure(text="")
            self.direct_c_info_label.configure(
                text="(将任意调直接转换为C大调简谱)",
                fg=ModernColors.TEXT_SECONDARY
            )
            # 恢复传统移调信息显示
            self._update_octave_offset_label()
    
    def _on_part_toggle(self):
        """音部开关切换"""
        play_melody = self.melody_var.get()
        play_bass = self.bass_var.get()
        
        # 确保至少有一个音部被选中
        if not play_melody and not play_bass:
            self.melody_var.set(True)
            play_melody = True
            messagebox.showwarning("提示", "至少需要选择一个音部")
        
        self.player.set_part_filter(play_melody, play_bass)
        
        # 重新分析映射
        self.player._analyze_and_setup_mapping()
        
        # 更新状态提示（显示音符数量）
        info = self.player.parser.get_pitch_analysis() if self.player.parser.notes else {}
        melody_count = info.get('melody_count', 0)
        bass_count = info.get('bass_count', 0)
        
        if play_melody and play_bass:
            self.part_info_label.configure(text=f"全部 (旋律{melody_count}+低音{bass_count})", fg=ModernColors.TEXT_SECONDARY)
        elif play_melody:
            self.part_info_label.configure(text=f"仅旋律 ({melody_count}音符)", fg=ModernColors.ACCENT_GREEN)
        else:
            self.part_info_label.configure(text=f"仅低音 ({bass_count}音符)", fg=ModernColors.ACCENT_ORANGE)
    
    def _on_bass_density_change(self, value):
        """伴奏密度变化"""
        density = float(value)
        self.player.set_bass_density(density)
        self.bass_density_label.configure(text=f"{density:.0%}")
        self.settings.set('bass_density', density)
    
    def _on_glissando_toggle(self):
        """结尾滑奏开关切换"""
        val = self.glissando_var.get()
        self.player._play_ending_glissando = val
        self.settings.set('glissando_enabled', val)
    
    def _on_proficiency_toggle(self):
        """熟练度模拟开关切换"""
        val = self.proficiency_var.get()
        self.player.set_proficiency_enabled(val)
        self.settings.set('proficiency_enabled', val)
    
    def _update_proficiency_label(self):
        """更新熟练度显示"""
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
        """更新音部分析信息"""
        if not self.player.parser.notes:
            self.part_info_label.configure(text="")
            return
        
        info = self.player.parser.get_pitch_analysis()
        
        melody_count = info.get('melody_count', 0)
        bass_count = info.get('bass_count', 0)
        recommend = info.get('recommend_melody_only', False)
        
        if recommend:
            self.part_info_label.configure(
                text=f"⚠撕裂严重 推荐关低音", 
                fg=ModernColors.ACCENT_RED
            )
            # 自动取消勾选低音部
            self.bass_var.set(False)
            self._on_part_toggle()
        else:
            self.part_info_label.configure(
                text=f"旋律{melody_count} 低音{bass_count}",
                fg=ModernColors.TEXT_SECONDARY
            )
            # 正常歌曲，自动勾选回低音部
            if not self.bass_var.get():
                self.bass_var.set(True)
                self._on_part_toggle()
        
        # 更新8度偏移显示
        self._update_octave_offset_label()
        
    def _update_octave_offset_label(self):
        """更新自动移调信息显示"""
        octave_offset = getattr(self.player, '_octave_offset', 0)
        key_transpose = getattr(self.player, '_key_transpose', 0)
        self.octave_offset_label.configure(text=f"自动:调{key_transpose:+d} 8度{octave_offset:+d}")
    
    def update_shift_state(self, is_shift: bool):
        """更新SHIFT模式指示器"""
        if is_shift:
            self.shift_indicator.configure(text="⬆ SHIFT模式", fg=ModernColors.ACCENT_ORANGE)
        else:
            self.shift_indicator.configure(text="🎹 普通模式", fg=ModernColors.TEXT_SECONDARY)
    
    def update_sustain_state(self, is_on: bool):
        """更新延音状态指示器（显示当前MIDI踏板加成状态）"""
        if is_on:
            self.sustain_indicator.configure(text="♫ 延音 加长", fg=ModernColors.ACCENT_GREEN)
        else:
            self.sustain_indicator.configure(text="♫ 延音 正常", fg=ModernColors.TEXT_SECONDARY)
        
    def update_progress(self, current: float, total: float):
        if total > 0:
            self.progress_var.set((current / total) * 100)
        c_str = f"{int(current // 60):02d}:{int(current % 60):02d}"
        t_str = f"{int(total // 60):02d}:{int(total % 60):02d}"
        self.time_label.configure(text=f"{c_str} / {t_str}")
        
    def on_playback_end(self):
        self.play_btn.set_text("▶ 播放")
        self.progress_var.set(0)
        self.status_label.configure(text="播放完成")
        self.update_shift_state(False)
        self.update_sustain_state(False)
    def speed_up(self):
        """加速"""
        current = self.speed_var.get()
        new_speed = min(2.0, current + 0.25)
        self.speed_var.set(new_speed)
        self._on_speed(new_speed)
        
    def speed_down(self):
        """减速"""
        current = self.speed_var.get()
        new_speed = max(0.25, current - 0.25)
        self.speed_var.set(new_speed)
        self._on_speed(new_speed)


class HotkeyPanel(tk.Frame):
    """快捷键设置面板 - 使用pynput独立监控，避免与按键模拟冲突"""
    
    def __init__(self, parent, settings: SettingsManager, 
                 callbacks: Dict[str, Callable], **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self.settings = settings
        self.callbacks = callbacks
        self.hotkey_widgets = {}
        self._registered_hotkeys = {}  # {hotkey_str: callback}
        self._pressed_keys = set()     # 当前按下的键
        self._listener = None          # pynput监听器
        self._listener_thread = None
        self._running = True
        self._create()
        
    def _create(self):
        """创建快捷键设置"""
        title = tk.Label(self, text="⌨️ 全局快捷键", bg=ModernColors.BG_CARD,
                        fg=ModernColors.TEXT_PRIMARY, font=('Microsoft YaHei UI', 12, 'bold'))
        title.pack(pady=(10, 15))
        
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
            widget.pack(fill=tk.X, padx=20, pady=4)
            self.hotkey_widgets[key_id] = widget
            
        # 重置按钮
        reset_btn = SmoothButton(self, text="重置默认", command=self._reset_hotkeys,
                                width=100, height=32, bg=ModernColors.ACCENT_PURPLE,
                                font_size=9)
        reset_btn.pack(pady=15)
        
        # 提示
        tip = tk.Label(self, text="点击按键框后按下新快捷键\n全局快捷键在窗口外也有效",
                      bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                      font=('Microsoft YaHei UI', 9), justify=tk.CENTER)
        tip.pack(pady=(0, 10))
        
        # 注册全局快捷键
        self._register_global_hotkeys()
        
    def _on_hotkey_change(self, key_id: str, new_key: str):
        """快捷键变更"""
        hotkeys = self.settings.get('hotkeys', {})
        hotkeys[key_id] = new_key
        self.settings.set('hotkeys', hotkeys)
        self._register_global_hotkeys()
        
    def _reset_hotkeys(self):
        """重置为默认"""
        self.settings.set('hotkeys', DEFAULT_HOTKEYS.copy())
        for key_id, widget in self.hotkey_widgets.items():
            widget.set_key(DEFAULT_HOTKEYS.get(key_id, ''))
        self._register_global_hotkeys()
        messagebox.showinfo("提示", "已重置为默认快捷键")
    
    def _normalize_key_name(self, key) -> str:
        """将pynput的Key对象转换为标准键名"""
        if PYNPUT_HOTKEY_AVAILABLE:
            if isinstance(key, Key):
                # 特殊键映射
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
                    # 处理没有char但有vk的情况（如小键盘）
                    return f'<{key.vk}>'
        return str(key).lower()
    
    def _get_current_hotkey_str(self) -> str:
        """获取当前按下的组合键字符串"""
        if not self._pressed_keys:
            return ''
        
        # 修饰键顺序：ctrl, alt, shift
        modifiers = []
        regular_keys = []
        
        for key in self._pressed_keys:
            key_lower = key.lower()
            if key_lower in ('ctrl', 'alt', 'shift'):
                modifiers.append(key_lower)
            else:
                regular_keys.append(key_lower)
        
        # 按固定顺序排列修饰键
        mod_order = {'ctrl': 0, 'alt': 1, 'shift': 2}
        modifiers.sort(key=lambda x: mod_order.get(x, 99))
        
        parts = modifiers + regular_keys
        return '+'.join(parts)
    
    def _on_key_press(self, key):
        """pynput键按下回调"""
        if not self._running:
            return
        
        key_name = self._normalize_key_name(key)
        if key_name and not key_name.startswith('<'):
            self._pressed_keys.add(key_name)
            
            # 检查是否匹配任何注册的快捷键
            current_combo = self._get_current_hotkey_str()
            if current_combo in self._registered_hotkeys:
                callback = self._registered_hotkeys[current_combo]
                # 在主线程中执行回调
                try:
                    self.after(0, callback)
                except:
                    pass
    
    def _on_key_release(self, key):
        """pynput键释放回调"""
        if not self._running:
            return
        
        key_name = self._normalize_key_name(key)
        self._pressed_keys.discard(key_name)
        
    def _register_global_hotkeys(self):
        """注册全局快捷键 - 使用pynput独立监控"""
        if not GLOBAL_HOTKEY_AVAILABLE:
            return
        
        # 更新注册的快捷键映射
        self._registered_hotkeys = {}
        hotkeys = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        
        for key_id, key in hotkeys.items():
            if key and key_id in self.callbacks:
                # 标准化快捷键字符串
                normalized = '+'.join(sorted(key.lower().split('+'), 
                    key=lambda x: {'ctrl': 0, 'alt': 1, 'shift': 2}.get(x, 99)))
                self._registered_hotkeys[normalized] = self.callbacks[key_id]
        
        # 启动pynput监听器（如果尚未启动）
        if PYNPUT_HOTKEY_AVAILABLE and self._listener is None:
            self._start_pynput_listener()
    
    def _start_pynput_listener(self):
        """启动pynput键盘监听器"""
        if not PYNPUT_HOTKEY_AVAILABLE:
            return
            
        # 停止已有的监听器
        self._stop_pynput_listener()
        
        self._running = True
        self._pressed_keys = set()
        
        try:
            self._listener = pynput_kb.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release
            )
            self._listener.start()
            print("[快捷键] pynput监听器已启动（独立于按键模拟）")
        except Exception as e:
            print(f"[快捷键] pynput监听器启动失败: {e}")
            self._listener = None
    
    def _stop_pynput_listener(self):
        """停止pynput监听器"""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except:
                pass
            self._listener = None
                    
    def _unregister_global_hotkeys(self):
        """取消全局快捷键"""
        self._stop_pynput_listener()
        self._registered_hotkeys = {}
        
    def cleanup(self):
        """清理"""
        self._unregister_global_hotkeys()


class InfoPanel(tk.Frame):
    """信息面板"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=ModernColors.BG_CARD, **kwargs)
        self._recent_notes = []  # 最近的音符列表
        self._create()
        
    def _create(self):
        """创建"""
        # 标题
        title = tk.Label(self, text="🎵 音符记录",
                        bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_PRIMARY,
                        font=('Microsoft YaHei UI', 12, 'bold'))
        title.pack(pady=(10, 5))
        
        # 音符显示框
        self.notes_frame = tk.Frame(self, bg=ModernColors.BG_INPUT)
        self.notes_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # 创建15个音符标签
        self.note_labels = []
        for i in range(15):
            lbl = tk.Label(self.notes_frame, text="",
                          bg=ModernColors.BG_INPUT, fg=ModernColors.TEXT_SECONDARY,
                          font=('Consolas', 10), anchor='w')
            lbl.pack(fill=tk.X, padx=10, pady=2)
            self.note_labels.append(lbl)
        
    def update_note(self, key: str, note: NoteEvent, is_chord: bool = False):
        """更新音符显示"""
        # 格式化音符信息
        if is_chord:
            text = f"♫ {key.upper():2s}  和弦"
        else:
            # 显示按键、MIDI音符号、持续时间
            duration_str = f"{note.duration:.2f}s" if note.duration < 10 else f"{note.duration:.1f}s"
            text = f"♪ {key.upper():2s}  MIDI:{note.note:3d}  {duration_str}"
        
        # 添加到最近音符列表（最多保留15个）
        self._recent_notes.insert(0, text)
        if len(self._recent_notes) > 15:
            self._recent_notes.pop()
        
        # 更新显示
        for i, lbl in enumerate(self.note_labels):
            if i < len(self._recent_notes):
                lbl.configure(text=self._recent_notes[i], 
                            fg=ModernColors.ACCENT_CYAN if i == 0 else ModernColors.TEXT_SECONDARY)
            else:
                lbl.configure(text="")
    
    def clear(self):
        """清除音符记录"""
        self._recent_notes.clear()
        for lbl in self.note_labels:
            lbl.configure(text="")


class MidiPlayerGUI:
    """主应用"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.configure(bg=ModernColors.BG_DARK)
        self.root.resizable(True, True)
        
        # 最小尺寸
        self.root.minsize(900, 800)
        
        # 置顶状态
        self.is_topmost = False
        
        # 设置管理器
        self.settings = SettingsManager()
        
        # 播放器
        self.player = MidiPlayer()
        
        # 设置图标
        self._set_icon()
        
        # 创建界面
        self._create_ui()
        
        # 绑定回调
        self._bind_callbacks()
        
        # 检查快捷键状态并提示
        self._check_hotkey_status()
        
    def _check_hotkey_status(self):
        """检查快捷键功能状态"""
        if not GLOBAL_HOTKEY_AVAILABLE:
            msg = f"全局快捷键功能不可用"
            if KEYBOARD_ERROR_MSG:
                msg += f"\n原因: {KEYBOARD_ERROR_MSG}"
            if not is_admin():
                msg += f"\n\n解决方案: 请以管理员身份运行程序"
            
            # 延迟显示消息，让窗口先显示出来
            self.root.after(500, lambda: messagebox.showwarning("快捷键提示", msg))
        
    def _set_icon(self):
        icon_path = get_icon_path()
        if icon_path:
            try:
                self.root.iconbitmap(default=icon_path)
                self.root.iconbitmap(icon_path)
            except Exception as e:
                print(f"设置图标失败: {e}")
        
        # 设置任务栏图标（Windows特有）
        try:
            import ctypes
            # 设置AppUserModelID，使任务栏显示正确图标
            myappid = 'midi.28keys.player.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"设置任务栏ID失败: {e}")
            
    def _create_ui(self):
        """创建界面"""
        # 顶部标题栏
        header = tk.Frame(self.root, bg=ModernColors.BG_DARK)
        header.pack(fill=tk.X, padx=20, pady=(15, 10))
        
        title = tk.Label(header, text="🎹 咲Midi player v1.253",
                        bg=ModernColors.BG_DARK, fg=ModernColors.TEXT_PRIMARY,
                        font=('Microsoft YaHei UI', 18, 'bold'))
        title.pack(side=tk.LEFT)
        
        # 置顶按钮
        self.topmost_btn = SmoothButton(header, text="📌 置顶", command=self._toggle_topmost,
                                       width=80, height=32, bg=ModernColors.BG_HOVER,
                                       font_size=9)
        self.topmost_btn.pack(side=tk.RIGHT)
        
        # 主内容区
        main = tk.Frame(self.root, bg=ModernColors.BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 左侧 - 键盘和控制
        left = tk.Frame(main, bg=ModernColors.BG_DARK)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 键盘卡片
        keyboard_card = tk.Frame(left, bg=ModernColors.BG_CARD)
        keyboard_card.pack(fill=tk.X, pady=(0, 10))
        
        self.piano = PianoKeyboard(keyboard_card)
        self.piano.pack(padx=15, pady=15)
        
        # 控制面板卡片
        control_card = tk.Frame(left, bg=ModernColors.BG_CARD)
        control_card.pack(fill=tk.X, pady=5)
        
        self.control = ControlPanel(control_card, self.player, self.settings,
                                    on_stop_callback=lambda: self.root.after(100, self._restore_focus_and_hotkeys))
        self.control.pack(fill=tk.X)
        
        # 右侧 - 快捷键和信息
        right = tk.Frame(main, bg=ModernColors.BG_DARK, width=280)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(15, 0))
        right.pack_propagate(False)
        
        # 快捷键卡片
        hotkey_card = tk.Frame(right, bg=ModernColors.BG_CARD)
        hotkey_card.pack(fill=tk.X, pady=(0, 10))
        
        def stop_and_restore():
            self.control._stop()
            self.root.after(100, self._restore_focus_and_hotkeys)
        
        self.hotkey_panel = HotkeyPanel(hotkey_card, self.settings, {
            'play_pause': lambda: self.root.after(0, self.control._toggle_play),
            'stop': lambda: self.root.after(0, stop_and_restore),
            'speed_up': lambda: self.root.after(0, self.control.speed_up),
            'speed_down': lambda: self.root.after(0, self.control.speed_down),
            'toggle_topmost': lambda: self.root.after(0, self._toggle_topmost),
        })
        self.hotkey_panel.pack(fill=tk.X)
        
        # 信息卡片
        info_card = tk.Frame(right, bg=ModernColors.BG_CARD)
        info_card.pack(fill=tk.BOTH, expand=True)
        
        self.info = InfoPanel(info_card)
        self.info.pack(fill=tk.BOTH, expand=True)
        
        # 状态栏
        self.status_bar = tk.Label(self.root, text="就绪 | 按 F5 播放/暂停",
                                  bg=ModernColors.BG_CARD, fg=ModernColors.TEXT_SECONDARY,
                                  font=('Microsoft YaHei UI', 9), anchor='w', padx=20)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, ipady=8)
        
    def _toggle_topmost(self):
        """切换置顶"""
        self.is_topmost = not self.is_topmost
        self.root.attributes('-topmost', self.is_topmost)
        
        if self.is_topmost:
            self.topmost_btn.set_text("📌 已置顶")
            self.topmost_btn.set_bg(ModernColors.ACCENT_ORANGE)
            self.status_bar.configure(text="窗口已置顶")
        else:
            self.topmost_btn.set_text("📌 置顶")
            self.topmost_btn.set_bg(ModernColors.BG_HOVER)
            self.status_bar.configure(text="已取消置顶")
            
    def _bind_callbacks(self):
        """绑定回调"""
        def on_note(key, note, is_chord=False):
            # 根据音符持续时间计算高亮时长(毫秒)
            # 音符时长转换为毫秒，最小100ms，最大2000ms
            duration_ms = int(min(2000, max(100, note.duration * 1000)))
            self.root.after(0, lambda: self.piano.highlight_key(key, duration_ms))
            self.root.after(0, lambda: self.info.update_note(key, note, is_chord))
            
        def on_progress(current, total):
            self.root.after(0, lambda: self.control.update_progress(current, total))
            
        def on_end():
            self.root.after(0, self.control.on_playback_end)
            self.root.after(0, lambda: self.status_bar.configure(text="播放完成"))
            self.root.after(0, self.piano.reset_all)
            self.root.after(0, self.info.clear)
            # 文件夹循环：自动播放下一首
            if self.control._folder_loop_active:
                self.root.after(500, self.control._play_next_folder_song)
            else:
                # 播放结束后恢复快捷键
                self.root.after(100, self._restore_focus_and_hotkeys)
            
        self.player.on_note_play = on_note
        self.player.on_progress = on_progress
        self.player.on_playback_end = on_end
        
        # SHIFT模式和延音踏板状态回调
        def on_shift(is_shift):
            self.root.after(0, lambda: self.control.update_shift_state(is_shift))
        
        def on_sustain(is_on):
            self.root.after(0, lambda: self.control.update_sustain_state(is_on))
        
        self.player.on_shift_change = on_shift
        self.player.on_sustain_change = on_sustain
        
        # 全局点击事件：点击任何地方后恢复焦点并刷新快捷键
        def on_click(event):
            # 延迟执行，确保其他事件处理完成
            self.root.after(100, self._restore_focus_and_hotkeys)
        
        self.root.bind('<Button-1>', on_click)
        
        # 窗口获得焦点时刷新快捷键
        def on_focus_in(event):
            if event.widget == self.root:
                self.root.after(50, self._restore_focus_and_hotkeys)
        
        self.root.bind('<FocusIn>', on_focus_in)
        
    def _restore_focus_and_hotkeys(self):
        """恢复焦点（pynput独立监控，无需重新注册）"""
        try:
            self.root.focus_force()
            # 释放所有按键
            if hasattr(self, 'player') and self.player:
                self.player.simulator.release_all()
            
            # pynput监听器是独立的，不需要重新注册
            # 只需清空按键状态防止粘连
            if hasattr(self, 'hotkey_panel') and self.hotkey_panel:
                self.hotkey_panel._pressed_keys.clear()
        except Exception as e:
            print(f"恢复状态失败: {e}")
        
    def run(self):
        """运行"""
        def on_close():
            self.hotkey_panel.cleanup()
            self.player.stop()
            self.root.destroy()
            
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


def main():
    app = MidiPlayerGUI()
    app.run()


if __name__ == "__main__":
    main()
