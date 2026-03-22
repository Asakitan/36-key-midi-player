# -*- coding: utf-8 -*-
"""
MIDI控制器界面 - 通道/乐器/音符控制、钢琴键盘可视化、MIDI预览播放

功能：
1. 通道控制面板：显示乐器名称、音符范围，支持开关/移调
2. 钢琴键盘可视化：60/88键、命中范围显示、可拖拽调整移调
3. 内置MIDI预览播放器（FluidSynth高品质 / Pygame回退）
4. 保存到MIDI文件或歌曲设置（SongSettings）
"""

import tkinter as tk
from tkinter import ttk, filedialog
import threading
import os
import sys
import json
import time
import math
import ctypes
import tempfile
import shutil
from typing import Optional, Dict, List, Tuple, Set

import mido

# ==================== 常量 ====================

NOTE_NAMES_12 = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
WHITE_PC = {0, 2, 4, 5, 7, 9, 11}   # C, D, E, F, G, A, B
BLACK_PC = {1, 3, 6, 8, 10}          # C#, D#, F#, G#, A#

CHANNEL_COLORS = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
    '#FFEEAD', '#D4A5A5', '#9B59B6', '#E67E22',
    '#3498DB', '#2ECC71', '#F39C12', '#1ABC9C',
    '#E74C3C', '#8E44AD', '#2980B9', '#27AE60',
]

# SoundFont 搜索路径 (Windows)
# ==================== 钢琴音源自动安装 (FluidSynth + GeneralUser GS) ====================
# FluidSynth 2.3.6 portable Windows x64
_PIANO_FS_URL = "https://github.com/FluidSynth/fluidsynth/releases/download/v2.3.6/fluidsynth-2.3.6-win10-x64.zip"
# GeneralUser GS — 开源 GM 音源，~30 MB sf2 文件 (直接从仓库下载，该项目无 Release 页)
_PIANO_SF_URL = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2"
# FluidSynth DLL 安装目录 — 写入用户 AppData，无需管理员权限
_PIANO_FS_BIN_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'fluidsynth', 'bin')


def _sf2_search_paths():
    base = os.path.dirname(os.path.abspath(__file__))
    appdata = os.environ.get('APPDATA', '')
    localappdata = os.environ.get('LOCALAPPDATA', '')
    pf = os.environ.get('PROGRAMFILES', 'C:/Program Files')
    pf86 = os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')
    paths = [
        # 项目本地
        os.path.join(base, 'soundfont'),
        os.path.join(base, 'soundfonts'),
        base,
        # 用户目录
        os.path.join(appdata, 'fluidsynth'),
        os.path.join(localappdata, 'fluidsynth'),
        os.path.join(os.path.expanduser('~'), 'soundfonts'),
        os.path.join(os.path.expanduser('~'), 'soundfont'),
        # 常见安装位置
        'C:/soundfonts',
        'C:/soundfont',
        'C:/tools/fluidsynth/soundfonts',
        os.path.join(pf, 'FluidSynth', 'soundfonts'),
        os.path.join(pf86, 'FluidSynth', 'soundfonts'),
        os.path.join(pf, 'MuseScore 4', 'sound'),
        os.path.join(pf, 'MuseScore 3', 'sound'),
        os.path.join(pf86, 'MuseScore 3', 'sound'),
        os.path.join(pf, 'MuseScore 4', 'sounds'),
        os.path.join(localappdata, 'MuseScore', 'MuseScore4', 'Soundfonts'),
    ]
    return paths


def find_soundfont() -> Optional[str]:
    """查找可用的 .sf2 SoundFont 文件"""
    for d in _sf2_search_paths():
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith('.sf2'):
                    return os.path.join(d, f)
    return None


def note_name(midi_note: int) -> str:
    """MIDI 音符号 → 名称 (例: 60 → C4)"""
    return f"{NOTE_NAMES_12[midi_note % 12]}{midi_note // 12 - 1}"


def is_white(n: int) -> bool:
    return n % 12 in WHITE_PC


def is_black(n: int) -> bool:
    return n % 12 in BLACK_PC


# ==================== 主题色获取（懒加载避免循环引用） ====================

_ModernColors = None

def _get_colors():
    """延迟加载 gui.ModernColors, 避免循环引用"""
    global _ModernColors
    if _ModernColors is None:
        try:
            from gui import ModernColors
            _ModernColors = ModernColors
        except ImportError:
            _ModernColors = type('FallbackColors', (), {
                'BG_DARK': '#1C1C1E', 'BG_CARD': '#2C2C2E', 'BG_HOVER': '#3A3A3C',
                'BG_INPUT': '#1C1C1E', 'BG_PANEL': '#2C2C2E',
                'ACCENT_BLUE': '#0A84FF', 'ACCENT_GREEN': '#30D158', 'ACCENT_RED': '#FF453A',
                'ACCENT_ORANGE': '#FF9F0A', 'ACCENT_PURPLE': '#BF5AF2', 'ACCENT_CYAN': '#64D2FF',
                'TEXT_PRIMARY': '#F5F5F7', 'TEXT_SECONDARY': '#98989D',
                'TEXT_BRIGHT': '#FFFFFF', 'TEXT_DIM': '#636366',
                'BTN_PRIMARY': '#0A84FF', 'BTN_SECONDARY': '#48484A', 'BTN_DANGER': '#FF453A',
                'BORDER': '#38383A', 'BORDER_BRIGHT': '#48484A',
                'PIANO_WHITE': '#DCDCE0', 'PIANO_BLACK': '#2A2A2E', 'PIANO_BG': '#1A1A1C',
                'KEY_NORMAL': '#3A3A3C',
            })
    return _ModernColors


class _SAOWhiteColors:
    """SAO 对话框白色主题 (与截图匹配)"""
    BG_DARK     = '#f0f0f5'
    BG_CARD     = '#ffffff'
    BG_HOVER    = '#eaeaef'
    BG_INPUT    = '#f5f5f7'
    BG_PANEL    = '#f5f5f7'
    ACCENT_BLUE   = '#0A84FF'
    ACCENT_GREEN  = '#28a745'
    ACCENT_RED    = '#dc3545'
    ACCENT_ORANGE = '#FF9F0A'
    ACCENT_PURPLE = '#7c4dff'
    ACCENT_CYAN   = '#0078d7'
    TEXT_PRIMARY   = '#1c1c1e'
    TEXT_SECONDARY = '#636366'
    TEXT_BRIGHT    = '#000000'
    TEXT_DIM       = '#8e8e93'
    BTN_PRIMARY    = '#0A84FF'
    BTN_SECONDARY  = '#d1d1d6'
    BTN_DANGER     = '#dc3545'
    BORDER         = '#d1d1d6'
    BORDER_BRIGHT  = '#aeaeb2'
    PIANO_WHITE    = '#ffffff'
    PIANO_BLACK    = '#1a1a1e'
    PIANO_BG       = '#e0e0e8'
    KEY_NORMAL     = '#c8c8cc'
    VIZ_BG         = '#e8e8ed'


# ==================== MIDI 预览播放器 ====================

