# -*- coding: utf-8 -*-
"""
配置模块 - 60键电子琴配置（含黑键/半音，支持SHIFT/CTRL三模式切换）

游戏实际布局（36物理键 × 3模式 = 60唯一音位，C2-B6 完整5八度）：
  普通模式（无修饰键）：C3-B5 (MIDI 48-83)
  SHIFT模式（按L Shift切换高八度）：C4-B6 (MIDI 60-95)
  CTRL模式（按L Ctrl切换低八度）：C2-B4 (MIDI 36-71)

物理按键不变（36键），修饰键改变八度映射：
             CTRL模式(-12)   普通模式        SHIFT模式(+12)
- Z-M白键:   C2-B2(36-47)   C3-B3(48-59)   C4-B4(60-71)
- A-J白键:   C3-B3(48-59)   C4-B4(60-71)   C5-B5(72-83)
- Q-U白键:   C4-B4(60-71)   C5-B5(72-83)   C6-B6(84-95)
- 1-5黑键:   C#2-A#2        C#3-A#3        C#4-A#4
- 6-0黑键:   C#3-A#3        C#4-A#4        C#5-A#5
- I,O,P,[,]黑键: C#4-A#4    C#5-A#5        C#6-A#6

总音域：C2-B6 (MIDI 36-95, 5个八度, 60个半音)
  MIDI 36-47: C2-B2 仅CTRL模式可达
  MIDI 48-59: CTRL或普通模式可达 (C3-B3)
  MIDI 60-71: 三种模式均可达 (C4-B4)
  MIDI 72-83: 普通或SHIFT模式可达 (C5-B5)
  MIDI 84-95: 仅SHIFT模式可达 (C6-B6)
"""

# 键盘映射配置
KEYBOARD_LAYOUT = {
    # 第一行 - 高音区白键 (键盘 Q-U) - C5-B5
    'row1': ['q', 'w', 'e', 'r', 't', 'y', 'u'],
    # 第二行 - 中音区白键 (键盘 A-J) - C4-B4
    'row2': ['a', 's', 'd', 'f', 'g', 'h', 'j'],
    # 第三行 - 低音区白键 (键盘 Z-M) - C3-B3
    'row3': ['z', 'x', 'c', 'v', 'b', 'n', 'm'],
}

# 黑键布局
BLACK_KEY_LAYOUT = {
    # 高音区黑键 (C#5-A#5) 
    'row1_black': ['i', 'o', None, 'p', '[', ']'],   # C# D# [gap] F# G# A#
    # 中音区黑键 (C#4-A#4)
    'row2_black': ['6', '7', None, '8', '9', '0'],   # C# D# [gap] F# G# A#
    # 低音区黑键 (C#3-A#3)
    'row3_black': ['1', '2', None, '3', '4', '5'],   # C# D# [gap] F# G# A#
}

# 音符名称映射 (用于显示)
# 简谱: 1=do, 2=re, 3=mi, 4=fa, 5=sol, 6=la, 7=si
NOTE_NAMES = {
    'row1': ['1̇', '2̇', '3̇', '4̇', '5̇', '6̇', '7̇'],       # 高音(点在上)
    'row2': ['1', '2', '3', '4', '5', '6', '7'],           # 中音
    'row3': ['1̣', '2̣', '3̣', '4̣', '5̣', '6̣', '7̣'],       # 低音(点在下)
}

BLACK_KEY_NAMES = {
    'row1_black': ['#1̇', '#2̇', None, '#4̇', '#5̇', '#6̇'],
    'row2_black': ['#1', '#2', None, '#4', '#5', '#6'],
    'row3_black': ['#1̣', '#2̣', None, '#4̣', '#5̣', '#6̣'],
}

# 扩展模式（</>）键盘显示用绝对音名（如 C5、C#4）
NOTE_NAMES_EXTENDED = {
    'row1': ['C5', 'D5', 'E5', 'F5', 'G5', 'A5', 'B5'],   # Q-U
    'row2': ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4'],   # A-J
    'row3': ['C3', 'D3', 'E3', 'F3', 'G3', 'A3', 'B3'],   # Z-M
}

