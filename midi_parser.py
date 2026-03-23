# -*- coding: utf-8 -*-
"""
MIDI解析模块 - 负责解析MIDI文件、JS文件和识别和弦
"""

import mido
import mido.midifiles.meta as _mido_meta
import mido.midifiles.midifiles as _mido_files
import re
from typing import List, Tuple, Optional, Set, Dict, Any
from dataclasses import dataclass, field

# === 修复 mido 无法处理损坏的 meta 事件（如空 key_signature）===
_original_build_meta_message = _mido_meta.build_meta_message

def _safe_build_meta_message(meta_type, data, delta):
    """安全版本：遇到损坏的 meta 事件时返回空文本事件而非崩溃"""
    try:
        return _original_build_meta_message(meta_type, data, delta)
    except (IndexError, ValueError, KeyError):
        # 损坏的 meta 事件（如空 key_signature data），返回无害的占位消息
        return mido.MetaMessage('text', text='', time=delta)

# 同时修补 midifiles.py 中的直接引用
_mido_meta.build_meta_message = _safe_build_meta_message
_mido_files.build_meta_message = _safe_build_meta_message


@dataclass
class SustainPedalEvent:
    """延音踏板事件（MIDI CC64）"""
    time: float         # 绝对时间(秒)
    is_on: bool         # True=踩下踏板, False=抬起踏板
    channel: int        # MIDI通道
    value: int          # CC值 (0-127, >=64为踩下)


@dataclass
class NoteEvent:
    """音符事件"""
    note: int           # MIDI音符号 (0-127)
    velocity: int       # 力度 (0-127)
    time: float         # 绝对时间(秒)
    duration: float     # 持续时间(秒)
    channel: int        # MIDI通道


@dataclass
class ChordEvent:
    """和弦事件"""
    chord_key: str          # 和弦对应的按键 (z, x, c, v, b, n, m)
    chord_name: str         # 和弦名称 (C, Dm, Em, F, G, Am, G7)
    notes: List[int]        # 组成音符
    time: float             # 时间
    duration: float         # 持续时间
    original_notes: List[NoteEvent] = field(default_factory=list)  # 原始音符事件


@dataclass
class GlissandoEvent:
    """滑奏事件"""
    time: float             # 开始时间
    duration: float         # 持续时间
    direction: str          # 方向: 'up', 'down', 'updown'
    start_note: int         # 起始音符
    end_note: int           # 结束音符
    note_count: int         # 音符数量
    interval: float         # 每个音符间隔(秒)
    original_notes: List[NoteEvent] = field(default_factory=list)  # 原始音符


@dataclass  
class PlayEvent:
    """统一的播放事件"""
    time: float
    duration: float
    is_chord: bool
    is_glissando: bool = False  # 是否是滑奏
    key: str = ''           # 要按的键
    midi_notes: List[int] = field(default_factory=list)   # 相关的MIDI音符
    original_event: Any = None    # 原始事件 (NoteEvent, ChordEvent 或 GlissandoEvent)


class ChordDetector:
    """
    增强版和弦检测器
    
    支持：
    1. 识别同时发声的音符是否构成已知和弦
    2. 支持移调后的和弦识别（歌曲移调到C大调后）
    3. 返回对应的Z-M和弦键
    4. 扩展识别：将更多和弦映射到最接近的游戏和弦
    """
    
    # 音符名称
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    # 游戏中Z-M键对应的和弦（基于C大调）
    GAME_CHORDS = {
        # 和弦名: (按键, 根音音级, 和弦类型, 和弦音程)
        'C':  ('z', 0, 'major', (0, 4, 7)),    # C-E-G
        'Dm': ('x', 2, 'minor', (0, 3, 7)),    # D-F-A  
        'Em': ('c', 4, 'minor', (0, 3, 7)),    # E-G-B
        'F':  ('v', 5, 'major', (0, 4, 7)),    # F-A-C
        'G':  ('b', 7, 'major', (0, 4, 7)),    # G-B-D
        'Am': ('n', 9, 'minor', (0, 3, 7)),    # A-C-E
        'G7': ('m', 7, 'dom7', (0, 4, 7, 10)), # G-B-D-F
    }
    
    # 扩展和弦识别：将其他常见和弦映射到最接近的游戏和弦
    # 格式: (根音, 和弦类型) -> 映射到的游戏和弦名
    CHORD_MAPPINGS = {
        # C系列
        (0, 'major'): 'C',
        (0, 'maj7'): 'C',      # Cmaj7 -> C
        (0, 'add9'): 'C',      # Cadd9 -> C
        (0, 'sus4'): 'C',      # Csus4 -> C
        (0, 'sus2'): 'C',      # Csus2 -> C
        (0, '6'): 'C',         # C6 -> C
        
        # D系列
        (2, 'minor'): 'Dm',
        (2, 'min7'): 'Dm',     # Dm7 -> Dm
        (2, 'minor_add9'): 'Dm',
        (2, 'major'): 'Dm',    # D大调 -> Dm (最接近)
        (2, 'dom7'): 'Dm',     # D7 -> Dm
        (2, 'sus4'): 'Dm',
        
        # E系列
        (4, 'minor'): 'Em',
        (4, 'min7'): 'Em',     # Em7 -> Em
        (4, 'major'): 'Em',    # E大调 -> Em (最接近)
        (4, 'dom7'): 'Em',     # E7 -> Em
        (4, 'sus4'): 'Em',
        
        # F系列
        (5, 'major'): 'F',
        (5, 'maj7'): 'F',      # Fmaj7 -> F
        (5, 'add9'): 'F',
        (5, 'sus4'): 'F',
        (5, '6'): 'F',
        (5, 'minor'): 'F',     # Fm -> F (最接近)
        
        # G系列
        (7, 'major'): 'G',
        (7, 'dom7'): 'G7',
        (7, 'maj7'): 'G',      # Gmaj7 -> G
        (7, 'add9'): 'G',
        (7, 'sus4'): 'G',
        (7, '6'): 'G',
        (7, 'minor'): 'G',     # Gm -> G (最接近)
        (7, 'min7'): 'G7',     # Gm7 -> G7
        
        # A系列
        (9, 'minor'): 'Am',
        (9, 'min7'): 'Am',     # Am7 -> Am
        (9, 'major'): 'Am',    # A大调 -> Am (最接近)
        (9, 'dom7'): 'Am',     # A7 -> Am
        (9, 'sus4'): 'Am',
        
        # B系列 (没有直接对应，映射到最接近的)
        (11, 'minor'): 'Em',   # Bm -> Em (五度关系)
        (11, 'dim'): 'G7',     # Bdim -> G7 (包含B-D-F)
        (11, 'min7b5'): 'G7',  # Bm7b5 -> G7
        (11, 'major'): 'G',    # B -> G (最接近)
        
        # 其他根音的常见和弦
        # C#/Db
        (1, 'major'): 'C',
        (1, 'minor'): 'Dm',
        (1, 'dim'): 'Dm',
        
        # D#/Eb
        (3, 'major'): 'Em',
        (3, 'minor'): 'Em',
        
        # F#/Gb
        (6, 'major'): 'G',
        (6, 'minor'): 'Em',
        (6, 'dim'): 'Em',
        
        # G#/Ab
        (8, 'major'): 'Am',
        (8, 'minor'): 'Am',
        
        # A#/Bb
        (10, 'major'): 'F',
        (10, 'minor'): 'Am',
        (10, 'dom7'): 'F',
    }
    
    # 和弦音程模式 -> 和弦类型
    INTERVAL_PATTERNS = {
        (0, 4, 7): 'major',           # 大三和弦
        (0, 3, 7): 'minor',           # 小三和弦
        (0, 4, 7, 10): 'dom7',        # 属七和弦
        (0, 4, 7, 11): 'maj7',        # 大七和弦
        (0, 3, 7, 10): 'min7',        # 小七和弦
        (0, 5, 7): 'sus4',            # 挂四和弦
        (0, 2, 7): 'sus2',            # 挂二和弦
        (0, 3, 6): 'dim',             # 减和弦
        (0, 4, 8): 'aug',             # 增和弦
        (0, 3, 6, 10): 'min7b5',      # 半减七和弦
        (0, 3, 6, 9): 'dim7',         # 减七和弦
        (0, 4, 7, 9): '6',            # 大六和弦
        (0, 3, 7, 9): 'min6',         # 小六和弦
        (0, 4, 7, 14): 'add9',        # 加九和弦 (简化为0,2,4,7)
        (0, 2, 4, 7): 'add9',         # 加九和弦
        (0, 2, 3, 7): 'minor_add9',   # 小加九
    }
    
    def __init__(self):
        # 构建快速查找表: (根音音级, 和弦音程) -> (按键, 和弦名)
        self.chord_lookup = {}
        for name, (key, root, ctype, intervals) in self.GAME_CHORDS.items():
            self.chord_lookup[(root, intervals)] = (key, name)
        
        # 构建仅基于音程的查找表
        self.interval_lookup = {}
        for name, (key, root, ctype, intervals) in self.GAME_CHORDS.items():
            if intervals not in self.interval_lookup:
                self.interval_lookup[intervals] = []
            self.interval_lookup[intervals].append((key, name, root))
    
    def _identify_chord_type(self, intervals: tuple) -> Optional[str]:
        """识别和弦类型"""
        # 精确匹配
        if intervals in self.INTERVAL_PATTERNS:
            return self.INTERVAL_PATTERNS[intervals]
        
        # 尝试匹配子集（处理额外音符）
        intervals_set = set(intervals)
        
        # 优先匹配七和弦
        for pattern, ctype in self.INTERVAL_PATTERNS.items():
            if len(pattern) >= 3 and set(pattern).issubset(intervals_set):
                return ctype
        
        # 检查是否包含基本三和弦
        if {0, 4, 7}.issubset(intervals_set):
            return 'major'
        if {0, 3, 7}.issubset(intervals_set):
            return 'minor'
        if {0, 3, 6}.issubset(intervals_set):
            return 'dim'
        if {0, 4, 8}.issubset(intervals_set):
            return 'aug'
        if {0, 5, 7}.issubset(intervals_set):
            return 'sus4'
        if {0, 2, 7}.issubset(intervals_set):
            return 'sus2'
        
        return None
    
    def detect_chord(self, notes: List[int], transpose: int = 0) -> Optional[Tuple[str, str, List[int]]]:
        """
        检测和弦
        
        Args:
            notes: MIDI音符列表（原始值，未移调）
            transpose: 当前的移调值（用于将和弦映射到C大调）
            
        Returns:
            (按键, 和弦名称, 和弦音符列表) 或 None
        """
        if len(notes) < 3:
            return None
        
        # 移调后的音符
        transposed = [n + transpose for n in notes]
        
        # 提取音级（0-11）
        pitch_classes = sorted(set(n % 12 for n in transposed))
        
        if len(pitch_classes) < 3:
            return None
        
        best_match = None
        
        # 尝试每个音作为根音
        for root in pitch_classes:
            # 计算相对于根音的音程
            intervals = tuple(sorted((pc - root) % 12 for pc in pitch_classes))
            
            # 1. 精确匹配游戏和弦
            if (root, intervals) in self.chord_lookup:
                key, name = self.chord_lookup[(root, intervals)]
                chord_notes = [n for n in notes if (n + transpose) % 12 in pitch_classes]
                return (key, name, chord_notes)
            
            # 2. 识别和弦类型并查找映射
            chord_type = self._identify_chord_type(intervals)
            if chord_type and (root, chord_type) in self.CHORD_MAPPINGS:
                game_chord = self.CHORD_MAPPINGS[(root, chord_type)]
                key = self.GAME_CHORDS[game_chord][0]
                chord_notes = [n for n in notes if (n + transpose) % 12 in pitch_classes]
                # 保存为候选（继续寻找更好的匹配）
                if best_match is None:
                    best_match = (key, game_chord, chord_notes)
            
            # 3. 尝试匹配三和弦子集
            for triad, ctype in [((0, 4, 7), 'major'), ((0, 3, 7), 'minor'), ((0, 3, 6), 'dim')]:
                if all(i in intervals for i in triad):
                    if (root, ctype) in self.CHORD_MAPPINGS:
                        game_chord = self.CHORD_MAPPINGS[(root, ctype)]
                        key = self.GAME_CHORDS[game_chord][0]
                        chord_notes = [n for n in notes if (n + transpose) % 12 in pitch_classes]
                        if best_match is None:
                            best_match = (key, game_chord, chord_notes)
        
        if best_match:
            return best_match
        
        # 4. 最后尝试：找最低音为根音，猜测和弦
        bass_note = min(transposed) % 12
        intervals = tuple(sorted((pc - bass_note) % 12 for pc in pitch_classes))
        chord_type = self._identify_chord_type(intervals)
        
        if chord_type:
            # 找最接近的游戏和弦
            for root_offset in [0, -1, 1, -2, 2]:  # 尝试附近的根音
                test_root = (bass_note + root_offset) % 12
                if (test_root, chord_type) in self.CHORD_MAPPINGS:
                    game_chord = self.CHORD_MAPPINGS[(test_root, chord_type)]
                    key = self.GAME_CHORDS[game_chord][0]
                    chord_notes = [n for n in notes if (n + transpose) % 12 in pitch_classes]
                    return (key, game_chord, chord_notes)
                # 尝试简化的和弦类型
                simple_type = 'major' if chord_type in ['maj7', 'add9', '6', 'sus4', 'sus2'] else \
                              'minor' if chord_type in ['min7', 'min6', 'minor_add9'] else None
                if simple_type and (test_root, simple_type) in self.CHORD_MAPPINGS:
                    game_chord = self.CHORD_MAPPINGS[(test_root, simple_type)]
                    key = self.GAME_CHORDS[game_chord][0]
                    chord_notes = [n for n in notes if (n + transpose) % 12 in pitch_classes]
                    return (key, game_chord, chord_notes)
        
        return None
    
    def get_chord_key(self, chord_name: str) -> Optional[str]:
        """获取和弦对应的按键"""
        if chord_name in self.GAME_CHORDS:
            return self.GAME_CHORDS[chord_name][0]
        return None
    
    def get_all_chord_keys(self) -> Dict[str, str]:
        """获取所有和弦到按键的映射"""
        return {name: info[0] for name, info in self.GAME_CHORDS.items()}


