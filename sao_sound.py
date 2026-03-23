# -*- coding: utf-8 -*-
"""
SAO 音效管理器 + 升级特效
使用 winsound (Windows) 或 pygame 播放 SAO-UI 原版音效
升级用经典 8-bit 音效 (procedurally generated via winsound.Beep)
"""

import os
import threading
import math
import time
import tkinter as tk
from typing import Optional

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_SOUNDS = os.path.join(_ASSETS, 'sounds')
_FONTS = os.path.join(_ASSETS, 'fonts')

# ═══════════════════════════════════════════════
#  SAO 音效
# ═══════════════════════════════════════════════

# 预定义音效路径
SAO_SOUNDS = {
    'click':       os.path.join(_SOUNDS, 'Feedback.SAO.Click.mp3'),
    'menu_open':   os.path.join(_SOUNDS, 'Popup.SAO.Launcher.mp3'),
    'menu_close':  os.path.join(_SOUNDS, 'Dismiss.SAO.Launcher.mp3'),
    'panel':       os.path.join(_SOUNDS, 'Popup.SAO.Panel.mp3'),
    'submenu':     os.path.join(_SOUNDS, 'Popup.SAO.Menu.mp3'),
    'alert':       os.path.join(_SOUNDS, 'Popup.SAO.Alert.mp3'),
    'alert_close': os.path.join(_SOUNDS, 'Dismiss.SAO.Message.mp3'),
    'welcome':     os.path.join(_SOUNDS, 'Popup.SAO.Welcome.mp3'),
    'alo_welcome': os.path.join(_SOUNDS, 'Popup.ALO.Welcome.mp3'),
    'link_start':  os.path.join(_SOUNDS, 'LinkStart.SAO.Kirito.mp3'),
    'nervegear':   os.path.join(_SOUNDS, 'Startup.SAO.NerveGear.mp3'),
}

# 缓存 pygame 状态
_pygame_inited = False
_has_pygame = None


def _init_pygame():
    """懒初始化 pygame mixer"""
    global _pygame_inited, _has_pygame
    if _has_pygame is not None:
        return _has_pygame
    try:
        import pygame
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        _pygame_inited = True
        _has_pygame = True
    except Exception:
        _has_pygame = False
    return _has_pygame


def play_sound(name: str, volume: float = 0.7):
    """
    播放 SAO 音效 (非阻塞)
    
    Args:
        name: 音效名 (见 SAO_SOUNDS)
        volume: 0.0~1.0 音量
    """
    path = SAO_SOUNDS.get(name, '')
    if not path or not os.path.exists(path):
        return

    def _play():
        try:
            if _init_pygame():
                import pygame
                snd = pygame.mixer.Sound(path)
                snd.set_volume(volume)
                snd.play()
                return
        except Exception:
            pass
        # 回退: winsound (仅支持 .wav, mp3 不支持)
        # 尝试用 Windows Media API
        try:
            import winsound
            # winsound 不支持 mp3, 跳过
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


# ═══════════════════════════════════════════════
#  8-bit 升级音效 (using winsound.Beep)
# ═══════════════════════════════════════════════

def play_levelup_sfx():
    """播放经典 8-bit 升级音效 (winsound.Beep 合成)"""
    def _beep_sequence():
        try:
            import winsound
            # 经典升级旋律: C5 → E5 → G5 → C6 (快速上行)
            notes = [
                (523, 80),   # C5
                (587, 60),   # D5
                (659, 80),   # E5
                (784, 60),   # G5
                (880, 80),   # A5
                (1047, 120), # C6
                (1319, 150), # E6
                (1568, 200), # G6 (hold)
            ]
            for freq, dur in notes:
                winsound.Beep(freq, dur)
        except Exception:
            pass

    threading.Thread(target=_beep_sequence, daemon=True).start()


# ═══════════════════════════════════════════════
#  升级特效 (全屏闪光 + 文字)
# ═══════════════════════════════════════════════