BLACK_KEY_NAMES_EXTENDED = {
    'row1_black': ['C#5', 'D#5', None, 'F#5', 'G#5', 'A#5'],
    'row2_black': ['C#4', 'D#4', None, 'F#4', 'G#4', 'A#4'],
    'row3_black': ['C#3', 'D#3', None, 'F#3', 'G#3', 'A#3'],
}

# MIDI音符到按键的映射（普通模式，36键全音阶）
# 普通模式音域: C3-B5 (MIDI 48-83, 3个八度, 36个键)
#   低音区 C3-B3 (48-59) -> Z-M (白键) + 1-5 (黑键)
#   中音区 C4-B4 (60-71) -> A-J (白键) + 6-0 (黑键)
#   高音区 C5-B5 (72-83) -> Q-U (白键) + I,O,P,[,] (黑键)

MIDI_TO_KEY = {
    # === 低音区 C3-B3 (MIDI 48-59) ===
    # 白键
    48: 'z', 50: 'x', 52: 'c', 53: 'v', 55: 'b', 57: 'n', 59: 'm',
    # 黑键
    49: '1', 51: '2', 54: '3', 56: '4', 58: '5',
    
    # === 中音区 C4-B4 (MIDI 60-71) ===
    # 白键
    60: 'a', 62: 's', 64: 'd', 65: 'f', 67: 'g', 69: 'h', 71: 'j',
    # 黑键
    61: '6', 63: '7', 66: '8', 68: '9', 70: '0',
    
    # === 高音区 C5-B5 (MIDI 72-83) ===
    # 白键
    72: 'q', 74: 'w', 76: 'e', 77: 'r', 79: 't', 81: 'y', 83: 'u',
    # 黑键
    73: 'i', 75: 'o', 78: 'p', 80: '[', 82: ']',
}

# 按键到MIDI音符的反向映射（普通模式）
KEY_TO_MIDI = {v: k for k, v in MIDI_TO_KEY.items()}

# SHIFT模式映射（每个键+12 MIDI，物理按键不变）
# SHIFT模式音域: C4-B6 (MIDI 60-95, 3个八度, 36个键)
#   低音区 C4-B4 (60-71) -> Z-M (白键) + 1-5 (黑键)
#   中音区 C5-B5 (72-83) -> A-J (白键) + 6-0 (黑键)
#   高音区 C6-B6 (84-95) -> Q-U (白键) + I,O,P,[,] (黑键)
MIDI_TO_KEY_SHIFT = {midi + 12: key for midi, key in MIDI_TO_KEY.items()}

KEY_TO_MIDI_SHIFT = {v: k for k, v in MIDI_TO_KEY_SHIFT.items()}

# CTRL模式映射（每个键-12 MIDI，物理按键不变）
# CTRL模式音域: C2-B4 (MIDI 36-71, 3个八度, 36个键)
#   低音区 C2-B2 (36-47) -> Z-M (白键) + 1-5 (黑键)
#   中音区 C3-B3 (48-59) -> A-J (白键) + 6-0 (黑键)
#   高音区 C4-B4 (60-71) -> Q-U (白键) + I,O,P,[,] (黑键)
MIDI_TO_KEY_CTRL = {midi - 12: key for midi, key in MIDI_TO_KEY.items()}

KEY_TO_MIDI_CTRL = {v: k for k, v in MIDI_TO_KEY_CTRL.items()}

# === 扩展模式 </>  (全钢琴88键) ===
# <模式：每个键 -27 半音，覆盖 A0-B2 (MIDI 21-47)
# 物理键不变，音符下移27半音，只取落在21-47范围内的映射
MIDI_TO_KEY_LT = {midi - 27: key for midi, key in MIDI_TO_KEY.items()
                  if 21 <= midi - 27 <= 47}

KEY_TO_MIDI_LT = {v: k for k, v in MIDI_TO_KEY_LT.items()}

# >模式：每个键 +36 半音，覆盖 C6-C8 (MIDI 84-108)
MIDI_TO_KEY_GT = {midi + 36: key for midi, key in MIDI_TO_KEY.items()
                  if 84 <= midi + 36 <= 108}