class MidiParser:
    """MIDI文件解析器 - 支持和弦识别和智能通道分析"""
    
    # GM乐器分类
    INSTRUMENT_CATEGORIES = {
        'piano': list(range(0, 8)),      # 钢琴类 0-7
        'chromatic': list(range(8, 16)), # 色彩打击乐 8-15
        'organ': list(range(16, 24)),    # 风琴 16-23
        'guitar': list(range(24, 32)),   # 吉他 24-31
        'bass': list(range(32, 40)),     # 贝斯 32-39
        'strings': list(range(40, 48)),  # 弦乐 40-47
        'ensemble': list(range(48, 56)), # 合奏 48-55
        'brass': list(range(56, 64)),    # 铜管 56-63
        'reed': list(range(64, 72)),     # 簧片 64-71
        'pipe': list(range(72, 80)),     # 管乐 72-79
        'synth_lead': list(range(80, 88)), # 合成主音 80-87
        'synth_pad': list(range(88, 96)),  # 合成铺底 88-95
        'synth_fx': list(range(96, 104)),  # 合成特效 96-103
        'ethnic': list(range(104, 112)),   # 民族乐器 104-111
        'percussive': list(range(112, 120)), # 打击乐 112-119
        'sfx': list(range(120, 128)),      # 音效 120-127
    }
    
    # 乐器优先级（主旋律 > 和声 > 贝斯）
    MELODY_INSTRUMENTS = ['piano', 'strings', 'synth_lead', 'pipe', 'reed', 'brass']
    HARMONY_INSTRUMENTS = ['organ', 'guitar', 'ensemble', 'synth_pad']
    BASS_INSTRUMENTS = ['bass']
    
    def __init__(self):
        self.midi_file: Optional[mido.MidiFile] = None
        self.notes: List[NoteEvent] = []
        self.chords: List[ChordEvent] = []
        self.play_events: List[PlayEvent] = []
        self.tempo = 500000  # 微秒/拍，500000 = 120 BPM
        self.bpm = 120.0  # 从MIDI文件读取的BPM
        self.tempo_changes: List[Tuple[float, int, float]] = []  # [(时间, tempo微秒, bpm)]
        self.ticks_per_beat = 480
        self.total_time = 0.0
        
        # 乐器和通道信息
        self.channel_instruments: Dict[int, int] = {}  # {channel: program}
        self.channel_categories: Dict[int, str] = {}   # {channel: category}
        self.track_names: List[str] = []
        
        # 智能分析结果
        self.melody_channels: List[int] = []    # 主旋律通道
        self.harmony_channels: List[int] = []   # 和声通道
        self.bass_channels: List[int] = []      # 贝斯通道
        self.recommended_transpose: Dict[int, int] = {}  # 推荐移调 {channel: semitones}
        self.recommended_global_octave_shift: int = 0     # 全局推荐八度偏移 (正=向上)
        
        # === 音高分部分析（按音高而非乐器） ===
        self.melody_notes: List[NoteEvent] = []   # 高音部（主旋律）
        self.bass_notes: List[NoteEvent] = []     # 低音部
        self.pitch_split_point: int = 60          # 分割点（默认C4）
        self.pitch_gap: int = 0                   # 高低音部间隔
        self.recommend_melody_only: bool = False  # 推荐只播放旋律
        
        # === MIDI调号信息 ===
        self.key_signatures: List[Tuple[float, int, str]] = []  # [(时间, key, mode)]
        self.primary_key: Optional[int] = None    # 主要调号 (0-11, C=0)
        self.primary_mode: Optional[str] = None   # 主要调式 ('major' or 'minor')
        
        self.chord_detector = ChordDetector()
        self.chord_detection_enabled = False  # 默认关闭和弦检测
        self.chord_time_threshold = 0.02  # 同时发声的时间阈值(秒)
        
        # 滑奏检测
        self.glissandos: List[GlissandoEvent] = []
        self.glissando_detection_enabled = True  # 默认开启滑奏检测
        
        # === 延音踏板（CC64）===
        self.sustain_events: List[SustainPedalEvent] = []  # 延音踏板事件列表
        self.has_sustain_pedal: bool = False  # MIDI文件是否包含延音踏板数据
        
    def load_file(self, filepath: str) -> bool:
        """加载MIDI文件"""
        try:
            # clip=True: 自动修正超出0-127范围的数据字节，兼容更多MIDI文件
            self.midi_file = mido.MidiFile(filepath, clip=True)
            self.ticks_per_beat = self.midi_file.ticks_per_beat
            
            # 先扫描一遍获取所有tempo和乐器信息
            self._scan_tempo()
            self._scan_instruments()
            self._scan_key_signatures()  # 扫描调号信息
            
            self._parse_notes()
            
            # 智能精简：过密的曲子自动重新编曲
            self._smart_rearrange()
            
            # 智能编曲：清理杂乱无章的歌曲
            self._intelligent_arrange()
            
            # 极速段检测与时间拉伸
            self._humanize_speed()
            
            # 智能分析通道
            self._analyze_channels()
            
            # 按音高智能分析高/低音部（多因子分析）
            self._analyze_pitch_parts()
            
            self._detect_chords()
            self._detect_glissandos()  # 滑奏检测
            self._build_play_events()
            return True
        except Exception as e:
            print(f"加载MIDI文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _smart_rearrange(self):
        """
        智能精简过密曲目
        
        当音符密度过高（人手无法弹奏）时，自动重新编曲：
        1. 保留旋律线（每个时刻的最高音）
        2. 保留低音基础（每个节拍的最低音）
        3. 去除快速重复音
        4. 简化过密和弦（保留骨架音）
        5. 合并过近的同音
        
        触发条件：平均密度 > 12 notes/sec（人手极限约 10-15 notes/sec）
        """
        if not self.notes or self.total_time <= 0:
            return
        
        return  # 不丢弃音符：全部音符交由播放器处理
        
        density = len(self.notes) / self.total_time
        
        if density <= 18:
            return  # 密度正常，不需要精简
        
        original_count = len(self.notes)
        print(f"[智能编曲] 检测到过密曲目: {original_count}音符/{self.total_time:.0f}秒 "
              f"(密度={density:.1f}notes/s, 阈值=18)")
        
        # === 第一步：按时间窗口分组（50ms窗口 ≈ 同时发声） ===
        WINDOW_MS = 0.05  # 50ms
        time_groups = []   # [(window_start, [notes])]
        current_group = []
        group_start = self.notes[0].time
        
        for note in self.notes:
            if note.time - group_start > WINDOW_MS and current_group:
                time_groups.append((group_start, current_group))
                current_group = [note]
                group_start = note.time
            else:
                current_group.append(note)
        if current_group:
            time_groups.append((group_start, current_group))
        
        # === 第二步：智能筛选每个时间窗口的音符 ===
        MAX_SIMULTANEOUS = 6  # 每个时刻最多保留6个音符
        MIN_REPEAT_GAP = 0.04  # 同音重复最小间隔40ms
        
        kept_notes = []
        last_note_time = {}  # {pitch: last_time} 用于去重复
        
        # 计算每拍时长用于低音保留
        beat_duration = 60.0 / max(self.bpm, 60)
        last_bass_beat = -1
        
        for group_time, group_notes in time_groups:
            if not group_notes:
                continue
            
            # 去除同音快速重复
            filtered = []
            for n in group_notes:
                last_t = last_note_time.get(n.note, -999)
                if n.time - last_t >= MIN_REPEAT_GAP:
                    filtered.append(n)
            
            if not filtered:
                continue
            
            # 如果同时音符不超过限制，全部保留
            if len(filtered) <= MAX_SIMULTANEOUS:
                for n in filtered:
                    kept_notes.append(n)
                    last_note_time[n.note] = n.time
                continue
            
            # 过多同时音符 → 保留骨架
            # 按音高排序
            filtered.sort(key=lambda x: x.note)
            
            selected = []
            
            # 1. 保留最高音（旋律）
            selected.append(filtered[-1])
            
            # 2. 保留最低音（低音基础）
            if filtered[0] not in selected:
                selected.append(filtered[0])
            
            # 3. 保留力度最大的（重要性）
            remaining = [n for n in filtered if n not in selected]
            remaining.sort(key=lambda x: x.velocity, reverse=True)
            
            # 4. 优先保留五度音
            root = filtered[0].note
            for n in remaining[:]:
                if len(selected) >= MAX_SIMULTANEOUS:
                    break
                if (n.note - root) % 12 == 7:  # 五度音
                    selected.append(n)
                    remaining.remove(n)
            
            # 5. 填充剩余名额
            for n in remaining:
                if len(selected) >= MAX_SIMULTANEOUS:
                    break
                selected.append(n)
            
            for n in selected:
                kept_notes.append(n)
                last_note_time[n.note] = n.time
        
        # === 第三步：确保低音节奏骨架 ===
        # 每拍至少保留一个低音，避免完全丢失低音部
        kept_notes.sort(key=lambda x: x.time)
        
        final_count = len(kept_notes)
        reduction = (1 - final_count / original_count) * 100
        new_density = final_count / self.total_time if self.total_time > 0 else 0
        
        print(f"[智能编曲] 精简完成: {original_count} → {final_count}音符 "
              f"(减少{reduction:.0f}%, 新密度={new_density:.1f}notes/s)")
        
        # 检查是否仍然过密，进行第二轮更激进的精简
        if new_density > 25:
            # 进一步精简：只保留旋律线+稀疏低音
            print(f"[智能编曲] 仍然过密，进行第二轮精简...")
            
            melody_only = []
            last_pitch_time = {}
            
            # 重新分组
            time_groups2 = []
            current_group2 = []
            group_start2 = kept_notes[0].time if kept_notes else 0
            
            for note in kept_notes:
                if note.time - group_start2 > WINDOW_MS and current_group2:
                    time_groups2.append((group_start2, current_group2))
                    current_group2 = [note]
                    group_start2 = note.time
                else:
                    current_group2.append(note)
            if current_group2:
                time_groups2.append((group_start2, current_group2))
            
            for _, gn in time_groups2:
                if not gn:
                    continue
                # 只保留最高音(旋律)和最低音(低音)
                gn.sort(key=lambda x: x.note)
                melody_only.append(gn[-1])
                if len(gn) > 1 and gn[0].note != gn[-1].note:
                    melody_only.append(gn[0])
            
            melody_only.sort(key=lambda x: x.time)
            kept_notes = melody_only
            
            final_count2 = len(kept_notes)
            print(f"[智能编曲] 第二轮: {final_count} → {final_count2}音符 "
                  f"(新密度={final_count2/self.total_time:.1f}notes/s)")
        
        self.notes = kept_notes
    
    def _intelligent_arrange(self):
        """
        智能编曲算法 - 清理杂乱无章的歌曲，保留主旋律
        
        借鉴专业编曲软件的思路（如MuseScore的音符简化、Band-in-a-Box的智能编曲）：
        
        核心原则：
        1. 主旋律神圣不可侵犯 - 只清理伴奏，不改变旋律走向
        2. 保留和声骨架 - 每个和弦保留根音、三度、五度
        3. 删除装饰性噪音 - 快速经过音、无规律的伴奏碎片
        4. 保持节奏脉搏 - 保留强拍低音和规律节奏型
        5. 动态密度控制 - 安静段落保留更多细节，密集段适当简化
        
        目标：让杂乱的曲子弹起来更干净好听，同时不失去原曲特色
        
        触发条件：
        - 音符密度 > 8 notes/sec 的段落占比 > 40%
        - 或同时发声音符经常 > 6个
        """
        if not self.notes or self.total_time <= 0:
            return
        
        return  # 不丢弃音符：全部音符交由播放器处理
        
        sorted_notes = sorted(self.notes, key=lambda n: n.time)
        density = len(sorted_notes) / self.total_time
        
        # === 分析歌曲是否需要智能编曲 ===
        # 统计"杂乱"段落占比
        WINDOW = 0.5  # 500ms分析窗口
        DENSITY_THRESHOLD = 14  # 每秒14个音符以上视为密集
        SIMULTANEOUS_THRESHOLD = 8  # 同时8个音符以上视为过密
        
        dense_windows = 0
        total_windows = 0
        thick_chords = 0
        
        t = 0
        while t < self.total_time:
            window_notes = [n for n in sorted_notes if t <= n.time < t + WINDOW]
            total_windows += 1
            
            if len(window_notes) / WINDOW > DENSITY_THRESHOLD:
                dense_windows += 1
            
            # 检查同时发声数
            if window_notes:
                sub_window = 0.05  # 50ms
                for sub_t in [t + i * sub_window for i in range(int(WINDOW / sub_window))]:
                    simultaneous = sum(1 for n in window_notes if sub_t <= n.time < sub_t + sub_window)
                    if simultaneous > SIMULTANEOUS_THRESHOLD:
                        thick_chords += 1
            
            t += WINDOW
        
        dense_ratio = dense_windows / max(total_windows, 1)
        
        if dense_ratio < 0.50 and thick_chords < 20 and density <= 14:
            return  # 歌曲不杂乱，不需要处理
        
        print(f"[智能编曲] 检测到杂乱段落: 密集段{dense_ratio:.0%}, 厚重和弦{thick_chords}处, "
              f"平均密度{density:.1f}n/s")
        
        original_count = len(sorted_notes)
        bpm = self.bpm if hasattr(self, 'bpm') and self.bpm else 120
        beat_duration = 60.0 / bpm
        
        # === 第一步：提取主旋律线（Skyline算法）===
        # Skyline算法：在每个时间点取最高音作为旋律
        melody_line = self._extract_skyline_melody(sorted_notes, beat_duration)
        melody_set = set(id(n) for n in melody_line)
        
        # === 第二步：提取低音根音线 ===
        bass_line = self._extract_bass_line(sorted_notes, beat_duration)
        bass_set = set(id(n) for n in bass_line)
        
        # === 第三步：评估每个音符的重要性 ===
        note_importance = {}  # id(note) -> importance_score (0-1)
        
        for note in sorted_notes:
            score = 0.0
            nid = id(note)
            
            # 1. 旋律音 = 最高优先级
            if nid in melody_set:
                score += 0.8
            
            # 2. 低音根音 = 高优先级
            if nid in bass_set:
                score += 0.6
            
            # 3. 力度贡献（强音更重要）
            score += (note.velocity / 127.0) * 0.15
            
            # 4. 时值贡献（长音符更重要）
            if note.duration > beat_duration:
                score += 0.15
            elif note.duration > beat_duration * 0.5:
                score += 0.08
            
            # 5. 节拍位置（强拍上的音符更重要）
            beat_pos = (note.time % beat_duration) / beat_duration
            if beat_pos < 0.1 or abs(beat_pos - 0.5) < 0.1:  # 第1拍或第3拍
                score += 0.1
            
            # 6. 和弦音（与旋律同时的和声支撑）
            is_chord_tone = False
            for mn in melody_line:
                if abs(note.time - mn.time) < 0.05 and note.note != mn.note:
                    interval = abs(note.note - mn.note) % 12
                    if interval in (0, 3, 4, 5, 7, 8, 9):  # 和弦音程
                        is_chord_tone = True
                        score += 0.12
                        break
            
            note_importance[nid] = min(1.0, score)
        
        # === 第四步：基于密度的动态筛选 ===
        # 密集段落降低阈值（删更多），稀疏段落保留更多
        kept_notes = []
        
        t = 0
        while t < self.total_time:
            window_notes = [n for n in sorted_notes if t <= n.time < t + WINDOW]
            window_density = len(window_notes) / WINDOW
            
            if window_density <= 10:
                # 稀疏段：保留所有
                kept_notes.extend(window_notes)
            else:
                # 密集段：根据重要性筛选
                # 目标密度：10-12 notes/sec
                target_count = max(4, int(10 * WINDOW))
                
                # 按重要性排序
                scored = [(n, note_importance.get(id(n), 0)) for n in window_notes]
                scored.sort(key=lambda x: x[1], reverse=True)
                
                # 保留最重要的音符
                for n, score in scored[:target_count]:
                    kept_notes.append(n)
                
                # 额外保留所有旋律音和低音根音（即使超出配额）
                for n, score in scored[target_count:]:
                    nid = id(n)
                    if nid in melody_set or nid in bass_set:
                        kept_notes.append(n)
            
            t += WINDOW
        
        # 去重并按时间排序
        seen = set()
        unique_kept = []
        for n in kept_notes:
            nid = id(n)
            if nid not in seen:
                seen.add(nid)
                unique_kept.append(n)
        
        unique_kept.sort(key=lambda x: x.time)
        
        final_count = len(unique_kept)
        if final_count < original_count * 0.95:  # 只在实际减少5%以上时才应用
            self.notes = unique_kept
            reduction = (1 - final_count / original_count) * 100
            new_density = final_count / self.total_time if self.total_time > 0 else 0
            print(f"[智能编曲] 清理完成: {original_count} → {final_count}音符 "
                  f"(减少{reduction:.0f}%, 新密度={new_density:.1f}notes/s)")
        else:
            print(f"[智能编曲] 歌曲结构良好，保持原样")
    
    def _extract_skyline_melody(self, sorted_notes: list, beat_duration: float) -> list:
        """
        Skyline算法提取主旋律线
        
        原理：在每个时间窗口取最高音，然后用声部追踪(voice leading)
        确保旋律线连贯。避免把伴奏中偶尔出现的高音当作旋律。
        
        改进：
        1. 连续性检查：旋律跳跃不应过大（>12半音可疑）
        2. 力度检查：旋律通常力度较强
        3. 通道一致性：同一通道的音符更可能是同一声部
        """
        if not sorted_notes:
            return []
        
        melody = []
        WINDOW = 0.08  # 80ms窗口（比50ms稍大，更好捕捉旋律）
        last_melody_note = None
        last_melody_channel = None
        
        t = sorted_notes[0].time
        end_time = sorted_notes[-1].time + 0.1
        
        while t < end_time:
            window_notes = [n for n in sorted_notes if t <= n.time < t + WINDOW]
            
            if not window_notes:
                t += WINDOW
                continue
            
            # 候选：窗口内最高音
            candidates = sorted(window_notes, key=lambda n: n.note, reverse=True)
            
            best = None
            best_score = -1
            
            for candidate in candidates[:3]:  # 检查前3个最高音
                score = candidate.note / 127.0 * 0.4  # 高音优先
                score += candidate.velocity / 127.0 * 0.25  # 力度
                score += min(candidate.duration / beat_duration, 1.0) * 0.15  # 时值
                
                # 连续性奖励：与上一个旋律音距离近
                if last_melody_note is not None:
                    interval = abs(candidate.note - last_melody_note.note)
                    if interval <= 7:  # 五度以内 = 旋律连贯
                        score += 0.15
                    elif interval <= 12:  # 八度以内
                        score += 0.05
                    else:  # 超过八度 = 可能不是旋律
                        score -= 0.1
                
                # 通道一致性奖励
                if last_melody_channel is not None and candidate.channel == last_melody_channel:
                    score += 0.05
                
                if score > best_score:
                    best_score = score
                    best = candidate
            
            if best:
                melody.append(best)
                last_melody_note = best
                last_melody_channel = best.channel
            
            t += WINDOW
        
        return melody
    
    def _extract_bass_line(self, sorted_notes: list, beat_duration: float) -> list:
        """
        提取低音根音线
        
        策略：
        1. 每个小节的强拍（第1拍、第3拍）保留最低音
        2. 连续的低音线条保留（行进低音）
        3. 力度强的低音保留（和弦根音）
        """
        if not sorted_notes:
            return []
        
        bass_notes = []
        measure_duration = beat_duration * 4  # 假设4/4拍
        
        # 按小节分组
        t = 0
        while t < self.total_time:
            # 强拍位置（第1拍和第3拍）
            for beat_offset in [0, beat_duration * 2]:
                beat_time = t + beat_offset
                beat_end = beat_time + beat_duration
                
                beat_notes = [n for n in sorted_notes if beat_time <= n.time < beat_end]
                if beat_notes:
                    # 取最低音
                    lowest = min(beat_notes, key=lambda n: n.note)
                    bass_notes.append(lowest)
            
            t += measure_duration
        
        return bass_notes
    
    def _humanize_speed(self):
        """
        极速段检测与时间拉伸 - 让超人速度的段落变得人类可弹
        
        检测逻辑：
        1. 滑动窗口扫描，找出音符密度 > 15 notes/sec 的段落
        2. 在这些段落中，将音符时间微调（拉伸），使密度降到 ~12 notes/sec
        3. 不改变整体时长，只对局部极速段做时间扩展
        4. 保持音符间的相对时序关系
        
        核心原则：
        - 只处理真正不可能弹奏的速度（>15n/s）
        - 拉伸幅度最小化，尽量不影响听感
        - 不删除音符，只调整时间
        """
        if not self.notes or self.total_time <= 0:
            return
        
        sorted_notes = sorted(self.notes, key=lambda n: n.time)
        
        # === 检测极速段落 ===
        WINDOW = 0.3  # 300ms窗口
        HUMAN_MAX_DENSITY = 14  # 人类极限约14notes/sec（考虑和弦）
        TARGET_DENSITY = 11     # 目标密度
        
        fast_segments = []  # [(start_time, end_time, current_density)]
        
        t = 0
        while t < self.total_time:
            window_notes = [n for n in sorted_notes if t <= n.time < t + WINDOW]
            window_density = len(window_notes) / WINDOW
            
            if window_density > HUMAN_MAX_DENSITY:
                fast_segments.append((t, t + WINDOW, window_density))
            
            t += WINDOW * 0.5  # 50%重叠
        
        if not fast_segments:
            return
        
        # 合并相邻的极速段
        merged_segments = []
        if fast_segments:
            current = list(fast_segments[0])
            for start, end, density in fast_segments[1:]:
                if start <= current[1] + WINDOW:
                    current[1] = end
                    current[2] = max(current[2], density)
                else:
                    merged_segments.append(tuple(current))
                    current = [start, end, density]
            merged_segments.append(tuple(current))
        
        total_fast_time = sum(e - s for s, e, _ in merged_segments)
        print(f"[速度优化] 检测到 {len(merged_segments)} 个极速段落 "
              f"(合计{total_fast_time:.1f}秒, 最高密度{max(d for _,_,d in merged_segments):.0f}n/s)")
        
        # === 对极速段落进行时间微拉伸 ===
        # 策略：将极速段内的音符时间等比拉伸，使密度降到目标值
        # 后续音符的时间向后推移
        
        # BPM 保护：拉伸因子上限 = 1/0.85 ≈ 1.176（最多减速到原速85%）
        # 对应：不允许 BPM 变慢超过 15%，也不能快过 15%（此函数只拉伸不压缩）
        MAX_STRETCH = 1.0 / 0.85          # ≈ 1.176 → BPM 最低为原始的 85%
        MAX_TOTAL_RATIO = 1.0 / 0.85      # 全曲累积总时长变化不超过此倍数
        
        time_shift = 0.0  # 累积时间偏移
        notes_adjusted = 0
        original_total_time = self.total_time
        
        for seg_start, seg_end, seg_density in merged_segments:
            if seg_density <= HUMAN_MAX_DENSITY:
                continue
            
            # 全局保护：如果已经累积拉伸超过上限，停止继续拉伸
            if (original_total_time + time_shift) / original_total_time >= MAX_TOTAL_RATIO:
                print(f"[速度优化] 已达BPM下限(85%)，停止继续拉伸")
                break
            
            # 单段拉伸系数：密度比值，但不超过 MAX_STRETCH
            stretch_ratio = min(seg_density / TARGET_DENSITY, MAX_STRETCH)
            
            seg_duration = seg_end - seg_start
            new_duration = seg_duration * stretch_ratio
            time_added = new_duration - seg_duration
            
            # 精确控制：不超出全局总时长上限
            budget_left = original_total_time * MAX_TOTAL_RATIO - original_total_time - time_shift
            if time_added > budget_left:
                time_added = max(0.0, budget_left)
                new_duration = seg_duration + time_added
                stretch_ratio = new_duration / seg_duration if seg_duration > 0 else 1.0
            
            # 调整该段内的音符时间
            for note in sorted_notes:
                if seg_start + time_shift <= note.time < seg_end + time_shift:
                    # 段内音符：按比例拉伸
                    relative_pos = (note.time - seg_start - time_shift) / seg_duration
                    note.time = seg_start + time_shift + relative_pos * new_duration
                    notes_adjusted += 1
                elif note.time >= seg_end + time_shift:
                    # 段后音符：整体后移
                    note.time += time_added
            
            time_shift += time_added
        
        if time_shift > 0:
            self.total_time += time_shift
            bpm_ratio = original_total_time / self.total_time  # 拉伸后BPM变慢
            print(f"[速度优化] 已拉伸 {notes_adjusted} 个音符, "
                  f"总时长增加 {time_shift:.2f}秒 ({time_shift/self.total_time*100:.1f}%), "
                  f"BPM变化: {bpm_ratio:.2%} (范围: 85%~115%)")
    
    def _analyze_pitch_parts(self):
        """
        智能音部分析 - 多因子分割（不只按音高）
        
        改进策略（解决低音太多扰乱主旋律的问题）：
        1. Skyline旋律追踪：用声部追踪算法识别真正的旋律线
        2. 通道分析：MIDI通道信息辅助判断（不同通道通常是不同声部）
        3. 节奏角色分析：持续低音 vs 旋律性低音
        4. 密度感知：某段时间只有低音时，那是旋律不是伴奏
        5. 力度模式：旋律通常力度更强且有变化
        """
        if not self.notes:
            return
        
        all_pitches = [n.note for n in self.notes]
        pitch_min = min(all_pitches)
        pitch_max = max(all_pitches)
        total_range = pitch_max - pitch_min
        
        sorted_notes = sorted(self.notes, key=lambda n: n.time)
        bpm = self.bpm if hasattr(self, 'bpm') and self.bpm else 120
        beat_duration = 60.0 / bpm
        
        # === 第一步：Skyline旋律线追踪 ===
        window_size = 0.08  # 80ms
        melody_line_pitches = []
        melody_line_notes = []  # 保存实际的NoteEvent
        
        i = 0
        last_melody_pitch = None
        
        while i < len(sorted_notes):
            window_start = sorted_notes[i].time
            window_end = window_start + window_size
            
            window_notes = []
            j = i
            while j < len(sorted_notes) and sorted_notes[j].time < window_end:
                window_notes.append(sorted_notes[j])
                j += 1
            
            if window_notes:
                # 智能选择旋律音（不一定是最高音）
                best_note = None
                best_score = -1
                
                for n in window_notes:
                    score = n.note / 127.0 * 0.35  # 高音倾向
                    score += n.velocity / 127.0 * 0.25  # 力度
                    score += min(n.duration / beat_duration, 1.0) * 0.15  # 时值
                    
                    # 连续性：与上一个旋律音距离近
                    if last_melody_pitch is not None:
                        interval = abs(n.note - last_melody_pitch)
                        if interval <= 5:
                            score += 0.2
                        elif interval <= 12:
                            score += 0.1
                        elif interval > 24:
                            score -= 0.15  # 超过2个八度跳跃，可能不是旋律
                    
                    if score > best_score:
                        best_score = score
                        best_note = n
                
                if best_note:
                    melody_line_pitches.append(best_note.note)
                    melody_line_notes.append(best_note)
                    last_melody_pitch = best_note.note
            
            i = j if j > i else i + 1
        
        # === 第二步：通道分析辅助 ===
        # 统计每个通道的平均音高，确定哪些通道是低音声部
        channel_stats = {}
        for note in self.notes:
            ch = note.channel
            if ch not in channel_stats:
                channel_stats[ch] = {'pitches': [], 'velocities': [], 'count': 0}
            channel_stats[ch]['pitches'].append(note.note)
            channel_stats[ch]['velocities'].append(note.velocity)
            channel_stats[ch]['count'] += 1
        
        bass_channels = set()
        melody_channels = set()
        for ch, stats in channel_stats.items():
            avg_pitch = sum(stats['pitches']) / len(stats['pitches'])
            if avg_pitch < 55:  # 平均音高低于G3，大概率是低音声部
                bass_channels.add(ch)
            elif avg_pitch > 65:  # 平均音高高于F4，大概率是旋律声部
                melody_channels.add(ch)
        
        # === 第三步：计算智能分割点（最大音高间隙法 / Largest Pitch Gap）===
        # 标准MIR方法（Cambouropoulos 2006等）：
        #   在音高分布中，找高低音区之间音高值最稀疏的间隙作为分割点。
        #   默认分割点 = C4(60)，即钢琴五线谱高低音谱号分界线。
        #   只有当分布中存在 ≥3 半音的明显间隙，且两侧各有 ≥5% 的音符时，
        #   才用间隙中点替代默认值。
        SPLIT_SEARCH_MIN = 36   # C2 搜索范围下限
        SPLIT_SEARCH_MAX = 72   # C5 搜索范围上限
        
        pitch_counts: Dict[int, int] = {}
        for p in all_pitches:
            pitch_counts[p] = pitch_counts.get(p, 0) + 1
        
        unique_sorted_pitches = sorted(pitch_counts.keys())
        best_gap = 0
        best_split = 60  # 默认 C4
        
        for _idx in range(len(unique_sorted_pitches) - 1):
            lo = unique_sorted_pitches[_idx]
            hi = unique_sorted_pitches[_idx + 1]
            gap = hi - lo
            mid = (lo + hi) // 2
            if SPLIT_SEARCH_MIN <= mid <= SPLIT_SEARCH_MAX and gap >= 3 and gap > best_gap:
                lo_count = sum(pitch_counts.get(p, 0) for p in unique_sorted_pitches[:_idx + 1])
                hi_count = sum(pitch_counts.get(p, 0) for p in unique_sorted_pitches[_idx + 1:])
                # 两侧各需至少 5% 的音符，排除边缘孤立音偷走分割点
                if min(lo_count, hi_count) >= len(all_pitches) * 0.05:
                    best_gap = gap
                    best_split = mid
        
        self.pitch_split_point = best_split
        # 安全边界：确保分割点在实际音域内
        self.pitch_split_point = max(pitch_min, min(pitch_max - 5, self.pitch_split_point))
        
        # 旋律线中位音（供后续打印统计）
        if melody_line_pitches:
            melody_sorted = sorted(melody_line_pitches)
            melody_median = melody_sorted[len(melody_sorted) // 2]
        else:
            melody_median = (pitch_min + pitch_max) // 2
        
        # === 第四步：智能分割（多因子，不只看音高）===
        self.melody_notes = []
        self.bass_notes = []
        
        # 对每个音符进行智能分类
        melody_note_set = set(id(n) for n in melody_line_notes)
        
        for note in self.notes:
            is_melody = False
            
            # 规则1：被Skyline算法识别为旋律的音符 → 旋律
            if id(note) in melody_note_set:
                is_melody = True
            # 规则2：音高高于分割点 → 旋律
            elif note.note >= self.pitch_split_point:
                is_melody = True
            # 规则3：虽然低音高，但属于旋律通道 → 旋律
            elif note.channel in melody_channels and note.note >= self.pitch_split_point - 5:
                is_melody = True
            # 规则4：低音但是时值很长（旋律性低音） → 旋律
            elif note.duration > beat_duration * 2 and note.velocity > 80:
                is_melody = True
            # 规则5：低音段落中的唯一声部（低音独奏） → 旋律
            # (在该时间窗口内没有高音，低音就是旋律)
            elif note.note < self.pitch_split_point:
                # 检查附近是否有高音
                has_nearby_melody = False
                for mn in melody_line_notes:
                    if abs(mn.time - note.time) < beat_duration and mn.note >= self.pitch_split_point:
                        has_nearby_melody = True
                        break
                if not has_nearby_melody:
                    is_melody = True  # 没有高音伴随，低音就是旋律
            
            if is_melody:
                self.melody_notes.append(note)
            else:
                # 额外过滤：低音中的重复模式（持续低音伴奏）
                # 如果同一个低音在短时间内重复出现多次，标记为伴奏型低音
                self.bass_notes.append(note)
        
        # === 第五步：低音部去重复模式（减少扰乱） ===
        # 检测低音中的重复伴奏模式，标记为可减持
        if self.bass_notes:
            bass_sorted = sorted(self.bass_notes, key=lambda n: n.time)
            pattern_bass = []  # 有规律的伴奏低音
            non_pattern_bass = []  # 非规律低音（保留更多）
            
            # 检测连续重复音（同一个音高反复出现）
            repeat_count = {}  # pitch -> [(time, note)]
            for note in bass_sorted:
                pc = note.note % 12  # 音名
                if pc not in repeat_count:
                    repeat_count[pc] = []
                repeat_count[pc].append(note)
            
            # 标记高重复度的低音（同一音名出现次数占低音总数的40%以上）
            heavy_repeat_pitches = set()
            for pc, notes_list in repeat_count.items():
                if len(notes_list) > len(bass_sorted) * 0.40:
                    heavy_repeat_pitches.add(pc)
            
            # 对重复度高的低音进行稀疏化：每拍只保留一个
            for note in bass_sorted:
                pc = note.note % 12
                if pc in heavy_repeat_pitches:
                    pattern_bass.append(note)
                else:
                    non_pattern_bass.append(note)
            
            # 稀疏化重复低音：每拍保留一个
            if pattern_bass:
                sparse_pattern = []
                last_kept_time = {}
                for note in pattern_bass:
                    pc = note.note % 12
                    last_t = last_kept_time.get(pc, -beat_duration * 2)
                    if note.time - last_t >= beat_duration:
                        sparse_pattern.append(note)
                        last_kept_time[pc] = note.time
                
                self.bass_notes = non_pattern_bass + sparse_pattern
                self.bass_notes.sort(key=lambda n: n.time)
                
                removed = len(pattern_bass) - len(sparse_pattern)
                if removed > 0:
                    print(f"[音部分析] 低音去重复: 移除 {removed} 个重复伴奏低音")
        
        # 空隙
        if self.bass_notes and self.melody_notes:
            self.pitch_gap = min(n.note for n in self.melody_notes) - max(n.note for n in self.bass_notes)
        else:
            self.pitch_gap = 0
        
        # 推荐只播放旋律
        if self.melody_notes and self.bass_notes:
            melody_avg = sum(n.note for n in self.melody_notes) / len(self.melody_notes)
            bass_avg = sum(n.note for n in self.bass_notes) / len(self.bass_notes)
            part_distance = melody_avg - bass_avg
            bass_ratio = len(self.bass_notes) / len(self.notes)
            melody_ratio = len(self.melody_notes) / len(self.notes)
            
            self.recommend_melody_only = (
                part_distance > 30 and 
                bass_ratio > 0.3 and 
                melody_ratio > 0.3
            )
        else:
            self.recommend_melody_only = False
        
        # 打印
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        def midi_to_name(m):
            return f"{note_names[m % 12]}{m // 12 - 1}"
        
        total_range = pitch_max - pitch_min
        melody_min = min(melody_line_pitches) if melody_line_pitches else pitch_min
        melody_max = max(melody_line_pitches) if melody_line_pitches else pitch_max
        
        print(f"[音部分析] 总音域: {midi_to_name(pitch_min)}-{midi_to_name(pitch_max)} ({total_range}半音)")
        print(f"[音部分析] 旋律线: {midi_to_name(melody_min)}-{midi_to_name(melody_max)} (中位{midi_to_name(melody_median)})")
        print(f"[音部分析] 分割点: {midi_to_name(self.pitch_split_point)}, 空隙: {self.pitch_gap}半音")
        print(f"[音部分析] 主旋律: {len(self.melody_notes)}音符, 低音部: {len(self.bass_notes)}音符")
        if bass_channels:
            print(f"[音部分析] 低音通道: {bass_channels}, 旋律通道: {melody_channels}")
        if self.recommend_melody_only:
            print(f"[音部分析] ! 高低音撕裂严重，推荐只播放主旋律")
    
    def get_pitch_analysis(self) -> dict:
        """获取音高分析结果"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        def midi_to_name(m):
            return f"{note_names[m % 12]}{m // 12 - 1}"
        
        result = {
            'melody_count': len(self.melody_notes),
            'bass_count': len(self.bass_notes),
            'split_point': self.pitch_split_point,
            'split_point_name': midi_to_name(self.pitch_split_point) if self.pitch_split_point else 'N/A',
            'pitch_gap': self.pitch_gap,
            'recommend_melody_only': self.recommend_melody_only,
        }
        
        if self.melody_notes:
            melody_pitches = [n.note for n in self.melody_notes]
            result['melody_range'] = (min(melody_pitches), max(melody_pitches))
            result['melody_range_names'] = (midi_to_name(min(melody_pitches)), midi_to_name(max(melody_pitches)))
        
        if self.bass_notes:
            bass_pitches = [n.note for n in self.bass_notes]
            result['bass_range'] = (min(bass_pitches), max(bass_pitches))
            result['bass_range_names'] = (midi_to_name(min(bass_pitches)), midi_to_name(max(bass_pitches)))
        
        return result
    
    def _scan_instruments(self):
        """扫描乐器信息"""
        if self.midi_file is None:
            return
        
        self.channel_instruments = {}
        self.channel_categories = {}
        self.track_names = []
        
        for track in self.midi_file.tracks:
            for msg in track:
                if msg.type == 'track_name':
                    self.track_names.append(msg.name)
                elif msg.type == 'program_change':
                    ch = msg.channel
                    prog = msg.program
                    self.channel_instruments[ch] = prog
                    
                    # 确定乐器类别
                    for category, programs in self.INSTRUMENT_CATEGORIES.items():
                        if prog in programs:
                            self.channel_categories[ch] = category
                            break
    
    def _get_instrument_category(self, program: int) -> str:
        """获取乐器类别"""
        for category, programs in self.INSTRUMENT_CATEGORIES.items():
            if program in programs:
                return category
        return 'unknown'
    
    def _analyze_channels(self):
        """智能分析通道，根据音高分布和乐器类型分类"""
        self.melody_channels = []
        self.harmony_channels = []
        self.bass_channels = []
        self.recommended_transpose = {}
        
        # 收集每个通道的音符统计
        channel_stats = {}
        for note in self.notes:
            ch = note.channel
            if ch not in channel_stats:
                channel_stats[ch] = {
                    'notes': [],
                    'count': 0,
                    'min_note': 127,
                    'max_note': 0,
                    'avg_note': 0,
                }
            stats = channel_stats[ch]
            stats['notes'].append(note.note)
            stats['count'] += 1
            stats['min_note'] = min(stats['min_note'], note.note)
            stats['max_note'] = max(stats['max_note'], note.note)
        
        # 计算平均音高并分类
        for ch, stats in channel_stats.items():
            if stats['notes']:
                stats['avg_note'] = sum(stats['notes']) / len(stats['notes'])
            
            # 获取乐器类别
            category = self.channel_categories.get(ch, 'piano')  # 默认钢琴
            
            # 根据音高范围和乐器类型分类
            avg = stats['avg_note']
            
            if category in self.BASS_INSTRUMENTS or avg < 48:
                # 贝斯或低音通道
                self.bass_channels.append(ch)
                # 推荐移调到低音区 (48-59) Z-M
                target_center = 54  # Z-M行中心
                self.recommended_transpose[ch] = int(target_center - avg)
            elif avg >= 72:
                # 高音通道 - 主旋律
                self.melody_channels.append(ch)
                # 推荐移调到高音区 (72-83) Q-U
                target_center = 78  # Q-U行中心
                self.recommended_transpose[ch] = int(target_center - avg) if abs(target_center - avg) > 6 else 0
            elif avg >= 60:
                # 中音通道 - 主旋律或和声
                if category in self.MELODY_INSTRUMENTS:
                    self.melody_channels.append(ch)
                else:
                    self.harmony_channels.append(ch)
                target_center = 66  # A-J行中心
                self.recommended_transpose[ch] = int(target_center - avg) if abs(target_center - avg) > 6 else 0
            else:
                # 低音通道 - 和声或贝斯
                if category in self.BASS_INSTRUMENTS:
                    self.bass_channels.append(ch)
                else:
                    self.harmony_channels.append(ch)
                target_center = 54  # Z-M行中心
                self.recommended_transpose[ch] = int(target_center - avg) if abs(target_center - avg) > 6 else 0
        
        # === 全局八度偏移推荐 ===
        # 综合所有音符, 当整体偏低时推荐向上移
        all_notes_flat = [n for stats in channel_stats.values() for n in stats['notes']]
        if all_notes_flat:
            global_avg = sum(all_notes_flat) / len(all_notes_flat)
            IDEAL_CENTER = 65.0  # F4 — 演奏最佳区
            low_note_ratio = sum(1 for n in all_notes_flat if n < 60) / len(all_notes_flat)
            
            if global_avg < 54 and low_note_ratio > 0.6:
                # 严重偏低 — 推荐上移2个八度
                self.recommended_global_octave_shift = 2
                print(f"[通道分析] 全局音高偏低 (均值{global_avg:.0f}, 低音占{low_note_ratio:.0%}), 推荐上移+2八度")
            elif global_avg < 60 and low_note_ratio > 0.4:
                # 较低 — 推荐上移1个八度
                self.recommended_global_octave_shift = 1
                print(f"[通道分析] 全局音高偏低 (均值{global_avg:.0f}, 低音占{low_note_ratio:.0%}), 推荐上移+1八度")
            else:
                self.recommended_global_octave_shift = 0
    
    def _scan_tempo(self):
        """预扫描MIDI文件获取tempo信息"""
        if self.midi_file is None:
            return
        
        # 重置tempo相关信息
        self.tempo_changes = []
        self.bpm = 120.0
        self.tempo = 500000
        
        # 遍历所有轨道查找tempo事件
        all_tempos = []
        for track in self.midi_file.tracks:
            current_tick = 0
            for msg in track:
                current_tick += msg.time
                if msg.type == 'set_tempo':
                    all_tempos.append((current_tick, msg.tempo))
        
        # 如果找到tempo事件，使用第一个作为主要tempo
        if all_tempos:
            all_tempos.sort(key=lambda x: x[0])
            first_tempo = all_tempos[0][1]
            self.tempo = first_tempo
            self.bpm = mido.tempo2bpm(first_tempo)
    
    def _scan_key_signatures(self):
        """预扫描MIDI文件获取调号信息"""
        if self.midi_file is None:
            return
        
        # 重置调号信息
        self.key_signatures = []
        self.primary_key = None
        self.primary_mode = None
        
        # MIDI key signature 的 key 字段映射到半音数
        # key字段: 升降号数量（-7到+7，负数为降号，正数为升号）
        # 五度圈顺序: F(-1), Bb(-2), Eb(-3), Ab(-4), Db(-5), Gb(-6), Cb(-7)
        #            G(+1), D(+2), A(+3), E(+4), B(+5), F#(+6), C#(+7)
        # 对应的根音:
        SHARPS_TO_KEY = {
            0: 0,   # C / Am
            1: 7,   # G / Em
            2: 2,   # D / Bm
            3: 9,   # A / F#m
            4: 4,   # E / C#m
            5: 11,  # B / G#m
            6: 6,   # F# / D#m
            7: 1,   # C# / A#m
        }
        FLATS_TO_KEY = {
            0: 0,   # C / Am
            -1: 5,  # F / Dm
            -2: 10, # Bb / Gm
            -3: 3,  # Eb / Cm
            -4: 8,  # Ab / Fm
            -5: 1,  # Db / Bbm
            -6: 6,  # Gb / Ebm
            -7: 11, # Cb / Abm
        }
        
        # 遍历所有轨道查找key_signature事件
        all_key_sigs = []
        for track in self.midi_file.tracks:
            current_tick = 0
            for msg in track:
                current_tick += msg.time
                if msg.type == 'key_signature':
                    # mido的key_signature有两个属性: key (字符串如'C', 'Am') 和 mode (有时没有)
                    key_str = msg.key if hasattr(msg, 'key') else None
                    if key_str:
                        all_key_sigs.append((current_tick, key_str))
        
        if not all_key_sigs:
            return
        
        # 解析调号字符串
        # 格式可能是: 'C', 'Am', 'Bb', 'F#m', 'Gbm' 等
        NOTE_TO_SEMITONE = {
            'C': 0, 'C#': 1, 'Db': 1,
            'D': 2, 'D#': 3, 'Eb': 3,
            'E': 4, 'Fb': 4, 'E#': 5,
            'F': 5, 'F#': 6, 'Gb': 6,
            'G': 7, 'G#': 8, 'Ab': 8,
            'A': 9, 'A#': 10, 'Bb': 10,
            'B': 11, 'Cb': 11, 'B#': 0,
        }
        
        parsed_sigs = []
        for tick, key_str in all_key_sigs:
            key_str = key_str.strip()
            is_minor = key_str.endswith('m')
            if is_minor:
                key_str = key_str[:-1]
            
            # 处理调号名
            if key_str in NOTE_TO_SEMITONE:
                key_num = NOTE_TO_SEMITONE[key_str]
            else:
                # 尝试解析
                continue
            
            mode = 'minor' if is_minor else 'major'
            parsed_sigs.append((tick, key_num, mode))
        
        if parsed_sigs:
            # 按tick排序
            parsed_sigs.sort(key=lambda x: x[0])
            self.key_signatures = parsed_sigs
            
            # 使用第一个调号作为主要调号
            first_key = parsed_sigs[0]
            self.primary_key = first_key[1]
            self.primary_mode = first_key[2]
            
            # 打印调号信息
            key_names = ['C', 'C#/Db', 'D', 'D#/Eb', 'E', 'F', 'F#/Gb', 'G', 'G#/Ab', 'A', 'A#/Bb', 'B']
            print(f"[MIDI调号] 检测到调号: {key_names[self.primary_key]} {self.primary_mode}")
            if len(parsed_sigs) > 1:
                print(f"[MIDI调号] 共有{len(parsed_sigs)}个调号变化")
    
    def _parse_notes(self):
        """解析音符"""
        self.notes = []
        self.tempo_changes = []
        
        if self.midi_file is None:
            return
            
        merged_track = mido.merge_tracks(self.midi_file.tracks)
        
        current_time = 0.0
        active_notes = {}
        current_tempo = self.tempo
        first_tempo_set = False
        
        for msg in merged_track:
            delta_seconds = mido.tick2second(msg.time, self.ticks_per_beat, current_tempo)
            current_time += delta_seconds
            
            if msg.type == 'set_tempo':
                current_tempo = msg.tempo
                current_bpm = mido.tempo2bpm(msg.tempo)
                self.tempo_changes.append((current_time, msg.tempo, current_bpm))
                
                # 保存第一个tempo作为主要BPM
                if not first_tempo_set:
                    self.tempo = msg.tempo
                    self.bpm = current_bpm
                    first_tempo_set = True
                continue
            
            if msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.note, msg.channel)
                active_notes[key] = (current_time, msg.velocity)
                
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.note, msg.channel)
                if key in active_notes:
                    start_time, velocity = active_notes.pop(key)
                    duration = current_time - start_time
                    
                    self.notes.append(NoteEvent(
                        note=msg.note,
                        velocity=velocity,
                        time=start_time,
                        duration=max(duration, 0.01),
                        channel=msg.channel
                    ))
            
            # === 解析延音踏板 CC64 ===
            elif msg.type == 'control_change' and msg.control == 64:
                is_on = msg.value >= 64
                self.sustain_events.append(SustainPedalEvent(
                    time=current_time,
                    is_on=is_on,
                    channel=msg.channel,
                    value=msg.value
                ))
        
        self.notes.sort(key=lambda x: x.time)
        self.sustain_events.sort(key=lambda x: x.time)
        self.has_sustain_pedal = len(self.sustain_events) > 0
        
        if self.has_sustain_pedal:
            on_count = sum(1 for e in self.sustain_events if e.is_on)
            off_count = sum(1 for e in self.sustain_events if not e.is_on)
            print(f"[延音踏板] 检测到 {len(self.sustain_events)} 个踏板事件 (踩下{on_count}次, 抬起{off_count}次)")
            # 防抖：合并秒开秒关的踏板事件（ON→OFF间隔<0.3s视为抖动，删除该OFF+ON对）
            self.sustain_events = self._debounce_sustain_events(self.sustain_events)
        
        if self.notes:
            last_note = max(self.notes, key=lambda x: x.time + x.duration)
            self.total_time = last_note.time + last_note.duration
        
        # 如果没有CC64数据，启动启发式延音检测
        if not self.has_sustain_pedal and self.notes:
            self._detect_sustain_heuristic()
    
    def _debounce_sustain_events(self, events: list) -> list:
        """
        延音踏板智能防抖：只合并机械抖动，保留有意义的踏板编排
        
        策略：
        1. OFF→ON 间隔 < 0.06秒：纯MIDI机械抖动（量化误差），合并为持续踩下
        2. 其余事件完整保留，尊重原始MIDI的踏板编排（包括短踏板触碰）
        3. 去除连续重复状态（如连续两个ON）
        
        不删除短ON→OFF对！短踏板是音乐家有意为之的 踩——松——踩 节奏。
        """
        if len(events) < 2:
            return events
        
        JITTER_THRESHOLD = 0.06  # 秒，仅过滤真正的机械抖动（<60ms）
        
        # 合并 OFF→ON 间隔极短的机械抖动
        remove_indices = set()
        i = 0
        while i < len(events) - 1:
            if not events[i].is_on and events[i + 1].is_on:
                gap = events[i + 1].time - events[i].time
                if gap < JITTER_THRESHOLD:
                    remove_indices.add(i)
                    remove_indices.add(i + 1)
                    i += 2
                    continue
            i += 1
        
        result = [e for idx, e in enumerate(events) if idx not in remove_indices]
        jitter_removed = len(remove_indices) // 2
        
        # 去除连续重复状态（如两个连续ON，只保留第一个）
        cleaned = []
        last_state = None
        for evt in result:
            if evt.is_on != last_state:
                cleaned.append(evt)
                last_state = evt.is_on
        
        dedup_removed = len(result) - len(cleaned)
        
        if jitter_removed > 0 or dedup_removed > 0:
            print(f"[延音踏板] 防抖: 合并 {jitter_removed} 组机械抖动, 去重 {dedup_removed} 个")
        
        return cleaned
    
    def _detect_sustain_heuristic(self):
        """
        启发式延音踏板检测 - 模拟真实钢琴家的踏板习惯
        
        结合音符时长、力度和密度来智能决定踏板行为：
        - 连奏/长音段落：保持踏板踩下，充分共鸣
        - 断奏/快速段落：模拟音乐家 踩——松——踩 节奏性换踏板
          · 高力度: 每3拍换一次（更多共鸣）
          · 中力度: 每2拍换一次
          · 低力度: 每1.5拍换一次（更清晰）
        - 乐句间隙(>1拍)：抬起踏板清理共鸣
        - 曲末自动关闭踏板
        """
        beat_duration = 60.0 / max(self.bpm, 60)
        
        sorted_notes = sorted(self.notes, key=lambda n: n.time)
        if not sorted_notes:
            return
        
        # 计算曲子覆盖范围
        song_end = max(n.time + n.duration for n in sorted_notes)
        
        # 构建音符覆盖区间
        intervals = [(n.time, n.time + n.duration) for n in sorted_notes]
        intervals.sort()
        
        # 合并重叠/相近的区间（间隙 < 0.3拍也合并）
        merge_gap = beat_duration * 0.3
        merged = [list(intervals[0])]
        for start, end in intervals[1:]:
            if start <= merged[-1][1] + merge_gap:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        
        # 踏板策略：在每个连续音区域开启踏板，根据段落特征决定踏板风格
        # 间隙阈值：超过1拍才关闭踏板
        gap_threshold = beat_duration * 1.0
        
        self.sustain_events = []
        staccato_segs = 0
        legato_segs = 0
        
        for i, (seg_start, seg_end) in enumerate(merged):
            segment_duration = seg_end - seg_start
            
            # 收集此段落中的音符
            seg_notes = [n for n in sorted_notes if seg_start <= n.time < seg_end]
            
            if seg_notes and segment_duration > beat_duration * 2:
                avg_dur = sum(n.duration for n in seg_notes) / len(seg_notes)
                avg_vel = sum(n.velocity for n in seg_notes) / len(seg_notes)
                note_density = len(seg_notes) / max(segment_duration, 0.1)
                
                # 判断是否为断奏/快速段落
                is_staccato = (avg_dur < beat_duration * 0.4 and note_density > 3)
                
                if is_staccato:
                    # === 断奏段落：模拟音乐家 踩——松——踩 节奏 ===
                    staccato_segs += 1
                    
                    # 根据力度决定脉冲长度
                    if avg_vel > 90:
                        pulse_beats = 3.0    # 强力度：每3拍换踏板，更多共鸣
                    elif avg_vel > 50:
                        pulse_beats = 2.0    # 中力度：每2拍换踏板
                    else:
                        pulse_beats = 1.5    # 弱力度：每1.5拍换踏板，更清晰
                    
                    pulse_len = beat_duration * pulse_beats
                    lift_duration = 0.08  # 踏板抬起持续 ~80ms 清理共鸣
                    
                    t = seg_start
                    while t < seg_end:
                        # 踩下
                        on_time = max(0, t - 0.02)
                        self.sustain_events.append(SustainPedalEvent(
                            time=on_time, is_on=True, channel=0, value=int(avg_vel)
                        ))
                        
                        pulse_end = t + pulse_len
                        if pulse_end + lift_duration < seg_end:
                            # 松开（短暂抬起清理共鸣）
                            self.sustain_events.append(SustainPedalEvent(
                                time=pulse_end, is_on=False, channel=0, value=0
                            ))
                        # else: 最后一段不松开，让间隙处理来决定
                        
                        t = pulse_end + lift_duration
                else:
                    # === 连奏段落：保持踏板踩下 ===
                    legato_segs += 1
                    on_time = max(0, seg_start - 0.03)
                    self.sustain_events.append(SustainPedalEvent(
                        time=on_time, is_on=True, channel=0, value=127
                    ))
            else:
                # === 短段落或音符稀少：直接踩下 ===
                legato_segs += 1
                on_time = max(0, seg_start - 0.03)
                self.sustain_events.append(SustainPedalEvent(
                    time=on_time, is_on=True, channel=0, value=127
                ))
            
            # 间隙处理：与下一段间隙 > 1拍时关闭踏板
            if i < len(merged) - 1:
                gap = merged[i + 1][0] - seg_end
                if gap >= gap_threshold:
                    self.sustain_events.append(SustainPedalEvent(
                        time=seg_end, is_on=False, channel=0, value=0
                    ))
        
        # 曲末关闭踏板
        self.sustain_events.append(SustainPedalEvent(
            time=song_end + 0.1, is_on=False, channel=0, value=0
        ))
        
        # 排序 + 去重：如果连续两个事件状态相同，只保留第一个
        cleaned = []
        last_state = None
        for evt in sorted(self.sustain_events, key=lambda x: x.time):
            if evt.is_on != last_state:
                cleaned.append(evt)
                last_state = evt.is_on
        self.sustain_events = cleaned
        
        # 防抖处理
        self.sustain_events = self._debounce_sustain_events(self.sustain_events)
        
        self.has_sustain_pedal = len(self.sustain_events) > 0
        
        if self.sustain_events:
            on_count = sum(1 for e in self.sustain_events if e.is_on)
            print(f"[延音踏板] 启发式: {on_count}个踏板段落 "
                  f"({staccato_segs}断奏踩松踩 + {legato_segs}连奏持续), "
                  f"共{len(self.sustain_events)}个事件")
    
    def get_sustain_events(self) -> List[SustainPedalEvent]:
        """获取延音踏板事件列表"""
        return self.sustain_events
    
    def _detect_glissandos(self):
        """
        检测滑奏片段 - 快速连续的音阶上行/下行
        
        滑奏特征：
        1. 连续5个以上音符
        2. 每个音符间隔 < 100ms
        3. 音符连续上行或下行（允许半音/全音）
        4. 音域跨度 >= 一个八度
        """
        self.glissandos = []
        
        if not self.glissando_detection_enabled or not self.notes:
            return
        
        # 滑奏检测参数
        MIN_NOTES = 5           # 最少音符数
        MAX_INTERVAL = 0.12     # 最大音符间隔(秒)
        MIN_RANGE = 10          # 最小音域跨度(半音)，约一个八度
        MAX_STEP = 3            # 最大单步跨度(半音)，大于3可能是跳音不是滑奏
        
        # 按时间排序的音符
        sorted_notes = sorted(self.notes, key=lambda n: n.time)
        
        used_indices = set()
        i = 0
        
        while i < len(sorted_notes):
            if i in used_indices:
                i += 1
                continue
            
            # 尝试从当前位置开始检测滑奏
            sequence = [sorted_notes[i]]
            last_note = sorted_notes[i].note
            direction = 0  # 0=未确定, 1=上行, -1=下行
            
            j = i + 1
            while j < len(sorted_notes):
                note = sorted_notes[j]
                time_gap = note.time - sequence[-1].time
                
                # 时间间隔太大，结束
                if time_gap > MAX_INTERVAL:
                    break
                
                # 同时发声的音符跳过（可能是和弦）
                if time_gap < 0.01:
                    j += 1
                    continue
                
                pitch_diff = note.note - last_note
                
                # 跨度太大，不是滑奏
                if abs(pitch_diff) > MAX_STEP or pitch_diff == 0:
                    break
                
                # 确定/验证方向
                current_dir = 1 if pitch_diff > 0 else -1
                if direction == 0:
                    direction = current_dir
                elif direction != current_dir:
                    # 方向改变，结束当前序列
                    break
                
                sequence.append(note)
                last_note = note.note
                j += 1
            
            # 检查是否满足滑奏条件
            if len(sequence) >= MIN_NOTES:
                note_range = abs(sequence[-1].note - sequence[0].note)
                
                if note_range >= MIN_RANGE:
                    # 找到一个滑奏！
                    start_time = sequence[0].time
                    end_time = sequence[-1].time + sequence[-1].duration
                    duration = end_time - start_time
                    avg_interval = (sequence[-1].time - sequence[0].time) / (len(sequence) - 1)
                    
                    direction_str = 'up' if direction > 0 else 'down'
                    
                    glissando = GlissandoEvent(
                        time=start_time,
                        duration=duration,
                        direction=direction_str,
                        start_note=sequence[0].note,
                        end_note=sequence[-1].note,
                        note_count=len(sequence),
                        interval=avg_interval,
                        original_notes=sequence
                    )
                    self.glissandos.append(glissando)
                    
                    # 标记已使用的音符
                    for k in range(i, i + len(sequence)):
                        if k < len(sorted_notes):
                            used_indices.add(k)
                    
                    print(f"[滑奏检测] 发现{direction_str}滑奏: {sequence[0].note}->{sequence[-1].note}, "
                          f"{len(sequence)}个音符, 间隔{avg_interval*1000:.0f}ms, 时间{start_time:.2f}s")
                    
                    i = j
                    continue
            
            i += 1
        
        if self.glissandos:
            print(f"[滑奏检测] 共检测到 {len(self.glissandos)} 个滑奏片段")
            
    def _detect_chords(self):
        """检测和弦 - 支持同时和弦和琶音和弦检测"""
        self.chords = []
        
        if not self.chord_detection_enabled or not self.notes:
            return
        
        used_notes: Set[int] = set()
        
        # ========== 第一步：检测同时发声的和弦 ==========
        time_groups = []
        current_group = []
        current_group_time = -1
        
        for note in self.notes:
            if current_group_time < 0 or abs(note.time - current_group_time) <= self.chord_time_threshold:
                current_group.append(note)
                if current_group_time < 0:
                    current_group_time = note.time
            else:
                if current_group:
                    time_groups.append((current_group_time, current_group))
                current_group = [note]
                current_group_time = note.time
                
        if current_group:
            time_groups.append((current_group_time, current_group))
        
        for group_time, group_notes in time_groups:
            # 改进和弦判断：3-6个音符，音域合理，时长一致
            if len(group_notes) >= 3 and len(group_notes) <= 6:
                midi_notes = [n.note for n in group_notes]
                note_range = max(midi_notes) - min(midi_notes)
                
                # 和弦音域不应超过2个八度
                if note_range > 24:
                    continue
                
                # 检查时长一致性（和弦音符应该同时结束）
                durations = [n.duration for n in group_notes]
                avg_duration = sum(durations) / len(durations)
                duration_variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)
                
                # 放宽时长一致性要求（从0.1提高到0.2）
                if duration_variance > 0.2:
                    continue
                
                # 检查力度一致性（和弦音符力度应该相近）
                velocities = [n.velocity for n in group_notes]
                avg_velocity = sum(velocities) / len(velocities)
                velocity_variance = sum((v - avg_velocity) ** 2 for v in velocities) / len(velocities)
                
                # 力度差异太大说明不是同一个和弦
                if velocity_variance > 400:  # 允许±20的力度差
                    continue
                
                chord_result = self.chord_detector.detect_chord(midi_notes)
                
                if chord_result:
                    chord_key, chord_name, chord_notes = chord_result
                    
                    chord_event = ChordEvent(
                        chord_key=chord_key,
                        chord_name=chord_name,
                        notes=midi_notes,
                        time=group_time,
                        duration=avg_duration,
                        original_notes=group_notes
                    )
                    self.chords.append(chord_event)
                    
                    for n in group_notes:
                        used_notes.add(id(n))
        
        # ========== 第二步：琶音和弦检测（从连续快速音符中推断和弦） ==========
        self._detect_arpeggio_chords(used_notes)
        
        # 存储哪些音符被和弦使用了
        self._chord_used_notes = used_notes
    
    def _detect_arpeggio_chords(self, used_notes: Set[int]):
        """
        琶音和弦检测 - 从连续快速音符中推断和弦
        
        原理：
        1. 使用滑动窗口（时间窗口约0.3-0.5秒）收集连续音符
        2. 检查窗口内的音符是否形成已知和弦模式
        3. 如果形成和弦，标记并输出
        """
        if not self.notes:
            return
        
        # 琶音检测参数
        WINDOW_TIME = 0.4          # 时间窗口（秒）
        MIN_NOTES = 3              # 最少音符数
        MAX_INTERVAL = 0.2         # 相邻音符最大间隔
        MIN_PATTERN_REPEATS = 1    # 最少出现次数才认为是有意的和弦
        
        # 收集琶音模式
        arpeggio_chords = []
        i = 0
        
        while i < len(self.notes):
            # 跳过已被使用的音符
            if id(self.notes[i]) in used_notes:
                i += 1
                continue
            
            # 开始一个新窗口
            window_start = self.notes[i].time
            window_notes = [self.notes[i]]
            j = i + 1
            
            # 收集窗口内的音符
            while j < len(self.notes):
                note = self.notes[j]
                
                # 检查是否已被使用
                if id(note) in used_notes:
                    j += 1
                    continue
                
                # 检查时间是否在窗口内
                if note.time - window_start > WINDOW_TIME:
                    break
                
                # 检查与前一个音符的间隔
                if window_notes and note.time - window_notes[-1].time > MAX_INTERVAL:
                    break
                
                window_notes.append(note)
                j += 1
            
            # 检查窗口内的音符是否形成和弦
            if len(window_notes) >= MIN_NOTES:
                midi_notes = [n.note for n in window_notes]
                unique_pitches = set(n % 12 for n in midi_notes)
                
                # 需要至少3个不同的音级
                if len(unique_pitches) >= 3:
                    chord_result = self.chord_detector.detect_chord(midi_notes)
                    
                    if chord_result:
                        chord_key, chord_name, chord_notes_list = chord_result
                        
                        # 计算琶音的时间跨度
                        start_time = window_notes[0].time
                        end_time = window_notes[-1].time + window_notes[-1].duration
                        duration = end_time - start_time
                        
                        chord_event = ChordEvent(
                            chord_key=chord_key,
                            chord_name=chord_name,
                            notes=midi_notes,
                            time=start_time,
                            duration=duration,
                            original_notes=window_notes
                        )
                        arpeggio_chords.append(chord_event)
                        
                        # 标记这些音符
                        for n in window_notes:
                            used_notes.add(id(n))
                        
                        # 跳过这些音符
                        i = j
                        continue
            
            i += 1
        
        # 合并琶音和弦到主列表
        self.chords.extend(arpeggio_chords)
        self.chords.sort(key=lambda c: c.time)
        
    def _build_play_events(self):
        """构建统一的播放事件列表"""
        self.play_events = []
        
        # 收集被滑奏覆盖的音符ID
        glissando_note_ids = set()
        for gliss in self.glissandos:
            for note in gliss.original_notes:
                glissando_note_ids.add(id(note))
        
        # 记录被和弦覆盖的时间段
        chord_time_ranges = []
        for chord in self.chords:
            chord_time_ranges.append((chord.time - 0.01, chord.time + chord.duration + 0.01))
            
            # 添加和弦事件
            self.play_events.append(PlayEvent(
                time=chord.time,
                duration=chord.duration,
                is_chord=True,
                is_glissando=False,
                key=chord.chord_key,
                midi_notes=chord.notes,
                original_event=chord
            ))
        
        # 添加滑奏事件
        glissando_time_ranges = []
        for gliss in self.glissandos:
            glissando_time_ranges.append((gliss.time - 0.01, gliss.time + gliss.duration + 0.01))
            
            self.play_events.append(PlayEvent(
                time=gliss.time,
                duration=gliss.duration,
                is_chord=False,
                is_glissando=True,
                key='',  # 滑奏不需要单个键
                midi_notes=[gliss.start_note, gliss.end_note],
                original_event=gliss
            ))
        
        # 添加不在和弦/滑奏中的单音符
        for note in self.notes:
            # 跳过滑奏中的音符
            if id(note) in glissando_note_ids:
                continue
            
            # 检查是否被和弦覆盖
            is_in_chord = False
            for start, end in chord_time_ranges:
                if start <= note.time <= end:
                    # 检查音符是否是和弦的一部分
                    for chord in self.chords:
                        if (abs(chord.time - note.time) <= self.chord_time_threshold and 
                            note.note in chord.notes):
                            is_in_chord = True
                            break
                if is_in_chord:
                    break
                    
            if not is_in_chord:
                self.play_events.append(PlayEvent(
                    time=note.time,
                    duration=note.duration,
                    is_chord=False,
                    is_glissando=False,
                    key='',  # 将由mapper填充
                    midi_notes=[note.note],
                    original_event=note
                ))
        
        # 按时间排序
        self.play_events.sort(key=lambda x: x.time)
        
    def set_chord_detection(self, enabled: bool):
        """设置是否启用和弦检测"""
        self.chord_detection_enabled = enabled
        if self.notes:
            self._detect_chords()
            self._build_play_events()
    
    def get_notes(self) -> List[NoteEvent]:
        """获取所有音符"""
        return self.notes
    
    def get_chords(self) -> List[ChordEvent]:
        """获取检测到的和弦"""
        return self.chords
    
    def get_play_events(self) -> List[PlayEvent]:
        """获取播放事件列表"""
        return self.play_events
    
    def get_total_time(self) -> float:
        """获取总时长"""
        return self.total_time
    
    def get_note_range(self) -> Tuple[int, int]:
        """获取音符范围"""
        if not self.notes:
            return (48, 60)
        notes = [n.note for n in self.notes]
        return (min(notes), max(notes))
    
    def get_info(self) -> dict:
        """获取MIDI信息"""
        return {
            'total_notes': len(self.notes),
            'total_chords': len(self.chords),
            'total_time': self.total_time,
            'note_range': self.get_note_range(),
            'ticks_per_beat': self.ticks_per_beat,
            'bpm': self.bpm,
            'tempo': self.tempo,
            'tempo_changes': len(self.tempo_changes),
            'play_events': len(self.play_events),
            'channels': self.get_channels_info(),
            'instruments': self.channel_instruments,
            'channel_categories': self.channel_categories,
            'melody_channels': self.melody_channels,
            'harmony_channels': self.harmony_channels,
            'bass_channels': self.bass_channels,
            'recommended_transpose': self.recommended_transpose,
            'recommended_global_octave_shift': self.recommended_global_octave_shift,
        }
    
    def get_instrument_info(self) -> dict:
        """获取乐器信息"""
        GM_INSTRUMENT_NAMES = [
            'Acoustic Grand Piano', 'Bright Acoustic Piano', 'Electric Grand Piano', 'Honky-tonk Piano',
            'Electric Piano 1', 'Electric Piano 2', 'Harpsichord', 'Clavinet',
            'Celesta', 'Glockenspiel', 'Music Box', 'Vibraphone', 'Marimba', 'Xylophone', 'Tubular Bells', 'Dulcimer',
            'Drawbar Organ', 'Percussive Organ', 'Rock Organ', 'Church Organ', 'Reed Organ', 'Accordion', 'Harmonica', 'Tango Accordion',
            'Acoustic Guitar (nylon)', 'Acoustic Guitar (steel)', 'Electric Guitar (jazz)', 'Electric Guitar (clean)',
            'Electric Guitar (muted)', 'Overdriven Guitar', 'Distortion Guitar', 'Guitar Harmonics',
            'Acoustic Bass', 'Electric Bass (finger)', 'Electric Bass (pick)', 'Fretless Bass',
            'Slap Bass 1', 'Slap Bass 2', 'Synth Bass 1', 'Synth Bass 2',
            'Violin', 'Viola', 'Cello', 'Contrabass', 'Tremolo Strings', 'Pizzicato Strings', 'Orchestral Harp', 'Timpani',
            'String Ensemble 1', 'String Ensemble 2', 'Synth Strings 1', 'Synth Strings 2', 'Choir Aahs', 'Voice Oohs', 'Synth Choir', 'Orchestra Hit',
            'Trumpet', 'Trombone', 'Tuba', 'Muted Trumpet', 'French Horn', 'Brass Section', 'Synth Brass 1', 'Synth Brass 2',
            'Soprano Sax', 'Alto Sax', 'Tenor Sax', 'Baritone Sax', 'Oboe', 'English Horn', 'Bassoon', 'Clarinet',
            'Piccolo', 'Flute', 'Recorder', 'Pan Flute', 'Blown bottle', 'Shakuhachi', 'Whistle', 'Ocarina',
            'Lead 1 (square)', 'Lead 2 (sawtooth)', 'Lead 3 (calliope)', 'Lead 4 (chiff)', 'Lead 5 (charang)', 'Lead 6 (voice)', 'Lead 7 (fifths)', 'Lead 8 (bass + lead)',
            'Pad 1 (new age)', 'Pad 2 (warm)', 'Pad 3 (polysynth)', 'Pad 4 (choir)', 'Pad 5 (bowed)', 'Pad 6 (metallic)', 'Pad 7 (halo)', 'Pad 8 (sweep)',
            'FX 1 (rain)', 'FX 2 (soundtrack)', 'FX 3 (crystal)', 'FX 4 (atmosphere)', 'FX 5 (brightness)', 'FX 6 (goblins)', 'FX 7 (echoes)', 'FX 8 (sci-fi)',
            'Sitar', 'Banjo', 'Shamisen', 'Koto', 'Kalimba', 'Bagpipe', 'Fiddle', 'Shanai',
            'Tinkle Bell', 'Agogo', 'Steel Drums', 'Woodblock', 'Taiko Drum', 'Melodic Tom', 'Synth Drum', 'Reverse Cymbal',
            'Guitar Fret Noise', 'Breath Noise', 'Seashore', 'Bird Tweet', 'Telephone Ring', 'Helicopter', 'Applause', 'Gunshot',
        ]
        
        result = {}
        for ch, prog in self.channel_instruments.items():
            name = GM_INSTRUMENT_NAMES[prog] if prog < len(GM_INSTRUMENT_NAMES) else f'Program {prog}'
            category = self.channel_categories.get(ch, 'unknown')
            result[ch] = {
                'program': prog,
                'name': name,
                'category': category,
            }
        return result
    
    def get_bpm(self) -> float:
        """获取MIDI文件的BPM"""
        return self.bpm
    
    def get_tempo_changes(self) -> List[Tuple[float, int, float]]:
        """获取所有tempo变化点
        
        Returns:
            [(时间秒, tempo微秒/拍, bpm), ...]
        """
        return self.tempo_changes
    
    def get_channels_info(self) -> dict:
        """
        获取各通道的信息
        
        Returns:
            {
                channel: {
                    'note_count': 音符数量,
                    'note_range': (最低音, 最高音),
                    'avg_note': 平均音高,
                }
            }
        """
        channels = {}
        for note in self.notes:
            ch = note.channel
            if ch not in channels:
                channels[ch] = {
                    'notes': [],
                    'note_count': 0,
                }
            channels[ch]['notes'].append(note.note)
            channels[ch]['note_count'] += 1
        
        # 计算统计信息
        result = {}
        for ch, info in channels.items():
            notes = info['notes']
            result[ch] = {
                'note_count': info['note_count'],
                'note_range': (min(notes), max(notes)) if notes else (0, 0),
                'avg_note': sum(notes) / len(notes) if notes else 0,
            }
        
        return result
    
    def get_notes_by_channel(self, channel: int) -> List[NoteEvent]:
        """获取指定通道的所有音符"""
        return [n for n in self.notes if n.channel == channel]
    
    def get_chord_summary(self) -> dict:
        """获取和弦统计"""
        chord_counts = {}
        for chord in self.chords:
            name = chord.chord_name
            chord_counts[name] = chord_counts.get(name, 0) + 1
        return {
            'chord_count': len(self.chords),
            'chord_types': chord_counts,
        }


class JSParser:
    """
    JS谱面文件解析器
    
    解析格式: parseGenshinImpactMusic("曲名", "{A4}<170>{B4}<170>...", 2)
    
    格式说明:
    - {音符} 表示按键，如 {A4} 表示A4键
    - <时间> 表示延迟（毫秒）
    - 连续的 {音符}{音符} 表示同时按下
    
    JS文件中的音符已经是游戏内映射好的，可以直接使用！
    """
    
    # 音符名转MIDI偏移
    NOTE_MAP = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 
                'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}
    
    def __init__(self):
        self.notes: List[NoteEvent] = []
        self.play_events: List[PlayEvent] = []
        self.bpm = 120.0  # 默认BPM
        self.total_time = 0.0
        self.title = ""
        
        # 兼容 MidiParser 的接口
        self.chords: List[ChordEvent] = []
        self.chord_detection_enabled = False
        self.chord_detector = ChordDetector()  # 添加和弦检测器以兼容播放器
        
        # 音部分析兼容属性
        self.melody_notes: List[NoteEvent] = []
        self.bass_notes: List[NoteEvent] = []
        self.pitch_split_point: int = 60
        self.pitch_gap: int = 0
        self.recommend_melody_only: bool = False
        
        # 延音踏板兼容
        self.sustain_events: list = []
        self.has_sustain_pedal: bool = False
        
        # 调号信息兼容
        self.key_signatures: list = []
        self.primary_key = None
        self.primary_mode = None
        
        # 乐器/通道信息兼容
        self.channel_instruments: Dict[int, int] = {}
        self.channel_categories: Dict[int, str] = {}
        self.track_names: List[str] = []
        self.melody_channels: List[int] = []
        self.harmony_channels: List[int] = []
        self.bass_channels: List[int] = []
        self.recommended_transpose: Dict[int, int] = {}
        self.recommended_global_octave_shift: int = 0
        
        # tempo兼容
        self.tempo_changes: list = []
        self.ticks_per_beat: int = 480
        self.midi_file = None
        self.tempo: int = 500000
        
        # 滑奏兼容
        self.glissandos: list = []
        self.glissando_detection_enabled: bool = False
        
    def load_file(self, filepath: str) -> bool:
        """加载JS谱面文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return self._parse_content(content)
        except Exception as e:
            print(f"加载JS文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _parse_content(self, content: str) -> bool:
        """解析JS内容"""
        # 提取曲名
        title_match = re.search(r'parseGenshinImpactMusic\s*\(\s*"([^"]*)"', content)
        if title_match:
            self.title = title_match.group(1)
        
        # 提取谱面数据（最长的字符串）
        matches = re.findall(r'"([^"]{50,})"', content)
        if not matches:
            print("未找到谱面数据")
            return False
        
        data = max(matches, key=len)
        
        # 解析事件
        self.notes = []
        self.play_events = []
        
        current_time = 0.0
        
        # 按 <时间> 分割
        events = re.split(r'<(\d+)>', data)
        
        # 先收集所有事件和时长
        parsed_events = []  # [(time, midi_notes, duration_ms)]
        
        # events 格式: [音符组, 时间, 音符组, 时间, ...]
        i = 0
        while i < len(events):
            note_group = events[i].strip()
            
            # 获取下一个延迟时间（作为当前音符的时长）
            duration_ms = 170  # 默认时长
            if i + 1 < len(events):
                try:
                    duration_ms = int(events[i + 1])
                except (ValueError, IndexError):
                    pass
            
            if note_group:
                # 解析这组音符（可能是同时多个）
                note_strs = re.findall(r'\{([A-G]#?\d)\}', note_group)
                
                if note_strs:
                    # 转换为MIDI音符
                    midi_notes = []
                    for ns in note_strs:
                        midi_note = self._note_str_to_midi(ns)
                        if midi_note is not None:
                            midi_notes.append(midi_note)
                    
                    if midi_notes:
                        parsed_events.append((current_time, midi_notes, duration_ms))
            
            # 更新时间
            current_time += duration_ms / 1000.0
            i += 2
        
        # 创建音符事件，使用实际时长
        for event_time, midi_notes, duration_ms in parsed_events:
            # 时长转换为秒，但限制最大值避免太长
            duration_sec = min(duration_ms / 1000.0, 1.0)  # 最长1秒
            duration_sec = max(duration_sec, 0.05)  # 最短50ms
            
            for midi_note in midi_notes:
                note_event = NoteEvent(
                    note=midi_note,
                    velocity=100,
                    time=event_time,
                    duration=duration_sec,
                    channel=0
                )
                self.notes.append(note_event)
        
        self.total_time = current_time
        
        # 估算BPM
        if self.notes and self.total_time > 0:
            # 假设大部分延迟是基于节拍的
            delays = re.findall(r'<(\d+)>', data)
            if delays:
                delays = [int(d) for d in delays if int(d) > 0]
                if delays:
                    # 找最常见的延迟
                    from collections import Counter
                    common_delay = Counter(delays).most_common(1)[0][0]
                    # 假设这是一个十六分音符
                    if common_delay > 0:
                        self.bpm = 60000 / (common_delay * 4)  # 估算BPM
        
        self._build_play_events()
        
        print(f"JS解析完成: {len(self.notes)} 个音符, 时长 {self.total_time:.2f}秒, BPM约 {self.bpm:.0f}")
        return True
    
    def _note_str_to_midi(self, note_str: str) -> Optional[int]:
        """将音符字符串转换为MIDI音符号"""
        # 格式: A4, C#3, etc.
        if '#' in note_str:
            note_name = note_str[:2]
            octave = int(note_str[2])
        else:
            note_name = note_str[0]
            octave = int(note_str[1])
        
        if note_name not in self.NOTE_MAP:
            return None
        
        # JS文件中的音符直接就是游戏键位
        # 游戏中: 2-3-4-5 八度对应低-中-高-超高音区
        # 转换为标准MIDI: (octave + 1) * 12 + note_offset
        midi_note = (octave + 1) * 12 + self.NOTE_MAP[note_name]
        return midi_note
    
    def _build_play_events(self):
        """构建播放事件（不做和弦检测，JS文件已经是最终格式）"""
        self.play_events = []
        
        # 按时间分组
        time_groups: Dict[float, List[NoteEvent]] = {}
        for note in self.notes:
            t = round(note.time, 4)
            if t not in time_groups:
                time_groups[t] = []
            time_groups[t].append(note)
        
        # 创建播放事件
        for t, notes in sorted(time_groups.items()):
            # JS文件中的同时音符就是要同时按的键，不需要检测和弦
            for note in notes:
                event = PlayEvent(
                    time=t,
                    duration=note.duration,
                    is_chord=False,
                    key='',  # 将由 player 决定
                    midi_notes=[note.note],
                    original_event=note
                )
                self.play_events.append(event)
    
    def get_info(self) -> dict:
        """获取文件信息"""
        note_range = (min(n.note for n in self.notes), max(n.note for n in self.notes)) if self.notes else (0, 0)
        return {
            'type': 'js',
            'title': self.title,
            'bpm': self.bpm,
            'note_count': len(self.notes),
            'total_time': self.total_time,
            'note_range': note_range,
        }
    
    def set_chord_detection(self, enabled: bool):
        """设置和弦检测（JS文件不需要，仅为兼容）"""
        self.chord_detection_enabled = enabled
    
    def get_chord_summary(self) -> dict:
        """获取和弦摘要（JS文件没有和弦概念）"""
        return {'chord_count': 0, 'chord_types': {}}
    
    def get_bpm(self) -> float:
        """获取BPM"""
        return self.bpm
    
    def get_tempo_changes(self) -> list:
        """获取tempo变化（JS文件无此概念）"""
        return []
    
    def get_channels_info(self) -> dict:
        """获取通道信息（JS文件无此概念）"""
        return {}
    
    def get_notes_by_channel(self, channel: int) -> List[NoteEvent]:
        """获取指定通道的音符（JS文件只有一个通道）"""
        if channel == 0:
            return self.notes
        return []
    
    def get_play_events(self) -> List[PlayEvent]:
        """获取播放事件列表"""
        return self.play_events
    
    def get_pitch_analysis(self) -> dict:
        """获取音高分析结果（JS文件兼容stub）"""
        result = {
            'melody_count': len(self.melody_notes),
            'bass_count': len(self.bass_notes),
            'split_point': self.pitch_split_point,
            'split_point_name': 'C4',
            'pitch_gap': self.pitch_gap,
            'recommend_melody_only': self.recommend_melody_only,
        }
        if self.notes:
            pitches = [n.note for n in self.notes]
            result['melody_range'] = (min(pitches), max(pitches))
        return result
    
    def get_instrument_info(self) -> dict:
        """获取乐器信息（JS文件无乐器概念）"""
        return {}


def analyze_midi(filepath: str) -> dict:
    """分析MIDI文件"""
    parser = MidiParser()
    if parser.load_file(filepath):
        info = parser.get_info()
        info['chord_summary'] = parser.get_chord_summary()
        
        note_counts = {}
        for note in parser.notes:
            note_counts[note.note] = note_counts.get(note.note, 0) + 1
        info['note_distribution'] = note_counts
        
        return info
    return {}

def debug_midi(filepath: str) -> str:
    """详细调试MIDI文件，返回诊断报告"""
    import mido
    
    try:
        midi = mido.MidiFile(filepath, clip=True)
    except Exception as e:
        return f"无法打开MIDI文件: {e}"
    
    report = []
    report.append(f"=== MIDI文件分析报告 ===")
    report.append(f"文件: {filepath}")
    report.append(f"类型: {midi.type} (0=单轨, 1=多轨同步, 2=多轨异步)")
    report.append(f"轨道数: {len(midi.tracks)}")
    report.append(f"Ticks/Beat: {midi.ticks_per_beat}")
    report.append(f"总时长: {midi.length:.2f} 秒")
    report.append("")
    
    # 统计各种事件
    tempo_events = []
    note_events = []
    program_changes = []
    
    for track_idx, track in enumerate(midi.tracks):
        track_notes = 0
        track_tempo = 0
        current_tick = 0
        
        for msg in track:
            current_tick += msg.time
            
            if msg.type == 'set_tempo':
                tempo_events.append((track_idx, current_tick, msg.tempo, mido.tempo2bpm(msg.tempo)))
                track_tempo += 1
            elif msg.type == 'note_on' and msg.velocity > 0:
                track_notes += 1
                note_events.append((track_idx, msg.channel, msg.note, current_tick))
            elif msg.type == 'program_change':
                program_changes.append((track_idx, msg.channel, msg.program))
        
        if track_notes > 0 or track_tempo > 0:
            report.append(f"轨道 {track_idx}: {track_notes} 音符, {track_tempo} tempo变化")
    
    report.append("")
    report.append(f"--- Tempo事件 ({len(tempo_events)}个) ---")
    for track_idx, tick, tempo, bpm in tempo_events[:10]:  # 只显示前10个
        report.append(f"  轨道{track_idx} @ tick {tick}: tempo={tempo} ({bpm:.1f} BPM)")
    if len(tempo_events) > 10:
        report.append(f"  ... 还有 {len(tempo_events) - 10} 个")
    
    report.append("")
    report.append(f"--- 乐器/音色 ---")
    for track_idx, channel, program in program_changes:
        report.append(f"  轨道{track_idx} 通道{channel}: Program {program}")
    
    # 解析后的结果
    report.append("")
    report.append(f"=== 解析结果 ===")
    parser = MidiParser()
    if parser.load_file(filepath):
        report.append(f"解析后BPM: {parser.bpm:.1f}")
        report.append(f"解析后音符数: {len(parser.notes)}")
        report.append(f"解析后总时长: {parser.total_time:.2f} 秒")
        
        # 检查时间分布
        if parser.notes:
            times = [n.time for n in parser.notes]
            report.append(f"首个音符时间: {min(times):.3f} 秒")
            report.append(f"最后音符时间: {max(times):.3f} 秒")
            
            # 检查音符间隔
            sorted_times = sorted(times)
            intervals = [sorted_times[i+1] - sorted_times[i] for i in range(len(sorted_times)-1) if sorted_times[i+1] - sorted_times[i] > 0]
            if intervals:
                report.append(f"平均音符间隔: {sum(intervals)/len(intervals)*1000:.1f} 毫秒")
                report.append(f"最小音符间隔: {min(intervals)*1000:.1f} 毫秒")
    
    return "\n".join(report)