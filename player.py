# -*- coding: utf-8 -*-
"""
播放器模块 - 负责控制MIDI/JS播放和键盘模拟，支持和弦
"""

import time
import threading
import random
from typing import List, Callable, Optional
from dataclasses import dataclass

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("警告: keyboard模块未安装，将使用pynput")

try:
    from pynput.keyboard import Controller, Key
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

from midi_parser import MidiParser, JSParser, NoteEvent, ChordEvent, PlayEvent, SustainPedalEvent
from keyboard_mapper import KeyboardMapper
from config import (KEY_PRESS_DURATION, MIN_NOTE_INTERVAL, KEY_DURATION_MAX, KEY_DURATION_MIN,
                    VELOCITY_MIN, VELOCITY_SCALE, VELOCITY_DURATION_MIN, VELOCITY_DURATION_MAX,
                    MAX_SIMULTANEOUS_KEYS, TRACK_PRIORITY_MODE, MELODY_PRIORITY,
                    CHORD_PRESERVE_BASS, CHORD_PRESERVE_TOP,
                    MIDI_TO_KEY_SHIFT, SHIFT_TOGGLE_DELAY_MS)


# 人性化设置 - 模拟真人弹奏的微小不确定性
HUMANIZE_ENABLED = True          # 启用人性化
HUMANIZE_TIMING_MS = 30          # 时间偏移范围(毫秒)，±30ms模拟人手的不精确
HUMANIZE_DURATION_RATIO = 0.12   # 时长变化比例(12%)，变化幅度更自然
HUMANIZE_ARPEGGIO_MS = 15        # 琶音延迟(毫秒)，和弦从低到高微微展开，像真人

# === 延音模拟 - 用按键时长做延音，不使用游戏踏板键 ===
# 核心原则：按键时长 = MIDI音符时长 × 缩放，让游戏内置延音自然工作
# 当MIDI踏板踩下时，额外延长按键时长来模拟延音效果
SUSTAIN_ENABLED = True           # 启用延音模式（尊重MIDI音符原始时长）
SUSTAIN_SCALE = 1.45             # 延音缩放系数（基础延长45%，让音符更饱满丰润）
SUSTAIN_MIN_MS = 220             # 最短按键时长(ms)，确保游戏识别且音色饱满
SUSTAIN_MAX_S = 12.0             # 最长按键时长(秒)，允许超长延音自然衰减
SUSTAIN_OVERLAP_MS = 280         # 连音重叠(ms)，充分重叠使音符衔接如歌无断裂

# === MIDI踏板数据 → 按键时长加成 ===
# 不再按空格键切换游戏踏板（容易卡住），改为读取MIDI踏板数据延长按键
SUSTAIN_PEDAL_BOOST = 2.10       # 踏板踩下时按键时长额外乘以此系数（更饱满的延音共鸣）
SUSTAIN_PEDAL_MIN_MS = 500       # 踏板踩下时最短按键时长(ms)，让短音符也有延音感

# === 同键防吞音设置 ===
SAME_KEY_RELEASE_GAP_MS = 35     # 同一个键连续按时，释放后等待的间隔(毫秒)，确保游戏识别
SAME_KEY_REPRESS_MIN_MS = 50     # 同键已按下时允许重新触发的最小间隔(毫秒)

# === 单键速率限制 ===
# 同一个键两次按下的最小间隔(毫秒)，随机 8~12 次/秒
# 每次按下时在此范围内随机选取阈值，模拟人手不稳定性
PER_KEY_MIN_INTERVAL_LOW  = 80    # ≈12次/秒
PER_KEY_MIN_INTERVAL_HIGH = 125   # ≈8次/秒

# === 钢琴家演奏模拟 - 细节化表情处理 ===
# 力度到时长映射：强音符持续更久，弱音符更短促
PIANO_VEL_SUSTAIN_MIN = 0.88     # 最弱力度的时长缩放 (pp)，不过度缩短弱音
PIANO_VEL_SUSTAIN_MAX = 1.30     # 最强力度的时长缩放 (ff)，重音更饱满
# 音区表情差异
PIANO_HIGH_SUSTAIN = 1.25        # 高音旋律充分延长，突出歌唱性与旋律线条
PIANO_MID_SUSTAIN = 1.12         # 中音区微延长，保持温暖饱满
PIANO_LOW_SUSTAIN = 0.85         # 低音根音缩短，避免低音抢戏
# 弹性速度（rubato）：长音符微微拉伸，短音符微微加快
PIANO_RUBATO_ENABLED = True      # 启用弹性速度
PIANO_RUBATO_LONG_STRETCH = 1.22 # 长音符拉伸系数 (>0.5s 的音符)，更有歌唱感
PIANO_RUBATO_SHORT_TIGHTEN = 1.0 # 短音符不缩短（避免游戏吞音）
# 乐句呼吸：乐句结尾稍微渐慢
PIANO_PHRASE_BREATH = True       # 启用乐句呼吸
PIANO_PHRASE_GAP_THRESHOLD = 0.3 # 乐句间隙阈值(秒)，超过此值视为新乐句
PIANO_PHRASE_END_STRETCH = 1.40  # 乐句末尾音符充分拉伸，句尾自然渐慢如呼吸

@dataclass
class PlaybackState:
    """播放状态"""
    is_playing: bool = False
    is_paused: bool = False
    current_time: float = 0.0
    current_event_index: int = 0
    speed: float = 1.0


class KeyboardSimulator:
    """键盘模拟器（支持SHIFT切换扩展音域）"""
    
    def __init__(self):
        self.use_keyboard = KEYBOARD_AVAILABLE
        self.controller = None
        self._active_keys = set()  # 当前按下的键
        self._release_timers = []  # 延迟释放定时器
        self._key_press_gen = {}   # 每个键的按下代数，防止旧的释放线程杀死新的按下
        self._last_press_time = {}  # 每个键上次按下的时间戳，用于速率限制
        self._shift_active = False  # SHIFT模式状态（普通模式=False）
        
        if not KEYBOARD_AVAILABLE and PYNPUT_AVAILABLE:
            self.controller = Controller()
    
    def _do_press(self, key: str):
        """实际按下按键，返回按下代数（用于释放时验证）"""
        now = time.monotonic()
        last = self._last_press_time.get(key, 0.0)
        elapsed_ms = (now - last) * 1000.0
        
        # 同键重复按下时使用更短的间隔阈值，防止快速同音被吞
        if key in self._active_keys:
            if elapsed_ms < SAME_KEY_REPRESS_MIN_MS:
                return 0
        else:
            min_interval = random.uniform(PER_KEY_MIN_INTERVAL_LOW, PER_KEY_MIN_INTERVAL_HIGH)
            if elapsed_ms < min_interval:
                return 0
        
        self._last_press_time[key] = now

        gen = self._key_press_gen.get(key, 0) + 1
        self._key_press_gen[key] = gen
        
        try:
            if key in self._active_keys:
                # 同键重复：先释放，短暂等待让游戏识别，再重新按下
                if self.use_keyboard and KEYBOARD_AVAILABLE:
                    keyboard.release(key)
                elif self.controller:
                    self.controller.release(key)
                time.sleep(SAME_KEY_RELEASE_GAP_MS / 1000.0)
                if self.use_keyboard and KEYBOARD_AVAILABLE:
                    keyboard.press(key)
                elif self.controller:
                    self.controller.press(key)
            else:
                if self.use_keyboard and KEYBOARD_AVAILABLE:
                    keyboard.press(key)
                elif self.controller:
                    self.controller.press(key)
            self._active_keys.add(key)
        except Exception as e:
            print(f"按键按下失败: {e}")
        return gen
    
    def _do_release(self, key: str):
        """实际释放按键"""
        try:
            if key in self._active_keys:
                if self.use_keyboard and KEYBOARD_AVAILABLE:
                    keyboard.release(key)
                elif self.controller:
                    self.controller.release(key)
                self._active_keys.discard(key)
        except Exception as e:
            print(f"按键释放失败: {e}")
    
    def _schedule_release(self, keys_with_gen: list, delay: float):
        """安排延迟释放按键，带代数检查防止误释放"""
        def release_keys():
            time.sleep(delay)
            for key, gen in keys_with_gen:
                # 只有当按下代数匹配时才释放，防止旧的计时器杀死新的按下
                if self._key_press_gen.get(key, 0) == gen:
                    self._do_release(key)
        
        timer_thread = threading.Thread(target=release_keys, daemon=True)
        timer_thread.start()
        self._release_timers.append(timer_thread)
            
    def press_key(self, key: str, duration: float = KEY_PRESS_DURATION):
        """模拟单个按键（阻塞模式）"""
        try:
            if self.use_keyboard and KEYBOARD_AVAILABLE:
                keyboard.press(key)
                time.sleep(duration)
                keyboard.release(key)
            elif self.controller:
                self.controller.press(key)
                time.sleep(duration)
                self.controller.release(key)
        except Exception as e:
            print(f"按键模拟失败: {e}")
    
    def press_key_async(self, key: str, duration: float = KEY_PRESS_DURATION):
        """模拟单个按键（非阻塞模式，按键在后台延迟释放）"""
        gen = self._do_press(key)
        if gen == 0:  # 速率限制丢弃
            return
        self._schedule_release([(key, gen)], duration)
    
    def press_keys_async(self, keys: List[str], duration: float = KEY_PRESS_DURATION):
        """同时按下多个键（非阻塞模式）"""
        if not keys:
            return
        keys_with_gen = []
        # 按键之间加入微小延迟(2ms)，避免游戏/应用吞键
        for i, key in enumerate(keys):
            gen = self._do_press(key)
            if gen == 0:  # 速率限制丢弃
                continue
            keys_with_gen.append((key, gen))
            if i < len(keys) - 1:
                time.sleep(0.002)  # 2ms间隔
        self._schedule_release(keys_with_gen, duration)
            
    def press_keys(self, keys: List[str], duration: float = KEY_PRESS_DURATION):
        """同时按下多个键（阻塞模式）"""
        if not keys:
            return
            
        try:
            if self.use_keyboard and KEYBOARD_AVAILABLE:
                # 按键之间加入微小延迟(2ms)，避免被吞
                for i, key in enumerate(keys):
                    keyboard.press(key)
                    if i < len(keys) - 1:
                        time.sleep(0.002)
                time.sleep(duration)
                for key in keys:
                    keyboard.release(key)
            elif self.controller:
                for i, key in enumerate(keys):
                    self.controller.press(key)
                    if i < len(keys) - 1:
                        time.sleep(0.002)
                time.sleep(duration)
                for key in keys:
                    self.controller.release(key)
        except Exception as e:
            print(f"按键模拟失败: {e}")
    
    def release_all(self):
        """释放所有当前按下的键"""
        for key in list(self._active_keys):
            self._do_release(key)
        self._last_press_time.clear()  # 重置速率限制状态
    
    def toggle_shift(self):
        """切换SHIFT模式（游戏内八度切换）"""
        try:
            if self.use_keyboard and KEYBOARD_AVAILABLE:
                keyboard.press('shift')
                time.sleep(0.03)
                keyboard.release('shift')
            elif self.controller:
                self.controller.press(Key.shift)
                time.sleep(0.03)
                self.controller.release(Key.shift)
            
            self._shift_active = not self._shift_active
            time.sleep(SHIFT_TOGGLE_DELAY_MS / 1000.0)
        except Exception as e:
            print(f"[SHIFT] 切换失败: {e}")
    
    def ensure_shift_state(self, need_shift: bool):
        """确保SHIFT处于指定状态"""
        if self._shift_active != need_shift:
            self.toggle_shift()
    
    def reset_shift(self):
        """重置为普通模式（如果当前在SHIFT模式则切换回来）"""
        if self._shift_active:
            self.toggle_shift()
    
    # 延音踏板已移除（不再按空格键），改用按键时长模拟延音