class LevelUpEffect:
    """
    SAO 风格升级特效
    - 全屏金色闪光 (flash)  
    - "LEVEL UP!" 文字从中心放大弹出
    - 等级数字显示
    - 经典 8-bit 升级音效
    """

    @staticmethod
    def show(root: tk.Tk, old_level: int, new_level: int):
        """显示升级特效"""
        # 播放升级音效
        play_levelup_sfx()

        ov = tk.Toplevel(root)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.attributes('-alpha', 0.0)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        ov.geometry(f'{sw}x{sh}+0+0')
        ov.configure(bg='#000000')

        # 使用 Canvas 绘制
        cv = tk.Canvas(ov, width=sw, height=sh, bg='#000000',
                       highlightthickness=0)
        cv.pack()

        # 文字元素 (初始隐藏)
        cx, cy = sw // 2, sh // 2
        
        # "LEVEL UP!" 大字
        title_id = cv.create_text(cx, cy - 40, text='LEVEL UP!',
                                   font=('Segoe UI', 1, 'bold'),
                                   fill='#f3af12')
        # 等级数字
        level_id = cv.create_text(cx, cy + 40, text=f'Lv.{new_level}',
                                   font=('Segoe UI', 1),
                                   fill='#ffffff')

        # 动画
        t0 = time.time()
        total_dur = 2.5  # 总时长

        def _tick():
            if not ov.winfo_exists():
                return
            elapsed = time.time() - t0
            t = elapsed / total_dur

            if t >= 1.0:
                ov.destroy()
                return

            # 阶段 1: 金色闪光 (0~0.3)
            if t < 0.15:
                # 快速闪入
                alpha = min(0.85, t / 0.15 * 0.85)
                ov.attributes('-alpha', alpha)
                # 背景从黑到金色
                g = int(t / 0.15 * 243)
                b_val = int(t / 0.15 * 175)
                cv.configure(bg=f'#{g:02x}{b_val:02x}12')
            elif t < 0.3:
                # 闪白
                ov.attributes('-alpha', 0.85)
                wt = (t - 0.15) / 0.15
                gv = int(255 - 12 * wt)
                cv.configure(bg=f'#{gv:02x}{gv:02x}{gv:02x}')

            # 阶段 2: 文字放大弹入 (0.2~0.6)
            if 0.2 <= t < 0.6:
                text_t = (t - 0.2) / 0.4
                # ease-out elastic
                et = 1 - (1 - text_t) ** 3
                size = max(1, int(48 * et))
                cv.itemconfigure(title_id, font=('Segoe UI', size, 'bold'))
                lv_size = max(1, int(28 * et))
                cv.itemconfigure(level_id, font=('Segoe UI', lv_size))
                # 背景渐暗为半透明黑
                bg_alpha = 0.85 - 0.5 * text_t
                ov.attributes('-alpha', max(0.35, bg_alpha))
                cv.configure(bg='#1a1a1a')

            # 阶段 3: 保持 (0.6~0.8)
            elif 0.6 <= t < 0.8:
                ov.attributes('-alpha', 0.35)

            # 阶段 4: 淡出 (0.8~1.0)
            elif t >= 0.8:
                fade_t = (t - 0.8) / 0.2
                ov.attributes('-alpha', 0.35 * (1 - fade_t))

            ov.after(16, _tick)

        ov.after(50, _tick)


# ═══════════════════════════════════════════════
#  SAO 字体加载
# ═══════════════════════════════════════════════

_fonts_loaded = False

def load_sao_fonts():
    """加载 SAO-UI 字体 (Windows: AddFontResourceExW)"""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    
    try:
        import ctypes
        # 使用 0 而非 FR_PRIVATE 以让 tkinter 可见
        for fname in ['SAOUI.ttf', 'ZhuZiAYuanJWD.ttf']:
            fpath = os.path.join(_FONTS, fname)
            if os.path.exists(fpath):
                ctypes.windll.gdi32.AddFontResourceExW(fpath, 0, 0)
    except Exception:
        pass


def _font_available(name):
    """检查字体是否在 tkinter 可用"""
    try:
        import tkinter.font as tkfont
        return name in tkfont.families()
    except Exception:
        return False


def get_sao_font(size: int = 12, bold: bool = False):
    """获取 SAO 字体族名 (回退到 Segoe UI)"""
    load_sao_fonts()
    family = 'SAO UI' if _font_available('SAO UI') else (
             'SAOUI' if _font_available('SAOUI') else 'Segoe UI')
    weight = 'bold' if bold else ''
    return (family, size, weight) if weight else (family, size)


def get_cjk_font(size: int = 10, bold: bool = False):
    """获取中文圆体字体 (回退到 Microsoft YaHei UI)"""
    load_sao_fonts()
    for name in ['方正FW筑紫A圆 简 D', 'ZhuZiAYuanJWD', 'Microsoft YaHei UI']:
        if _font_available(name):
            family = name
            break
    else:
        family = 'Microsoft YaHei UI'
    weight = 'bold' if bold else ''
    return (family, size, weight) if weight else (family, size)