class MIDIPreviewPlayer:
    """
    内置 MIDI 预览播放器 (三后端优先级: FluidSynth → WinMCI → Pygame)

    WinMCI 后端使用 Windows 内置 GS 软件合成器 (ctypes, 无需任何外部安装),
    在 Win10/Win11 上音质极佳 (Microsoft GS Wavetable Synth 或兼容 DLS 引擎).
    支持 seek / pause / resume / 通道静音 (生成带静音的临时 MIDI 文件).
    """

    _MCI_ALIAS = 'mcp_midi_preview'

    def __init__(self):
        self._backend: Optional[str] = None
        self._synth = None          # fluidsynth.Synth 实例
        self._sfid = None           # SoundFont ID
        self._soundfont_path: Optional[str] = None

        self._playing = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._channel_mutes: Set[int] = set()

        self._current_time = 0.0
        self._total_time = 0.0
        self._play_gen: int = 0   # 每次 play() 递增；旧线程通过比对 gen 自行退出

        # WinMCI 状态
        self._mci_open = False
        self._mci_lock = threading.Lock()  # MCI 不是线程安全的，需要序列化所有 MCI 调用
        self._mci_tmp_dir: Optional[str] = None   # 临时目录 (静音MIDI)
        self._mci_tmp_file: Optional[str] = None  # 当前使用的临时 MIDI 路径

        # 回调
        self.on_progress: Optional[callable] = None      # (current, total)
        self.on_playback_end: Optional[callable] = None   # ()

        # 检测可用后端
        self._fs_ok = False
        self._pg_ok = False
        self._mci_ok = False
        self._detect_backends()

    # ---------- 检测 ----------

    @staticmethod
    def _find_fluidsynth_dll_dir() -> Optional[str]:
        """搜索 libfluidsynth DLL 所在目录"""
        pf = os.environ.get('PROGRAMFILES', 'C:/Program Files')
        pf86 = os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')
        localappdata = os.environ.get('LOCALAPPDATA', '')
        candidates = [
            _PIANO_FS_BIN_DIR,              # %LOCALAPPDATA%\fluidsynth\bin (新安装位置，首选)
            r'C:\tools\fluidsynth\bin',     # 旧版兼容
            os.path.join(localappdata, 'fluidsynth', 'bin'),   # 备用
            'C:/fluidsynth/bin',
            f'{pf}/FluidSynth/bin',
            f'{pf86}/FluidSynth/bin',
            'C:/Windows/System32',
            'C:/Windows/SysWOW64',
        ]
        for p in os.environ.get('PATH', '').split(os.pathsep):
            if 'fluid' in p.lower():
                candidates.insert(0, p)
        for d in candidates:
            if os.path.isdir(d):
                for name in os.listdir(d):
                    if name.lower().startswith('libfluidsynth') and name.lower().endswith('.dll'):
                        return d
        return None

    def _ensure_fluid_dll_in_path(self, bin_dir: str):
        """将 FluidSynth DLL 目录注册到 DLL 搜索路径，并预加载 DLL（安装后调用）"""
        # 更新 PATH 环境变量
        curr = os.environ.get('PATH', '')
        if bin_dir.lower() not in curr.lower():
            os.environ['PATH'] = bin_dir + os.pathsep + curr
        # Python 3.8+ 的 DLL 搜索目录（直接调用原始函数，不经过 _safe_add_dll）
        _orig = getattr(os, '_orig_add_dll_directory', None)
        if _orig is None:
            _orig = getattr(os, 'add_dll_directory', None)
        if _orig and os.path.isdir(bin_dir):
            try:
                _orig(bin_dir)
            except Exception:
                pass
        # 用 ctypes 预加载 DLL，这样 fluidsynth.py 的 ctypes.cdll.LoadLibrary
        # 可以找到已加载的 DLL，无需依赖硬编码的 C:\tools 路径
        if os.path.isdir(bin_dir):
            for name in sorted(os.listdir(bin_dir)):
                if name.lower().startswith('libfluidsynth') and name.lower().endswith('.dll'):
                    try:
                        ctypes.CDLL(os.path.join(bin_dir, name))
                        print(f'[FluidSynth] 预加载 DLL: {name}')
                    except Exception as _e:
                        print(f'[FluidSynth] 预加载失败: {_e}')
                    break

    def reinit_fluidsynth(self, fluid_bin_dir: str, sf_path: str) -> bool:
        """安装 FluidSynth DLL + SoundFont 后调用此方法重新初始化"""
        self._ensure_fluid_dll_in_path(fluid_bin_dir)
        self._fs_ok = False
        # 从 sys.modules 移除缓存，强制重新导入（以便加载新注册的 DLL 路径）
        import sys as _sys
        _sys.modules.pop('fluidsynth', None)
        # 防止第三方 fluidsynth.py 在模块级调用 os.add_dll_directory('C:\\tools\\fluidsynth\\bin')
        # 时因目录不存在而抛出 FileNotFoundError — 用安全版本临时替换
        _orig_add = getattr(os, 'add_dll_directory', None)
        if _orig_add is not None:
            def _safe_reimport_add(path):
                try:
                    if os.path.isdir(path):
                        return _orig_add(path)
                except Exception:
                    pass
            os.add_dll_directory = _safe_reimport_add
        try:
            import fluidsynth as _fs  # noqa
            self._fs_ok = True
        except Exception as _e:
            print(f'[FluidSynth] 重新导入失败: {_e}')
        finally:
            if _orig_add is not None:
                os.add_dll_directory = _orig_add
        if not self._fs_ok:
            return False
        # 停止当前后端并切换到 FluidSynth
        self.stop()
        if self._synth:
            try: self._synth.delete()
            except Exception: pass
            self._synth = None
        self._backend = None
        return self._init_fluidsynth(sf_path)

    def _detect_backends(self):
        # 1) pyfluidsynth
        _orig_add_dll = getattr(os, 'add_dll_directory', None)
        if _orig_add_dll is not None:
            real_dll_dir = self._find_fluidsynth_dll_dir()
            if real_dll_dir:
                try:
                    _orig_add_dll(real_dll_dir)
                except Exception:
                    pass
            def _safe_add_dll(path):
                try:
                    if os.path.isdir(path):
                        return _orig_add_dll(path)
                except Exception:
                    pass
            os.add_dll_directory = _safe_add_dll
        try:
            import fluidsynth
            self._fs_ok = True
        except (ImportError, OSError, Exception):
            pass
        finally:
            if _orig_add_dll is not None:
                os.add_dll_directory = _orig_add_dll

        # 2) Windows MCI (ctypes 内置, 无需安装)
        if sys.platform == 'win32':
            try:
                buf = ctypes.create_unicode_buffer(128)
                ctypes.windll.winmm.mciSendStringW(
                    'sysinfo all quantity', buf, 128, None)
                self._mci_ok = True
            except Exception:
                pass

        # 3) pygame 后备
        try:
            import pygame
            self._pg_ok = True
        except (ImportError, OSError):
            pass

    # ---------- 属性 ----------

    @property
    def backend_name(self) -> str:
        if self._backend == 'fluidsynth':
            return f'FluidSynth ({os.path.basename(self._soundfont_path or "")})'
        if self._backend == 'winmci':
            return 'Windows GS 合成器 (高品质内置)'
        if self._backend == 'pygame':
            return 'Pygame (系统MIDI合成器)'
        return '未初始化'

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def total_time(self) -> float:
        return self._total_time

    # ---------- 初始化 ----------

    def init(self, soundfont_path: Optional[str] = None) -> bool:
        """初始化最佳可用后端 (FluidSynth > WinMCI > Pygame)"""
        if self._fs_ok:
            sf = soundfont_path or find_soundfont()
            if sf and os.path.exists(sf):
                if self._init_fluidsynth(sf):
                    return True
        if self._mci_ok:
            if self._init_winmci():
                return True
        if self._pg_ok:
            if self._init_pygame():
                return True
        return False

    def _init_fluidsynth(self, sf_path: str) -> bool:
        try:
            import fluidsynth  # type: ignore
            self._synth = fluidsynth.Synth(gain=0.6)
            started = False
            for drv in ('dsound', 'portaudio', None):
                try:
                    if drv:
                        self._synth.start(driver=drv)
                    else:
                        self._synth.start()
                    started = True
                    break
                except Exception:
                    continue
            if not started:
                return False
            self._sfid = self._synth.sfload(sf_path)
            if self._sfid < 0:
                return False
            for ch in range(16):
                self._synth.program_select(ch, self._sfid, 0, 0)
            self._backend = 'fluidsynth'
            self._soundfont_path = sf_path
            print(f"[预览] FluidSynth 就绪: {os.path.basename(sf_path)}")
            return True
        except Exception as e:
            print(f"[预览] FluidSynth 初始化失败: {e}")
            if self._synth:
                try:
                    self._synth.delete()
                except Exception:
                    pass
                self._synth = None
            self._fs_ok = False
            return False

    def _init_winmci(self) -> bool:
        """初始化 Windows MCI 后端 (无需外部依赖)"""
        try:
            self._mci_tmp_dir = tempfile.mkdtemp(prefix='midi_preview_')
            self._backend = 'winmci'
            print("[预览] Windows MCI (GS合成器) 就绪")
            return True
        except Exception as e:
            print(f"[预览] WinMCI 初始化失败: {e}")
            return False

    def _init_pygame(self) -> bool:
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2,
                                  buffer=1024)
            self._backend = 'pygame'
            print("[预览] Pygame MIDI 后端就绪")
            return True
        except Exception as e:
            print(f"[预览] Pygame 初始化失败: {e}")
            return False

    # ---------- WinMCI 辅助 ----------

    def _mci_send(self, cmd: str) -> str:
        """发送 MCI 命令，返回结果字符串（线程安全）"""
        with self._mci_lock:
            buf = ctypes.create_unicode_buffer(512)
            err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 512, None)
            if err != 0:
                # 非致命：MCI 在设备未打开时返回错误是正常的
                pass
            return buf.value.strip()

    def _mci_close_current(self):
        """强制停止并关闭 MCI MIDI 设备（不依赖 _mci_open 标志，确保音频立即停止）"""
        # 无条件发送 stop + close；对无效别名 MCI 会静默失败，不影响逻辑
        try:
            self._mci_send(f'stop {self._MCI_ALIAS}')
        except Exception:
            pass
        try:
            self._mci_send(f'close {self._MCI_ALIAS}')
        except Exception:
            pass
        self._mci_open = False

    def _mci_open_file(self, path: str) -> bool:
        """打开 MIDI 文件到 MCI 别名"""
        self._mci_close_current()
        # MCI 路径不允许有空格，使用 8.3 短路径
        try:
            safe = ctypes.create_unicode_buffer(512)
            ctypes.windll.kernel32.GetShortPathNameW(path, safe, 512)
            safe_path = safe.value or path
        except Exception:
            safe_path = path
        with self._mci_lock:
            ret_buf = ctypes.create_unicode_buffer(512)
            err = ctypes.windll.winmm.mciSendStringW(
                f'open "{safe_path}" type sequencer alias {self._MCI_ALIAS}',
                ret_buf, 512, None)
            if err != 0:
                print(f"[WinMCI] open 失败, err={err:#06x}")
                return False
        self._mci_open = True
        # 必须设置为毫秒格式，否则 position 返回 MIDI ticks
        self._mci_send(f'set {self._MCI_ALIAS} time format milliseconds')
        return True

    def _generate_muted_midi(self, src: str) -> str:
        """
        根据当前 _channel_mutes 生成静音版临时 MIDI 文件。
        静音通道的所有 note_on velocity 强制为 0。
        返回临时文件路径。
        """
        out_path = os.path.join(
            self._mci_tmp_dir,
            f'muted_{id(self)}.mid')
        try:
            mid = mido.MidiFile(src)
            for track in mid.tracks:
                for i, msg in enumerate(track):
                    if (hasattr(msg, 'channel')
                            and msg.channel in self._channel_mutes
                            and msg.type == 'note_on'
                            and msg.velocity > 0):
                        track[i] = msg.copy(velocity=0)
            mid.save(out_path)
            return out_path
        except Exception as e:
            print(f"[WinMCI] 生成静音MIDI失败: {e}")
            # 回退: 直接用原文件
            return src

    # ---------- 播放控制 ----------

    def play(self, midi_path: str, start_time: float = 0.0):
        self.stop()                       # 递增 _play_gen，令旧线程退出
        self._playing = True
        self._paused = False
        my_gen = self._play_gen           # 在 stop() 之后捕获当前 gen
        if self._backend == 'fluidsynth':
            self._thread = threading.Thread(
                target=self._play_fs, args=(midi_path, start_time, my_gen), daemon=True)
            self._thread.start()
        elif self._backend == 'winmci':
            self._thread = threading.Thread(
                target=self._play_mci, args=(midi_path, start_time, my_gen), daemon=True)
            self._thread.start()
        elif self._backend == 'pygame':
            self._play_pg(midi_path)

    def pause(self):
        if self._playing and not self._paused:
            self._paused = True
            if self._backend == 'fluidsynth' and self._synth:
                self._all_off()
            elif self._backend == 'winmci' and self._mci_open:
                try:
                    self._mci_send(f'pause {self._MCI_ALIAS}')
                except Exception:
                    pass
            elif self._backend == 'pygame':
                try:
                    import pygame; pygame.mixer.music.pause()
                except Exception:
                    pass

    def resume(self):
        if self._playing and self._paused:
            self._paused = False
            if self._backend == 'winmci' and self._mci_open:
                try:
                    self._mci_send(f'resume {self._MCI_ALIAS}')
                except Exception:
                    pass
            elif self._backend == 'pygame':
                try:
                    import pygame; pygame.mixer.music.unpause()
                except Exception:
                    pass

    def stop(self):
        self._play_gen += 1          # 令所有旧线程的 gen 校验失败，立刻退出循环
        self._playing = False
        self._paused = False
        self._current_time = 0.0
        if self._backend == 'fluidsynth' and self._synth:
            self._all_off()
        elif self._backend == 'pygame':
            try:
                import pygame; pygame.mixer.music.stop()
            except Exception:
                pass
        # WinMCI: 不从主线程发 MCI 命令 (MCI 不是线程安全的)
        # 而是让工作线程在 finally 中自行 stop+close
        # 等待旧线程退出并在其 finally 中关闭 MCI
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        # 如果线程超时未退出 (极端情况), 主线程兜底关闭 MCI
        if self._backend == 'winmci' and self._mci_open:
            self._mci_close_current()
        self._thread = None

    def set_channel_mute(self, channel: int, muted: bool):
        if muted:
            self._channel_mutes.add(channel)
        else:
            self._channel_mutes.discard(channel)
        if self._backend == 'fluidsynth' and self._synth and muted:
            if self._playing:
                for n in range(128):
                    try:
                        self._synth.noteoff(channel, n)
                    except Exception:
                        pass
        # WinMCI/Pygame: 下次 play() 时会自动生成新的静音 MIDI

    def cleanup(self):
        self.stop()
        if self._synth:
            try:
                self._synth.delete()
            except Exception:
                pass
            self._synth = None
        # 清理临时目录
        if self._mci_tmp_dir and os.path.isdir(self._mci_tmp_dir):
            try:
                shutil.rmtree(self._mci_tmp_dir, ignore_errors=True)
            except Exception:
                pass
            self._mci_tmp_dir = None

    # ---------- WinMCI 播放线程 ----------

    def _play_mci(self, midi_path: str, start_time: float, gen: int):
        """WinMCI 播放线程：打开文件、seek、play，然后轮询进度。
        gen: 本次播放的代次，与 self._play_gen 不一致时表示被新的 play() 取代，立即退出。"""
        try:
            # 计算 MIDI 总长度
            try:
                mid_info = mido.MidiFile(midi_path)
                self._total_time = max(mid_info.length, 0.1)
            except Exception:
                self._total_time = 0.0

            # 生成带静音的临时 MIDI（如有静音通道则需要）
            if self._channel_mutes and self._mci_tmp_dir:
                play_path = self._generate_muted_midi(midi_path)
            else:
                play_path = midi_path

            if not self._mci_open_file(play_path):
                self._playing = False
                return

            # 查询 MCI 报告的总长度 (ms) 作为更准确的 total_time
            try:
                len_str = self._mci_send(f'status {self._MCI_ALIAS} length')
                mci_total = int(len_str.strip()) / 1000.0
                if mci_total > 0:
                    self._total_time = mci_total
            except Exception:
                pass

            # 跳转到 start_time
            if start_time > 0 and self._total_time > 0:
                seek_ms = int(start_time * 1000)
                self._mci_send(f'seek {self._MCI_ALIAS} to {seek_ms}')

            # 开始播放
            self._mci_send(f'play {self._MCI_ALIAS}')

            # 竞态保护：如果 stop() 在打开文件期间已被调用，直接退出
            # (MCI 将在 finally 中由本线程关闭)
            if not self._playing or self._play_gen != gen:
                return

            # 轮询进度
            last_cb = 0.0
            while self._playing and self._play_gen == gen:
                if self._paused:
                    time.sleep(0.05)
                    continue
                try:
                    pos_str = self._mci_send(
                        f'status {self._MCI_ALIAS} position')
                    cur_ms = int(pos_str.strip())
                    cur = cur_ms / 1000.0
                    self._current_time = cur
                except Exception:
                    cur = self._current_time  # 保持上次值

                # 检测播放结束
                try:
                    mode = self._mci_send(
                        f'status {self._MCI_ALIAS} mode')
                    if mode == 'stopped':
                        break
                except Exception:
                    pass

                # 进度回调 (主线程动画循环也会轮询，这里仅做补充)
                if self.on_progress and time.perf_counter() - last_cb > 0.05:
                    last_cb = time.perf_counter()
                    try:
                        self.on_progress(cur, self._total_time)
                    except Exception:
                        pass

                time.sleep(0.05)

        except Exception as e:
            print(f"[WinMCI] 播放异常: {e}")
        finally:
            # 无论哪个代次的线程都必须关闭自己打开的 MCI 设备
            # （MCI 不是线程安全的，必须在同一线程中 open→play→stop→close）
            self._mci_close_current()
            # 只有当前代次才设置 _playing=False 并发送播放结束回调
            if self._play_gen == gen:
                self._playing = False
                if self.on_playback_end:
                    try:
                        self.on_playback_end()
                    except Exception:
                        pass

    # ---------- FluidSynth 播放线程 ----------

    def _play_fs(self, midi_path: str, start_time: float, gen: int):
        try:
            mid = mido.MidiFile(midi_path)
        except Exception as e:
            print(f"[预览] MIDI 加载失败: {e}")
            if self._play_gen == gen:
                self._playing = False
            return

        self._total_time = mid.length

        # 预计算绝对时间
        events = []
        tempo = 500000
        tpb = mid.ticks_per_beat
        t = 0.0
        for msg in mido.merge_tracks(mid.tracks):
            t += mido.tick2second(msg.time, tpb, tempo)
            if msg.type == 'set_tempo':
                tempo = msg.tempo
            events.append((t, msg))

        # 快进到 start_time 前的 program_change
        for at, msg in events:
            if at > start_time:
                break
            if msg.type == 'program_change' and self._sfid is not None:
                try:
                    self._synth.program_select(msg.channel, self._sfid, 0, msg.program)
                except Exception:
                    pass

        # 播放主循环
        t0 = time.perf_counter() - start_time
        last_prog = 0

        for at, msg in events:
            if not self._playing:
                break
            if at < start_time:
                continue

            while self._playing and self._play_gen == gen:
                if self._paused:
                    self._all_off()
                    ps = time.perf_counter()
                    while self._paused and self._playing and self._play_gen == gen:
                        time.sleep(0.02)
                    t0 += time.perf_counter() - ps

                now = time.perf_counter()
                target = t0 + at
                if now >= target:
                    break
                time.sleep(min(target - now, 0.005))

            if not self._playing:
                break

            self._current_time = at

            if msg.is_meta:
                continue

            try:
                if msg.type == 'note_on' and msg.velocity > 0:
                    if msg.channel not in self._channel_mutes:
                        self._synth.noteon(msg.channel, msg.note, msg.velocity)
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    self._synth.noteoff(msg.channel, msg.note)
                elif msg.type == 'program_change' and self._sfid is not None:
                    self._synth.program_select(msg.channel, self._sfid, 0, msg.program)
                elif msg.type == 'control_change':
                    self._synth.cc(msg.channel, msg.control, msg.value)
            except Exception:
                pass

            if self.on_progress and at - last_prog > 0.1:
                last_prog = at
                try:
                    self.on_progress(at, self._total_time)
                except Exception:
                    pass

        if self._play_gen == gen:
            self._playing = False
            self._all_off()
            if self.on_playback_end:
                try:
                    self.on_playback_end()
                except Exception:
                    pass

    def _play_pg(self, midi_path: str):
        try:
            import pygame
            pygame.mixer.music.load(midi_path)
            pygame.mixer.music.play()
        except Exception as e:
            print(f"[预览] Pygame 播放失败: {e}")

    def _all_off(self):
        if self._synth:
            for ch in range(16):
                for n in range(128):
                    try:
                        self._synth.noteoff(ch, n)
                    except Exception:
                        pass