class MidiPlayer:
    """MIDI播放器 - 支持和弦"""
    
    def __init__(self):
        self.parser = MidiParser()
        self.mapper = KeyboardMapper()
        self.simulator = KeyboardSimulator()
        
        self.state = PlaybackState()
        self._play_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 音部控制
        self.play_melody = True   # 播放高音部（主旋律）
        self.play_bass = True     # 播放低音部
        self.bass_density = 1.0   # 伴奏密度 (1.0=全部, 0.5=一半, 0.33=三分之一)
        self._bass_skip_counter = 0  # 伴奏跳过计数器
        
        # 智能低音整合（关闭低音部时，保留重要的低音音符到主旋律）
        self._bass_integration_enabled = True  # 启用低音整合
        self._integrated_bass_notes = set()  # 需要整合到主旋律的低音音符时间戳集合
        self._bass_solo_sections = []  # 低音独奏段落 [(start_time, end_time)]
        
        # 动态延音分析结果
        self._song_sustain_profile = None  # 歌曲延音特征分析结果
        
        # 结尾Glissando
        self._play_ending_glissando = False  # 播放结尾滑奏（默认关闭）
        self._glissando_style = 'auto'      # 滑奏风格: 'auto', 'up', 'down', 'updown'
        
        # 熟练度模拟系统
        self._proficiency_enabled = True    # 启用熟练度模拟
        self._song_play_counts = {}         # 曲目播放次数记录 {song_hash: count}
        self._current_song_hash = None      # 当前曲目hash
        self._current_proficiency = 0.0     # 当前熟练度 0.0-1.0
        
        # 按键时长设置（根据MIDI音符时长自动决定）
        self.duration_max = KEY_DURATION_MAX
        self.duration_min = KEY_DURATION_MIN
        
        # 调性移调（自动检测）
        self._key_transpose = 0
        
        # 八度偏移（自动检测）
        self._octave_offset = 0
        
        # 用户额外移调（手动调整）
        self._user_transpose = 0
        
        # 智能映射表（用于传统模式）
        self._note_remap = {}
        
        # ========== C调直转模式 ==========
        # 直接将任意调转换为C调，不使用八度/半音偏移
        # 而是将音符按音级(1234567)直接映射到C大调
        self._direct_c_mode = False          # 是否启用C调直转模式
        self._detected_key = 0               # 检测到的原曲调性 (0-11, 0=C)
        self._detected_mode = 'major'        # 检测到的调式 (major/minor)
        self._direct_c_note_map = {}         # C调直转音符映射表
        self._direct_c_chord_map = {}        # C调直转低音和弦映射
        
        # 回调函数 (key, note_event, is_chord)
        self.on_note_play: Optional[Callable[[str, NoteEvent, bool], None]] = None
        self.on_progress: Optional[Callable[[float, float], None]] = None
        self.on_playback_end: Optional[Callable[[], None]] = None
        self.on_shift_change: Optional[Callable[[bool], None]] = None    # SHIFT模式变化回调
        self.on_sustain_change: Optional[Callable[[bool], None]] = None  # 延音状态变化回调（显示当前是否在踏板加成区）
        
        # 文件类型标识
        self._is_js_file = False
        
        # === MIDI踏板数据（用于按键时长加成，不按空格键）===
        self._sustain_pedal_events = []     # MIDI踏板事件列表
        self._sustain_event_index = 0       # 当前踏板事件索引
        self._sustain_active_now = False    # 当前时间点踏板是否踩下（用于时长加成）
        
        # 加载熟练度数据
        self._load_proficiency_data()
        
    # ==================== 熟练度系统 ====================
    
    def _load_proficiency_data(self):
        """从settings.json加载熟练度数据和C调直转设置"""
        import json
        from config import CONFIG_FILE
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._song_play_counts = data.get('song_play_counts', {})
                # 加载C调直转模式设置
                self._direct_c_mode = data.get('direct_c_mode', False)
        except:
            self._song_play_counts = {}
            self._direct_c_mode = False
    
    def _save_proficiency_data(self):
        """保存熟练度数据到settings.json"""
        import json
        from config import CONFIG_FILE
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[熟练度] 读取配置失败: {e}")
            data = {}
        data['song_play_counts'] = self._song_play_counts
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[熟练度] 已保存到 {CONFIG_FILE}")
        except Exception as e:
            print(f"[熟练度] 保存失败: {e}")
    
    def _save_direct_c_mode(self):
        """保存C调直转模式设置到settings.json"""
        import json
        from config import CONFIG_FILE
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            data = {}
        data['direct_c_mode'] = self._direct_c_mode
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[C调直转] 设置已保存: {'开启' if self._direct_c_mode else '关闭'}")
        except Exception as e:
            print(f"[C调直转] 保存设置失败: {e}")
    
    def _calculate_song_hash(self, filepath: str) -> str:
        """计算曲目的唯一标识（基于文件名+音符数+时长）"""
        import os
        import hashlib
        filename = os.path.basename(filepath)
        note_count = len(self.parser.notes) if self.parser.notes else 0
        total_time = self.parser.total_time if hasattr(self.parser, 'total_time') else 0
        # 使用文件名+音符数+时长生成hash
        key = f"{filename}_{note_count}_{total_time:.1f}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def _update_proficiency(self):
        """更新当前曲目的熟练度"""
        if not self._current_song_hash:
            return
        
        play_count = self._song_play_counts.get(self._current_song_hash, 0)
        # 每次弹奏增加5%熟练度，最高95%（保留5%犯错几率）
        # 熟练度 = min(0.95, play_count * 0.05)
        # 但最低也有1%犯错几率，所以最高熟练度是99%
        self._current_proficiency = min(0.99, play_count * 0.05)
        
    def _increment_play_count(self):
        """增加当前曲目的播放次数"""
        if not self._current_song_hash:
            return
        count = self._song_play_counts.get(self._current_song_hash, 0)
        self._song_play_counts[self._current_song_hash] = count + 1
        self._save_proficiency_data()
        self._update_proficiency()
        print(f"[熟练度] 播放次数: {count + 1}, 熟练度: {self._current_proficiency*100:.0f}%")
    
    def get_proficiency_info(self) -> dict:
        """获取当前曲目的熟练度信息"""
        play_count = self._song_play_counts.get(self._current_song_hash, 0) if self._current_song_hash else 0
        return {
            'play_count': play_count,
            'proficiency': self._current_proficiency,
            'enabled': self._proficiency_enabled
        }
    
    def set_proficiency_enabled(self, enabled: bool):
        """设置是否启用熟练度模拟"""
        self._proficiency_enabled = enabled
        print(f"[熟练度] {'启用' if enabled else '禁用'}熟练度模拟")
        
    def reset_proficiency(self):
        """重置当前曲目的熟练度"""
        if self._current_song_hash:
            self._song_play_counts[self._current_song_hash] = 0
            self._current_proficiency = 0.0
            self._save_proficiency_data()
            print(f"[熟练度] 已重置当前曲目熟练度")
    
    def _apply_proficiency_effect(self, key: str, duration: float, is_chord: bool) -> tuple:
        """
        应用熟练度效果
        
        不熟练时的效果：
        - 按键时间变化（偏长或偏短）
        - 小概率按错相邻键
        - 节奏微微不稳
        
        返回: (实际按键, 实际时长)
        """
        if not self._proficiency_enabled:
            return key, duration
        
        final_key = key
        final_duration = duration
        
        # 犯错概率 = (1 - 熟练度) * 基础错误率
        # 最低0.5%错误率（最熟练时），最高5%错误率（完全不熟练时）
        base_error_rate = 0.05
        min_error_rate = 0.005
        error_rate = max(min_error_rate, (1.0 - self._current_proficiency) * base_error_rate)
        
        # 按键时长变化：不熟练时按键时长不稳定
        duration_variance = (1.0 - self._current_proficiency) * 0.3  # 最大30%变化
        if duration_variance > 0:
            final_duration = duration * (1.0 + random.uniform(-duration_variance, duration_variance))
            final_duration = max(0.03, final_duration)  # 最小30ms
        
        # 按错键：小概率按到左右相邻的键
        if random.random() < error_rate:
            # 定义键位的左右相邻关系（36键布局）
            KEY_NEIGHBORS = {
                # 高音区 Q-U
                'q': ['w', 'i'], 'w': ['q', 'e', 'o'], 'e': ['w', 'r'], 'r': ['e', 't', 'p'],
                't': ['r', 'y', '['], 'y': ['t', 'u', ']'], 'u': ['y'],
                # 中音区 A-J
                'a': ['s', '6'], 's': ['a', 'd', '7'], 'd': ['s', 'f'], 'f': ['d', 'g', '8'],
                'g': ['f', 'h', '9'], 'h': ['g', 'j', '0'], 'j': ['h'],
                # 低音区 Z-M
                'z': ['x', '1'], 'x': ['z', 'c', '2'], 'c': ['x', 'v'], 'v': ['c', 'b', '3'],
                'b': ['v', 'n', '4'], 'n': ['b', 'm', '5'], 'm': ['n'],
                # 黑键
                '1': ['z', '2'], '2': ['1', 'x'], '3': ['v', '4'], '4': ['3', 'b'], '5': ['4', 'n'],
                '6': ['a', '7'], '7': ['6', 's'], '8': ['f', '9'], '9': ['8', 'g'], '0': ['9', 'h'],
                'i': ['q', 'o'], 'o': ['i', 'w'], 'p': ['r', '['], '[': ['p', 't'], ']': ['[', 'y'],
            }
            
            if key in KEY_NEIGHBORS and KEY_NEIGHBORS[key]:
                # 选择一个相邻键
                final_key = random.choice(KEY_NEIGHBORS[key])
        
        return final_key, final_duration
    
    # ==================== 音部设置 ====================
        
    def set_part_filter(self, play_melody: bool, play_bass: bool):
        """设置音部过滤"""
        self.play_melody = play_melody
        self.play_bass = play_bass
    
    def set_bass_density(self, density: float):
        """设置伴奏密度 (1.0=全部, 0.5=一半, 0.33=三分之一)"""
        self.bass_density = max(0.1, min(1.0, density))
        self._bass_skip_counter = 0
        print(f"[伴奏] 密度设置为 {self.bass_density:.0%}")
        
    def load_midi(self, filepath: str) -> bool:
        """加载MIDI或JS文件"""
        # 加载前先重置SHIFT状态，防止上一首残留导致后续曲目映射错乱
        self.simulator.reset_shift()
        # 判断文件类型
        if filepath.lower().endswith('.js'):
            return self._load_js(filepath)
        else:
            return self._load_midi(filepath)
    
    def _load_midi(self, filepath: str) -> bool:
        """加载MIDI文件"""
        self._is_js_file = False
        # 确保使用 MidiParser
        if not isinstance(self.parser, MidiParser):
            self.parser = MidiParser()
        success = self.parser.load_file(filepath)
        if success:
            self.state = PlaybackState()
            # 分析音域并建立全局映射
            self._analyze_and_setup_mapping()
            # 动态分析歌曲延音特征
            self._song_sustain_profile = self._analyze_song_sustain_profile()
            # 分析低音独奏段落和低音整合
            self._analyze_bass_solo_sections()
            self._select_bass_for_integration()
            # 加载MIDI踏板数据（用于按键时长加成，不按空格键）
            self._sustain_pedal_events = getattr(self.parser, 'sustain_events', [])
            self._sustain_event_index = 0
            self._sustain_active_now = False
            if self._sustain_pedal_events:
                print(f"[延音] 已加载 {len(self._sustain_pedal_events)} 个踏板事件，将用于按键时长加成")
            # 计算曲目hash并更新熟练度
            self._current_song_hash = self._calculate_song_hash(filepath)
            self._update_proficiency()
            play_count = self._song_play_counts.get(self._current_song_hash, 0)
            print(f"[熟练度] 曲目识别: {self._current_song_hash}, 已弹{play_count}次, 熟练度{self._current_proficiency*100:.0f}%")
        return success
    
    def _load_js(self, filepath: str) -> bool:
        """加载JS谱面文件"""
        self._is_js_file = True
        js_parser = JSParser()
        success = js_parser.load_file(filepath)
        if success:
            # 替换 parser
            self.parser = js_parser
            self.state = PlaybackState()
            # JS文件已经是游戏内格式，直接映射
            self._setup_js_mapping()
        return success
    
    def _setup_js_mapping(self):
        """设置JS文件的直接映射（JS已经是游戏格式）"""
        self.mapper.set_transpose(0)
        self._note_remap = {}
        
        bass_count = 0
        for note in self.parser.notes:
            midi_note = note.note
            
            if midi_note < 48:
                self._note_remap[midi_note] = 48 + (midi_note % 12)
                bass_count += 1
            elif midi_note > 95:
                self._note_remap[midi_note] = midi_note - 12
            else:
                self._note_remap[midi_note] = midi_note
        
        min_note = min(n.note for n in self.parser.notes)
        max_note = max(n.note for n in self.parser.notes)
        print(f"[JS映射] 音符范围: {min_note}-{max_note}")
        if bass_count > 0:
            print(f"[JS映射] {bass_count}个低音已八度折叠")
        else:
            print(f"[JS映射] 直接使用游戏内键位，无需转换")
    
    def _detect_key_transpose(self, notes: list) -> int:
        """
        检测歌曲调性并返回最优移调值
        
        36键全音阶电子琴可以弹所有半音，不再需要移调到C大调。
        只需要做八度移动让音域尽量落在48-95范围内（支持SHIFT扩展4八度）。
        偏向中高音区，避免歌曲被拉太低。
        
        Args:
            notes: MIDI音符列表
            
        Returns:
            移调半音数（12的倍数，纯八度移动）
        """
        if not notes:
            return 0
        
        # 优化目标: 完整4八度范围 C3-B6 (MIDI 48-95)
        TARGET_MIN = 48
        TARGET_MAX = 95
        # 偏向中高音区的目标中心
        PREFERRED_CENTER = 73.0
        
        note_center = (min(notes) + max(notes)) / 2
        
        # 计算最佳八度偏移，偏向保持或提升音高
        octave_adjust = round((PREFERRED_CENTER - note_center) / 12) * 12
        octave_adjust = max(-36, min(36, octave_adjust))
        
        # 如果偏移为负（降低音高），检查是否真的需要
        if octave_adjust < 0:
            # 检查不偏移时的命中率
            hits_no_shift = sum(1 for n in notes if TARGET_MIN <= n <= TARGET_MAX)
            hits_with_shift = sum(1 for n in notes if TARGET_MIN <= n + octave_adjust <= TARGET_MAX)
            # 如果不偏移也有80%以上命中率，就不要降调
            if hits_no_shift / len(notes) >= 0.8:
                octave_adjust = 0
        
        return octave_adjust
    
    def _analyze_and_setup_mapping(self):
        """
        分析音域并建立智能映射方案（36键全音阶版本）
        
        36键电子琴支持全部半音，不需要白键吸附。
        策略：
        1. 计算音域中心，做八度平移使音域落在48-95范围内
        2. 超出范围的音符折叠到最近的八度
        3. 直接使用MIDI音符映射，保留所有半音信息
        
        游戏键盘：36键全音阶 + SHIFT (MIDI 48-95, C3-B6, 4个八度)
        """
        # 如果启用了C调直转模式，跳过
        if self._direct_c_mode:
            print("[智能映射] 跳过 - C调直转模式已启用")
            return
        
        # 根据音部设置过滤音符
        if self.play_melody and self.play_bass:
            notes = [n.note for n in self.parser.melody_notes] if self.parser.melody_notes and len(self.parser.melody_notes) >= 8 else [n.note for n in self.parser.notes]
        elif self.play_melody:
            notes = [n.note for n in self.parser.melody_notes] if self.parser.melody_notes and len(self.parser.melody_notes) >= 8 else [n.note for n in self.parser.notes]
        elif self.play_bass:
            notes = [n.note for n in self.parser.bass_notes] if self.parser.bass_notes else [n.note for n in self.parser.notes]
        else:
            notes = [n.note for n in self.parser.notes]

        if not notes:
            self.mapper.set_transpose(0)
            self._note_remap = {}
            return
        
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        def midi_to_name(m):
            return f"{note_names[m % 12]}{m // 12 - 1}"
        
        # === 完整4八度范围 C3-B6 (MIDI 48-95) ===
        GAME_MIN = 48   # C3
        GAME_MAX = 95   # B6
        GAME_CENTER = (GAME_MIN + GAME_MAX) / 2  # 71.5
        
        original_min = min(notes)
        original_max = max(notes)
        original_range = original_max - original_min
        
        # === 计算最佳八度偏移（充分利用4八度音域） ===
        # 改进：偏向中高音区，避免歌曲被拉太低导致不好听
        # 目标中心偏向C5(72)而非数学中心(71.5)，因为旋律在中高音区更好听
        PREFERRED_CENTER = 73.0  # 略偏向中高音区
        
        best_offset = 0
        best_hit_rate = 0
        best_score = -1
        
        for octave_shift in range(-5, 6):
            offset = octave_shift * 12
            # 命中率：落在完整4八度范围(48-95)的比例
            hits = sum(1 for n in notes if GAME_MIN <= n + offset <= GAME_MAX)
            hit_rate = hits / len(notes)
            
            # 居中评分：偏向中高音区，旋律在中高音更自然
            shifted = [max(GAME_MIN, min(GAME_MAX, n + offset)) for n in notes]
            actual_center = sum(shifted) / len(shifted)
            center_dist = abs(actual_center - PREFERRED_CENTER) / 24.0  # 归一化
            center_score = max(0, 1.0 - center_dist)
            
            # 音域覆盖评分：鼓励使用更宽的音域（保留原曲音域跨度）
            in_range = [n + offset for n in notes if GAME_MIN <= n + offset <= GAME_MAX]
            if len(in_range) >= 2:
                spread = (max(in_range) - min(in_range)) / 47.0  # 47 = 95-48
            else:
                spread = 0
            
            # 低音惩罚：如果大量音符落在低音区(48-59)，降低评分
            # 低音区太多音符会让歌曲变得沉闷不好听
            low_ratio = sum(1 for n in in_range if n <= 59) / max(len(in_range), 1)
            low_penalty = max(0, low_ratio - 0.25) * 0.5  # 超过25%低音开始扣分
            
            # 向下移调惩罚：偏移量为负（降低音高）时轻微扣分
            # 避免不必要地把歌曲拉低
            down_penalty = 0.03 * max(0, -offset / 12)  # 每降一个八度扣3%
            
            score = hit_rate * 0.45 + center_score * 0.3 + spread * 0.15 - low_penalty - down_penalty
            
            # 额外：如果命中率100%且偏移为0，给奖励（原始音域已经完美）
            if hit_rate >= 1.0 and offset == 0:
                score += 0.1
            
            # 同分时优先选择更小的偏移量（减少不必要的移调）
            if score > best_score or (score == best_score and abs(offset) < abs(best_offset)):
                best_score = score
                best_hit_rate = hit_rate
                best_offset = offset
        
        print(f"[智能映射] 原始: {midi_to_name(original_min)}-{midi_to_name(original_max)} ({original_range}半音)")
        print(f"[智能映射] 最佳八度偏移: {best_offset//12:+d}八度, 命中率: {best_hit_rate*100:.1f}%")
        
        self.mapper.set_transpose(0)
        self._note_remap = {}
        
        # 保存移调信息
        self._key_transpose = best_offset  # 仅八度移动
        self._octave_offset = best_offset // 12
        
        # === 构建映射表 ===
        for orig_note in set(notes):
            target = orig_note + best_offset
            
            # 超出范围时八度折叠 (48-95)
            while target < GAME_MIN:
                target += 12
            while target > GAME_MAX:
                target -= 12
            
            self._note_remap[orig_note] = target
        
        # === 统计结果 ===
        mapped_notes = [self._note_remap[n] for n in notes]
        mapped_min = min(mapped_notes)
        mapped_max = max(mapped_notes)
        
        low_count = sum(1 for n in mapped_notes if 48 <= n <= 59)
        mid_count = sum(1 for n in mapped_notes if 60 <= n <= 71)
        high_count = sum(1 for n in mapped_notes if 72 <= n <= 83)
        shift_count = sum(1 for n in mapped_notes if 84 <= n <= 95)
        
        print(f"[智能映射] 映射后: {midi_to_name(mapped_min)}-{midi_to_name(mapped_max)}")
        print(f"[智能映射] 分布: 低音(Z-M){low_count} + 中音(A-J){mid_count} + 高音(Q-U){high_count}")
        if shift_count > 0:
            print(f"[智能映射] SHIFT区(C6-B6): {shift_count}个音符需要SHIFT模式")
    
    def _analyze_song_sustain_profile(self):
        """
        动态分析整首歌曲的延音特征，为每个段落计算最佳延音参数
        
        分析内容：
        1. 歌曲整体节奏密度（慢歌需要更长延音）
        2. 每个段落的音符密度和时值分布
        3. BPM和拍号对延音的影响
        4. 长音符/短音符比例
        
        Returns:
            dict: 歌曲延音特征
        """
        if not self.parser.notes:
            return None
        
        notes = sorted(self.parser.notes, key=lambda n: n.time)
        total_time = self.parser.total_time or 1.0
        bpm = self.parser.bpm if hasattr(self.parser, 'bpm') else 120
        beat_duration = 60.0 / bpm
        
        # 整体分析
        durations = [n.duration for n in notes]
        avg_duration = sum(durations) / len(durations) if durations else 0.3
        median_duration = sorted(durations)[len(durations)//2] if durations else 0.3
        long_note_ratio = sum(1 for d in durations if d > beat_duration) / len(durations) if durations else 0.3
        
        # 音符密度（每秒音符数）
        density = len(notes) / total_time
        
        # 分析力度分布
        velocities = [n.velocity for n in notes]
        avg_velocity = sum(velocities) / len(velocities) if velocities else 80
        
        # 计算gap分布（音符间的间隔）
        gaps = []
        for i in range(1, len(notes)):
            gap = notes[i].time - notes[i-1].time
            if gap > 0:
                gaps.append(gap)
        avg_gap = sum(gaps) / len(gaps) if gaps else 0.2
        
        # 动态延音缩放系数
        # 慢歌（密度低、长音符多）→ 延音更长
        # 快歌（密度高、短音符多）→ 延音适中
        if density < 3:       # 极慢歌曲
            dynamic_sustain_scale = 1.8
        elif density < 5:     # 慢歌/抒情曲
            dynamic_sustain_scale = 1.6
        elif density < 8:     # 中速
            dynamic_sustain_scale = 1.4
        elif density < 12:    # 中快速
            dynamic_sustain_scale = 1.25
        else:                 # 快歌
            dynamic_sustain_scale = 1.1
        
        # 长音符多的歌曲额外增加延音
        if long_note_ratio > 0.3:
            dynamic_sustain_scale *= 1.15
        
        # 动态重叠量
        if density < 5:
            dynamic_overlap_ms = 350  # 慢歌更多重叠
        elif density < 10:
            dynamic_overlap_ms = 280
        else:
            dynamic_overlap_ms = 200
        
        profile = {
            'avg_duration': avg_duration,
            'median_duration': median_duration,
            'long_note_ratio': long_note_ratio,
            'density': density,
            'bpm': bpm,
            'beat_duration': beat_duration,
            'avg_gap': avg_gap,
            'avg_velocity': avg_velocity,
            'dynamic_sustain_scale': dynamic_sustain_scale,
            'dynamic_overlap_ms': dynamic_overlap_ms,
        }
        
        print(f"[延音分析] 密度:{density:.1f}n/s 平均时值:{avg_duration:.3f}s "
              f"长音比:{long_note_ratio:.1%} 动态缩放:{dynamic_sustain_scale:.2f} "
              f"动态重叠:{dynamic_overlap_ms}ms")
        
        return profile
    
    def _analyze_bass_solo_sections(self):
        """
        分析低音部独奏段落（过渡段用低音当主旋律的情况）
        
        检测条件：
        1. 某段时间内只有低音部的音符
        2. 低音部音符形成连续的旋律线
        3. 高音部在该段时间内无音符或极少
        
        结果保存到 self._bass_solo_sections 和 self._integrated_bass_notes
        """
        if not self.parser.notes or not self.parser.melody_notes:
            self._bass_solo_sections = []
            self._integrated_bass_notes = set()
            return
        
        split_point = self.parser.pitch_split_point
        sorted_notes = sorted(self.parser.notes, key=lambda n: n.time)
        
        # 使用滑动窗口检测低音独奏段落
        WINDOW_SIZE = 1.0  # 1秒窗口
        STEP = 0.25  # 250ms步进
        MIN_BASS_ONLY_DURATION = 0.5  # 最少持续0.5秒才算独奏段
        
        bass_solo_windows = []
        t = 0
        total_time = self.parser.total_time or 1.0
        
        while t < total_time:
            window_end = t + WINDOW_SIZE
            
            # 统计窗口内的高低音音符数
            melody_in_window = sum(1 for n in sorted_notes 
                                   if t <= n.time < window_end and n.note >= split_point)
            bass_in_window = [n for n in sorted_notes 
                             if t <= n.time < window_end and n.note < split_point]
            
            # 如果窗口内几乎只有低音
            if len(bass_in_window) >= 2 and melody_in_window <= 1:
                bass_solo_windows.append((t, window_end, bass_in_window))
            
            t += STEP
        
        # 合并连续的独奏段落
        sections = []
        if bass_solo_windows:
            current_start = bass_solo_windows[0][0]
            current_end = bass_solo_windows[0][1]
            current_notes = list(bass_solo_windows[0][2])
            
            for start, end, notes in bass_solo_windows[1:]:
                if start <= current_end + STEP:  # 连续窗口
                    current_end = end
                    current_notes.extend(notes)
                else:
                    if current_end - current_start >= MIN_BASS_ONLY_DURATION:
                        sections.append((current_start, current_end))
                        # 将这些低音音符标记为需要整合
                        for n in current_notes:
                            self._integrated_bass_notes.add((round(n.time, 4), n.note))
                    current_start = start
                    current_end = end
                    current_notes = list(notes)
            
            # 最后一段
            if current_end - current_start >= MIN_BASS_ONLY_DURATION:
                sections.append((current_start, current_end))
                for n in current_notes:
                    self._integrated_bass_notes.add((round(n.time, 4), n.note))
        
        self._bass_solo_sections = sections
        
        if sections:
            print(f"[低音分析] 发现 {len(sections)} 个低音独奏段落:")
            for s, e in sections[:5]:
                print(f"  {s:.1f}s - {e:.1f}s")
            print(f"[低音分析] 已标记 {len(self._integrated_bass_notes)} 个低音整合到主旋律")
    
    def _select_bass_for_integration(self):
        """
        当自动关闭低音部后，选取一部分低音音符整合到主旋律中
        
        选取算法（加强版）：
        1. 低音独奏段的所有音符（已在 _analyze_bass_solo_sections 中标记）
        2. 每个小节的第一拍和第三拍低音（标记节拍重音根音）
        3. 旋律有间隙时的低音填充（降低间隙门槛到1拍）
        4. 力度较强的低音（和弦根音）
        5. 持续时间较长的低音（通常是旋律性低音）
        6. 旋律与低音同步出现的低音（已被编曲者认为是旋律的一部分）
        """
        if not self.parser.bass_notes or not self.parser.melody_notes:
            return
        
        bpm = self.parser.bpm if hasattr(self.parser, 'bpm') else 120
        beat_duration = 60.0 / bpm
        measure_duration = beat_duration * 4  # 假设4/4拍
        
        sorted_bass = sorted(self.parser.bass_notes, key=lambda n: n.time)
        sorted_melody = sorted(self.parser.melody_notes, key=lambda n: n.time)
        
        # 建立旋律时间索引（加速查询）
        melody_times = [n.time for n in sorted_melody]
        
        # 1. 每小节第一拍和第三拍的低音根音
        last_integrated_time = -beat_duration * 4
        for note in sorted_bass:
            # 每四拍至少取一个低音
            if note.time - last_integrated_time >= beat_duration * 3.5:
                self._integrated_bass_notes.add((round(note.time, 4), note.note))
                last_integrated_time = note.time
        
        # 2. 旋律间隙时的低音填充（门槛提高到2拍）
        for i in range(1, len(sorted_melody)):
            gap = sorted_melody[i].time - sorted_melody[i-1].time
            if gap > beat_duration * 2.0:  # 超过2拍的间隙
                gap_start = sorted_melody[i-1].time + sorted_melody[i-1].duration * 0.5
                gap_end = sorted_melody[i].time
                for bass_note in sorted_bass:
                    if gap_start <= bass_note.time < gap_end:
                        self._integrated_bass_notes.add((round(bass_note.time, 4), bass_note.note))
        
        # 3. 力度较强的低音（可能是和弦根音）
        if sorted_bass:
            avg_vel = sum(n.velocity for n in sorted_bass) / len(sorted_bass)
            for note in sorted_bass:
                if note.velocity > avg_vel * 1.25:  # 力度超过平均值25%才保留
                    self._integrated_bass_notes.add((round(note.time, 4), note.note))
        
        # 4. 持续时间较长的低音（旋律性低音线条）
        if sorted_bass:
            avg_dur = sum(n.duration for n in sorted_bass) / len(sorted_bass)
            for note in sorted_bass:
                if note.duration > avg_dur * 1.8:  # 时值超过平均值80%
                    self._integrated_bass_notes.add((round(note.time, 4), note.note))
        
        # 5. 与旋律同步出现的低音（编曲者有意安排，间距<50ms视为同步，但只保留力度较强的）
        import bisect
        for bass_note in sorted_bass:
            idx = bisect.bisect_left(melody_times, bass_note.time - 0.05)
            if idx < len(melody_times) and abs(melody_times[idx] - bass_note.time) < 0.05:
                if bass_note.velocity > avg_vel * 1.1:
                    self._integrated_bass_notes.add((round(bass_note.time, 4), bass_note.note))
        
        # 6. 低音音高接近分割点的（主旋律低音区，仅保留3个半音内）
        split_point = self.parser.pitch_split_point if hasattr(self.parser, 'pitch_split_point') else 48
        for note in sorted_bass:
            if note.note >= split_point - 3:  # 分割点附近3个半音内
                self._integrated_bass_notes.add((round(note.time, 4), note.note))
        
        print(f"[低音整合] 共选取 {len(self._integrated_bass_notes)} 个低音整合到主旋律 (共{len(sorted_bass)}个低音)")
    
    def set_transpose(self, semitones: int):
        """
        设置额外移调（在智能映射基础上的额外偏移）
        
        智能映射已自动检测调性并映射，此功能用于用户微调。
        例如：自动检测到需要-6半音，用户还可以额外+2或-2微调。
        """
        self._user_transpose = semitones
        print(f"[用户移调] 设置额外移调: {semitones:+d} 半音")
        
    def set_speed(self, speed: float):
        """设置播放速度"""
        self.state.speed = max(0.1, min(3.0, speed))
        
    # ==================== C调直转模式 ====================
    
    def set_direct_c_mode(self, enabled: bool, save: bool = True):
        """
        设置C调直转模式
        
        开启后：
        - 自动检测原曲调性
        - 将音符按音级(1234567)直接映射到C大调
        - 禁用传统的半音偏移和八度偏移
        - 低音自动用和弦键替代
        
        关闭后：
        - 使用传统的智能映射方式
        
        Args:
            enabled: 是否启用
            save: 是否保存设置到配置文件
        """
        self._direct_c_mode = enabled
        if enabled and self.parser.notes:
            # 清除传统移调设置
            self._key_transpose = 0
            self._octave_offset = 0
            self.mapper.set_transpose(0)
            self._note_remap = {}
            # 设置C调直转映射
            self._setup_direct_c_mapping()
            print(f"[C调直转] 已启用，原曲检测为: {self._get_key_name(self._detected_key)} {self._detected_mode}")
            print(f"[C调直转] 传统移调已禁用")
        elif not enabled and self.parser.notes:
            # 关闭时恢复传统映射
            self._analyze_and_setup_mapping()
            print(f"[C调直转] 已关闭，恢复传统映射")
        
        # 保存设置
        if save:
            self._save_direct_c_mode()
    
    def is_direct_c_mode(self) -> bool:
        """获取C调直转模式状态"""
        return self._direct_c_mode
    
    def _get_key_name(self, key: int) -> str:
        """获取调性名称"""
        key_names = ['C', 'C#/Db', 'D', 'D#/Eb', 'E', 'F', 'F#/Gb', 'G', 'G#/Ab', 'A', 'A#/Bb', 'B']
        return key_names[key % 12]
    
    def _detect_song_key(self, notes: list, note_events: list = None) -> tuple:
        """
        使用改进的调性检测算法（借鉴music21的多种权重方案）
        
        改进点：
        1. 优先使用MIDI文件内嵌的调号信息（最准确）
        2. 考虑音符时值（持续时间），不只是出现次数
        3. 使用皮尔逊相关系数代替简单加权求和
        4. 支持多种权重模板，选择最适合的
        
        Args:
            notes: MIDI音符号列表
            note_events: NoteEvent对象列表（包含时值信息）
            
        Returns:
            (key, mode, confidence): key为0-11表示C-B，mode为'major'或'minor'，confidence为置信度
        """
        if not notes:
            return 0, 'major'
        
        # 注意：不再优先使用MIDI内嵌调号，因为很多MIDI文件的调号标注是错误的
        # 始终使用算法检测
        
        # ========== 第一步：计算音级分布（考虑时值）==========
        pitch_distribution = [0.0] * 12
        
        if note_events:
            # 使用时值加权
            for note_event in note_events:
                pc = note_event.note % 12
                # 用时长作为权重（更长的音符更重要）
                duration = max(0.1, note_event.duration)
                pitch_distribution[pc] += duration
        else:
            # 仅使用出现次数
            for note in notes:
                pc = note % 12
                pitch_distribution[pc] += 1.0
        
        total = sum(pitch_distribution)
        if total == 0:
            return 0, 'major'
        
        # 归一化
        pitch_freq = [c / total for c in pitch_distribution]
        
        # ========== 第二步：多种调性权重模板 ==========
        # 来自 music21 的研究成果
        
        # Aarden-Essen 权重 (推荐，最不容易误认为属调)
        # "Weak tendency to identify the subdominant key as the tonic"
        AARDEN_MAJOR = [17.7661, 0.145624, 14.9265, 0.160186, 19.8049, 11.3587,
                        0.291248, 22.062, 0.145624, 8.15494, 0.232998, 4.95122]
        AARDEN_MINOR = [18.2648, 0.737619, 14.0499, 16.8599, 0.702494, 14.4362,
                        0.702494, 18.6161, 4.56621, 1.93186, 7.37619, 1.75623]
        
        # Krumhansl-Schmuckler 权重 (经典算法)
        KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
        
        # Bellman-Budge 权重 (不容易误认邻近调)
        BB_MAJOR = [16.80, 0.86, 12.95, 1.41, 13.49, 11.93, 1.25, 20.28, 1.80, 8.04, 0.62, 10.57]
        BB_MINOR = [18.16, 0.69, 12.99, 13.34, 1.07, 11.15, 1.38, 21.07, 7.49, 1.53, 0.92, 10.21]
        
        def pearson_correlation(x, y):
            """计算皮尔逊相关系数"""
            n = len(x)
            mean_x = sum(x) / n
            mean_y = sum(y) / n
            
            numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
            sum_sq_x = sum((xi - mean_x) ** 2 for xi in x)
            sum_sq_y = sum((yi - mean_y) ** 2 for yi in y)
            
            denominator = (sum_sq_x * sum_sq_y) ** 0.5
            if denominator == 0:
                return 0
            return numerator / denominator
        
        def analyze_with_weights(major_weights, minor_weights, name):
            """使用指定权重进行分析"""
            best_key = 0
            best_mode = 'major'
            best_corr = -2
            
            for key in range(12):
                # 旋转音级分布以匹配当前调
                rotated = pitch_freq[key:] + pitch_freq[:key]
                
                # 计算皮尔逊相关系数
                major_corr = pearson_correlation(rotated, major_weights)
                minor_corr = pearson_correlation(rotated, minor_weights)
                
                if major_corr > best_corr:
                    best_corr = major_corr
                    best_key = key
                    best_mode = 'major'
                if minor_corr > best_corr:
                    best_corr = minor_corr
                    best_key = key
                    best_mode = 'minor'
            
            return best_key, best_mode, best_corr
        
        # ========== 第三步：综合多种算法结果 ==========
        results = []
        
        # 使用三种算法分析
        aarden_result = analyze_with_weights(AARDEN_MAJOR, AARDEN_MINOR, 'Aarden')
        ks_result = analyze_with_weights(KS_MAJOR, KS_MINOR, 'KS')
        bb_result = analyze_with_weights(BB_MAJOR, BB_MINOR, 'BB')
        
        results.append(('Aarden', aarden_result))
        results.append(('KS', ks_result))
        results.append(('BB', bb_result))
        
        # 选择置信度最高的结果
        best_result = max(results, key=lambda x: x[1][2])
        best_key, best_mode, best_corr = best_result[1]
        
        # ========== 第四步：投票验证 ==========
        # 如果多个算法结果一致，增加置信度
        key_votes = {}
        for name, (k, m, c) in results:
            key_str = f"{k}_{m}"
            if key_str not in key_votes:
                key_votes[key_str] = 0
            key_votes[key_str] += 1
        
        # 找出票数最多的
        max_votes = max(key_votes.values())
        consensus_keys = [k for k, v in key_votes.items() if v == max_votes]
        
        # 如果有共识且与最佳结果一致，使用共识结果
        best_key_str = f"{best_key}_{best_mode}"
        if best_key_str in consensus_keys:
            # 一致，使用最佳结果
            pass
        elif max_votes >= 2:
            # 多数算法同意另一个结果
            consensus_key_str = consensus_keys[0]
            parts = consensus_key_str.split('_')
            best_key = int(parts[0])
            best_mode = parts[1]
            # 找出对应的相关系数
            for name, (k, m, c) in results:
                if k == best_key and m == best_mode:
                    best_corr = c
                    break
        
        # 保存置信度
        self._key_confidence = best_corr
        
        print(f"[调性检测] 算法投票: Aarden={self._get_key_name(aarden_result[0])} {aarden_result[1]} ({aarden_result[2]:.3f}), "
              f"KS={self._get_key_name(ks_result[0])} {ks_result[1]} ({ks_result[2]:.3f}), "
              f"BB={self._get_key_name(bb_result[0])} {bb_result[1]} ({bb_result[2]:.3f})")
        print(f"[调性检测] 最终结果: {self._get_key_name(best_key)} {best_mode} (置信度: {best_corr:.3f})")
        
        return best_key, best_mode
    
    def _setup_direct_c_mapping(self):
        """
        设置C调直转映射
        
        核心原理：
        1. 检测原曲调性（如G大调、D小调）
        2. 计算需要移调多少才能变成C大调/A小调（白键调）
        3. 直接把音符移调到对应的C大调白键位置
        4. 根据原音高选择使用中音/中高音/高音区
        5. 低音部分用和弦键替代
        
        关键改进：对于任何调性，都先转到C大调/A小调（白键调），
        然后直接映射到对应的白键，保持相对音高关系。
        
        36键布局 + SHIFT扩展（全音阶，4八度）：
        普通模式：
        - 高音区 (Q-U + I,O,P,[,]): C5-B5  -> MIDI 72-83
        - 中音区 (A-J + 6-0):       C4-B4  -> MIDI 60-71
        - 低音区 (Z-M + 1-5):       C3-B3  -> MIDI 48-59
        SHIFT模式扩展：
        - 高音区 (Q-U + I,O,P,[,]): C6-B6  -> MIDI 84-95
        
        === 改进算法：基于音级的智能映射 ===
        
        不是简单移调，而是分析每个音符在原调中的"功能角色"（音级），
        然后将该角色映射到C大调中对应的音符。
        
        例如：F大调的Bb（降7级）在旋律中作为"第4音"，
        应该映射到C大调的F（第4音），而不是随意吸附。
        
        这样能保持旋律的"级进"和"跳进"关系，听起来更自然。
        """
        if not self.parser.notes:
            return
        
        notes = [n.note for n in self.parser.notes]
        note_events = self.parser.notes
        
        # 检测原曲调性
        self._detected_key, self._detected_mode = self._detect_song_key(notes, note_events)
        
        print(f"[C调直转] 检测到原曲调性: {self._get_key_name(self._detected_key)} {self._detected_mode}")
        
        # ========== 改进：基于音级的映射算法 ==========
        # 
        # 核心思想：分析每个音符在原调音阶中的角色，然后映射到C大调
        # 
        # 原调音阶（以F大调为例）：F G A Bb C D E（对应音级1 2 3 4 5 6 7）
        # C大调音阶：              C D E F  G A B（对应音级1 2 3 4 5 6 7）
        # 
        # 所以F大调的Bb（音级4）-> C大调的F（音级4）
        
        # 构建原调的音阶
        root = self._detected_key
        
        # 大调音阶间隔：全全半全全全半 (2,2,1,2,2,2,1)
        MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
        # 自然小调音阶间隔：全半全全半全全 (2,1,2,2,1,2,2)  
        MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10]
        
        if self._detected_mode == 'major':
            scale_intervals = MAJOR_INTERVALS
            target_intervals = MAJOR_INTERVALS  # 目标是C大调
            target_root = 0  # C
        else:
            scale_intervals = MINOR_INTERVALS
            target_intervals = MINOR_INTERVALS  # 目标是A小调
            target_root = 9  # A
        
        # 构建原调音阶（12个半音对应的音级）
        # -1 表示不在音阶内（变化音）
        original_scale_degrees = [-1] * 12
        for degree, interval in enumerate(scale_intervals):
            pitch_class = (root + interval) % 12
            original_scale_degrees[pitch_class] = degree + 1  # 1-7
        
        # 构建目标调音阶
        target_scale = {}  # degree -> pitch_class
        for degree, interval in enumerate(target_intervals):
            pitch_class = (target_root + interval) % 12
            target_scale[degree + 1] = pitch_class
        
        # 打印音阶信息（调试用）
        scale_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        original_scale_notes = [(scale_names[(root + i) % 12]) for i in scale_intervals]
        target_scale_notes = [(scale_names[(target_root + i) % 12]) for i in target_intervals]
        print(f"[C调直转] 原调音阶: {' '.join(original_scale_notes)}")
        print(f"[C调直转] 目标音阶: {' '.join(target_scale_notes)}")
        
        # ========== 变化音处理策略 ==========
        # 对于不在音阶内的音（变化音/借用音），智能判断其功能
        # 
        # 策略：
        # 1. 先检查是否是"借用音"（如大调借用小调的音）
        # 2. 找最近的音阶音，判断是升高还是降低
        # 3. 在目标调中应用相同的变化
        
        def get_degree_and_alteration(pitch_class):
            """
            分析音符在原调中的角色
            返回: (基础音级, 变化类型)
            变化类型: 0=自然音阶音, +1=升高, -1=降低
            """
            degree = original_scale_degrees[pitch_class]
            if degree != -1:
                return degree, 0  # 自然音阶音
            
            # 变化音：找最近的音阶音
            # 优先考虑半音关系（装饰音、借用音最常见）
            lower = (pitch_class - 1) % 12
            upper = (pitch_class + 1) % 12
            
            if original_scale_degrees[lower] != -1:
                # 是某个音阶音的升高
                return original_scale_degrees[lower], +1
            elif original_scale_degrees[upper] != -1:
                # 是某个音阶音的降低
                return original_scale_degrees[upper], -1
            else:
                # 两个半音都不是音阶音（罕见），找最近的
                for dist in range(2, 6):
                    if original_scale_degrees[(pitch_class - dist) % 12] != -1:
                        return original_scale_degrees[(pitch_class - dist) % 12], +dist
                    if original_scale_degrees[(pitch_class + dist) % 12] != -1:
                        return original_scale_degrees[(pitch_class + dist) % 12], -dist
                # 兜底
                return 1, 0
        
        # 音区基准 (4八度范围: 48-95, 含SHIFT)
        OCTAVE_BASES = {'low': 48, 'mid': 60, 'high': 72, 'shift_high': 84}
        
        self._direct_c_note_map = {}
        self._direct_c_chord_map = {}
        perfect_count = 0
        altered_count = 0
        
        for orig_note in set(notes):
            pitch_class = orig_note % 12
            orig_octave = orig_note // 12
            
            # 分析在原调中的角色
            degree, alteration = get_degree_and_alteration(pitch_class)
            
            # 获取目标调中对应音级的音高
            target_pitch = target_scale.get(degree, 0)
            
            # 应用变化（升高/降低）
            if alteration != 0:
                # 变化音：在目标音上应用同样的变化
                # 36键支持所有半音，直接保留变化音
                target_pitch = (target_pitch + alteration) % 12
                altered_count += 1
            else:
                perfect_count += 1
            
            # 决定目标音区 (4八度范围, 含SHIFT)
            if orig_note >= 84:
                target_octave = 'shift_high'
            elif orig_note >= 72:
                target_octave = 'high'
            elif orig_note >= 60:
                target_octave = 'mid'
            elif orig_note >= 48:
                target_octave = 'low'
            else:
                # 太低 -> 折叠到低音区
                target_octave = 'low'
            
            # 计算目标MIDI
            base_midi = OCTAVE_BASES[target_octave]
            target_midi = base_midi + target_pitch
            
            # 确保在范围内 (4八度: 48-95)
            while target_midi < 48:
                target_midi += 12
            while target_midi > 95:
                target_midi -= 12
            
            self._direct_c_note_map[orig_note] = {
                'midi': target_midi,
                'degree': degree,
                'alteration': alteration,
                'target_octave': target_octave,
                'original_pc': pitch_class,
                'target_pc': target_pitch,
                'is_scale_tone': alteration == 0
            }
        
        # 统计
        low_count = sum(1 for v in self._direct_c_note_map.values() if v['target_octave'] == 'low')
        mid_count = sum(1 for v in self._direct_c_note_map.values() if v['target_octave'] == 'mid')
        high_count = sum(1 for v in self._direct_c_note_map.values() if v['target_octave'] == 'high')
        chord_count = len(self._direct_c_chord_map)
        total = len(self._direct_c_note_map)
        
        print(f"[C调直转] 映射完成: 中音{low_count} + 中高音{mid_count} + 高音{high_count} + 和弦{chord_count}")
        print(f"[C调直转] 音阶音: {perfect_count}, 变化音: {altered_count} ({perfect_count/(perfect_count+altered_count)*100:.1f}% 自然音)")
    
    def get_direct_c_info(self) -> dict:
        """获取C调直转模式的信息"""
        return {
            'enabled': self._direct_c_mode,
            'detected_key': self._detected_key,
            'detected_key_name': self._get_key_name(self._detected_key),
            'detected_mode': self._detected_mode,
            'note_count': len(self._direct_c_note_map),
            'chord_count': len(self._direct_c_chord_map),
            'confidence': getattr(self, '_key_confidence', 0.0)  # 置信度
        }
        
    def _map_note_direct_c(self, midi_note: int) -> tuple:
        """
        C调直转模式下的音符映射
        
        Returns:
            (key, is_chord, chord_name): 
            - key: 按键字符
            - is_chord: 是否是和弦
            - chord_name: 如果是和弦，返回和弦名；否则为None
        """
        # 优先检查是否在和弦映射中
        if midi_note in self._direct_c_chord_map:
            chord_key, chord_name, degree = self._direct_c_chord_map[midi_note]
            return chord_key, True, chord_name
        
        # 检查单音映射
        if midi_note in self._direct_c_note_map:
            info = self._direct_c_note_map[midi_note]
            target_midi = info['midi']
            key = self.mapper.midi_to_key_full.get(target_midi)
            if key:
                return key, False, None
        
        # 兜底：使用传统映射
        key = self.mapper.map_note(midi_note)
        return key, False, None
        
    def get_coverage_info(self) -> dict:
        """获取音符覆盖信息"""
        notes = [n.note for n in self.parser.notes]
        return self.mapper.analyze_coverage(notes)
    
    def get_chord_info(self) -> dict:
        """获取和弦信息"""
        return self.parser.get_chord_summary()
    
    def play(self, start_from: float = 0.0):
        """开始播放"""
        if self.state.is_playing and not self.state.is_paused:
            return
            
        if self.state.is_paused:
            self.resume()
            return
            
        self._stop_event.clear()
        self.state.is_playing = True
        self.state.is_paused = False
        self.state.current_time = start_from
        
        # 根据熟练度自动调整速度：不熟练减速30%，熟练后恢复
        if self._proficiency_enabled:
            # 速度 = 0.85 + 0.3 * 熟练度（0%熟练=0.85倍速，100%熟练=1.15倍速）
            proficiency_speed = 0.85 + 0.3 * self._current_proficiency
            self.state.speed = proficiency_speed
            print(f"[熟练度] 自动调速: {proficiency_speed:.0%}")
        
        # 使用统一的播放事件
        events = self.parser.get_play_events()
        
        # 找到起始事件索引
        self.state.current_event_index = 0
        for i, event in enumerate(events):
            if event.time >= start_from:
                self.state.current_event_index = i
                break
        
        self._play_thread = threading.Thread(target=self._play_loop_v2, daemon=True)
        self._play_thread.start()
        
    def pause(self):
        """暂停播放"""
        self.state.is_paused = True
        
    def resume(self):
        """恢复播放"""
        self.state.is_paused = False
        
    def stop(self):
        """停止播放"""
        self._stop_event.set()
        self.state.is_paused = False
        
        # 先等待播放线程完全退出
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=3.0)
        
        # 线程已退出，安全地做最终清理
        self.state.is_playing = False
        self.state.current_time = 0.0
        self.state.current_event_index = 0
        
        self.simulator.release_all()
        # 只需重置SHIFT，踏板已不使用空格键
        if self.simulator._shift_active:
            self.simulator.ensure_shift_state(False)
        
        # 通知GUI重置状态指示器
        if self.on_shift_change:
            self.on_shift_change(False)
        if self.on_sustain_change:
            self.on_sustain_change(False)
            
    def _play_loop_v2(self):
        """播放循环 (使用PlayEvent) - 精确时序控制"""
        events = self.parser.get_play_events()
        total_time = self.parser.total_time
        
        if not events:
            self.state.is_playing = False
            if self.on_playback_end:
                self.on_playback_end()
            return
        
        # 使用绝对开始时间来确保时序准确
        playback_start_time = time.perf_counter()
        music_start_time = self.state.current_time
        
        # 每次播放开始先强制重置SHIFT到普通模式，防止长时间播放后累积偏移
        self.simulator.reset_shift()
        if self.on_shift_change:
            self.on_shift_change(False)
        
        # 重置MIDI踏板索引，确定初始踏板状态（用于按键时长加成）
        self._sustain_event_index = 0
        self._sustain_active_now = False
        for i, evt in enumerate(self._sustain_pedal_events):
            if evt.time < music_start_time:
                self._sustain_active_now = evt.is_on
                self._sustain_event_index = i + 1
            else:
                break
        if self.on_sustain_change:
            self.on_sustain_change(self._sustain_active_now)
        
        while not self._stop_event.is_set():
            # 暂停检查
            if self.state.is_paused:
                time.sleep(0.005)
                # 暂停时重置开始时间
                playback_start_time = time.perf_counter()
                music_start_time = self.state.current_time
                continue
                
            # 检查是否播放完成
            if self.state.current_event_index >= len(events):
                break
            
            # 使用高精度计时器计算当前音乐时间
            real_elapsed = time.perf_counter() - playback_start_time
            self.state.current_time = music_start_time + real_elapsed * self.state.speed
            
            current_event = events[self.state.current_event_index]
            
            # === MIDI踏板状态跟踪（用于按键时长加成，不按空格键）===
            if (self._sustain_pedal_events and
                   self._sustain_event_index < len(self._sustain_pedal_events)):
                sustain_evt = self._sustain_pedal_events[self._sustain_event_index]
                if self.state.current_time >= sustain_evt.time:
                    self._sustain_active_now = sustain_evt.is_on
                    self._sustain_event_index += 1
                    if self.on_sustain_change:
                        self.on_sustain_change(sustain_evt.is_on)
            
            # 人性化：微小的时间偏移，模拟人手的微小延迟
            timing_offset = 0
            if HUMANIZE_ENABLED:
                timing_offset = random.uniform(-HUMANIZE_TIMING_MS, HUMANIZE_TIMING_MS) / 1000.0
            
            # 检查是否到达当前事件的播放时间（加上人性化偏移）
            target_time = current_event.time + timing_offset
            if self.state.current_time >= target_time:
                # 收集同时播放的事件（10ms内视为同时）
                simultaneous_events = [current_event]
                next_idx = self.state.current_event_index + 1
                
                while next_idx < len(events):
                    next_event = events[next_idx]
                    if next_event.time - current_event.time < MIN_NOTE_INTERVAL:
                        simultaneous_events.append(next_event)
                        next_idx += 1
                    else:
                        break
                
                # 计算下一个事件的时间（用于连音）
                next_event_time = None
                if next_idx < len(events):
                    next_event_time = events[next_idx].time
                
                # 播放事件（传入下一个事件时间用于连音计算）
                self._play_events(simultaneous_events, next_event_time)
                
                # 更新索引
                self.state.current_event_index = next_idx
                
                # 更新进度
                if self.on_progress:
                    self.on_progress(self.state.current_time, total_time)
            else:
                time.sleep(0.001)
        
        # 播放结尾Glissando
        if self._play_ending_glissando and not self._stop_event.is_set():
            self._play_glissando()
        
        # 播放完成（非中途停止），增加熟练度
        if not self._stop_event.is_set():
            self._increment_play_count()
        
        # 自然结束时，等待2.5秒让最后的音符自然衰减
        if not self._stop_event.is_set():
            self._stop_event.wait(timeout=2.5)
        
        # 衰减结束后再标记播放完成
        self.state.is_playing = False
        
        self.simulator.release_all()
        
        # 仅自然结束时由播放线程负责重置，stop()走自己的清理路径
        if not self._stop_event.is_set():
            self.simulator.reset_shift()
            # 通知GUI重置状态指示器
            if self.on_shift_change:
                self.on_shift_change(False)
            if self.on_sustain_change:
                self.on_sustain_change(False)
            if self.on_playback_end:
                self.on_playback_end()
    
    def _analyze_song_character(self) -> dict:
        """
        分析歌曲特征：调性、节奏、情绪
        
        Returns:
            {
                'key': 调性根音 (0-11, 0=C),
                'mode': 'major' 或 'minor',
                'tempo_feel': 'slow', 'medium', 'fast', 'very_fast',
                'energy': 'calm', 'moderate', 'energetic', 'intense',
                'rhythm_pattern': 'flowing', 'punchy', 'waltz', 'march'
            }
        """
        result = {
            'key': 0,  # 默认C
            'mode': 'major',
            'tempo_feel': 'medium',
            'energy': 'moderate',
            'rhythm_pattern': 'flowing'
        }
        
        if not self.parser.notes:
            return result
        
        # === 1. 调性检测 ===
        # 统计各音级出现频率
        pitch_counts = [0] * 12
        for note in self.parser.notes:
            pitch_class = note.note % 12
            pitch_counts[pitch_class] += 1
        
        # Krumhansl-Schmuckler 调性分析
        # 大调和小调的音级权重模板
        major_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        minor_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
        
        best_key = 0
        best_mode = 'major'
        best_score = -999
        
        total_notes = sum(pitch_counts)
        if total_notes > 0:
            pitch_freq = [c / total_notes for c in pitch_counts]
            
            # 尝试所有12个调
            for key in range(12):
                # 旋转音级频率以匹配当前调
                rotated = pitch_freq[key:] + pitch_freq[:key]
                
                # 计算与大调/小调模板的相关性
                major_corr = sum(r * p for r, p in zip(rotated, major_profile))
                minor_corr = sum(r * p for r, p in zip(rotated, minor_profile))
                
                if major_corr > best_score:
                    best_score = major_corr
                    best_key = key
                    best_mode = 'major'
                if minor_corr > best_score:
                    best_score = minor_corr
                    best_key = key
                    best_mode = 'minor'
        
        result['key'] = best_key
        result['mode'] = best_mode
        
        # === 2. 速度感 ===
        bpm = self.parser.bpm if hasattr(self.parser, 'bpm') else 120
        if bpm < 70:
            result['tempo_feel'] = 'slow'
        elif bpm < 110:
            result['tempo_feel'] = 'medium'
        elif bpm < 140:
            result['tempo_feel'] = 'fast'
        else:
            result['tempo_feel'] = 'very_fast'
        
        # === 3. 能量/情绪 ===
        # 基于力度和音符密度
        velocities = [n.velocity for n in self.parser.notes]
        avg_velocity = sum(velocities) / len(velocities) if velocities else 80
        
        note_density = len(self.parser.notes) / max(self.parser.total_time, 1)
        
        if avg_velocity < 60 and note_density < 4:
            result['energy'] = 'calm'
        elif avg_velocity < 80 and note_density < 8:
            result['energy'] = 'moderate'
        elif avg_velocity < 100 or note_density < 12:
            result['energy'] = 'energetic'
        else:
            result['energy'] = 'intense'
        
        # === 4. 节奏型 ===
        # 分析音符时值分布
        if self.parser.notes:
            intervals = []
            sorted_notes = sorted(self.parser.notes, key=lambda n: n.time)
            for i in range(1, min(len(sorted_notes), 200)):
                gap = sorted_notes[i].time - sorted_notes[i-1].time
                if gap > 0.01:
                    intervals.append(gap)
            
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                beat_duration = 60.0 / bpm
                
                # 检查是否是三拍子（华尔兹）
                waltz_count = sum(1 for iv in intervals if 0.9 < iv / (beat_duration * 3) < 1.1)
                march_count = sum(1 for iv in intervals if 0.9 < iv / beat_duration < 1.1)
                
                if waltz_count > len(intervals) * 0.3:
                    result['rhythm_pattern'] = 'waltz'
                elif march_count > len(intervals) * 0.4:
                    result['rhythm_pattern'] = 'march'
                elif avg_interval < 0.1:
                    result['rhythm_pattern'] = 'punchy'
                else:
                    result['rhythm_pattern'] = 'flowing'
        
        # 打印分析结果
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        print(f"[歌曲分析] 调性: {key_names[result['key']]} {result['mode']}, "
              f"速度: {result['tempo_feel']}({bpm:.0f}BPM), "
              f"能量: {result['energy']}, 节奏: {result['rhythm_pattern']}")
        
        return result
    
    def _calculate_ending_params(self, song_char: dict, bpm: float) -> dict:
        """
        根据歌曲内容计算结尾滑奏的自适应参数
        
        这是让滑奏更自然的核心函数，根据：
        - 歌曲的情感氛围（大调欢快/小调忧伤）
        - 歌曲的能量水平（安静/激烈）
        - 歌曲的速度感（慢板/快板）
        - 歌曲的节奏型（华尔兹/进行曲/流畅）
        - 歌曲的总时长和复杂度
        
        Returns:
            dict: 包含以下参数
            - phrase_length: 滑奏片段的音符数量 (短/中/长)
            - breath_time: 段落间的呼吸时间（秒）
            - final_hold: 最终和弦的持续时间（秒）
            - ritardando: 渐慢程度 (0.0-1.0)
            - diminuendo: 渐弱程度 (0.0-1.0)
            - chord_count: 结尾和弦数量
            - ending_style: 结尾风格建议 ('gentle', 'majestic', 'dramatic', 'intimate')
        """
        energy = song_char.get('energy', 'moderate')
        tempo_feel = song_char.get('tempo_feel', 'medium')
        rhythm = song_char.get('rhythm_pattern', 'flowing')
        mode = song_char.get('mode', 'major')
        
        # 分析歌曲长度
        song_duration = 0
        if self.parser.notes:
            song_duration = max(n.time + n.duration for n in self.parser.notes)
        
        # 分析旋律复杂度
        melody_complexity = 0
        if self.parser.melody_notes:
            # 音高变化多 = 复杂
            pitches = [n.note for n in self.parser.melody_notes[:100]]
            if len(pitches) > 1:
                changes = sum(1 for i in range(1, len(pitches)) if pitches[i] != pitches[i-1])
                melody_complexity = changes / len(pitches)
        
        params = {}
        
        # === 1. 滑奏片段长度 ===
        # 短曲用短结尾，长曲用长结尾
        # 安静的歌用短一点，激烈的歌可以长一点
        base_length = 8
        if song_duration > 180:  # 超过3分钟
            base_length = 12
        elif song_duration < 90:  # 不到1.5分钟
            base_length = 6
        
        if energy == 'calm':
            base_length = int(base_length * 0.7)
        elif energy == 'intense':
            base_length = int(base_length * 1.3)
        
        # 小调稍微克制一点
        if mode == 'minor':
            base_length = int(base_length * 0.85)
        
        params['phrase_length'] = max(4, min(16, base_length))
        
        # === 2. 呼吸时间（段落间停顿）===
        # 慢歌需要更多呼吸时间，快歌紧凑一点
        beat_duration = 60.0 / bpm
        
        if tempo_feel == 'slow':
            breath_mult = 2.5
        elif tempo_feel == 'very_fast':
            breath_mult = 1.0
        else:
            breath_mult = 1.8
        
        # 华尔兹需要优雅的停顿
        if rhythm == 'waltz':
            breath_mult *= 1.3
        # 进行曲紧凑
        elif rhythm == 'march':
            breath_mult *= 0.8
        
        # 安静的歌多留白
        if energy == 'calm':
            breath_mult *= 1.4
        
        params['breath_time'] = beat_duration * breath_mult
        params['breath_time'] = max(0.15, min(1.2, params['breath_time']))
        
        # === 3. 最终和弦持续时间 ===
        # 让最后的和弦有足够时间消散
        if energy == 'calm':
            final_mult = 6.0  # 安静的歌，让声音慢慢消散
        elif energy == 'intense':
            final_mult = 4.0  # 激烈的歌，干脆有力
        else:
            final_mult = 5.0
        
        # 慢歌需要更长的尾音
        if tempo_feel == 'slow':
            final_mult *= 1.5
        
        params['final_hold'] = beat_duration * final_mult
        params['final_hold'] = max(0.8, min(4.0, params['final_hold']))
        
        # === 4. 渐慢程度 (ritardando) ===
        # 浪漫/安静的歌需要更明显的渐慢
        if energy == 'calm' or rhythm == 'waltz':
            params['ritardando'] = 0.7  # 明显渐慢
        elif energy == 'intense' or rhythm == 'march':
            params['ritardando'] = 0.3  # 轻微渐慢
        else:
            params['ritardando'] = 0.5
        
        # 小调更忧伤，渐慢更明显
        if mode == 'minor':
            params['ritardando'] = min(1.0, params['ritardando'] + 0.15)
        
        # === 5. 渐弱程度 (diminuendo) ===
        if energy == 'calm':
            params['diminuendo'] = 0.8  # 明显渐弱
        elif energy == 'intense':
            params['diminuendo'] = 0.3  # 保持力度到最后
        else:
            params['diminuendo'] = 0.5
        
        # === 6. 结尾和弦数量 ===
        if energy == 'calm':
            params['chord_count'] = 2  # 简洁
        elif energy == 'intense':
            params['chord_count'] = 4  # 壮丽
        else:
            params['chord_count'] = 3
        
        # 长曲子可以多一点和弦
        if song_duration > 180:
            params['chord_count'] += 1
        
        # === 7. 结尾风格建议 ===
        if energy == 'calm' and mode == 'minor':
            params['ending_style'] = 'intimate'  # 亲密内敛
        elif energy == 'calm' and mode == 'major':
            params['ending_style'] = 'gentle'    # 温柔
        elif energy == 'intense' and rhythm in ['march', 'punchy']:
            params['ending_style'] = 'dramatic'  # 戏剧化
        elif energy == 'intense':
            params['ending_style'] = 'majestic'  # 壮丽
        else:
            params['ending_style'] = 'balanced'  # 平衡
        
        print(f"[结尾参数] 长度:{params['phrase_length']}音 | "
              f"呼吸:{params['breath_time']:.2f}s | "
              f"尾音:{params['final_hold']:.2f}s | "
              f"风格:{params['ending_style']}")
        
        return params
    
    def _extract_melody_phrase(self) -> List[int]:
        """
        提取主旋律中最有代表性的片段
        
        策略：
        1. 找出主旋律中最高潮的部分（音高最高、力度最大）
        2. 找出重复出现的音型模式
        3. 提取一段连续上行或下行的旋律线
        
        Returns:
            主旋律片段的MIDI音符列表（已映射到游戏范围）
        """
        if not self.parser.melody_notes:
            return []
        
        melody = self.parser.melody_notes
        remap = getattr(self, '_note_remap', {})
        
        # === 方法1：找出最高潮部分（高音+高力度） ===
        # 计算每个音符的"重要性"分数
        note_scores = []
        for i, note in enumerate(melody):
            # 高音加分
            pitch_score = (note.note - 48) / 47.0  # 归一化到0-1 (48-95范围)
            # 高力度加分
            velocity_score = note.velocity / 127.0
            # 综合分数
            score = pitch_score * 0.6 + velocity_score * 0.4
            note_scores.append((i, score, note))
        
        # 找出连续高分区域
        best_start = 0
        best_score = -1
        window_size = 8  # 滑动窗口大小
        
        for start in range(len(note_scores) - window_size):
            window_score = sum(ns[1] for ns in note_scores[start:start+window_size])
            if window_score > best_score:
                best_score = window_score
                best_start = start
        
        # 提取最佳片段
        phrase_notes = [ns[2] for ns in note_scores[best_start:best_start+window_size]]
        
        # === 方法2：检查是否有连续音阶（适合滑奏） ===
        # 尝试扩展成更长的连续片段
        extended_phrase = []
        for note in phrase_notes:
            midi_note = note.note
            # 映射到游戏范围
            if midi_note in remap:
                mapped = remap[midi_note]
            else:
                mapped = midi_note
            # 确保在范围内
            while mapped < 48:
                mapped += 12
            while mapped > 95:
                mapped -= 12
            extended_phrase.append(mapped)
        
        # 去除连续重复的音符
        final_phrase = []
        for note in extended_phrase:
            if not final_phrase or note != final_phrase[-1]:
                final_phrase.append(note)
        
        return final_phrase
    
    def _play_key_chord_ending(self, song_key: int, song_mode: str, interval: float, 
                               duration: float, energy: str):
        """
        根据调性播放和弦进行收尾
        
        使用该调的 I-IV-V-I 或 i-iv-V-i 进行
        """
        # 和弦键映射 (根据游戏的Z-M和弦)
        # Z=C, X=Dm, C=Em, V=F, B=G, N=Am, M=G7
        
        # 根据调性选择最接近的和弦组合
        # 简化处理：根据调性根音找最合适的终止式
        # 低音区全12半音映射
        nk = {0:'z', 1:'1', 2:'x', 3:'2', 4:'c', 5:'v', 6:'3', 7:'b', 8:'4', 9:'n', 10:'5', 11:'m'}
        # IV-V-I 终止式，根据调性计算
        key_chord_map = {}
        for k in range(12):
            iv = nk[(k + 5) % 12]
            v = nk[(k + 7) % 12]
            i = nk[k]
            key_chord_map[k] = [iv, v, i]
        
        # 小调修改
        if song_mode == 'minor':
            minor_chord_map = {
                0: ['v', 'b', 'n'],       # Cm: F-G-Am (近似)
                2: ['b', 'n', 'x'],       # Dm: G-Am-Dm
                4: ['n', 'b', 'c'],       # Em: Am-G-Em
                7: ['z', 'x', 'b'],       # Gm: C-Dm-G
                9: ['x', 'c', 'n'],       # Am: Dm-Em-Am
            }
            if song_key in minor_chord_map:
                chord_seq = minor_chord_map[song_key]
            else:
                chord_seq = key_chord_map.get(song_key, ['b', 'z'])
        else:
            chord_seq = key_chord_map.get(song_key, ['b', 'z'])
        
        time.sleep(interval * 1.5)
        
        # 根据能量调整和弦节奏
        if energy == 'calm':
            chord_interval = interval * 2
            chord_duration = duration * 2
        elif energy == 'intense':
            chord_interval = interval * 0.8
            chord_duration = duration * 1.2
        else:
            chord_interval = interval * 1.5
            chord_duration = duration * 1.5
        
        for i, chord in enumerate(chord_seq):
            if self._stop_event.is_set():
                return
            
            if i == len(chord_seq) - 1:
                # 最后一个和弦：全音域
                self.simulator.press_keys([chord, 'q', '1'], chord_duration * 2)
            else:
                self.simulator.press_key(chord, chord_duration)
            
            time.sleep(chord_interval)
        
        # 最终延长和弦
        time.sleep(interval)
        
        # 根据调性选择最终低音音符 - 全12半音
        nk_final = {0:'z', 1:'1', 2:'x', 3:'2', 4:'c', 5:'v', 6:'3', 7:'b', 8:'4', 9:'n', 10:'5', 11:'m'}
        final_chord = nk_final.get(song_key, 'z')
        self.simulator.press_keys([final_chord, 'a', 'q'], duration * 4)
    
    def _play_glissando(self):
        """
        播放结尾滑奏(Glissando) - 钢琴家谢幕风格 (增强版)
        
        设计理念：
        1. 【核心】BPM与原曲一致 - 滑奏节奏感和主曲统一，不突兀
        2. 慢歌延音更长 - BPM低时按键时间自动变长，更抒情
        3. 抒情歌按抒情方式结束 - 根据能量自动选择风格
        4. 渐慢(ritardando) - 结尾逐渐放慢，更有仪式感
        5. 装饰音点缀 - 增加华丽感
        """
        import random
        
        if self._stop_event.is_set():
            return
        
        # === 核心：直接使用原曲BPM，保持节奏统一 ===
        bpm = self.parser.bpm if hasattr(self.parser, 'bpm') else 120
        beat_duration = 60.0 / bpm  # 一拍的时长（秒）
        
        # 滑奏基础间隔 = 1/4拍 或 1/6拍（根据曲速微调）
        # 关键：保持和原曲的节拍感一致
        if bpm < 70:
            # 很慢的抒情歌：每个音占1/3拍，更有呼吸感
            base_interval = beat_duration / 3
        elif bpm < 100:
            # 中慢速抒情歌：每个音占1/4拍
            base_interval = beat_duration / 4
        elif bpm < 140:
            # 中速歌曲：每个音占1/5拍
            base_interval = beat_duration / 5
        else:
            # 快歌：每个音占1/6拍
            base_interval = beat_duration / 6
        
        # 音符时长也根据BPM调整 - 慢歌延音更长
        # 这是让慢歌更好听的关键
        if bpm < 70:
            note_duration_mult = 3.5  # 很慢的歌，音符很长
        elif bpm < 100:
            note_duration_mult = 2.8  # 抒情歌，音符较长
        elif bpm < 140:
            note_duration_mult = 2.2  # 中速
        else:
            note_duration_mult = 1.8  # 快歌，音符短促
        
        base_duration = base_interval * note_duration_mult
        
        # === 分析歌曲特征 ===
        song_char = self._analyze_song_character()
        energy = song_char.get('energy', 'moderate')
        rhythm = song_char.get('rhythm_pattern', 'flowing')
        tempo_feel = song_char.get('tempo_feel', 'medium')
        song_key = song_char.get('key', 0)
        song_mode = song_char.get('mode', 'major')
        
        # === 【新增】计算自适应结尾参数 ===
        ending_params = self._calculate_ending_params(song_char, bpm)
        song_char['ending_params'] = ending_params
        # 把BPM相关参数也传进去
        song_char['bpm'] = bpm
        song_char['beat_duration'] = beat_duration
        song_char['base_duration'] = base_duration
        
        # === 确定滑奏风格 - 抒情歌用抒情方式 ===
        style = self._glissando_style
        if style == 'auto':
            melody_phrase = self._extract_melody_phrase()
            
            # 判断是否是抒情歌：慢速 + 平静能量
            is_lyrical = (tempo_feel in ['slow', 'medium'] and energy == 'calm') or bpm < 85
            
            if is_lyrical:
                # 抒情歌：优先使用浪漫、琶音、主题风格
                if melody_phrase and len(melody_phrase) >= 5:
                    style = random.choice(['romantic', 'theme', 'arpeggio', 'romantic'])
                else:
                    style = random.choice(['romantic', 'arpeggio', 'romantic'])
            elif melody_phrase and len(melody_phrase) >= 5:
                if energy == 'calm':
                    style = random.choice(['theme', 'romantic', 'romantic'])
                elif energy == 'intense':
                    style = random.choice(['theme', 'virtuoso', 'finale'])
                else:
                    style = 'theme' if random.random() < 0.6 else random.choice(['grand', 'romantic'])
            else:
                if energy == 'calm':
                    style = random.choice(['romantic', 'arpeggio'])
                elif energy == 'intense':
                    style = random.choice(['virtuoso', 'finale', 'grand'])
                elif rhythm == 'waltz':
                    style = random.choice(['romantic', 'arpeggio'])
                else:
                    style = random.choice(['grand', 'finale', 'romantic'])
        
        # 36键白键（从低到高排列）
        # 白键序列（滑奏用，从低到高）
        all_keys = ['z', 'x', 'c', 'v', 'b', 'n', 'm',
                   'a', 's', 'd', 'f', 'g', 'h', 'j',
                   'q', 'w', 'e', 'r', 't', 'y', 'u']
        
        # 低音区白键
        chord_keys = ['z', 'x', 'c', 'v', 'b', 'n', 'm']
        
        # 调性音符映射 - 低音区12个半音全覆盖
        # MIDI 48-59: z,1,x,2,c,v,3,b,4,n,5,m
        note_to_key = {0:'z', 1:'1', 2:'x', 3:'2', 4:'c', 5:'v', 6:'3', 7:'b', 8:'4', 9:'n', 10:'5', 11:'m'}
        tonic_chord = note_to_key.get(song_key, 'z')
        subdominant = note_to_key.get((song_key + 5) % 12, 'v')   # IV度
        dominant = note_to_key.get((song_key + 7) % 12, 'b')       # V度
        
        # 根据调性生成音阶按键序列
        scale_keys = self._get_scale_keys(song_key, song_mode)
        
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        mode_name = '大调' if song_mode == 'major' else '小调'
        lyrical_tag = " (抒情)" if (tempo_feel in ['slow', 'medium'] and energy == 'calm') or bpm < 85 else ""
        print(f"[Glissando] {key_names[song_key]}{mode_name} | 风格:{style}{lyrical_tag} | BPM:{bpm:.0f} | 间隔:{base_interval*1000:.0f}ms")
        
        # === 主旋律回顾风格 ===
        if style == 'theme':
            self._play_theme_glissando_enhanced(base_interval, song_char, scale_keys, 
                                                tonic_chord, subdominant, dominant)
            return
        
        # === 浪漫风格 - 抒情歌最佳选择 ===
        if style == 'romantic':
            self._play_romantic_ending(base_interval, song_char, scale_keys,
                                      tonic_chord, subdominant, dominant)
            return
        
        # === 华丽大结局 ===
        if style == 'grand':
            self._play_grand_ending(base_interval, song_char, scale_keys,
                                   tonic_chord, subdominant, dominant)
            return
        
        # === 终极谢幕 ===
        if style == 'finale':
            self._play_finale_ending(base_interval, song_char, scale_keys,
                                    tonic_chord, subdominant, dominant)
            return
        
        # === 炫技结尾 ===
        if style == 'virtuoso':
            self._play_virtuoso_ending(base_interval, song_char, scale_keys,
                                      tonic_chord, subdominant, dominant)
            return
        
        # === 琶音风格 ===
        if style == 'arpeggio':
            self._play_arpeggio_ending(base_interval, song_char, scale_keys,
                                      tonic_chord, subdominant, dominant)
            return
        
        # === 其他简单风格 ===
        self._play_simple_glissando(style, base_interval, song_char, all_keys,
                                   tonic_chord, subdominant, dominant)
    
    def _get_scale_keys(self, song_key: int, song_mode: str) -> list:
        """根据调性获取音阶对应的按键序列"""
        if song_mode == 'major':
            scale_steps = [0, 2, 4, 5, 7, 9, 11]
        else:
            scale_steps = [0, 2, 3, 5, 7, 8, 10]
        
        scale_notes = []
        for octave in range(4, 8):
            for step in scale_steps:
                midi_note = (octave * 12) + song_key + step
                if 48 <= midi_note <= 95:
                    scale_notes.append(midi_note)
        
        scale_keys = []
        for midi_note in scale_notes:
            key = self.mapper.midi_to_key_full.get(midi_note)
            if key:
                scale_keys.append(key)
        
        return scale_keys if scale_keys else ['z', 'x', 'c', 'v', 'b', 'a', 's', 'd', 'f', 'g', 'q', 'w', 'e']
    
    def _humanize_timing(self, base_interval: float, variation: float = 0.15) -> float:
        """模拟人类演奏的微小timing变化"""
        import random
        return base_interval * (1 + random.uniform(-variation, variation))
    
    def _play_with_expression(self, key: str, base_duration: float, expression: str = 'normal'):
        """带表情的音符演奏"""
        if expression == 'accent':
            duration = base_duration * 1.3
        elif expression == 'soft':
            duration = base_duration * 0.85
        elif expression == 'long':
            duration = base_duration * 1.8
        elif expression == 'short':
            duration = base_duration * 0.6
        else:
            duration = base_duration
        self.simulator.press_key(key, duration)
    
    def _play_romantic_ending(self, base_interval: float, song_char: dict, scale_keys: list,
                              tonic: str, subdominant: str, dominant: str):
        """
        浪漫收尾 - 像肖邦的夜曲结尾（抒情歌最佳选择）
        
        核心设计：
        1. BPM越慢，音符越长，更有抒情感
        2. 呼吸时间和BPM同步，不会突兀
        3. 渐慢渐弱的自然收尾
        """
        import random
        
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 8)
        breath = params.get('breath_time', base_interval * 1.5)
        final_hold = params.get('final_hold', base_interval * 4)
        rit = params.get('ritardando', 0.5)
        dim = params.get('diminuendo', 0.5)
        
        energy = song_char.get('energy', 'moderate')
        mode = song_char.get('mode', 'major')
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2.5)
        
        # === 根据BPM调整基础时长 ===
        # 慢歌延音更长，这是抒情的关键
        if bpm < 70:
            duration_mult = 1.4  # 很慢的抒情歌
        elif bpm < 90:
            duration_mult = 1.2  # 中慢速
        else:
            duration_mult = 1.0
        
        interval = base_interval * 1.5 * duration_mult
        duration = base_duration * duration_mult
        
        # === 第一段：温柔的琶音上行 ===
        if len(scale_keys) >= 8:
            base_arpeggio = [scale_keys[0], scale_keys[2], scale_keys[4], scale_keys[7]]
            if len(scale_keys) >= 12 and phrase_len > 6:
                base_arpeggio.extend([scale_keys[9], scale_keys[11]])
            if phrase_len <= 5:
                arpeggio = base_arpeggio[:3]
            elif phrase_len <= 8:
                arpeggio = base_arpeggio[:4]
            else:
                arpeggio = base_arpeggio
        else:
            arpeggio = scale_keys[:min(phrase_len, len(scale_keys))]
        
        # 小调用更轻的装饰音
        if mode == 'minor' and len(scale_keys) > 2:
            grace_note = scale_keys[1]
            self.simulator.press_key(grace_note, duration * 0.25)
            time.sleep(interval * 0.2)
        elif len(scale_keys) > 3:
            grace_note = scale_keys[1]
            self.simulator.press_key(grace_note, duration * 0.3)
            time.sleep(interval * 0.25)
        
        # 上行琶音 - 使用渐慢参数
        for i, key in enumerate(arpeggio):
            if self._stop_event.is_set():
                return
            # 渐慢效果由rit参数控制
            slow_factor = 1 + i * 0.08 * (1 + rit)
            current_interval = interval * slow_factor
            self._play_with_expression(key, duration * (1 + i * 0.06), 'normal')
            time.sleep(current_interval)
        
        # === 第二段：高音区停留（抒情歌省略颤音）===
        time.sleep(breath * duration_mult)
        
        # 平静/抒情的歌省略颤音，直接过渡更自然
        if energy != 'calm' and bpm >= 90 and len(scale_keys) >= 12:
            high_notes = [scale_keys[-3], scale_keys[-1]]
            tremolo_count = 2 if phrase_len > 6 else 1
            for _ in range(tremolo_count):
                for note in high_notes:
                    if self._stop_event.is_set():
                        return
                    self.simulator.press_key(note, duration * 0.4)
                    time.sleep(interval * 0.35)
        
        # === 第三段：温柔下行 + 渐慢渐弱 ===
        time.sleep(breath * 0.6 * duration_mult)
        
        descending = list(reversed(arpeggio))
        desc_count = min(len(descending), max(3, phrase_len - 2))
        
        for i, key in enumerate(descending[:desc_count]):
            if self._stop_event.is_set():
                return
            vol_factor = 1 - (i / desc_count) * dim * 0.3
            slow_factor = 1.2 + i * 0.18 * (1 + rit)
            current_interval = interval * slow_factor
            self._play_with_expression(key, duration * vol_factor, 'soft')
            time.sleep(current_interval)
        
        # === 第四段：柔和和弦收尾 ===
        time.sleep(breath * duration_mult)
        
        # 低音铺垫 - 慢歌更长
        self.simulator.press_key('a', duration * 1.6)
        time.sleep(breath * 0.7 * duration_mult)
        
        # 主和弦
        self.simulator.press_keys([tonic, 'q'], duration * 1.8)
        time.sleep(breath * 0.8 * duration_mult)
        
        # 最后一个音 - 使用final_hold，慢歌更长
        self.simulator.press_key(scale_keys[0] if scale_keys else 'a', final_hold * duration_mult)
    
    def _play_grand_ending(self, base_interval: float, song_char: dict, scale_keys: list,
                           tonic: str, subdominant: str, dominant: str):
        """
        华丽大结局 - 像拉赫玛尼诺夫
        特点：渐强到高潮，然后壮丽收尾
        """
        import random
        
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 10)
        breath = params.get('breath_time', base_interval * 1.2)
        final_hold = params.get('final_hold', base_interval * 5)
        chord_count = params.get('chord_count', 3)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        # 根据BPM调整
        duration_mult = 1.2 if bpm < 100 else 1.0
        
        # === 第一段：从中音区开始的渐强滑奏 ===
        start_idx = max(0, len(scale_keys)//3)
        end_idx = min(len(scale_keys), start_idx + phrase_len)
        mid_keys = scale_keys[start_idx:end_idx] if len(scale_keys) > 6 else scale_keys
        
        interval = base_interval * 0.85 * duration_mult
        duration = base_duration * duration_mult
        
        # 渐强渐快上行
        for i, key in enumerate(mid_keys):
            if self._stop_event.is_set():
                return
            accel_factor = max(0.5, 1 - i * 0.025)
            current_interval = interval * accel_factor
            self._play_with_expression(key, duration * (1 + i * 0.04), 'normal')
            time.sleep(self._humanize_timing(current_interval, 0.08))
        
        # === 第二段：顶点震音 ===
        time.sleep(breath * 0.5 * duration_mult)
        
        if len(scale_keys) >= 2:
            high_pair = (scale_keys[-2], scale_keys[-1])
            tremolo_count = 2 if phrase_len < 8 else 3
            for _ in range(tremolo_count):
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(high_pair[0], duration * 0.4)
                time.sleep(base_interval * 0.32)
                self.simulator.press_key(high_pair[1], duration * 0.4)
                time.sleep(base_interval * 0.32)
        
        # === 第三段：壮丽和弦序列 ===
        time.sleep(breath * 0.8)
        
        # 根据chord_count决定和弦数量
        all_chords = [
            ([tonic, 'a', 'q'], 1.4),       # I
            ([subdominant, 'd', 't'], 1.2),  # IV
            ([dominant, 'f', 'y', 'm'], 1.3),  # V7
            ([tonic, 'a'], 1.1),             # I (简化)
        ]
        chord_sequence = all_chords[:min(chord_count, len(all_chords))]
        
        for chord, mult in chord_sequence:
            if self._stop_event.is_set():
                return
            self.simulator.press_keys(chord, duration * mult)
            time.sleep(breath * mult * 0.9)
        
        # === 第四段：最终大和弦 ===
        time.sleep(breath)
        
        # 低音先行
        self.simulator.press_key('a', duration * 1.3)
        time.sleep(breath * 0.6)
        
        # 全音域大和弦 - 使用final_hold
        final_chord = [tonic, 'a', 'q', '1']
        if len(scale_keys) > 10 and phrase_len > 8:
            final_chord.append('4')
        self.simulator.press_keys(final_chord, final_hold)
    
    def _play_finale_ending(self, base_interval: float, song_char: dict, scale_keys: list,
                            tonic: str, subdominant: str, dominant: str):
        """
        终极谢幕 - 交响乐结尾风格（适合气势磅礴的曲目）
        """
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 10)
        breath = params.get('breath_time', base_interval)
        final_hold = params.get('final_hold', base_interval * 5)
        chord_count = params.get('chord_count', 4)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        # 根据BPM调整 - 交响风格保持适度
        duration_mult = 1.15 if bpm < 100 else (0.95 if bpm > 130 else 1.0)
        
        # === 第一段：低音和高音交替呼应 ===
        mid_point = len(scale_keys)//2
        low_keys = scale_keys[:mid_point] if len(scale_keys) > 6 else scale_keys[:3]
        high_keys = scale_keys[mid_point:] if len(scale_keys) > 6 else scale_keys[3:]
        
        interval = base_interval * 0.75 * duration_mult
        duration = base_duration * 0.8 * duration_mult
        
        # 交替次数根据phrase_len
        alt_count = min(len(low_keys), len(high_keys), max(3, phrase_len // 2))
        
        for i in range(alt_count):
            if self._stop_event.is_set():
                return
            self.simulator.press_key(low_keys[i], duration)
            time.sleep(interval * 0.55)
            self.simulator.press_key(high_keys[i], duration * (1 + i * 0.08))
            time.sleep(interval * 0.5)
        
        # === 第二段：快速音阶冲刺 ===
        time.sleep(breath * 0.6)
        
        # 根据phrase_len决定冲刺长度
        sprint_len = min(len(scale_keys), max(5, phrase_len - 2))
        sprint_keys = scale_keys[-sprint_len:] if len(scale_keys) >= sprint_len else scale_keys
        fast_interval = base_interval * 0.45
        
        for key in sprint_keys:
            if self._stop_event.is_set():
                return
            self.simulator.press_key(key, duration * 0.55)
            time.sleep(fast_interval)
        
        # === 第三段：和弦轰炸 ===
        time.sleep(breath * 0.8)
        
        # 根据chord_count决定和弦数量
        all_progressions = [
            [subdominant],
            [dominant],
            [subdominant, dominant],
            [tonic, subdominant],
            [tonic, dominant, 'q'],
        ]
        chord_progression = all_progressions[:min(chord_count, len(all_progressions))]
        
        for i, chord in enumerate(chord_progression):
            if self._stop_event.is_set():
                return
            self.simulator.press_keys(chord, duration * (1.1 + i * 0.12))
            time.sleep(breath * (0.8 + i * 0.08))
        
        # === 第四段：终极大和弦 ===
        time.sleep(breath)
        
        # 连击次数根据能量
        hit_count = 3 if chord_count >= 4 else 2
        for i in range(hit_count):
            if self._stop_event.is_set():
                return
            volume_keys = [tonic, 'a', 'q', '1']
            if i == hit_count - 1:  # 最后一击最饱满
                volume_keys.extend(['4'])
            hold_time = final_hold if i == hit_count - 1 else duration * (1.5 + i * 0.5)
            self.simulator.press_keys(volume_keys, hold_time)
            if i < hit_count - 1:
                time.sleep(breath * (1.2 - i * 0.2))
    
    def _play_virtuoso_ending(self, base_interval: float, song_char: dict, scale_keys: list,
                              tonic: str, subdominant: str, dominant: str):
        """
        炫技结尾 - 李斯特风格（适合激昂曲目）
        """
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 12)
        breath = params.get('breath_time', base_interval * 0.8)
        final_hold = params.get('final_hold', base_interval * 5)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        # 炫技风格 - BPM快的曲子更短促，慢的稍长
        duration_mult = 1.1 if bpm < 100 else (0.9 if bpm > 140 else 1.0)
        
        # === 第一段：快速上行 ===
        fast_interval = base_interval * 0.5 * duration_mult
        duration = base_duration * 0.6 * duration_mult
        
        # 根据phrase_len决定上行长度
        up_keys = scale_keys[:min(len(scale_keys), phrase_len)]
        for key in up_keys:
            if self._stop_event.is_set():
                return
            self.simulator.press_key(key, duration * 0.65)
            time.sleep(fast_interval)
        
        # === 第二段：顶点停顿 + 装饰 ===
        time.sleep(breath * 0.5)
        
        # 高音颤音
        tremolo_count = 3 if phrase_len > 8 else 2
        if len(scale_keys) >= 2:
            for _ in range(tremolo_count):
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(scale_keys[-2], duration * 0.32)
                time.sleep(fast_interval * 0.38)
                self.simulator.press_key(scale_keys[-1], duration * 0.32)
                time.sleep(fast_interval * 0.4)
        
        # === 第三段：快速下行 ===
        time.sleep(base_interval * 0.3)
        
        for key in reversed(scale_keys):
            if self._stop_event.is_set():
                return
            self.simulator.press_key(key, duration * 0.6)
            time.sleep(fast_interval * 0.85)
        
        # === 第四段：震音 + 和弦爆发 ===
        time.sleep(breath * 0.8)
        
        # 低音震音 - 次数根据phrase_len
        tremolo_count = 4 if phrase_len > 10 else 3
        low_tremolo = scale_keys[:2] if len(scale_keys) >= 2 else [scale_keys[0], scale_keys[0]]
        for _ in range(tremolo_count):
            if self._stop_event.is_set():
                return
            self.simulator.press_key(low_tremolo[0], duration * 0.28)
            time.sleep(fast_interval * 0.32)
            self.simulator.press_key(low_tremolo[1], duration * 0.28)
            time.sleep(fast_interval * 0.32)
        
        # 和弦爆发
        time.sleep(breath * 0.4)
        explosion = [
            [dominant, 'f'],
            [subdominant, dominant],
            [tonic, dominant, 'q', '1'],
        ]
        for chord in explosion:
            if self._stop_event.is_set():
                return
            self.simulator.press_keys(chord, duration * 1.2)
            time.sleep(breath * 0.6)
        
        # 最终和弦 - 使用final_hold
        time.sleep(breath * 0.8)
        self.simulator.press_keys([tonic, subdominant, 'a', 'q', '1', '4'], final_hold)
    
    def _play_arpeggio_ending(self, base_interval: float, song_char: dict, scale_keys: list,
                              tonic: str, subdominant: str, dominant: str):
        """
        琶音结尾 - 优雅的分解和弦（适合抒情歌）
        """
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 8)
        breath = params.get('breath_time', base_interval * 1.5)
        final_hold = params.get('final_hold', base_interval * 4)
        rit = params.get('ritardando', 0.5)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        # 根据BPM调整 - 慢歌更长
        duration_mult = 1.3 if bpm < 90 else (1.15 if bpm < 110 else 1.0)
        
        # 构建和弦琶音序列
        if len(scale_keys) >= 12:
            all_tones = [0, 2, 4, 7, 9, 11]
            use_tones = all_tones[:min(len(all_tones), max(3, phrase_len - 2))]
            arpeggio_up = [scale_keys[i] for i in use_tones if i < len(scale_keys)]
        else:
            arpeggio_up = scale_keys[:min(len(scale_keys), phrase_len)]
        
        arpeggio_down = list(reversed(arpeggio_up[:-1])) if len(arpeggio_up) > 1 else []
        
        interval = base_interval * 1.2 * duration_mult
        duration = base_duration * duration_mult
        
        # === 上行琶音 ===
        for i, key in enumerate(arpeggio_up):
            if self._stop_event.is_set():
                return
            self.simulator.press_key(key, duration * (1 + i * 0.04))
            time.sleep(self._humanize_timing(interval, 0.1))
        
        # === 顶点停留 ===
        time.sleep(breath)
        if arpeggio_up:
            self.simulator.press_key(arpeggio_up[-1], duration * 1.6)
        time.sleep(breath * 0.7)
        
        # === 下行琶音 + 渐慢 ===
        for i, key in enumerate(arpeggio_down):
            if self._stop_event.is_set():
                return
            # 使用rit参数控制渐慢
            slow_factor = 1.1 + i * 0.12 * (1 + rit)
            current_interval = interval * slow_factor
            self.simulator.press_key(key, duration * 0.95)
            time.sleep(current_interval)
        
        # === 和弦收尾 ===
        time.sleep(breath)
        self.simulator.press_keys([tonic, 'q'], duration * 2.2)
        time.sleep(breath * 0.8)
        self.simulator.press_key(scale_keys[0] if scale_keys else 'a', final_hold)
    
    def _play_theme_glissando_enhanced(self, base_interval: float, song_char: dict, scale_keys: list,
                                       tonic: str, subdominant: str, dominant: str):
        """
        主旋律回顾增强版 - 提取歌曲精华，用更有表情的方式演绎
        """
        melody_phrase = self._extract_melody_phrase()
        
        if not melody_phrase or len(melody_phrase) < 4:
            # 没有好的主旋律，转用浪漫风格
            self._play_romantic_ending(base_interval, song_char, scale_keys,
                                      tonic, subdominant, dominant)
            return
        
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 8)
        breath = params.get('breath_time', base_interval * 1.5)
        final_hold = params.get('final_hold', base_interval * 4)
        rit = params.get('ritardando', 0.5)
        chord_count = params.get('chord_count', 2)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        energy = song_char.get('energy', 'moderate')
        rhythm = song_char.get('rhythm_pattern', 'flowing')
        
        # 根据BPM调整 - 慢歌需要更长的时值
        duration_mult = 1.25 if bpm < 90 else (1.1 if bpm < 110 else 1.0)
        
        interval = base_interval * 1.3 * duration_mult
        duration = base_duration * duration_mult
        
        # 根据phrase_len限制主旋律长度
        melody_to_play = melody_phrase[:min(len(melody_phrase), phrase_len + 2)]
        
        # === 第一段：主旋律演绎（带表情）===
        print(f"[Theme] 回顾主旋律 ({len(melody_to_play)}音符)")
        
        # 前奏装饰音（短曲省略）
        if len(scale_keys) > 2 and phrase_len > 6:
            self.simulator.press_key(scale_keys[0], duration * 0.35)
            time.sleep(base_interval * 0.35)
        
        # 根据节奏类型调整演绎方式
        if rhythm == 'waltz':
            # 三拍子强调
            for i, midi_note in enumerate(melody_to_play):
                if self._stop_event.is_set():
                    return
                key = self.mapper.midi_to_key_full.get(midi_note)
                if not key:
                    folded = self.mapper._fold_to_range(midi_note)
                    key = self.mapper.midi_to_key_full.get(folded, 'a')
                
                if i % 3 == 0:
                    self._play_with_expression(key, duration * 1.3, 'accent')
                    time.sleep(interval * 1.15)
                else:
                    self._play_with_expression(key, duration * 0.85, 'soft')
                    time.sleep(interval * 0.8)
        else:
            # 流畅演绎 + 渐慢（由rit参数控制）
            for i, midi_note in enumerate(melody_to_play):
                if self._stop_event.is_set():
                    return
                key = self.mapper.midi_to_key_full.get(midi_note)
                if not key:
                    folded = self.mapper._fold_to_range(midi_note)
                    key = self.mapper.midi_to_key_full.get(folded, 'a')
                
                # 最后几个音渐慢，程度由rit控制
                remaining = len(melody_to_play) - i
                if remaining <= 4:
                    slow_factor = 1 + (4 - remaining) * 0.1 * (1 + rit)
                else:
                    slow_factor = 1
                self._play_with_expression(key, duration * slow_factor, 'normal')
                time.sleep(self._humanize_timing(interval * slow_factor, 0.08))
        
        # === 第二段：过渡 ===
        time.sleep(breath)
        
        # === 第三段：调性和弦收尾 ===
        # 和弦数量由chord_count决定
        all_chords = [
            ([subdominant, 'd'], 1.2),
            ([dominant, 'f', 'm'], 1.3),
            ([tonic, 'a'], 1.1),
        ]
        chord_seq = all_chords[:min(chord_count, len(all_chords))]
        
        for chord, mult in chord_seq:
            if self._stop_event.is_set():
                return
            self.simulator.press_keys(chord, duration * mult)
            time.sleep(breath * mult * 0.8)
        
        # 最终主和弦
        time.sleep(breath * 0.8)
        
        if energy == 'calm':
            # 轻柔收尾
            self.simulator.press_keys([tonic, 'q'], duration * 2.5)
            time.sleep(breath)
            self.simulator.press_key(scale_keys[0] if scale_keys else 'a', final_hold)
        else:
            # 饱满收尾
            self.simulator.press_keys([tonic, 'a', 'q', '1'], final_hold)
    
    def _play_simple_glissando(self, style: str, base_interval: float, song_char: dict, 
                               all_keys: list, tonic: str, subdominant: str, dominant: str):
        """简单滑奏风格：up, down, updown, wave - 也使用自适应参数"""
        # 获取自适应参数
        params = song_char.get('ending_params', {})
        phrase_len = params.get('phrase_length', 10)
        breath = params.get('breath_time', base_interval * 1.2)
        final_hold = params.get('final_hold', base_interval * 4)
        bpm = song_char.get('bpm', 120)
        base_duration = song_char.get('base_duration', base_interval * 2)
        
        # 根据BPM调整 - 保持和主曲一致的节奏感
        duration_mult = 1.2 if bpm < 100 else 1.0
        
        interval = base_interval * duration_mult
        duration = base_duration * duration_mult
        song_key = song_char.get('key', 0)
        song_mode = song_char.get('mode', 'major')
        energy = song_char.get('energy', 'moderate')
        
        # 根据phrase_len决定滑奏音符数量
        gliss_len = min(len(all_keys), max(8, phrase_len + 4))
        
        if style == 'up':
            for key in all_keys[-gliss_len:]:
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(key, duration)
                time.sleep(interval)
        elif style == 'down':
            for key in reversed(all_keys[:14]):
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(key, duration)
                time.sleep(interval)
        elif style == 'updown':
            up_len = min(10, gliss_len // 2 + 2)
            down_len = gliss_len - up_len
            for key in all_keys[-up_len:]:
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(key, duration * 0.9)
                time.sleep(interval * 0.9)
            for key in list(reversed(all_keys[4:4+down_len])):
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(key, duration)
                time.sleep(interval)
        else:  # wave
            wave = []
            wave_cycles = max(2, phrase_len // 5)
            for i in range(wave_cycles):
                start = 7 + i * 3
                wave.extend(all_keys[start:start+4])
                wave.extend(list(reversed(all_keys[start:start+2])))
            for key in wave[:gliss_len]:
                if self._stop_event.is_set():
                    return
                self.simulator.press_key(key, duration)
                time.sleep(interval)
        
        # 和弦收尾 - 使用自适应参数
        time.sleep(breath)
        self.simulator.press_keys([tonic, 'q'], duration * 2)
        time.sleep(breath * 0.8)
        self.simulator.press_key('a', final_hold)
            
    def _calculate_legato_duration(self, base_duration: float, current_time: float, 
                                    next_event_time: Optional[float], midi_note: int,
                                    velocity: int = 100,
                                    current_key: Optional[str] = None, 
                                    next_keys: Optional[set] = None,
                                    is_phrase_end: bool = False) -> float:
        """
        计算按键持续时长 - 游戏用按键时长做延音踏板
        
        核心原则：按键时长 ≈ MIDI音符时长，让游戏内置延音自然工作。
        钢琴家模拟通过力度、音区、rubato、乐句呼吸来细化表情。
        
        同键防吞音由 KeyboardSimulator._do_press() 处理：
        - 如果同一个键还在按下状态，会先释放等待 SAME_KEY_RELEASE_GAP_MS 再重新按下
        
        Args:
            base_duration: MIDI音符原始时长(秒)
            current_time: 当前音符开始时间
            next_event_time: 下一个音符的开始时间
            midi_note: MIDI音符号（用于判断音区）
            velocity: MIDI力度值 (0-127)
            current_key: 当前音符使用的键
            next_keys: 下一个事件要按的键集合
            is_phrase_end: 是否为乐句末尾
            
        Returns:
            调整后的按键持续时长(秒)
        """
        if not SUSTAIN_ENABLED:
            # 延音关闭时，使用固定短时长
            return max(SUSTAIN_MIN_MS / 1000.0, min(0.15, base_duration * 0.5))
        
        # === 0. 动态延音缩放（基于整首歌曲分析）===
        profile = getattr(self, '_song_sustain_profile', None)
        if profile:
            dynamic_scale = profile.get('dynamic_sustain_scale', SUSTAIN_SCALE)
            dynamic_overlap = profile.get('dynamic_overlap_ms', SUSTAIN_OVERLAP_MS)
        else:
            dynamic_scale = SUSTAIN_SCALE
            dynamic_overlap = SUSTAIN_OVERLAP_MS
        
        # === 1. 基础：以MIDI音符原始时长为基准，使用动态缩放 ===
        duration = base_duration * dynamic_scale
        
        # === 2. 力度→时长映射（钢琴家核心表情） ===
        # 强音符(ff)按键更久→更饱满的延音；弱音符(pp)更短促→更轻柔
        vel_ratio = max(0, (velocity - VELOCITY_MIN)) / (127 - VELOCITY_MIN)
        vel_scale = PIANO_VEL_SUSTAIN_MIN + vel_ratio * (PIANO_VEL_SUSTAIN_MAX - PIANO_VEL_SUSTAIN_MIN)
        duration *= vel_scale
        
        # === 3. 音区表情差异 ===
        if midi_note >= 72:    # 高音区（Q-U行 + SHIFT区）
            duration *= PIANO_HIGH_SUSTAIN
        elif midi_note <= 59:  # 低音区（Z-M行）
            duration *= PIANO_LOW_SUSTAIN
            # 低音额外衰减：力度越弱的低音衰减越快，避免低音抢戏
            if velocity < 90:
                bass_dampen = 0.85 + 0.15 * (velocity / 127.0)  # 弱力度低音再缩短15%
                duration *= bass_dampen
        else:                  # 中音区（A-J行）
            duration *= PIANO_MID_SUSTAIN
        
        # === 4. 弹性速度（rubato）===
        if PIANO_RUBATO_ENABLED:
            if base_duration > 0.5:
                # 长音符微微拉伸 - 歌唱性
                duration *= PIANO_RUBATO_LONG_STRETCH
            elif base_duration < 0.15:
                # 短音符微微紧凑 - 灵巧感
                duration *= PIANO_RUBATO_SHORT_TIGHTEN
        
        # === 5. 乐句呼吸 ===
        if PIANO_PHRASE_BREATH and is_phrase_end:
            # 乐句末尾音符拉伸，模拟钢琴家在句尾的自然渐慢
            duration *= PIANO_PHRASE_END_STRETCH
        
        # === 6. MIDI踏板加成：踏板踩下时延长按键时长代替按空格 ===
        if getattr(self, '_sustain_active_now', False):
            duration *= SUSTAIN_PEDAL_BOOST
            # 踏板踩下时最短按键时长更长
            min_dur = SUSTAIN_PEDAL_MIN_MS / 1000.0
        else:
            min_dur = SUSTAIN_MIN_MS / 1000.0
        
        # === 7. 连音衔接（增强版：更长更自然的衔接） ===
        # 核心：让音符之间无缝过渡，像人声歌唱一样连贯
        if next_event_time is not None:
            gap = next_event_time - current_time
            overlap_ms = dynamic_overlap
            
            if 0 < gap < duration:
                # 音符已自然重叠 → 额外延长少量，确保重叠足够丰满
                extra_overlap = overlap_ms * 0.5 / 1000.0  # 额外50%重叠量
                duration = max(duration, gap + extra_overlap)
            elif 0 < gap < 2.5 and duration < gap:
                # 音符时长短于间隔 → 延长填充间隙 + 充足重叠
                duration = gap + (overlap_ms / 1000.0)
            
            # 连续短音符（快速旋律跑动）：确保最小重叠，避免断裂
            if 0 < gap < 0.25 and duration < gap + 0.04:
                duration = gap + 0.04  # 至少40ms重叠
        
        # === 8. 范围限制 ===
        duration = max(min_dur, duration)
        duration = min(SUSTAIN_MAX_S, duration)
        
        return duration
    
    def _play_events(self, events: List[PlayEvent], next_event_time: Optional[float] = None):
        """
        播放一组事件 - 单音直接映射 + 按键时长延音 + SHIFT切换
        
        策略：
        1. 收集所有同时发声的MIDI音符
        2. 映射到目标MIDI值（48-95范围）
        3. 判断SHIFT模式（48-59仅普通，84-95仅SHIFT，60-83两者皆可）
        4. 按键时长 = MIDI音符时长 × 各种缩放（踏板加成/力度/音区/rubato）
        5. 钢琴家模拟：力度/音区/rubato/乐句呼吸 细化表情
        """
        
        # 获取当前事件时间
        current_time = events[0].time if events else 0
        
        # 乐句边界检测：与上一个事件间隔大 → 新乐句开始
        is_phrase_end = False
        if PIANO_PHRASE_BREATH and next_event_time is not None:
            gap_to_next = next_event_time - current_time
            if gap_to_next > PIANO_PHRASE_GAP_THRESHOLD:
                is_phrase_end = True  # 当前事件是乐句的最后一个
        
        # 收集所有同时发声的MIDI音符
        all_midi_notes = []
        note_info_map = {}
        
        for event in events:
            velocity = 100
            if isinstance(event.original_event, NoteEvent):
                velocity = event.original_event.velocity
            elif isinstance(event.original_event, ChordEvent):
                velocity = 100
            
            if velocity < VELOCITY_MIN:
                continue
            
            # 使用MIDI音符的原始时长（游戏用按键时长做延音踏板）
            event_duration = event.duration
            # 宽松的范围限制，保留长音符的延音信息
            press_duration = max(self.duration_min, min(self.duration_max, event_duration))
            
            # 收集所有音符（根据音部设置过滤）
            for midi_note in event.midi_notes:
                # 通道过滤 - 检查该音符所在通道是否被用户禁用
                note_channel = None
                if isinstance(event.original_event, NoteEvent):
                    note_channel = event.original_event.channel
                if note_channel is not None and not self.mapper.is_channel_enabled(note_channel):
                    continue
                
                # 音部过滤
                split_point = self.parser.pitch_split_point if hasattr(self.parser, 'pitch_split_point') else 48
                
                if midi_note >= split_point:
                    if not self.play_melody:
                        continue
                else:
                    # 低音部处理
                    if not self.play_bass:
                        # 即使关闭低音部，也保留整合到主旋律的低音
                        if self._bass_integration_enabled and hasattr(self, '_integrated_bass_notes'):
                            note_key = (round(event.time, 4), midi_note)
                            is_integrated = note_key in self._integrated_bass_notes
                            # 也检查低音独奏段落
                            is_in_solo = any(s <= event.time <= e for s, e in self._bass_solo_sections)
                            if not is_integrated and not is_in_solo:
                                continue
                            # 整合的低音通过，不跳过
                        else:
                            continue
                    elif self.bass_density < 1.0:
                        self._bass_skip_counter += self.bass_density
                        if self._bass_skip_counter < 1.0:
                            continue
                        self._bass_skip_counter -= 1.0
                
                if midi_note not in all_midi_notes:
                    all_midi_notes.append(midi_note)
                    note_info_map[midi_note] = (event, velocity, press_duration)
        
        if not all_midi_notes:
            return
        
        # === 构建要按的键（支持SHIFT切换） ===
        keys_to_press = {}
        remap = getattr(self, '_note_remap', {})
        
        # 第一遍：映射所有音符到目标MIDI值（48-95范围）
        mapped_notes_list = []  # [(original_note, mapped_note, event, velocity, press_duration)]
        
        for original_note in all_midi_notes:
            if original_note not in note_info_map:
                continue
            
            event, velocity, press_duration = note_info_map[original_note]
            
            # 获取通道信息用于通道专属移调
            note_channel = None
            if isinstance(event.original_event, NoteEvent):
                note_channel = event.original_event.channel
            
            # ========== C调直转模式 ==========
            if self._direct_c_mode and self._direct_c_note_map:
                if original_note in self._direct_c_note_map:
                    info = self._direct_c_note_map[original_note]
                    mapped_note = info['midi']
                    user_transpose = getattr(self, '_user_transpose', 0)
                    if user_transpose != 0:
                        mapped_note += user_transpose
                        while mapped_note < 48:
                            mapped_note += 12
                        while mapped_note > 95:
                            mapped_note -= 12
                    mapped_notes_list.append((original_note, mapped_note, event, velocity, press_duration))
                    continue
            
            # ========== 传统映射模式 ==========
            if original_note in remap:
                mapped_note = remap[original_note]
            else:
                mapped_note = original_note
            
            # 应用用户额外移调
            user_transpose = getattr(self, '_user_transpose', 0)
            if user_transpose != 0:
                mapped_note += user_transpose
            
            # 应用通道专属移调（如果用户设置了通道移调）
            if note_channel is not None and note_channel in self.mapper.channel_transpose:
                ch_trans = self.mapper.channel_transpose[note_channel] - self.mapper.transpose
                if ch_trans != 0:
                    mapped_note += ch_trans
            
            # 确保在4八度范围内 (48-95)
            while mapped_note < 48:
                mapped_note += 12
            while mapped_note > 95:
                mapped_note -= 12
            
            mapped_notes_list.append((original_note, mapped_note, event, velocity, press_duration))
        
        if not mapped_notes_list:
            return
        
        # === 低音区(C3-B3, MIDI 48-59)力度/时长衰减，避免低音抢戏 ===
        # 在映射完成后基于实际mapped_note判断
        def _apply_bass_dampen(entries):
            result = []
            for orig, mn, ev, vel, dur in entries:
                if 48 <= mn <= 59:
                    bass_vel_scale = 0.65 + 0.15 * (1.0 - vel / 127.0)
                    vel = int(vel * bass_vel_scale)
                    dur = dur * 0.8
                result.append((orig, mn, ev, vel, dur))
            return result
        mapped_notes_list = _apply_bass_dampen(mapped_notes_list)
        
        # === 第二步：决定SHIFT模式（带防抖） ===
        # 分析这批音符理想需要哪种模式
        needs_normal = any(48 <= mn <= 59 for _, mn, _, _, _ in mapped_notes_list)  # 只能普通模式
        needs_shift = any(84 <= mn <= 95 for _, mn, _, _, _ in mapped_notes_list)   # 只能SHIFT模式
        
        if needs_shift and not needs_normal:
            target_shift = True
        elif needs_normal and not needs_shift:
            target_shift = False
        elif needs_shift and needs_normal:
            # 同时有 48-59 和 84-95 → 冲突，按数量选然后折叠少数方
            low_exclusive = [(o, m, e, v, d) for o, m, e, v, d in mapped_notes_list if m < 60]
            high_exclusive = [(o, m, e, v, d) for o, m, e, v, d in mapped_notes_list if m > 83]
            if len(high_exclusive) >= len(low_exclusive):
                target_shift = True
            else:
                target_shift = False
        else:
            # 所有音符都在重叠区 (60-83) → 维持当前模式
            target_shift = self.simulator._shift_active
        
        # === 模式适配：确保所有音符在当前模式可用范围内 ===
        if target_shift:
            # SHIFT模式可用范围60-95，48-59的音符折叠到60-71
            mapped_notes_list = [
                (o, m + 12, e, v, d) if m < 60 else (o, m, e, v, d)
                for o, m, e, v, d in mapped_notes_list
            ]
        else:
            # 普通模式可用范围48-83，84-95的音符折叠到72-83
            mapped_notes_list = [
                (o, m - 12, e, v, d) if m > 83 else (o, m, e, v, d)
                for o, m, e, v, d in mapped_notes_list
            ]
        
        # 切换SHIFT（如果需要）
        self.simulator.ensure_shift_state(target_shift)
        if self.on_shift_change:
            self.on_shift_change(self.simulator._shift_active)
        
        # 选择映射表
        midi_to_key = self.mapper.midi_to_key_shift if self.simulator._shift_active else self.mapper.midi_to_key
        
        # === 第三步：查找按键 ===
        for original_note, mapped_note, event, velocity, press_duration in mapped_notes_list:
            key = midi_to_key.get(mapped_note)
            if not key:
                # 尝试附近的音符
                for offset in [1, -1, 2, -2]:
                    key = midi_to_key.get(mapped_note + offset)
                    if key:
                        break
            
            if key and key not in keys_to_press:
                final_note = mapped_note
                
                press_duration = self._calculate_legato_duration(
                    press_duration, current_time, next_event_time, mapped_note,
                    velocity=velocity, is_phrase_end=is_phrase_end
                )
                
                note_event = event.original_event
                if isinstance(note_event, NoteEvent):
                    keys_to_press[key] = (press_duration, False, note_event, velocity, final_note, original_note)
                else:
                    dummy_note = NoteEvent(note=final_note, velocity=velocity,
                                          time=event.time, duration=event.duration, channel=0)
                    keys_to_press[key] = (press_duration, False, dummy_note, velocity, final_note, original_note)
        
        # === 智能简化 ===
        if TRACK_PRIORITY_MODE and len(keys_to_press) > MAX_SIMULTANEOUS_KEYS:
            keys_to_press = self._smart_chord_simplify(keys_to_press, MAX_SIMULTANEOUS_KEYS)
        
        # === 人性化处理 ===
        if HUMANIZE_ENABLED and len(keys_to_press) > 1:
            sorted_items = sorted(keys_to_press.items(), key=lambda x: x[1][4])
        else:
            sorted_items = list(keys_to_press.items())
        
        # === 执行按键 ===
        for idx, (key, (duration, is_chord, note_info, vel, midi_note, priority)) in enumerate(sorted_items):
            # 应用熟练度效果
            final_key, final_duration = self._apply_proficiency_effect(key, duration, is_chord)
            
            if HUMANIZE_ENABLED:
                duration_variation = 1.0 + random.uniform(-HUMANIZE_DURATION_RATIO, HUMANIZE_DURATION_RATIO)
                humanized_duration = final_duration * duration_variation
                humanized_duration = max(SUSTAIN_MIN_MS / 1000.0, min(self.duration_max, humanized_duration))
            else:
                humanized_duration = final_duration
            
            # 微小琶音延迟
            if HUMANIZE_ENABLED and idx > 0 and HUMANIZE_ARPEGGIO_MS > 0:
                arpeggio_delay = random.uniform(0, HUMANIZE_ARPEGGIO_MS) / 1000.0
                time.sleep(arpeggio_delay)
            
            # 不熟练时可能有额外的犹豫延迟
            if self._proficiency_enabled and self._current_proficiency < 0.8:
                hesitation_chance = (1.0 - self._current_proficiency) * 0.08  # 最多8%几率犹豫
                if random.random() < hesitation_chance:
                    # 不熟练时最大200ms犹豫，熟练后逐渐减少
                    max_hesitation = 0.2 * (1.0 - self._current_proficiency)  # 最大200ms
                    min_hesitation = 0.02 * (1.0 - self._current_proficiency)  # 最小20ms
                    hesitation_time = random.uniform(min_hesitation, max_hesitation)
                    time.sleep(hesitation_time)
            
            self.simulator.press_key_async(final_key, humanized_duration)
            
            if self.on_note_play and note_info:
                self.on_note_play(final_key, note_info, is_chord)
                
    def _smart_chord_simplify(self, keys_to_press: dict, max_keys: int) -> dict:
        """
        智能和弦简化：保留和弦骨架音
        
        策略：
        1. 始终保留最低音（根音/bass）
        2. 始终保留最高音（旋律）
        3. 中间音按力度和音程重要性选择
        """
        if len(keys_to_press) <= max_keys:
            return keys_to_press
        
        # 按音高排序
        sorted_items = sorted(keys_to_press.items(), key=lambda x: x[1][4])  # x[1][4] = midi_note
        
        # 必须保留的：最低音和最高音
        preserved = {}
        preserved[sorted_items[0][0]] = sorted_items[0][1]   # 最低音（根音）
        preserved[sorted_items[-1][0]] = sorted_items[-1][1]  # 最高音（旋律）
        
        # 剩余名额
        remaining_slots = max_keys - 2
        middle_items = sorted_items[1:-1] if len(sorted_items) > 2 else []
        
        if remaining_slots > 0 and middle_items:
            # 中间音按力度排序，保留力度最大的
            middle_by_velocity = sorted(middle_items, key=lambda x: x[1][3], reverse=True)  # x[1][3] = velocity
            
            # 优先保留五度音（与根音相差7个半音）
            root_note = sorted_items[0][1][4]
            fifth_candidates = [item for item in middle_by_velocity 
                               if abs(item[1][4] - root_note) % 12 == 7]  # 五度音
            
            # 先添加五度音
            for item in fifth_candidates[:remaining_slots]:
                preserved[item[0]] = item[1]
                remaining_slots -= 1
            
            # 再添加其他高力度音
            for item in middle_by_velocity:
                if remaining_slots <= 0:
                    break
                if item[0] not in preserved:
                    preserved[item[0]] = item[1]
                    remaining_slots -= 1
        
        return preserved
    
    def get_state(self) -> PlaybackState:
        """获取播放状态"""
        return self.state
    
    def get_total_time(self) -> float:
        """获取总时长"""
        return self.parser.total_time
    
    def get_midi_info(self) -> dict:
        """获取MIDI信息"""
        return self.parser.get_info()
    
    def seek(self, time_sec: float):
        """跳转到指定时间"""
        was_playing = self.state.is_playing and not self.state.is_paused
        
        if self.state.is_playing:
            self.stop()
            
        if was_playing:
            self.play(start_from=time_sec)
        else:
            self.state.current_time = time_sec
            events = self.parser.get_play_events()
            for i, event in enumerate(events):
                if event.time >= time_sec:
                    self.state.current_event_index = i
                    break