KEY_TO_MIDI_GT = {v: k for k, v in MIDI_TO_KEY_GT.items()}

# 模式系统选择: 'classic' = L Shift/L Ctrl, 'extended' = </>
# classic: C2-B6 (MIDI 36-95, 60键)
# extended: A0-C8 (MIDI 21-108, 88键/全钢琴)
DEFAULT_MODE_SYSTEM = 'classic'

# 模式切换设置
MODE_SWITCH_DELAY_MS = 65     # 切换模式后必须等待的延迟(毫秒)，确保游戏响应
MODE_KEY_PRESS_MS = 35        # 模式切换按键按下时长(毫秒)

# 黑键集合（完整5八度: C2-B6, MIDI 36-95）
BLACK_KEY_NOTES = {
    # CTRL独占区 C2-B2
    37, 39, 42, 44, 46,   # C#2, D#2, F#2, G#2, A#2
    # 普通模式 C3-B5
    49, 51, 54, 56, 58,   # C#3, D#3, F#3, G#3, A#3
    61, 63, 66, 68, 70,   # C#4, D#4, F#4, G#4, A#4
    73, 75, 78, 80, 82,   # C#5, D#5, F#5, G#5, A#5
    # SHIFT独占区 C6-B6
    85, 87, 90, 92, 94,   # C#6, D#6, F#6, G#6, A#6
}

# 和弦MIDI映射（保留兼容，但36键模式下不再需要和弦键）
CHORD_KEYS = {}

# 播放设置
DEFAULT_TEMPO = 120  # 默认BPM
MIN_NOTE_INTERVAL = 0.05  # 最小音符间隔(秒)，50ms内视为同时发声
KEY_PRESS_DURATION = 0.2  # 默认按键持续时间(秒)

# 按键时长设置（游戏用按键时长做延音踏板，需尊重MIDI音符时长）
KEY_DURATION_MAX = 10.0  # 最大按键持续时间(秒)，允许超长延音自然衰减
KEY_DURATION_MIN = 0.5  # 最小按键持续时间(秒)

# 力度(Velocity)映射设置
# MIDI力度范围 0-127，用于调整按键时长和表现力
VELOCITY_MIN = 20       # 低于此值的音符跳过（太弱听不到）
VELOCITY_SCALE = True   # 是否根据力度调整按键时长
VELOCITY_DURATION_MIN = 0.03  # 最弱力度对应的按键时长
VELOCITY_DURATION_MAX = 0.15  # 最强力度对应的按键时长

# 智能轨道优化设置
# 当同时发声的音符太多时，智能简化和弦（保留骨架音）
MAX_SIMULTANEOUS_KEYS = 8    # 最大同时按键数（6个足够表达大多数和弦）
TRACK_PRIORITY_MODE = True   # 启用智能优先级模式
# 和弦简化策略：保留根音、五度音、高音旋律
MELODY_PRIORITY = True       # 启用旋律优先（高音区为主旋律）
CHORD_PRESERVE_BASS = True   # 保留低音根音（和弦基础）
CHORD_PRESERVE_TOP = True    # 保留高音旋律（最重要）

# GUI设置
WINDOW_TITLE = "咏 Midiplayer v3.4.2+3402 60/88键位"
WINDOW_SIZE = "900x980"
BUTTON_WIDTH = 60
BUTTON_HEIGHT = 60

# 默认全局快捷键设置
DEFAULT_HOTKEYS = {
    'play_pause': 'F5',         # 播放/暂停
    'stop': 'F6',               # 停止
    'speed_up': 'F7',           # 加速
    'speed_down': 'F8',         # 减速
    'toggle_topmost': 'F9',     # 置顶切换
    'hide_panels': 'F10',       # 一键隐藏/显示面板
}

# 配置文件路径
import os
import sys

def _get_config_dir():
    """获取配置文件目录（打包后使用exe所在目录，开发时使用脚本目录）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后，使用exe所在目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境，使用脚本目录
        return os.path.dirname(__file__)

CONFIG_FILE = os.path.join(_get_config_dir(), 'settings.json')