# ==================== 钢琴键盘控件 ====================

class PianoKeyboardWidget(tk.Canvas):
    """
    交互式钢琴键盘:
      - 60键 (C2-B6) 或 88键 (A0-C8)
      - 显示歌曲音符分布 (各音高出现次数)
      - 可拖拽命中范围 (调整全局移调)
    """

    RANGE_60 = (36, 95)    # C2 – B6
    RANGE_88 = (21, 108)   # A0 – C8

    def __init__(self, parent, mode='classic', width=860, height=110,
                 on_transpose_change=None, colors=None, **kw):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, **kw)

        self.C = colors if colors is not None else _get_colors()
        self.mode = mode
        self._canvas_w = width
        self._canvas_h = height

        # 键盘范围
        if mode == 'extended':
            self.kb_range = self.RANGE_88
        else:
            self.kb_range = self.RANGE_60

        # 歌曲音符分布  {midi_note: count}
        self._note_dist: Dict[int, int] = {}
        self._max_count = 1

        # 移调偏移 (可拖拽调整)
        self._transpose = 0

        # 回调
        self.on_transpose_change = on_transpose_change

        # 布局缓存
        self._keys: Dict[int, dict] = {}   # midi_note -> {x, y, w, h, is_black}
        self._wk_w = 0.0   # 白键宽度
        self._bk_w = 0.0   # 黑键宽度
        self._bk_h = 0.0   # 黑键高度

        # 拖拽状态
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_transpose = 0

        self._compute_layout()

        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_release)
        self.bind('<Configure>', self._on_resize)

        # 延迟绘制，等 pack 完成后再执行
        self.after(10, self._full_draw)

    # ---------- 布局 ----------

    def _compute_layout(self):
        self._keys.clear()
        lo, hi = self.kb_range
        margin = 2
        usable = self._canvas_w - 2 * margin

        # 白键计数
        whites = [n for n in range(lo, hi + 1) if is_white(n)]
        nw = len(whites)
        if nw == 0:
            return
        self._wk_w = usable / nw
        self._bk_w = self._wk_w * 0.62
        self._bk_h = self._canvas_h * 0.60

        # 白键位置
        wi = 0
        for n in range(lo, hi + 1):
            if is_white(n):
                self._keys[n] = {
                    'x': margin + wi * self._wk_w,
                    'y': 0, 'w': self._wk_w,
                    'h': self._canvas_h, 'is_black': False,
                }
                wi += 1

        # 黑键位置 (靠左白键右边缘)
        for n in range(lo, hi + 1):
            if is_black(n):
                left = n - 1
                while left >= lo and not is_white(left):
                    left -= 1
                if left in self._keys:
                    lx = self._keys[left]['x']
                    bx = lx + self._wk_w - self._bk_w / 2
                    self._keys[n] = {
                        'x': bx, 'y': 0,
                        'w': self._bk_w, 'h': self._bk_h,
                        'is_black': True,
                    }

    # ---------- 数据接口 ----------

    def set_song_notes(self, notes):
        """设置歌曲音符列表 (NoteEvent 或 int)"""
        self._note_dist.clear()
        for n in notes:
            pitch = n.note if hasattr(n, 'note') else int(n)
            self._note_dist[pitch] = self._note_dist.get(pitch, 0) + 1
        self._max_count = max(self._note_dist.values()) if self._note_dist else 1
        self._full_draw()

    def set_transpose(self, t: int):
        self._transpose = t
        self._full_draw()

    def get_transpose(self) -> int:
        return self._transpose

    def set_mode(self, mode: str):
        self.mode = mode
        self.kb_range = self.RANGE_88 if mode == 'extended' else self.RANGE_60
        self._compute_layout()
        self._full_draw()

    def get_hit_stats(self) -> dict:
        """返回命中统计 {total, hit, miss, hit_pct, range_lo, range_hi}"""
        lo, hi = self.kb_range
        total = sum(self._note_dist.values())
        hit = 0
        miss = 0
        used_notes = []
        for pitch, cnt in self._note_dist.items():
            dp = pitch + self._transpose
            if lo <= dp <= hi:
                hit += cnt
                used_notes.append(dp)
            else:
                miss += cnt
        return {
            'total': total,
            'hit': hit,
            'miss': miss,
            'hit_pct': (hit / total * 100) if total > 0 else 0,
            'range_lo': min(used_notes) if used_notes else lo,
            'range_hi': max(used_notes) if used_notes else hi,
        }

    # ---------- 绘制 ----------

    def _full_draw(self):
        try:
            self.delete('all')
        except Exception:
            return

        # 使用实际渲染宽度，若还未布局则延迟重试
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            self.after(30, self._full_draw)
            return
        if w != self._canvas_w or h != self._canvas_h:
            self._canvas_w = w
            self._canvas_h = h
            self._compute_layout()

        C = self.C
        self.configure(bg=C.PIANO_BG)

        lo, hi = self.kb_range

        # ---- 白键 ----
        for n in range(lo, hi + 1):
            if n not in self._keys or self._keys[n]['is_black']:
                continue
            kr = self._keys[n]
            x, y, w, h = kr['x'], kr['y'], kr['w'], kr['h']
            # 判断该键上是否有歌曲音符 (经移调)
            orig = n - self._transpose  # 原始 MIDI 音符
            cnt = self._note_dist.get(orig, 0)
            if cnt > 0:
                # 命中 — 绿色渐变 (必须 clamp 到 0-255)
                t = min(1.0, cnt / max(self._max_count * 0.3, 1))
                r = max(0, min(255, int(0xDC * (1 - t * 0.35) + 0x30 * t * 0.35)))
                g = max(0, min(255, int(0xDC * (1 - t * 0.15) + 0xFF * t * 0.5)))
                b = max(0, min(255, int(0xE0 * (1 - t * 0.35) + 0x58 * t * 0.35)))
                fill = f'#{r:02x}{g:02x}{b:02x}'
            else:
                fill = C.PIANO_WHITE
            self.create_rectangle(x, y, x + w, y + h,
                                  fill=fill, outline=C.BORDER, width=1)
            # C 标注
            if n % 12 == 0:
                octave = n // 12 - 1
                self.create_text(x + w / 2, h - 10, text=f'C{octave}',
                                 font=('Segoe UI', 7), fill=C.TEXT_DIM)

        # ---- 黑键 ----
        for n in range(lo, hi + 1):
            if n not in self._keys or not self._keys[n]['is_black']:
                continue
            kr = self._keys[n]
            x, y, w, h = kr['x'], kr['y'], kr['w'], kr['h']
            orig = n - self._transpose
            cnt = self._note_dist.get(orig, 0)
            if cnt > 0:
                fill = '#2E6E4E'  # 深绿色黑键
            else:
                fill = C.PIANO_BLACK
            self.create_rectangle(x, y, x + w, y + h,
                                  fill=fill, outline='#111113', width=1)

        # ---- 音符密度条 ----
        for orig_pitch, cnt in self._note_dist.items():
            dp = orig_pitch + self._transpose
            if dp not in self._keys:
                continue
            kr = self._keys[dp]
            x, w = kr['x'], kr['w']
            intensity = min(1.0, cnt / max(self._max_count * 0.4, 1))
            bar_h = max(3, int(18 * intensity))
            color = C.ACCENT_GREEN

            if kr['is_black']:
                by = kr['h'] - bar_h - 2
                self.create_rectangle(x + 2, by, x + w - 2, by + bar_h,
                                      fill=color, outline='')
            else:
                by = self._bk_h + 6
                self.create_rectangle(x + 2, by, x + w - 2, by + bar_h,
                                      fill=color, outline='')

        # ---- 范围外音符指示 (红色边缘标记) ----
        left_miss = 0
        right_miss = 0
        for orig_pitch, cnt in self._note_dist.items():
            dp = orig_pitch + self._transpose
            if dp < lo:
                left_miss += cnt
            elif dp > hi:
                right_miss += cnt

        if left_miss > 0:
            self.create_rectangle(0, 0, 6, self._canvas_h,
                                  fill=C.ACCENT_RED, outline='')
            self.create_text(10, 12, text=f'↙{left_miss}',
                             font=('Segoe UI', 7, 'bold'), fill=C.ACCENT_RED, anchor='w')
        if right_miss > 0:
            self.create_rectangle(self._canvas_w - 6, 0, self._canvas_w, self._canvas_h,
                                  fill=C.ACCENT_RED, outline='')
            self.create_text(self._canvas_w - 10, 12, text=f'{right_miss}↗',
                             font=('Segoe UI', 7, 'bold'), fill=C.ACCENT_RED, anchor='e')

        # ---- 命中范围覆盖指示条 (顶部蓝色条) ----
        stats = self.get_hit_stats()
        if stats['total'] > 0 and stats['hit'] > 0:
            rlo = stats['range_lo']
            rhi = stats['range_hi']
            if rlo in self._keys and rhi in self._keys:
                sx = self._keys[rlo]['x']
                ex = self._keys[rhi]['x'] + self._keys[rhi]['w']
                self.create_rectangle(sx, 0, ex, 4,
                                      fill=C.ACCENT_BLUE, outline='')

    # ---------- 拖拽交互 ----------

    def _note_at_x(self, x: float) -> int:
        best = self.kb_range[0]
        best_d = float('inf')
        for n, kr in self._keys.items():
            cx = kr['x'] + kr['w'] / 2
            d = abs(cx - x)
            if d < best_d:
                best_d = d
                best = n
        return best

    def _on_press(self, event):
        self._dragging = True
        self._drag_start_x = event.x
        self._drag_start_transpose = self._transpose

    def _on_drag(self, event):
        if not self._dragging:
            return
        dx = event.x - self._drag_start_x
        # 每个白键宽度约等于1个全音(2半音), 但我们按像素计算半音移动
        if self._wk_w > 0:
            # 大约 7 白键 = 12 半音, 所以 1白键 ≈ 12/7 半音
            semitones_per_px = (12.0 / 7.0) / self._wk_w
            delta = int(round(dx * semitones_per_px))
        else:
            delta = 0

        new_t = self._drag_start_transpose + delta
        if new_t != self._transpose:
            self._transpose = new_t
            self._full_draw()
            if self.on_transpose_change:
                self.on_transpose_change(new_t)

    def _on_release(self, event):
        self._dragging = False

    def _on_resize(self, event):
        new_w = event.width
        new_h = event.height
        if new_w > 1 and (new_w != self._canvas_w or new_h != self._canvas_h):
            self._canvas_w = new_w
            self._canvas_h = new_h
            self._compute_layout()
            self._full_draw()


# ==================== 钢琴卷帘窗控件 ====================

class PianoRollWidget(tk.Frame):
    """
    DAW 风格钢琴卷帘窗
      - 左侧钢琴键 (固定宽度, 随主卷帘垂直滚动同步)
      - 右侧音符卷帘 (双向可滚动, Ctrl+滚轮缩放)
      - 不同通道用不同颜色
      - 播放头实时更新
    """

    PK_W = 52      # 左侧键盘宽度
    ROW_H = 14     # 每个半音行高
    SEC_W = 60     # 每秒宽度 (基准, 受缩放影响)

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.C = _get_colors()
        self._notes: List[Tuple] = []   # (pitch, start_sec, end_sec, ch)
        self._duration = 0.0
        self._ch_colors: Dict[int, str] = {}
        self._ch_visible: Dict[int, bool] = {}
        self._zoom = 1.0
        self._lo = 21
        self._hi = 108
        self._total_w = 800
        self._total_h = 600
        self._playhead_sec = -1.0          # -1 = 不显示
        self.on_note_click: Optional[callable] = None    # (ch) 单击通道回调 (未使用, 保留兼容)
        self.on_delete_selected: Optional[callable] = None  # (channels: Set[int]) 删除选中回调
        # 拖拽框选状态
        self._drag_start: Optional[Tuple[float, float]] = None  # canvas 坐标
        self._drag_rect_id = None
        # 拖拽时框内预选音符（橙色高亮，松开后转为确认选中）
        self._drag_preview_notes: Set[Tuple] = set()
        # 选中的音符 (note 元组的集合)
        self._selected_notes: Set[Tuple] = set()
        # 是否已完成首次滚动定位
        self._initial_scroll_done = False
        self._build()

    def _build(self):
        C = self.C
        self.configure(bg=C.BG_DARK)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # 左侧钢琴键 canvas
        self._pk = tk.Canvas(self, bg='#1C1C1E', width=self.PK_W,
                             highlightthickness=0)
        self._pk.grid(row=0, column=0, sticky='ns')

        # 主卷帘 canvas
        self._rc = tk.Canvas(self, bg=C.BG_DARK, highlightthickness=0)
        self._rc.grid(row=0, column=1, sticky='nsew')

        # 滚动条
        self._vs = tk.Scrollbar(self, orient=tk.VERTICAL,
                                command=self._yscroll_both)
        self._vs.grid(row=0, column=2, sticky='ns')
        self._hs = tk.Scrollbar(self, orient=tk.HORIZONTAL,
                                command=self._rc.xview)
        self._hs.grid(row=1, column=1, sticky='ew')

        self._rc.configure(xscrollcommand=self._hs.set,
                           yscrollcommand=self._ys_set)

        # 绑定
        self._rc.bind('<Configure>', lambda e: self._redraw())
        self._rc.bind('<MouseWheel>', self._on_wheel)
        self._rc.bind('<Control-MouseWheel>', self._on_zoom)
        self._rc.bind('<ButtonPress-1>', self._on_mouse_down)
        self._rc.bind('<B1-Motion>', self._on_drag)
        self._rc.bind('<ButtonRelease-1>', self._on_mouse_up)
        self._pk.bind('<MouseWheel>', self._on_wheel)
        # 键盘: 删除选中 / 取消选中
        self._rc.bind('<Delete>', self._on_key_delete)
        self._rc.bind('<BackSpace>', self._on_key_delete)
        self._rc.bind('<Escape>', self._on_key_escape)

    # --- 滚动同步 ---

    def _yscroll_both(self, *args):
        self._rc.yview(*args)
        frac = self._rc.yview()
        self._pk.yview_moveto(frac[0])

    def _ys_set(self, first, last):
        self._vs.set(first, last)
        self._pk.yview_moveto(float(first))

    def _on_wheel(self, event):
        self._rc.yview_scroll(int(-1 * event.delta / 120), 'units')
        frac = self._rc.yview()
        self._pk.yview_moveto(frac[0])

    def _on_zoom(self, event):
        self._zoom *= 1.15 if event.delta > 0 else 0.87
        self._zoom = max(0.1, min(20.0, self._zoom))
        self._redraw()

    def _on_mouse_down(self, event):
        """鼠标按下：将焦点转到 canvas，记录拖拽起点"""
        self._rc.focus_set()
        cx = self._rc.canvasx(event.x)
        cy = self._rc.canvasy(event.y)
        self._drag_start = (cx, cy)
        self._drag_rect_id = None

    def _on_drag(self, event):
        """鼠标拖拽：绘制选择矩形，并实时将框内音符高亮为橙色"""
        if self._drag_start is None:
            return
        cx = self._rc.canvasx(event.x)
        cy = self._rc.canvasy(event.y)
        x0, y0 = self._drag_start
        # 超过 5 像素才算拖拽
        if abs(cx - x0) < 5 and abs(cy - y0) < 5:
            return
        if self._drag_rect_id:
            self._rc.delete(self._drag_rect_id)
        # 无填充（透明），只显示虚线轮廓，避免遮挡音符
        self._drag_rect_id = self._rc.create_rectangle(
            x0, y0, cx, cy,
            outline='#FFD60A', fill='',
            width=2, tags='sel_rect', dash=(6, 3))
        # 实时计算框内音符 → 橙色预览
        if self._notes and self._total_w > 0 and self._duration > 0:
            lo, hi = self._lo, self._hi
            n_rows = hi - lo + 1
            rx0, rx1 = min(x0, cx), max(x0, cx)
            ry0, ry1 = min(y0, cy), max(y0, cy)
            t0_sel = rx0 / self._total_w * self._duration
            t1_sel = rx1 / self._total_w * self._duration
            row0 = int(ry0 // self.ROW_H)
            row1 = int(ry1 // self.ROW_H)
            pitch_hi = hi - max(0, row0)
            pitch_lo = hi - min(n_rows - 1, row1)
            new_preview: Set[Tuple] = set()
            for note in self._notes:
                pitch, start, end, ch = note
                if (pitch_lo <= pitch <= pitch_hi
                        and start < t1_sel and end > t0_sel
                        and self._ch_visible.get(ch, True)):
                    new_preview.add(note)
            if new_preview != self._drag_preview_notes:
                self._drag_preview_notes = new_preview
                self._update_note_colors()

    def _on_mouse_up(self, event):
        """鼠标释放：判断单击 or 框选结束"""
        if self._drag_start is None:
            return
        cx = self._rc.canvasx(event.x)
        cy = self._rc.canvasy(event.y)
        x0, y0 = self._drag_start
        dx, dy = abs(cx - x0), abs(cy - y0)

        # 清理选择矩形
        if self._drag_rect_id:
            self._rc.delete(self._drag_rect_id)
            self._drag_rect_id = None
        self._drag_start = None
        # 清除拖拽预览（松开后转为真正选中）
        self._drag_preview_notes.clear()

        if dx < 5 and dy < 5:
            # 单击：走原始通道检测逻辑
            self._on_single_click(cx, cy)
        else:
            # 框选：收集矩形内的所有通道
            self._on_box_select(min(x0, cx), min(y0, cy),
                                max(x0, cx), max(y0, cy))

    def _on_single_click(self, cx: float, cy: float):
        """单击音符 → 选中标记（中间态，红色），再次单击取消选中"""
        if not self._notes or self._total_w <= 0 or self._duration <= 0:
            return
        hit = self._find_note_at(cx, cy)
        if hit is not None:
            if hit in self._selected_notes:
                self._selected_notes.discard(hit)
            else:
                self._selected_notes.add(hit)
        else:
            # 点击空白处 → 清除选中
            self._selected_notes.clear()
        self._update_note_colors()

    def _find_note_at(self, cx: float, cy: float) -> Optional[Tuple]:
        """返回指定 canvas 坐标处最小范围内的音符元组，找不到返回 None"""
        lo, hi = self._lo, self._hi
        n_rows = hi - lo + 1
        row_idx = int(cy // self.ROW_H)
        if row_idx < 0 or row_idx >= n_rows:
            return None
        click_pitch = hi - row_idx
        click_t = cx / self._total_w * self._duration
        # 精确命中
        for note in self._notes:
            pitch, start, end, ch = note
            if pitch == click_pitch and start <= click_t <= end:
                return note
        # 同音高最近音符
        best, best_dist = None, float('inf')
        tol = self._duration * 0.05
        for note in self._notes:
            pitch, start, end, ch = note
            if pitch == click_pitch:
                d = min(abs(start - click_t), abs(end - click_t))
                if d < best_dist and d < tol:
                    best_dist, best = d, note
        return best

    def _on_box_select(self, rx0: float, ry0: float,
                       rx1: float, ry1: float):
        """框选区域内的所有音符 → 加入选中集（Shift）/ 替换选中集"""
        if not self._notes or self._total_w <= 0 or self._duration <= 0:
            return
        lo, hi = self._lo, self._hi
        n_rows = hi - lo + 1
        t0_sel = rx0 / self._total_w * self._duration
        t1_sel = rx1 / self._total_w * self._duration
        row0 = int(ry0 // self.ROW_H)
        row1 = int(ry1 // self.ROW_H)
        pitch_hi = hi - max(0, row0)
        pitch_lo = hi - min(n_rows - 1, row1)
        # 替换选中集
        self._selected_notes.clear()
        for note in self._notes:
            pitch, start, end, ch = note
            if (pitch_lo <= pitch <= pitch_hi
                    and start < t1_sel and end > t0_sel
                    and self._ch_visible.get(ch, True)):
                self._selected_notes.add(note)
        self._update_note_colors()

    def _update_note_colors(self, prev_ph: float = -1.0):
        """不重绘背景，只更新音符方块颜色。
        颜色优先级：拖拽预览(橙) > 确认选中(黄) > 已播放(琥珀) > 默认(蓝)
        prev_ph: 上一帧播放头位置。当 >= 0 时启用增量模式，仅更新状态变化的音符。"""
        ph = self._playhead_sec
        for i, note in enumerate(self._notes):
            pitch, start, end, ch = note
            if not self._ch_visible.get(ch, True):
                continue
            is_drag_preview = note in self._drag_preview_notes
            is_selected = note in self._selected_notes
            is_past = ph > 0 and start < ph
            # 增量优化：跳过颜色未发生变化的音符
            if prev_ph >= 0 and not is_selected and not is_drag_preview:
                was_past = prev_ph > 0 and start < prev_ph
                if was_past == is_past:
                    continue  # 状态未变，无需重绘
            tag = f'note_{i}'
            if is_drag_preview:
                color = '#FF8800'  # 拖拽框内预选 = 橙色
            elif is_selected:
                color = '#FFD60A'  # 确认选中 = 黄色
            elif is_past:
                color = '#FF9F0A'  # 已播放 = 琥珀色
            else:
                color = '#4488FF'  # 默认 = 蓝色
            try:
                self._rc.itemconfigure(tag, fill=color)
            except Exception:
                pass

    def _on_key_delete(self, event=None):
        """删除键：从卷帘中移除选中的音符（不影响通道开关）"""
        if not self._selected_notes:
            return
        deleted = set(self._selected_notes)
        # 从 _notes 列表中移除选中音符
        self._notes = [n for n in self._notes if n not in deleted]
        self._selected_notes.clear()
        self._redraw()
        # 通知外部（可选，用于回调方更新状态）
        if self.on_delete_selected:
            try:
                self.on_delete_selected(deleted)
            except Exception:
                pass

    def _on_key_escape(self, event=None):
        """退出键：取消选中"""
        if self._selected_notes:
            self._selected_notes.clear()
            self._update_note_colors()

    # --- 数据接口 ---

    def load_midi(self, midi_path: str, ch_colors: Dict[int, str]):
        """解析 MIDI 文件, 提取所有通道的音符"""
        if not midi_path or not os.path.exists(midi_path):
            return
        try:
            mid = mido.MidiFile(midi_path)
            self._duration = mid.length if mid.length > 0 else 1.0
            tempo = 500000
            tpb = mid.ticks_per_beat
            active: Dict[Tuple, float] = {}
            t = 0.0
            notes = []
            for msg in mido.merge_tracks(mid.tracks):
                dt = mido.tick2second(msg.time, tpb, tempo)
                t += dt
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
                elif msg.type == 'note_on' and msg.velocity > 0:
                    active[(msg.channel, msg.note)] = t
                elif msg.type in ('note_off', 'note_on'):
                    key = (msg.channel, msg.note)
                    if key in active:
                        s = active.pop(key)
                        notes.append((msg.note, s, t, msg.channel))
            for (ch, note), s in active.items():
                notes.append((note, s, self._duration, ch))
            self._notes = notes
            self._ch_colors = ch_colors
            self._ch_visible = {ch: True for ch in ch_colors}
            if notes:
                pitches = [n[0] for n in notes]
                self._lo = max(0, (min(pitches) // 12) * 12)
                self._hi = min(127, (max(pitches) // 12 + 1) * 12 - 1)
            self._redraw()
        except Exception as e:
            print(f'[PianoRoll] 加载失败: {e}')

    def set_channel_visible(self, ch: int, visible: bool):
        self._ch_visible[ch] = visible
        self._redraw()

    def set_playhead(self, sec: float):
        prev_ph = self._playhead_sec
        self._playhead_sec = sec
        if self._duration <= 0 or self._total_w <= 0:
            return
        self._rc.delete('playhead')
        x = sec / self._duration * self._total_w
        self._rc.create_line(x, 0, x, self._total_h,
                             fill='#00AAFF', width=2, tags='playhead')
        # 增量更新音符颜色（仅重绘状态发生变化的音符）
        self._update_note_colors(prev_ph=prev_ph)
        # 自动滚动到播放头附近
        cw = self._rc.winfo_width()
        if cw > 0:
            x_frac = x / self._total_w
            view = self._rc.xview()
            view_w = view[1] - view[0]
            # 当播放头接近右边 20% 时自动向前滚动
            if x_frac > view[1] - 0.05 or x_frac < view[0]:
                new_left = max(0.0, x_frac - view_w * 0.2)
                self._rc.xview_moveto(new_left)

    # --- 绘制 ---

    def _redraw(self):
        if not self._notes:
            return
        C = self.C
        lo, hi = self._lo, self._hi
        n_rows = hi - lo + 1
        total_h = n_rows * self.ROW_H
        total_w = max(400, int(self._duration * self.SEC_W * self._zoom))
        self._total_w = total_w
        self._total_h = total_h

        self._rc.configure(scrollregion=(0, 0, total_w, total_h))
        self._pk.configure(scrollregion=(0, 0, self.PK_W, total_h))
        self._rc.delete('all')
        self._pk.delete('all')

        # ---- 背景行 ----
        for i in range(n_rows):
            pitch = hi - i
            pc = pitch % 12
            bg = '#242426' if pc in BLACK_PC else '#2A2A2C'
            self._rc.create_rectangle(0, i * self.ROW_H, total_w,
                                      (i + 1) * self.ROW_H,
                                      fill=bg, outline='')
            if pitch % 12 == 0:   # 每个C画横线
                self._rc.create_line(0, i * self.ROW_H, total_w,
                                     i * self.ROW_H, fill='#3A3A3F')

        # ---- 小节线/秒线 ----
        step = max(1, int(4 / self._zoom)) if self._zoom < 4 else 1
        for sec in range(0, int(self._duration) + 1, step):
            x = sec / self._duration * total_w
            lc = '#404048' if sec % 4 == 0 else '#303034'
            self._rc.create_line(x, 0, x, total_h, fill=lc)
            if sec % 4 == 0 and self._zoom >= 0.3:
                self._rc.create_text(x + 2, 4, text=f'{sec}s',
                                     fill='#555560', anchor='nw',
                                     font=('Segoe UI', 7))

        # ---- 音符 ----
        dur = self._duration
        ph = self._playhead_sec
        for i, (pitch, start, end, ch) in enumerate(self._notes):
            if not self._ch_visible.get(ch, True):
                continue
            row = hi - pitch
            if row < 0 or row >= n_rows:
                continue
            x0 = start / dur * total_w
            x1 = max(x0 + 2, end / dur * total_w)
            y0 = row * self.ROW_H + 1
            y1 = (row + 1) * self.ROW_H - 1
            note = (pitch, start, end, ch)
            if note in self._drag_preview_notes:
                color = '#FF8800'  # 拖拽框内预选 = 橙色
            elif note in self._selected_notes:
                color = '#FFD60A'  # 确认选中 = 黄色
            elif ph > 0 and start < ph:
                color = '#FF9F0A'  # 已播放 = 琥珀色
            else:
                color = '#4488FF'  # 默认 = 蓝色
            self._rc.create_rectangle(x0, y0, x1, y1,
                                      fill=color, outline='',
                                      tags=(f'note_{i}', 'note'))

        # ---- 左侧钢琴键 ----
        for i in range(n_rows):
            pitch = hi - i
            pc = pitch % 12
            ry = i * self.ROW_H
            if pc in BLACK_PC:
                fill, tc = '#2A2A2E', '#888'
            else:
                fill, tc = '#D8D8DC', '#444'
            self._pk.create_rectangle(0, ry, self.PK_W - 1,
                                      ry + self.ROW_H - 1,
                                      fill=fill, outline='#555')
            if pc == 0:
                self._pk.create_text(self.PK_W // 2, ry + self.ROW_H // 2,
                                     text=note_name(pitch),
                                     font=('Segoe UI', 7), fill=tc)

        # 初始滚动: 只在首次加载时滚到音符集中的中间区域
        if self._notes and not self._initial_scroll_done:
            pitches = [n[0] for n in self._notes]
            mid_p = (min(pitches) + max(pitches)) / 2
            frac = max(0.0, min(0.9, (hi - mid_p) / n_rows - 0.3))
            self._rc.yview_moveto(frac)
            self._pk.yview_moveto(frac)
            self._initial_scroll_done = True

        # 保持播放头
        if self._playhead_sec >= 0 and self._duration > 0:
            x = self._playhead_sec / self._duration * self._total_w
            self._rc.create_line(x, 0, x, self._total_h,
                                 fill='#00AAFF', width=2, tags='playhead')


# ==================== MIDI 通道分析器 ====================

# GM 乐器族 → (中文名, 推荐分加成)
_GM_FAMILY_SCORE: List[Tuple[str, int]] = [
    ('钢琴',   +30),   # 0-7   Acoustic & Electric Pianos
    ('色彩打击乐', +8),  # 8-15  Chromatic Perc
    ('风琴',   +15),   # 16-23  Organ
    ('吉他',   +15),   # 24-31  Guitar
    ('贝斯',   -20),   # 32-39  Bass (低音区, 钢琴较难覆盖)
    ('弦乐',   +20),   # 40-47  Strings
    ('合唱/合奏', +8),  # 48-55  Ensemble
    ('铜管',   +10),   # 56-63  Brass
    ('木管',   +18),   # 64-71  Reed / Woodwind
    ('长笛/箫', +15),  # 72-79  Pipe
    ('合成主音', +12), # 80-87  Synth Lead
    ('合成衬垫', -8),  # 88-95  Synth Pad
    ('合成效果', -20), # 96-103 Synth Effects
    ('民族乐器', +5),  # 104-111 Ethnic
    ('打击乐',  -30),  # 112-119 Percussive
    ('音效',   -40),   # 120-127 Sound Effects
]


class MIDIAnalyzer:
    """
    分析 MIDI 各通道，为每个通道生成推荐分数和推荐理由。

    scoring 方法:
      - 乐器族基础分 (GM program_change)
      - 通道 10 = 打击乐 → 重罚
      - 音高区域 (均值在可演奏范围内加分)
      - 音符数 (太少或太多均减分)
      - 音域宽度 (旋律线通常有较宽音程)
    """

    RECOMMEND_THRESHOLD = 20  # 分数到此推荐开启

    def __init__(self, midi_path: str):
        self.midi_path = midi_path
        self._ch_info: Dict[int, dict] = {}   # {ch: {...}}
        self._parse()

    def _parse(self):
        """解析 MIDI 文件，收集每通道信息"""
        try:
            mid = mido.MidiFile(self.midi_path)
        except Exception as e:
            print(f"[MIDIAnalyzer] 解析失败: {e}")
            return

        tempo = 500000
        tpb = mid.ticks_per_beat

        ch_notes: Dict[int, List[int]] = {}      # ch → [pitch, ...]
        ch_program: Dict[int, int] = {}          # ch → last program
        ch_nd_times: Dict[int, List[float]] = {} # ch → [note_on times]
        active: Dict[Tuple, float] = {}
        t = 0.0

        for msg in mido.merge_tracks(mid.tracks):
            dt = mido.tick2second(msg.time, tpb, tempo)
            t += dt
            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type == 'program_change':
                ch_program[msg.channel] = msg.program
            elif msg.type == 'note_on' and msg.velocity > 0:
                ch = msg.channel
                ch_notes.setdefault(ch, []).append(msg.note)
                ch_nd_times.setdefault(ch, []).append(t)

        total_dur = mid.length or 1.0
        for ch, notes in ch_notes.items():
            pitches = notes
            n = len(pitches)
            pmin = min(pitches) if pitches else 60
            pmax = max(pitches) if pitches else 60
            pmean = sum(pitches) / n if pitches else 60
            program = ch_program.get(ch, 0)
            # 通道 9 (0-indexed) = MIDI 打击乐
            is_drum = (ch == 9)
            density = n / total_dur   # notes/sec
            self._ch_info[ch] = dict(
                note_count=n,
                pitch_min=pmin,
                pitch_max=pmax,
                pitch_mean=pmean,
                pitch_range=pmax - pmin,
                program=program,
                is_drum=is_drum,
                density=density,
            )

    def analyze(self) -> Dict[int, dict]:
        """
        返回各通道分析结果:
          {ch: {'score': float, 'recommended': bool,
                'reason': str, 'family': str}}
        """
        results = {}
        for ch, info in self._ch_info.items():
            score, reasons = self._score_channel(ch, info)
            recommended = score >= self.RECOMMEND_THRESHOLD
            results[ch] = {
                'score': score,
                'recommended': recommended,
                'reason': '；'.join(reasons) if reasons else '无特殊信息',
                'family': _GM_FAMILY_SCORE[info['program'] // 8][0]
                           if not info['is_drum'] else '打击乐',
            }
        return results

    def _score_channel(self, ch: int, info: dict) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []

        # 打击乐通道
        if info['is_drum']:
            score -= 100
            reasons.append('MIDI打击乐通道 (♩)')
            return score, reasons

        # 乐器族
        fam_idx = min(15, info['program'] // 8)
        fam_name, fam_bonus = _GM_FAMILY_SCORE[fam_idx]
        score += fam_bonus
        if fam_bonus > 10:
            reasons.append(f'乐器: {fam_name} (+{fam_bonus})')
        elif fam_bonus < 0:
            reasons.append(f'乐器: {fam_name} ({fam_bonus})')

        # 音符数
        n = info['note_count']
        if n >= 100:
            score += 15; reasons.append(f'音符多({n}个)')
        elif n >= 30:
            score += 10; reasons.append(f'音符适中({n}个)')
        elif n >= 8:
            score += 5
        else:
            score -= 15; reasons.append(f'音符少({n}个)')

        # 音高均值 (C3=48, B5=83 为最佳演奏区间)
        pm = info['pitch_mean']
        if 48 <= pm <= 83:
            score += 20; reasons.append('音高居中(适合弹奏)')
        elif 36 <= pm < 48:
            score += 5; reasons.append('偏低音区')
        elif 83 < pm <= 96:
            score += 8; reasons.append('偏高音区')
        else:
            score -= 10; reasons.append('音域极端')

        # 音域宽度
        pr = info['pitch_range']
        if pr >= 24:
            score += 15; reasons.append(f'音域宽({pr}半音 ≥ 2八度)')
        elif pr >= 12:
            score += 8
        else:
            score -= 8; reasons.append(f'音域窄({pr}半音)')

        # 密度
        d = info['density']
        if 0.5 <= d <= 15:
            score += 5   # 合理密度
        elif d > 30:
            score -= 5   # 过于密集 (可能是和弦填充)

        return score, reasons


# ==================== MIDI 控制器对话框 ====================

class MIDIControllerDialog(tk.Toplevel):
    """
    MIDI 控制器弹出窗口

    功能：
    - 通道开关 / 乐器显示 / 分通道移调
    - 钢琴键盘可视化 + 命中范围 + 拖拽移调
    - 内置预览播放器
    - 保存到 MIDI 文件 / 歌曲设置
    """

    def __init__(self, parent, player, settings, midi_path: str = '',
                 on_apply=None):
        super().__init__(parent)

        self.C = _SAOWhiteColors()
        self.player = player
        self.settings = settings
        self.midi_path = midi_path
        self._on_apply = on_apply

        # 预览播放器
        self._preview = MIDIPreviewPlayer()

        # 通道状态 {ch: {'enabled': BoolVar, 'transpose': IntVar}}
        self._ch_vars: Dict[int, dict] = {}

        # 撤销栈
        self._undo_stack: List[dict] = []

        # 智能推荐：分析MIDI通道
        self._rec_results: Dict[int, dict] = {}
        if midi_path and os.path.exists(midi_path):
            try:
                analyzer = MIDIAnalyzer(midi_path)
                self._rec_results = analyzer.analyze()
            except Exception as _e:
                print(f"[推荐] 分析失败: {_e}")

        # 悬停提示窗口
        self._tooltip_win = None
        # 动画循环状态（在 _init_preview 中正式初始化）
        self._anim_running = False

        # 窗口设置
        self.title("MIDI 控制器")
        self.geometry("1280x820")
        self.minsize(900, 600)
        self.resizable(True, True)        # 允许全屏/resize
        self.configure(bg=self.C.BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ttk Notebook 白色主题
        try:
            style = ttk.Style(self)
            style.theme_use('clam')
            style.configure('TNotebook', background=self.C.BG_DARK, borderwidth=0)
            style.configure('TNotebook.Tab', background=self.C.BG_CARD,
                            foreground=self.C.TEXT_PRIMARY,
                            padding=[10, 4], font=('Microsoft YaHei UI', 9))
            style.map('TNotebook.Tab',
                      background=[('selected', self.C.ACCENT_CYAN), ('active', self.C.BG_HOVER)],
                      foreground=[('selected', '#ffffff')])
            style.configure('TPanedwindow', background=self.C.BG_DARK)
        except Exception:
            pass

        self._build_ui()
        self._load_state()

        # 初始化预览
        self.after(200, self._init_preview)

    # ==================== UI 构建 ====================

    def _build_ui(self):
        C = self.C
        # 行配置: 只有第1行 (主区域) 可伸缩
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---- 头部 ----
        hdr = tk.Frame(self, bg=C.BG_CARD, padx=16, pady=8)
        hdr.grid(row=0, column=0, sticky='ew')

        tk.Label(hdr, text="MIDI 控制器", bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                 font=('Microsoft YaHei UI', 14, 'bold')).pack(side=tk.LEFT)

        song_name = os.path.basename(self.midi_path) if self.midi_path else "(未加载)"
        tk.Label(hdr, text=song_name, bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                 font=('Microsoft YaHei UI', 9)).pack(side=tk.RIGHT, padx=16)

        # 键位模式切换（radio buttons，可修改并保存到歌曲设置）
        mode_sys = getattr(self.player, '_mode_system', 'classic')
        self._mode_sys_var = tk.StringVar(value=mode_sys)
        tk.Label(hdr, text="键位:", bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                 font=('Microsoft YaHei UI', 9)).pack(side=tk.RIGHT, padx=(8, 0))
        for val, txt in [('classic', '60键'), ('extended', '88键')]:
            tk.Radiobutton(
                hdr, text=txt, variable=self._mode_sys_var, value=val,
                bg=C.BG_CARD, fg=C.ACCENT_CYAN, selectcolor=C.BG_INPUT,
                activebackground=C.BG_CARD, font=('Microsoft YaHei UI', 9),
                command=self._on_mode_change
            ).pack(side=tk.RIGHT, padx=2)

        # ---- 主区域: 左侧通道面板 | 右侧 Notebook ----
        pw = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                            bg=C.BG_DARK, sashwidth=5,
                            sashrelief=tk.FLAT, handlesize=0)
        pw.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)

        # 左侧通道列表
        ch_outer = tk.Frame(pw, bg=C.BG_DARK)
        pw.add(ch_outer, minsize=230, width=280)
        ch_label = tk.Label(ch_outer, text=" 通道 / 乐器控制 ",
                            bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                            font=('Microsoft YaHei UI', 10, 'bold'),
                            padx=8, pady=4, anchor='w')
        ch_label.pack(fill=tk.X)
        self._build_channel_panel(ch_outer)

        # 右侧: Notebook 含卷帘+键盘两标签
        nb = ttk.Notebook(pw)
        pw.add(nb)

        roll_tab = tk.Frame(nb, bg=C.BG_DARK)
        nb.add(roll_tab, text=" ♩ 音符卷帘 ")
        self._build_roll_panel(roll_tab)

        kb_tab = tk.Frame(nb, bg=C.BG_DARK)
        nb.add(kb_tab, text=" 🎹 键盘视图 ")
        self._build_piano_panel(kb_tab)

        # ---- 预览播放器 ----
        prev_frame = tk.Frame(self, bg=C.BG_CARD, padx=8, pady=4)
        prev_frame.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))
        self._build_preview_panel(prev_frame)

        # ---- 底部按钮 ----
        btn_frame = tk.Frame(self, bg=C.BG_DARK, pady=6)
        btn_frame.grid(row=3, column=0, sticky='ew', padx=8)
        self._build_action_buttons(btn_frame)

    # ---------- 通道控制 ----------

    def _build_channel_panel(self, parent):
        C = self.C
        parent.pack_propagate(True)

        # ---- 标题 + 智能推荐按钮 ----
        hdr_row = tk.Frame(parent, bg=C.BG_DARK)
        hdr_row.pack(fill=tk.X, padx=4, pady=(4, 2))

        tk.Label(hdr_row, text="通道 / 乐器控制", bg=C.BG_DARK,
                 fg=C.TEXT_DIM, font=('Microsoft YaHei UI', 8)
                 ).pack(side=tk.LEFT, padx=2)

        # 一键应用推荐按钮 (仅当有推荐数据时显示)
        if self._rec_results:
            rec_btn = tk.Button(
                hdr_row, text="★ 一键应用推荐",
                command=self._apply_recommendations,
                bg='#5A4FCF', fg=C.TEXT_BRIGHT,
                font=('Microsoft YaHei UI', 8, 'bold'),
                relief=tk.FLAT, padx=6, pady=0)
            rec_btn.pack(side=tk.RIGHT, padx=2)

        # ---- 列标题行 ----
        title_row = tk.Frame(parent, bg=C.BG_DARK)
        title_row.pack(fill=tk.X, padx=4, pady=(0, 2))
        for text, w in [("  ", 3), ("★", 2), ("显示", 4), ("通道", 6), ("乐器", 16),
                        ("音符数", 7), ("移调", 11), ("" * 3, 2)]:
            tk.Label(title_row, text=text, bg=C.BG_DARK, fg=C.TEXT_DIM,
                     font=('Microsoft YaHei UI', 8), width=w, anchor='w'
                     ).pack(side=tk.LEFT)

        # ---- 滚动区 ----
        canvas = tk.Canvas(parent, bg=C.BG_DARK, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=C.BG_DARK)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_scroll(e):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * e.delta / 120), 'units')
            except Exception:
                pass

        canvas.bind_all('<MouseWheel>', _on_scroll, add='+')
        canvas.bind('<Destroy>', lambda e: canvas.unbind_all('<MouseWheel>'))

        channels_info = {}
        instrument_info = {}
        if hasattr(self.player, 'parser') and self.player.parser.notes:
            channels_info = self.player.parser.get_channels_info()
            try:
                instrument_info = self.player.parser.get_instrument_info()
            except Exception:
                pass

        if not channels_info:
            tk.Label(inner, text="请先加载 MIDI 文件",
                     bg=C.BG_DARK, fg=C.TEXT_SECONDARY,
                     font=('Microsoft YaHei UI', 10)).pack(pady=20)
            return

        # 通道对应颜色字典 (PianoRoll 也将使用这个)
        self._ch_colors_map = {}
        for ch in sorted(channels_info.keys()):
            self._ch_colors_map[ch] = CHANNEL_COLORS[ch % len(CHANNEL_COLORS)]

        for ch in sorted(channels_info.keys()):
            info = channels_info[ch]
            inst = instrument_info.get(ch, {})
            inst_name = inst.get('name', '未知乐器')
            color = self._ch_colors_map[ch]
            rec = self._rec_results.get(ch, {})

            row = tk.Frame(inner, bg=C.BG_CARD, padx=4, pady=2)
            row.pack(fill=tk.X, pady=1, padx=2)

            # 彩色色块
            ci = tk.Canvas(row, width=8, height=24,
                           bg=C.BG_CARD, highlightthickness=0)
            ci.create_rectangle(0, 0, 8, 24, fill=color, outline='')
            ci.pack(side=tk.LEFT, padx=(0, 2))

            # 推荐徽章
            if rec:
                star_color = '#FFD60A' if rec['recommended'] else '#555560'
                star_tip = rec.get('reason', '')
                star_lbl = tk.Label(
                    row, text='★', bg=C.BG_CARD, fg=star_color,
                    font=('Segoe UI', 9))
                star_lbl.pack(side=tk.LEFT, padx=(0, 2))
                # 悬停提示
                _tip = star_tip
                star_lbl.bind('<Enter>',
                              lambda e, t=_tip: self._show_tooltip(e, t))
                star_lbl.bind('<Leave>', lambda e: self._hide_tooltip())
            else:
                tk.Label(row, text=' ', bg=C.BG_CARD,
                         width=1).pack(side=tk.LEFT, padx=(0, 2))

            # 卷帘可见性开关 (眼睛图标)
            roll_vis_var = tk.BooleanVar(value=True)
            roll_vis_btn = tk.Checkbutton(
                row, text='👁', variable=roll_vis_var,
                bg=C.BG_CARD, fg=C.TEXT_DIM, selectcolor=color,
                font=('Segoe UI', 9), indicatoron=False,
                width=2, padx=0, pady=0, relief=tk.FLAT,
                command=lambda c=ch, v=roll_vis_var: self._on_roll_vis(c, v))
            roll_vis_btn.pack(side=tk.LEFT, padx=(0, 2))

            # 通道开关
            en_var = tk.BooleanVar(
                value=self.player.mapper.is_channel_enabled(ch))
            tk.Checkbutton(
                row, text=f'CH{ch:>2d}', variable=en_var,
                bg=C.BG_CARD, fg=C.TEXT_PRIMARY, selectcolor=C.BG_INPUT,
                font=('Microsoft YaHei UI', 9, 'bold'), width=5, anchor='w',
                command=lambda c=ch, v=en_var: self._on_ch_toggle(c, v)
            ).pack(side=tk.LEFT)

            # 乐器名 (节省显示)
            disp = inst_name[:14] + '…' if len(inst_name) > 14 else inst_name
            tk.Label(row, text=disp, bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                     font=('Microsoft YaHei UI', 8), width=14, anchor='w'
                     ).pack(side=tk.LEFT, padx=2)

            # 音符数
            tk.Label(row, text=f"{info['note_count']}",
                     bg=C.BG_CARD, fg=C.TEXT_DIM,
                     font=('Microsoft YaHei UI', 8), width=5
                     ).pack(side=tk.LEFT)

            # 移调
            tp_var = tk.IntVar(
                value=self.player.mapper.get_channel_transpose(ch))
            tp_frame = tk.Frame(row, bg=C.BG_CARD)
            tp_frame.pack(side=tk.LEFT, padx=2)
            tk.Label(tp_frame, text='移调', bg=C.BG_CARD,
                     fg=C.TEXT_DIM, font=('Microsoft YaHei UI', 7)
                     ).pack(side=tk.LEFT)
            tk.Spinbox(tp_frame, from_=-48, to=48, width=4,
                       textvariable=tp_var,
                       font=('Microsoft YaHei UI', 8),
                       bg=C.BG_INPUT, fg=C.TEXT_PRIMARY, relief=tk.FLAT
                       ).pack(side=tk.LEFT)

            # 快捷移调按钮
            for label, tgt in [('自动', None), ('高', 'high'),
                                ('中', 'mid'), ('低', 'low')]:
                bc = {'high': '#FF6666', 'mid': C.ACCENT_BLUE,
                      'low': C.ACCENT_GREEN}.get(tgt, C.BTN_SECONDARY)
                tk.Button(row, text=label,
                          command=lambda c=ch, v=tp_var, t=tgt:
                              self._auto_transpose(c, v, t),
                          bg=bc, fg=C.TEXT_BRIGHT,
                          font=('Microsoft YaHei UI', 7), relief=tk.FLAT,
                          width=3, padx=1, pady=0
                          ).pack(side=tk.LEFT, padx=1)

            self._ch_vars[ch] = {'enabled': en_var, 'transpose': tp_var,
                                 'roll_vis': roll_vis_var}

    # ---------- 卷帘面板 ----------

    def _build_roll_panel(self, parent):
        C = self.C
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self.roll = PianoRollWidget(parent, bg=C.BG_DARK)
        self.roll.grid(row=0, column=0, sticky='nsew', padx=2, pady=2)

        # 工具栏: 缩放提示
        bar = tk.Frame(parent, bg=C.BG_CARD, pady=2)
        bar.grid(row=1, column=0, sticky='ew')
        tk.Label(bar, text='Ctrl+滚轮 缩放  |  滚轮 滚动  |  单击音符 选中(红色)  |  拖拽 框选  |  Del 删除选中通道  |  Esc 取消选中',
                 bg=C.BG_CARD, fg=C.TEXT_DIM,
                 font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT, padx=8)

        # 加载音符到卷帘
        if self.midi_path and hasattr(self, '_ch_colors_map'):
            self.roll.load_midi(self.midi_path, self._ch_colors_map)
        elif self.midi_path:
            # ch_colors_map 尚未建, 延迟加载
            self.after(100, self._load_roll_deferred)

        # 删除选中回调
        self.roll.on_delete_selected = self._on_delete_selected

    def _on_ch_toggle(self, ch: int, var: tk.BooleanVar):
        """通道开关切换 → 同步预览播放器"""
        self._push_undo()
        enabled = var.get()
        self._preview.set_channel_mute(ch, not enabled)

    def _on_roll_vis(self, ch: int, var: tk.BooleanVar):
        """钢琴卷帘通道可见性切换"""
        if hasattr(self, 'roll'):
            self.roll.set_channel_visible(ch, var.get())

    def _load_roll_deferred(self):
        """延迟加载卷帘 (等 _ch_colors_map 建立后)"""
        if self.midi_path and hasattr(self, '_ch_colors_map'):
            self.roll.load_midi(self.midi_path, self._ch_colors_map)
        elif self.midi_path and hasattr(self, 'roll'):
            # 构建最基础的颜色映射
            fallback = {i: CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
                        for i in range(16)}
            self.roll.load_midi(self.midi_path, fallback)
        if hasattr(self, 'roll'):
            self.roll.on_delete_selected = self._on_delete_selected

    def _on_delete_selected(self, deleted_notes):
        """卷帘中按 Del 键 → 音符已从 PianoRollWidget._notes 中移除。
        将删除前的状态压栈，使撤销可恢复已删音符。"""
        if not deleted_notes:
            return
        # 构造删除前快照：把已删音符加回当前列表
        snap = self._snapshot()
        current = snap.get('roll_notes') or []
        snap['roll_notes'] = current + list(deleted_notes)
        self._undo_stack.append(snap)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        if hasattr(self, '_undo_btn'):
            self._undo_btn.configure(state=tk.NORMAL)

    def _on_mode_change(self):
        """键位模式切换（60键/88键）"""
        mode = self._mode_sys_var.get()
        if hasattr(self.player, 'set_mode_system'):
            self.player.set_mode_system(mode)
        if hasattr(self, 'piano'):
            self.piano.set_mode(mode)  # PianoKeyboardWidget.set_mode()

    def _apply_recommendations(self):
        """一键应用智能推荐（推荐开启=True，否则关闭）"""
        if not self._rec_results:
            return
        self._push_undo()
        for ch, rec in self._rec_results.items():
            if ch not in self._ch_vars:
                continue
            vs = self._ch_vars[ch]
            new_val = rec['recommended']
            vs['enabled'].set(new_val)
            self._preview.set_channel_mute(ch, not new_val)
            if 'roll_vis' in vs:
                vs['roll_vis'].set(new_val)
            if hasattr(self, 'roll'):
                self.roll.set_channel_visible(ch, new_val)
        # 统计
        on_chs = [ch for ch, r in self._rec_results.items() if r['recommended']]
        off_chs = [ch for ch, r in self._rec_results.items() if not r['recommended']]
        msg = (f"已应用推荐设置\n"
               f"开启通道: {', '.join(f'CH{c}' for c in sorted(on_chs)) or '无'}\n"
               f"关闭通道: {', '.join(f'CH{c}' for c in sorted(off_chs)) or '无'}")
        self._show_msg("★ 推荐已应用", msg)

    # ---------- 悬停提示 ----------

    def _show_tooltip(self, event, text: str):
        """在鼠标位置显示简单文本提示"""
        self._hide_tooltip()
        if not text:
            return
        self._tooltip_win = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{event.x_root + 14}+{event.y_root + 8}')
        lbl = tk.Label(tw, text=text, bg='#2A2A2E', fg='#E5E5EA',
                       font=('Microsoft YaHei UI', 8), padx=6, pady=4,
                       wraplength=260, justify=tk.LEFT,
                       relief=tk.SOLID, borderwidth=1)
        lbl.pack()

    def _hide_tooltip(self):
        if self._tooltip_win:
            try:
                self._tooltip_win.destroy()
            except Exception:
                pass
            self._tooltip_win = None

    def _auto_transpose(self, ch: int, var: tk.IntVar, target: Optional[str]):
        """自动建议移调"""
        self._push_undo()
        notes = [n.note for n in self.player.parser.get_notes_by_channel(ch)]
        if not notes:
            return
        if target is None:
            avg = sum(notes) / len(notes)
            target = 'high' if avg >= 72 else ('mid' if avg >= 60 else 'low')
        suggested = self.player.mapper.suggest_channel_transpose(notes, target)
        var.set(suggested)

    # ---------- 预览播放器 ----------

    def _build_preview_panel(self, parent):
        C = self.C
        row = tk.Frame(parent, bg=C.BG_DARK)
        row.pack(fill=tk.X, pady=4)

        # 播放 / 暂停 / 停止
        self._btn_play = tk.Button(row, text="▶ 播放", command=self._preview_play,
                                   bg=C.ACCENT_GREEN, fg=C.TEXT_BRIGHT,
                                   font=('Microsoft YaHei UI', 9, 'bold'),
                                   relief=tk.FLAT, width=8, padx=4)
        self._btn_play.pack(side=tk.LEFT, padx=4)

        self._btn_pause = tk.Button(row, text="⏸ 暂停", command=self._preview_pause,
                                    bg=C.ACCENT_ORANGE, fg=C.TEXT_BRIGHT,
                                    font=('Microsoft YaHei UI', 9), relief=tk.FLAT,
                                    width=6, state=tk.DISABLED)
        self._btn_pause.pack(side=tk.LEFT, padx=2)

        self._btn_stop = tk.Button(row, text="⏹ 停止", command=self._preview_stop,
                                   bg=C.ACCENT_RED, fg=C.TEXT_BRIGHT,
                                   font=('Microsoft YaHei UI', 9), relief=tk.FLAT,
                                   width=6, state=tk.DISABLED)
        self._btn_stop.pack(side=tk.LEFT, padx=2)

        # 进度条 (Canvas)
        self._prog_canvas = tk.Canvas(
            row, bg='#2A2A2E', height=20,
            highlightthickness=1, highlightbackground='#444448')
        self._prog_canvas.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)
        self._prog_fill = self._prog_canvas.create_rectangle(
            0, 0, 0, 20, fill='#0A84FF', outline='', tags='fill')
        self._prog_head = self._prog_canvas.create_rectangle(
            0, 0, 3, 20, fill='#60CFFF', outline='', tags='head')
        self._prog_canvas.bind('<ButtonPress-1>', self._on_progress_seek)
        self._prog_canvas.bind('<B1-Motion>', self._on_progress_seek)

        # 时间
        self._time_label = tk.Label(row, text="0:00 / 0:00", bg=C.BG_DARK,
                                    fg=C.TEXT_SECONDARY,
                                    font=('Microsoft YaHei UI', 9))
        self._time_label.pack(side=tk.LEFT, padx=4)

        # 后端信息
        self._backend_label = tk.Label(row, text="", bg=C.BG_DARK,
                                       fg=C.TEXT_DIM,
                                       font=('Microsoft YaHei UI', 8))
        self._backend_label.pack(side=tk.RIGHT, padx=4)

        # SoundFont选择按钮
        self._btn_sf = tk.Button(row, text="🎵", command=self._select_soundfont,
                                 bg=C.BTN_SECONDARY, fg=C.TEXT_BRIGHT,
                                 font=('Segoe UI', 10), relief=tk.FLAT,
                                 width=3)
        self._btn_sf.pack(side=tk.RIGHT, padx=2)

        # 一键安装钢琴音源按钮
        self._btn_piano = tk.Button(row, text="🎹 获取钢琴音源",
                                    command=self._setup_piano_sound,
                                    bg='#1A3A1A', fg='#50D058',
                                    font=('Microsoft YaHei UI', 8), relief=tk.FLAT)
        self._btn_piano.pack(side=tk.RIGHT, padx=4)

    def _init_preview(self):
        """异步初始化预览播放器"""
        sf = self.settings.get('soundfont_path', None)
        ok = self._preview.init(sf)
        if ok:
            self._backend_label.configure(
                text=self._preview.backend_name, fg=self.C.ACCENT_GREEN)
        else:
            if self._preview._fs_ok:
                msg = 'FluidSynth就绪 — 点击🎵选择SoundFont(.sf2)以启用高品质'
                self._backend_label.configure(
                    text=msg, fg=self.C.ACCENT_ORANGE)
            elif self._preview._mci_ok:
                # WinMCI 检测到但 init 未被调用 (应该不会发生)
                self._backend_label.configure(
                    text='Windows GS 合成器就绪', fg=self.C.ACCENT_CYAN)
            else:
                self._backend_label.configure(
                    text='Pygame (系统MIDI合成器)', fg=self.C.TEXT_SECONDARY)
        # 进度回调（主线程动画循环负责 UI 更新，线程回调仅保留做兼容）
        self._preview.on_progress = None
        self._preview.on_playback_end = self._on_preview_end
        # 启动主线程动画轮询循环
        self._anim_running = False

    def _select_soundfont(self):
        """选择 SoundFont 文件"""
        path = filedialog.askopenfilename(
            parent=self, title="选择 SoundFont (.sf2)",
            filetypes=[("SoundFont", "*.sf2 *.SF2"), ("所有文件", "*.*")])
        if path:
            self._preview.cleanup()
            ok = self._preview.init(path)
            self._backend_label.configure(text=self._preview.backend_name)
            if ok:
                self.settings.set('soundfont_path', path)

    # ---------- 一键安装钢琴音源 (FluidSynth + GeneralUser GS) ----------

    def _setup_piano_sound(self):
        """弹出确认对话框，在后台线程中下载并安装 FluidSynth + 钢琴音源"""
        import urllib.request, zipfile, io

        # 检查是否已经是 FluidSynth 后端
        if self._preview.backend_name.startswith('FluidSynth'):
            self._show_info("钢琴音源", "已经在使用 FluidSynth 高品质钢琴音源！\n" +
                            f"音源: {self._preview.backend_name}")
            return

        msg = ("将从 GitHub 自动下载并安装：\n"
               "• FluidSynth 2.3.6 合成引擎 (~6 MB)\n"
               "• GeneralUser GS 音源 (~31 MB)\n\n"
               f"安装目录：{_PIANO_FS_BIN_DIR}\n"
               "音源目录：" + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soundfonts') + "\n\n"
               "合计约 37 MB，需要网络连接（可能需要科学上网），\n"
               "点击确定开始下载。")
        try:
            from tkinter import messagebox
            if not messagebox.askokcancel("获取钢琴音源", msg, parent=self):
                return
        except Exception:
            pass

        # 准备目录
        sf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soundfonts')
        os.makedirs(sf_dir, exist_ok=True)
        fs_bin = _PIANO_FS_BIN_DIR

        # 创建进度对话框
        dlg = tk.Toplevel(self)
        dlg.title("安装钢琴音源")
        dlg.configure(bg=self.C.BG_DARK)
        dlg.geometry("420x180")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg, text="正在安装钢琴音源，请稍候……",
                 bg=self.C.BG_DARK, fg=self.C.TEXT_PRIMARY,
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(20, 8))
        status_var = tk.StringVar(value="准备中...")
        tk.Label(dlg, textvariable=status_var, bg=self.C.BG_DARK, fg=self.C.ACCENT_CYAN,
                 font=('Microsoft YaHei UI', 9), wraplength=380).pack(pady=4)
        bar = ttk.Progressbar(dlg, mode='indeterminate', length=360)
        bar.pack(pady=8, padx=20)
        bar.start(12)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # 禁止关闭

        def set_status(msg):
            try:
                self.after(0, lambda: status_var.set(msg))
            except Exception:
                pass

        def run():
            try:
                import urllib.request, zipfile, io

                # ---- Step 1: 下载 FluidSynth ----
                set_status("Step 1/3  下载 FluidSynth (~6 MB)...")
                req = urllib.request.Request(_PIANO_FS_URL,
                    headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    fs_data = r.read()
                if len(fs_data) < 100_000:
                    raise RuntimeError(f"FluidSynth 下载异常 (仅 {len(fs_data)} 字节)，可能是网络问题")

                # ---- Step 2: 解压 DLL 到目标目录 ----
                set_status("Step 2/3  解压 FluidSynth DLL...")
                os.makedirs(fs_bin, exist_ok=True)
                extracted = 0
                with zipfile.ZipFile(io.BytesIO(fs_data)) as zf:
                    for zi in zf.infolist():
                        name = zi.filename
                        if name.lower().endswith('.dll') or name.lower().endswith('.exe'):
                            basename = os.path.basename(name)
                            if not basename:
                                continue
                            dest = os.path.join(fs_bin, basename)
                            with zf.open(zi) as src_f, open(dest, 'wb') as dst_f:
                                dst_f.write(src_f.read())
                            extracted += 1
                if extracted == 0:
                    raise RuntimeError("FluidSynth 压缩包中未找到 DLL 文件")
                print(f"[FluidSynth] 解压 {extracted} 个文件到 {fs_bin}")

                # ---- Step 3: 下载音源 (sf2 直接下载，非 zip) ----
                set_status("Step 3/3  下载 GeneralUser GS 音源 (~31 MB)...")
                sf_path = os.path.join(sf_dir, 'GeneralUser-GS.sf2')
                req_sf = urllib.request.Request(_PIANO_SF_URL,
                    headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_sf, timeout=180) as r:
                    sf_data = r.read()
                if len(sf_data) < 1_000_000:
                    raise RuntimeError(f"音源文件下载异常 (仅 {len(sf_data)} 字节)，可能是网络问题")
                with open(sf_path, 'wb') as f:
                    f.write(sf_data)
                print(f"[FluidSynth] 音源已保存: {sf_path} ({len(sf_data)/1024/1024:.1f} MB)")

                # ---- 重新初始化 FluidSynth ----
                set_status("正在初始化 FluidSynth...")
                ok = self._preview.reinit_fluidsynth(fs_bin, sf_path)

                def finish():
                    try:
                        bar.stop()
                        dlg.destroy()
                        if ok:
                            self._backend_label.configure(
                                text=self._preview.backend_name,
                                fg=self.C.ACCENT_GREEN)
                            self._btn_piano.configure(
                                text="🎹 钢琴音源已就绪", state=tk.DISABLED,
                                bg='#0A2A0A')
                            self.settings.set('soundfont_path', sf_path)
                            self._show_info("安装成功", f"钢琴音源安装完毕！\n音源: {self._preview.backend_name}")
                        else:
                            self._show_info("初始化失败", f"FluidSynth DLL 已安装到:\n{fs_bin}\n"
                                            f"音源文件: {sf_path}\n\n"
                                            "请重启软件后再试，或手动点击 🎵 按钮选择音源文件。")
                    except Exception:
                        pass
                self.after(0, finish)

            except Exception as e:
                def show_err(msg=str(e)):
                    try:
                        bar.stop()
                        dlg.destroy()
                        self._show_info("安装失败",
                            f"下载或安装过程中发生错误：\n{msg}\n\n"
                            "请检查网络连接后重试，或手动下载：\n"
                            f"FluidSynth: {_PIANO_FS_URL}\n"
                            f"音源:       {_PIANO_SF_URL}")
                    except Exception:
                        pass
                self.after(0, show_err)

        threading.Thread(target=run, daemon=True).start()

    def _preview_play(self):
        if not self.midi_path:
            return
        if self._preview.is_paused:
            self._preview.resume()
        else:
            # 同步通道静音
            for ch, vs in self._ch_vars.items():
                self._preview.set_channel_mute(ch, not vs['enabled'].get())
            self._preview.play(self.midi_path)

        self._btn_play.configure(text="▶ 播放中", state=tk.DISABLED)
        self._btn_pause.configure(state=tk.NORMAL)
        self._btn_stop.configure(state=tk.NORMAL)
        self._start_anim_loop()

    def _preview_pause(self):
        if self._preview.is_playing:
            if self._preview.is_paused:
                self._preview.resume()
                self._btn_pause.configure(text="⏸ 暂停")
            else:
                self._preview.pause()
                self._btn_pause.configure(text="▶ 继续")
                self._btn_play.configure(text="▶ 已暂停", state=tk.DISABLED)

    def _on_progress_seek(self, event):
        """点击/拖拽进度条跳转"""
        w = self._prog_canvas.winfo_width()
        if w <= 0 or self._preview.total_time <= 0:
            return
        frac = max(0.0, min(1.0, event.x / w))
        seek_t = frac * self._preview.total_time
        # 更新显示
        self._update_progress_bar(frac * 100)
        # 重启播放 (简单实现: 停止再从指定时间播)
        if self._preview.is_playing or self._preview.is_paused:
            self._preview.stop()
            self._preview.play(self.midi_path, start_time=seek_t)
            self._btn_play.configure(text="▶ 播放中", state=tk.DISABLED)
            self._btn_pause.configure(state=tk.NORMAL)
            self._btn_stop.configure(state=tk.NORMAL)
            self._start_anim_loop()  # 确保动画循环继续运行

    def _update_progress_bar(self, pct: float):
        """更新 Canvas 进度条 (pct 0-100)"""
        try:
            w = self._prog_canvas.winfo_width()
            if w <= 1:
                return
            fill_w = max(0, int(pct / 100 * w))
            self._prog_canvas.coords(self._prog_fill, 0, 0, fill_w, 20)
            self._prog_canvas.coords(self._prog_head,
                                     fill_w - 2, 1, fill_w + 2, 19)
        except Exception:
            pass

    def _preview_stop(self):
        self._stop_anim_loop()
        self._preview.stop()
        self._btn_play.configure(text="▶ 播放", state=tk.NORMAL)
        self._btn_pause.configure(text="⏸ 暂停", state=tk.DISABLED)
        self._btn_stop.configure(state=tk.DISABLED)
        self._update_progress_bar(0)
        self._time_label.configure(text="0:00 / 0:00")
        if hasattr(self, 'roll'):
            self.roll.set_playhead(-1)

    # ---------- 主线程动画轮询循环 (30 fps) ----------

    def _start_anim_loop(self):
        """启动主线程动画循环，以 ~30fps 轮询播放进度，平滑驱动播放头"""
        if self._anim_running:
            return
        self._anim_running = True
        self._anim_tick()

    def _stop_anim_loop(self):
        self._anim_running = False

    def _anim_tick(self):
        """每 33ms 轮询一次播放进度并更新 UI"""
        if not self._anim_running:
            return
        try:
            if self._preview.is_playing or self._preview.is_paused:
                cur = self._preview.current_time
                total = self._preview.total_time
                if total > 0:
                    self._update_progress_ui(cur, total)
        except Exception:
            pass
        if self._anim_running:
            self.after(33, self._anim_tick)

    def _on_preview_progress(self, cur: float, total: float):
        """预览进度回调 (兼容保留，主 UI 更新由 _anim_loop 驱动)"""
        pass  # 动画循环已接管，无需再通过线程回调调度

    def _update_progress_ui(self, cur: float, total: float):
        """在主线程中更新进度 UI"""
        try:
            pct = (cur / total * 100) if total > 0 else 0
            self._update_progress_bar(pct)
            cm, cs = int(cur // 60), int(cur % 60)
            tm, ts = int(total // 60), int(total % 60)
            self._time_label.configure(text=f"{cm}:{cs:02d} / {tm}:{ts:02d}")
            if hasattr(self, 'roll'):
                self.roll.set_playhead(cur)
        except Exception:
            pass

    def _on_preview_end(self):
        """预览播放完毕"""
        try:
            self._stop_anim_loop()
            self.after(0, self._preview_stop)
        except Exception:
            pass

    # ---------- 钢琴键盘 ----------

    def _build_piano_panel(self, parent):
        C = self.C
        mode = getattr(self.player, '_mode_system', 'classic')

        # 钢琴控件
        self.piano = PianoKeyboardWidget(
            parent, mode=mode, width=900, height=130,
            on_transpose_change=self._on_piano_transpose,
            colors=self.C,
            bg=self.C.PIANO_BG)
        self.piano.pack(fill=tk.X, padx=4, pady=4)

        # 统计行
        stat_row = tk.Frame(parent, bg=C.BG_DARK)
        stat_row.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._hit_label = tk.Label(stat_row, text="命中: --", bg=C.BG_DARK,
                                   fg=C.ACCENT_GREEN,
                                   font=('Microsoft YaHei UI', 10, 'bold'))
        self._hit_label.pack(side=tk.LEFT, padx=8)

        self._range_label = tk.Label(stat_row, text="范围: --", bg=C.BG_DARK,
                                     fg=C.ACCENT_CYAN,
                                     font=('Microsoft YaHei UI', 9))
        self._range_label.pack(side=tk.LEFT, padx=8)

        self._transpose_label = tk.Label(stat_row, text="拖拽移调: 0", bg=C.BG_DARK,
                                         fg=C.TEXT_SECONDARY,
                                         font=('Microsoft YaHei UI', 9))
        self._transpose_label.pack(side=tk.LEFT, padx=8)

        hint = tk.Label(stat_row, text="← 拖拽钢琴上的音符分布来调整移调 →",
                        bg=C.BG_DARK, fg=C.TEXT_DIM,
                        font=('Microsoft YaHei UI', 8))
        hint.pack(side=tk.RIGHT, padx=8)

        # 加载音符到钢琴
        if self.player.parser.notes:
            self.piano.set_song_notes(self.player.parser.notes)
            # 使用 user_transpose (用户手动移调), 叠加 auto 八度偏移做可视化
            auto_offset = getattr(self.player, '_key_transpose', 0)
            user_tp = getattr(self.player, '_user_transpose', 0)
            self.piano.set_transpose(auto_offset + user_tp)
            self._update_hit_stats()

    def _on_piano_transpose(self, new_transpose: int):
        """钢琴拖拽改变移调"""
        self._push_undo()
        self._transpose_label.configure(text=f"拖拽移调: {new_transpose:+d}")
        self._update_hit_stats()

    def _update_hit_stats(self):
        stats = self.piano.get_hit_stats()
        pct = stats['hit_pct']
        color = self.C.ACCENT_GREEN if pct >= 80 else (self.C.ACCENT_ORANGE if pct >= 50 else self.C.ACCENT_RED)
        self._hit_label.configure(
            text=f"命中: {stats['hit']}/{stats['total']} ({pct:.0f}%)", fg=color)
        if stats['hit'] > 0:
            self._range_label.configure(
                text=f"范围: {note_name(stats['range_lo'])} - {note_name(stats['range_hi'])}")
        else:
            self._range_label.configure(text="范围: --")

    # ---------- 底部按钮 ----------

    def _build_action_buttons(self, parent):
        C = self.C

        # 右侧按钮
        close_btn = tk.Button(parent, text="关闭", command=self._on_close,
                              bg=C.BTN_SECONDARY, fg=C.TEXT_BRIGHT,
                              font=('Microsoft YaHei UI', 10), relief=tk.FLAT,
                              width=8, padx=6, pady=4)
        close_btn.pack(side=tk.RIGHT, padx=4)

        apply_btn = tk.Button(parent, text="应用设置", command=self._apply,
                              bg=C.BTN_PRIMARY, fg=C.TEXT_BRIGHT,
                              font=('Microsoft YaHei UI', 10, 'bold'), relief=tk.FLAT,
                              width=10, padx=6, pady=4)
        apply_btn.pack(side=tk.RIGHT, padx=4)

        reset_btn = tk.Button(parent, text="重置", command=self._reset,
                              bg=C.BTN_SECONDARY, fg=C.TEXT_BRIGHT,
                              font=('Microsoft YaHei UI', 10), relief=tk.FLAT,
                              width=6, padx=6, pady=4)
        reset_btn.pack(side=tk.RIGHT, padx=4)

        self._undo_btn = tk.Button(parent, text="↩ 撤销",
                                   command=self._undo,
                                   bg='#4A4A52', fg=C.TEXT_BRIGHT,
                                   font=('Microsoft YaHei UI', 10), relief=tk.FLAT,
                                   width=8, padx=6, pady=4,
                                   state=tk.DISABLED)
        self._undo_btn.pack(side=tk.RIGHT, padx=4)

        # 左侧保存按钮
        save_midi_btn = tk.Button(parent, text="💾 保存到MIDI", command=self._save_to_midi,
                                  bg=C.ACCENT_PURPLE, fg=C.TEXT_BRIGHT,
                                  font=('Microsoft YaHei UI', 10), relief=tk.FLAT,
                                  width=14, padx=6, pady=4)
        save_midi_btn.pack(side=tk.LEFT, padx=4)

        save_song_btn = tk.Button(parent, text="📋 保存到歌曲设置",
                                  command=self._save_to_song_settings,
                                  bg=C.ACCENT_ORANGE, fg=C.TEXT_BRIGHT,
                                  font=('Microsoft YaHei UI', 10), relief=tk.FLAT,
                                  width=14, padx=6, pady=4)
        save_song_btn.pack(side=tk.LEFT, padx=4)

    # ==================== 状态管理 ====================

    def _load_state(self):
        """从当前 player/mapper 读取状态"""
        pass  # 构建时已读取

    # ==================== 撤销 ====================

    def _snapshot(self) -> dict:
        """快照当前所有通道+移调状态+钢琴卷帘音符"""
        return {
            'ch': {
                ch: {'enabled': vs['enabled'].get(),
                     'transpose': vs['transpose'].get()}
                for ch, vs in self._ch_vars.items()
            },
            'piano_tp': self.piano.get_transpose() if hasattr(self, 'piano') else 0,
            'roll_notes': list(self.roll._notes) if hasattr(self, 'roll') else None,
        }

    def _push_undo(self):
        """保存撤销快照 (最多保留 50 步)"""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        if hasattr(self, '_undo_btn'):
            self._undo_btn.configure(state=tk.NORMAL)

    def _undo(self):
        """撤销到上一步"""
        if not self._undo_stack:
            return
        state = self._undo_stack.pop()
        for ch, cfg in state['ch'].items():
            if ch in self._ch_vars:
                vs = self._ch_vars[ch]
                vs['enabled'].set(cfg['enabled'])
                vs['transpose'].set(cfg['transpose'])
                # 同步预览播放器
                self._preview.set_channel_mute(ch, not cfg['enabled'])
                # 同步 mapper（应用时生效）
                self.player.mapper.set_channel_enabled(ch, cfg['enabled'])
                self.player.mapper.set_channel_transpose(ch, cfg['transpose'])
                # 同步钢琴卷帘可见性
                if 'roll_vis' in vs:
                    vs['roll_vis'].set(cfg['enabled'])
                if hasattr(self, 'roll'):
                    self.roll.set_channel_visible(ch, cfg['enabled'])
        if hasattr(self, 'piano'):
            self.piano.set_transpose(state['piano_tp'])
            if hasattr(self, '_transpose_label'):
                self._transpose_label.configure(
                    text=f"拖拽移调: {state['piano_tp']:+d}")
            self._update_hit_stats()
        # 恢复钢琴卷帘音符（如果快照中包含）
        if state.get('roll_notes') is not None and hasattr(self, 'roll'):
            self.roll._notes = list(state['roll_notes'])
            self.roll._selected_notes.clear()
            self.roll._redraw()
        if not self._undo_stack:
            self._undo_btn.configure(state=tk.DISABLED)

    def _apply(self):
        """应用所有设置到 player"""
        # 通道设置
        for ch, vs in self._ch_vars.items():
            self.player.mapper.set_channel_enabled(ch, vs['enabled'].get())
            self.player.mapper.set_channel_transpose(ch, vs['transpose'].get())

        # 钢琴键盘拖拽的全局移调 → 仅调整 user_transpose, 不覆盖 mapper.transpose
        piano_transpose = self.piano.get_transpose()
        self.player.set_transpose(piano_transpose)

        # 保存通道设置到全局 settings
        ch_settings = {}
        for ch, vs in self._ch_vars.items():
            ch_settings[str(ch)] = {
                'enabled': vs['enabled'].get(),
                'transpose': vs['transpose'].get(),
            }
        self.settings.set('channel_settings', ch_settings)

        # 回调通知主 GUI
        if self._on_apply:
            self._on_apply({
                'channel_config': ch_settings,
                'global_transpose': piano_transpose,
            })

        self._show_msg("完成", "设置已应用")

    def _reset(self):
        """重置所有设置"""
        self._push_undo()  # 支持撤销重置操作
        self.player.mapper.clear_channel_settings()
        for ch, vs in self._ch_vars.items():
            vs['enabled'].set(True)
            vs['transpose'].set(0)
            # 同步预览播放器和卷帘
            self._preview.set_channel_mute(ch, False)
            self.player.mapper.set_channel_enabled(ch, True)
            self.player.mapper.set_channel_transpose(ch, 0)
            if 'roll_vis' in vs:
                vs['roll_vis'].set(True)
            if hasattr(self, 'roll'):
                self.roll.set_channel_visible(ch, True)
        if hasattr(self, 'piano'):
            self.piano.set_transpose(0)
        self._transpose_label.configure(text="拖拽移调: 0")
        self._update_hit_stats()

    def _save_to_midi(self):
        """保存修改后的 MIDI 文件"""
        if not self.midi_path:
            self._show_msg("提示", "未加载 MIDI 文件")
            return

        # 默认文件名
        base, ext = os.path.splitext(self.midi_path)
        default_name = f"{base}_modified{ext}"

        path = filedialog.asksaveasfilename(
            parent=self, title="保存修改后的 MIDI",
            defaultextension=".mid",
            initialfile=os.path.basename(default_name),
            filetypes=[("MIDI文件", "*.mid *.midi"), ("所有文件", "*.*")])
        if not path:
            return

        try:
            self._do_save_midi(self.midi_path, path)
            self._show_msg("成功", f"已保存到:\n{path}")
        except Exception as e:
            self._show_msg("错误", f"保存失败: {e}")

    def _do_save_midi(self, src: str, dst: str):
        """执行 MIDI 文件保存 (静音 + 移调)"""
        mid = mido.MidiFile(src)
        piano_tp = self.piano.get_transpose()

        for track in mid.tracks:
            for i, msg in enumerate(track):
                if not hasattr(msg, 'channel'):
                    continue
                ch = msg.channel
                vs = self._ch_vars.get(ch)

                # 静音通道
                if vs and not vs['enabled'].get():
                    if msg.type == 'note_on':
                        track[i] = msg.copy(velocity=0)
                    continue

                # 移调
                ch_tp = vs['transpose'].get() if vs else 0
                total_tp = piano_tp + ch_tp
                if total_tp != 0 and msg.type in ('note_on', 'note_off'):
                    new_note = max(0, min(127, msg.note + total_tp))
                    track[i] = msg.copy(note=new_note)

        mid.save(dst)

    def _save_to_song_settings(self):
        """保存当前配置到歌曲设置 (SongSettings)"""
        if not self.midi_path:
            self._show_msg("提示", "未加载 MIDI 文件")
            return

        song_key = os.path.abspath(self.midi_path)
        all_song_settings = self.settings.get('song_settings', {})
        song_data = all_song_settings.get(song_key, {})

        # 通道配置
        ch_cfg = {}
        for ch, vs in self._ch_vars.items():
            ch_cfg[str(ch)] = {
                'enabled': vs['enabled'].get(),
                'transpose': vs['transpose'].get(),
            }
        song_data['channel_config'] = ch_cfg
        song_data['global_transpose'] = self.piano.get_transpose()
        song_data['mode_system'] = getattr(self.player, '_mode_system', 'classic')

        # 命中范围
        stats = self.piano.get_hit_stats()
        song_data['hit_range'] = [stats['range_lo'], stats['range_hi']]

        all_song_settings[song_key] = song_data
        self.settings.set('song_settings', all_song_settings)
        self._show_msg("已保存", f"歌曲设置已保存\n({os.path.basename(self.midi_path)})")

    # ==================== 辅助 ====================

    def _show_msg(self, title: str, msg: str):
        """简单消息窗口"""
        try:
            from gui import ThemedDialog
            ThemedDialog.showinfo(self, title, msg)
        except ImportError:
            from tkinter import messagebox
            messagebox.showinfo(title, msg, parent=self)

    def _on_close(self):
        """关闭窗口"""
        self._stop_anim_loop()
        self._preview.stop()
        self._preview.cleanup()
        self.destroy()


# ==================== 加载歌曲设置 (供 GUI 调用) ====================

def load_song_channel_settings(settings, player, filepath: str) -> bool:
    """
    从 SongSettings 恢复通道配置
    返回 True 如果找到并应用了设置
    """
    if not filepath:
        return False

    song_key = os.path.abspath(filepath)
    all_ss = settings.get('song_settings', {})
    song_data = all_ss.get(song_key, {})

    ch_cfg = song_data.get('channel_config')
    if not ch_cfg:
        return False

    for ch_str, cfg in ch_cfg.items():
        ch = int(ch_str)
        player.mapper.set_channel_enabled(ch, cfg.get('enabled', True))
        player.mapper.set_channel_transpose(ch, cfg.get('transpose', 0))

    # 全局移调 → 仅设置 user_transpose, 不覆盖 mapper.transpose
    gt = song_data.get('global_transpose')
    if gt is not None:
        player.set_transpose(gt)

    # 键位模式
    ms = song_data.get('mode_system')
    if ms and hasattr(player, 'set_mode_system'):
        player.set_mode_system(ms)

    return True
