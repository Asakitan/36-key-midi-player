# -*- coding: utf-8 -*-
"""
键盘映射模块 - 负责将MIDI音符映射到键盘按键（支持SHIFT/CTRL三模式切换）

游戏60键电子琴布局（含黑键/半音）+ SHIFT/CTRL扩展：
  普通模式（无修饰键）：
  - Z-M = 低音区 (C3-B3, MIDI 48-59)
  - A-J = 中音区 (C4-B4, MIDI 60-71)
  - Q-U = 高音区 (C5-B5, MIDI 72-83)

  SHIFT模式（按L Shift切换高八度）：
  - Z-M = 低音区 (C4-B4, MIDI 60-71)
  - A-J = 中音区 (C5-B5, MIDI 72-83)
  - Q-U = 高音区 (C6-B6, MIDI 84-95)

  CTRL模式（按L Ctrl切换低八度）：
  - Z-M = 低音区 (C2-B2, MIDI 36-47)
  - A-J = 中音区 (C3-B3, MIDI 48-59)
  - Q-U = 高音区 (C4-B4, MIDI 60-71)

完整支持范围: C2-B6 (MIDI 36-95, 5个八度, 60个半音)
  MIDI 36-47: C2-B2 仅CTRL模式可达
  MIDI 48-59: CTRL或普通模式可达
  MIDI 60-71: 三种模式均可达
  MIDI 72-83: 普通或SHIFT模式可达
  MIDI 84-95: 仅SHIFT模式可达
"""

from typing import Optional, List, Dict
from config import (MIDI_TO_KEY, MIDI_TO_KEY_SHIFT, MIDI_TO_KEY_CTRL,
                    MIDI_TO_KEY_LT, MIDI_TO_KEY_GT, DEFAULT_MODE_SYSTEM)


class KeyboardMapper:
    """键盘映射器 - 将MIDI音符映射到60键全音阶（支持SHIFT/CTRL三模式 + </>扩展模式）"""
    
    # === classic 模式范围（CTRL/SHIFT, C2-B6, MIDI 36-95） ===
    CLASSIC_MIN = 36   # C2
    CLASSIC_MAX = 95   # B6
    
    CTRL_RANGE = (36, 47)       # C2-B2 -> 仅CTRL模式
    LOW_RANGE = (48, 59)        # C3-B3 -> CTRL或普通模式
    MID_RANGE = (60, 71)        # C4-B4 -> 三种模式均可
    HIGH_RANGE = (72, 83)       # C5-B5 -> 普通或SHIFT模式
    SHIFT_RANGE = (84, 95)      # C6-B6 -> 仅SHIFT模式
    
    NORMAL_MIN = 48; NORMAL_MAX = 83
    SHIFT_MIN = 60;  SHIFT_MAX = 95
    CTRL_MIN = 36;   CTRL_MAX = 71
    
    # === extended 模式范围（</>，A0-C8, MIDI 21-108） ===
    EXTENDED_MIN = 21   # A0
    EXTENDED_MAX = 108  # C8
    
    LT_RANGE = (21, 47)         # A0-B2 -> 仅<模式
    # NORMAL same as above      # C3-B5 -> 普通模式
    GT_RANGE = (84, 108)        # C6-C8 -> 仅>模式
    
    LT_MIN = 21;  LT_MAX = 47
    GT_MIN = 84;  GT_MAX = 108
    
    def __init__(self):
        # 模式系统: 'classic' (CTRL/SHIFT) 或 'extended' (</>)
        self.mode_system = DEFAULT_MODE_SYSTEM
        
        # 普通模式映射表（36键 C3-B5）
        self.midi_to_key = MIDI_TO_KEY.copy()
        # SHIFT模式映射表（36键 C4-B6）
        self.midi_to_key_shift = MIDI_TO_KEY_SHIFT.copy()
        # CTRL模式映射表（36键 C2-B4）
        self.midi_to_key_ctrl = MIDI_TO_KEY_CTRL.copy()
        # <模式映射表（27键 A0-B2）
        self.midi_to_key_lt = MIDI_TO_KEY_LT.copy()
        # >模式映射表（25键 C6-C8）
        self.midi_to_key_gt = MIDI_TO_KEY_GT.copy()
        
        # 全范围映射表（classic: 36-95，用于分析和覆盖率计算）
        self.midi_to_key_full = {}
        self.midi_to_key_full.update(self.midi_to_key_ctrl)
        self.midi_to_key_full.update(self.midi_to_key)
        for k, v in self.midi_to_key_shift.items():
            if k not in self.midi_to_key_full:
                self.midi_to_key_full[k] = v
        
        # extended全范围映射表（21-108）
        self.midi_to_key_full_ext = {}
        self.midi_to_key_full_ext.update(self.midi_to_key_lt)
        self.midi_to_key_full_ext.update(self.midi_to_key)
        for k, v in self.midi_to_key_gt.items():
            if k not in self.midi_to_key_full_ext:
                self.midi_to_key_full_ext[k] = v
        
        # 全局移调设置
        self.transpose = 0
        
        # 分通道移调设置 {channel: transpose_value}
        self.channel_transpose: Dict[int, int] = {}
        
        # 通道启用状态 {channel: enabled}
        self.channel_enabled: Dict[int, bool] = {}
        
        # 保持音区模式：尽量保持音符在原本的音区
        self.preserve_octave = True
                
    def set_transpose(self, semitones: int):
        """设置全局移调"""
        self.transpose = semitones
    
    def set_channel_transpose(self, channel: int, semitones: int):
        """设置指定通道的移调"""
        self.channel_transpose[channel] = semitones
    
    def get_channel_transpose(self, channel: int) -> int:
        """获取指定通道的移调值"""
        return self.channel_transpose.get(channel, self.transpose)
    
    def set_channel_enabled(self, channel: int, enabled: bool):
        """设置指定通道是否启用"""
        self.channel_enabled[channel] = enabled
    
    def is_channel_enabled(self, channel: int) -> bool:
        """获取指定通道是否启用"""
        return self.channel_enabled.get(channel, True)
    
    def clear_channel_settings(self):
        """清除所有通道设置"""
        self.channel_transpose.clear()
        self.channel_enabled.clear()
    
    def set_smart_mapping(self, enabled: bool):
        """设置是否启用智能映射（兼容旧接口）"""
        pass  # 36键模式下始终直接映射
    
    def set_mode_system(self, system: str):
        """设置模式系统: 'classic' (CTRL/SHIFT) 或 'extended' (</>)"""
        self.mode_system = system
    
    def get_playable_range(self) -> tuple:
        """获取当前模式系统的可弹奏范围"""
        if self.mode_system == 'extended':
            return (self.EXTENDED_MIN, self.EXTENDED_MAX)
        return (self.CLASSIC_MIN, self.CLASSIC_MAX)
    
    def map_note(self, midi_note: int, channel: int = None, shift_mode: bool = False,
                 ctrl_mode: bool = False, lt_mode: bool = False, gt_mode: bool = False) -> Optional[str]:
        """
        将MIDI音符映射到36键

        Args:
            midi_note: MIDI音符号 (0-127)
            channel: MIDI通道 (0-15)
            shift_mode: 当前是否为SHIFT模式
            ctrl_mode: 当前是否为CTRL模式
            lt_mode: 当前是否为<模式
            gt_mode: 当前是否为>模式
            
        Returns:
            键盘按键字符，如果无法映射则返回None
        """
        # 检查通道是否启用
        if channel is not None and not self.is_channel_enabled(channel):
            return None
        
        # 获取移调值
        if channel is not None and channel in self.channel_transpose:
            transpose = self.channel_transpose[channel]
        else:
            transpose = self.transpose
        
        # 应用移调
        adjusted_note = midi_note + transpose
        
        # 选择映射表（根据当前模式）
        if lt_mode:
            mapping = self.midi_to_key_lt
        elif gt_mode:
            mapping = self.midi_to_key_gt
        elif ctrl_mode:
            mapping = self.midi_to_key_ctrl
        elif shift_mode:
            mapping = self.midi_to_key_shift
        else:
            mapping = self.midi_to_key
        
        # 直接查找
        if adjusted_note in mapping:
            return mapping[adjusted_note]
        
        # 超出当前模式范围：尝试全范围映射表
        full_map = self.midi_to_key_full_ext if self.mode_system == 'extended' else self.midi_to_key_full
        if adjusted_note in full_map:
            return full_map[adjusted_note]
        
        # 超出范围的音符：八度折叠
        target_note = self._fold_to_range(adjusted_note)
        
        if target_note in mapping:
            return mapping[target_note]
        if target_note in full_map:
            return full_map[target_note]
        
        return None
    
    def needs_shift(self, midi_note: int) -> Optional[bool]:
        """
        判断一个MIDI音符是否需要SHIFT模式（向后兼容）
        """
        pmin, pmax = self.get_playable_range()
        if midi_note < pmin or midi_note > pmax:
            midi_note = self._fold_to_range(midi_note)
        
        if midi_note < 48:
            return False  # 低音区：不需要SHIFT
        elif midi_note > 83:
            return True   # 高音区：需要SHIFT(classic)或>(extended)
        else:
            return None   # 中音区：多种模式均可
    
    def needs_mode(self, midi_note: int) -> Optional[str]:
        """
        判断一个MIDI音符需要哪种模式
        
        Returns:
            'ctrl'/'shift'/'lt'/'gt' = 必须特定模式, None = 普通模式可选
        """
        pmin, pmax = self.get_playable_range()
        if midi_note < pmin or midi_note > pmax:
            midi_note = self._fold_to_range(midi_note)
        
        if self.mode_system == 'extended':
            if midi_note < 48:
                return 'lt'     # A0-B2: 仅<模式
            elif midi_note > 83:
                return 'gt'     # C6-C8: 仅>模式
            else:
                return None     # C3-B5: 普通模式
        else:
            # classic 模式
            if midi_note < 48:
                return 'ctrl'   # C2-B2: 仅CTRL模式
            elif midi_note > 83:
                return 'shift'  # C6-B6: 仅SHIFT模式
            else:
                return None     # C3-B5: 多种模式可选
    
    def _fold_to_range(self, midi_note: int) -> int:
        """将超出范围的音符折叠到可弹奏范围"""
        pmin, pmax = self.get_playable_range()
        
        if pmin <= midi_note <= pmax:
            return midi_note
        
        # 保留音名（pitch class），折叠到可弹奏范围内
        while midi_note < pmin:
            midi_note += 12
        while midi_note > pmax:
            midi_note -= 12
        
        return midi_note
    
    def map_notes(self, midi_notes: List[int]) -> List[Optional[str]]:
        """批量映射MIDI音符"""
        return [self.map_note(note) for note in midi_notes]
    
    def get_supported_range(self) -> tuple:
        """获取支持的音符范围"""
        return self.get_playable_range()
    
    def analyze_coverage(self, midi_notes: List[int]) -> dict:
        """分析音符覆盖率"""
        total = len(midi_notes)
        mapped = sum(1 for n in midi_notes if self.map_note(n) is not None)
        unmapped_notes = set(n for n in midi_notes if self.map_note(n) is None)
        
        return {
            'total': total,
            'mapped': mapped,
            'coverage': mapped / total if total > 0 else 0,
            'unmapped_notes': sorted(unmapped_notes)
        }
    
    def suggest_transpose(self, midi_notes: List[int]) -> int:
        """
        智能移调算法 - 优化音域覆盖率（对称评分，不偏向任何音区）
        """
        if not midi_notes:
            return 0
        
        # 根据模式系统选择目标范围
        pmin, pmax = self.get_playable_range()
        TARGET_MIN = pmin
        TARGET_MAX = pmax
        # 使用可弹奏范围的真实中心（对称，不偏向任何音区）
        PREFERRED_CENTER = (pmin + pmax) / 2.0
        
        note_min = min(midi_notes)
        note_max = max(midi_notes)
        note_center = (note_min + note_max) / 2
        
        # 计算需要的八度调整
        octave_adjust = round((PREFERRED_CENTER - note_center) / 12) * 12
        
        # 限制范围
        octave_adjust = max(-36, min(36, octave_adjust))
        
        # 如果不偏移时命中率已经很高，优先保持原始音高
        hits_no_shift = sum(1 for n in midi_notes if TARGET_MIN <= n <= TARGET_MAX)
        if hits_no_shift / len(midi_notes) >= 0.8:
            octave_adjust = 0
        
        # 保存分析信息
        self._last_key_transpose = 0
        self._last_white_ratio = 1.0
        self._last_octave_adjust = octave_adjust
        
        return octave_adjust
    
    def suggest_channel_transpose(self, midi_notes: List[int], target_octave: str = None) -> int:
        """为特定通道建议移调值"""
        if not midi_notes:
            return 0
        
        note_avg = sum(midi_notes) / len(midi_notes)
        
        if target_octave == 'high':
            target_center = 83.5
        elif target_octave == 'low':
            target_center = 53.5
        else:
            pmin, pmax = self.get_playable_range()
            target_center = (pmin + pmax) / 2.0
        
        suggested = round((target_center - note_avg) / 12) * 12
        
        best_transpose = suggested
        best_coverage = 0
        
        original_transpose = self.transpose
        
        for t in range(suggested - 12, suggested + 13):
            self.transpose = t
            coverage = self.analyze_coverage(midi_notes)['coverage']
            if coverage > best_coverage:
                best_coverage = coverage
                best_transpose = t
        
        self.transpose = original_transpose
        return best_transpose
    
    @staticmethod
    def is_black_key(midi_note: int) -> bool:
        """判断一个MIDI音符是否为黑键"""
        return midi_note % 12 in {1, 3, 6, 8, 10}
    
    @staticmethod
    def note_to_name(midi_note: int) -> str:
        """MIDI音符转音符名称"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = midi_note // 12 - 1
        return f"{note_names[midi_note % 12]}{octave}"
    
    def get_key_for_display(self, key: str, shift_mode: bool = False, ctrl_mode: bool = False) -> str:
        """获取按键的显示名称（支持三模式）"""
        if ctrl_mode:
            key_display = {
                # CTRL高音区白键 (C4-B4)
                'q': '1', 'w': '2', 'e': '3', 'r': '4', 't': '5', 'y': '6', 'u': '7',
                # CTRL中音区白键 (C3-B3)
                'a': '1̣', 's': '2̣', 'd': '3̣', 'f': '4̣', 'g': '5̣', 'h': '6̣', 'j': '7̣',
                # CTRL低音区白键 (C2-B2)
                'z': '1̤', 'x': '2̤', 'c': '3̤', 'v': '4̤', 'b': '5̤', 'n': '6̤', 'm': '7̤',
                # CTRL低音区黑键 (C#2-A#2)
                '1': '#1̤', '2': '#2̤', '3': '#4̤', '4': '#5̤', '5': '#6̤',
                # CTRL中音区黑键 (C#3-A#3)
                '6': '#1̣', '7': '#2̣', '8': '#4̣', '9': '#5̣', '0': '#6̣',
                # CTRL高音区黑键 (C#4-A#4)
                'i': '#1', 'o': '#2', 'p': '#4', '[': '#5', ']': '#6',
            }
        elif shift_mode:
            key_display = {
                # SHIFT高音区白键 (C6-B6)
                'q': '1̈', 'w': '2̈', 'e': '3̈', 'r': '4̈', 't': '5̈', 'y': '6̈', 'u': '7̈',
                # SHIFT中音区白键 (C5-B5)
                'a': '1̇', 's': '2̇', 'd': '3̇', 'f': '4̇', 'g': '5̇', 'h': '6̇', 'j': '7̇',
                # SHIFT低音区白键 (C4-B4)
                'z': '1', 'x': '2', 'c': '3', 'v': '4', 'b': '5', 'n': '6', 'm': '7',
                # SHIFT低音区黑键 (C#4-A#4)
                '1': '#1', '2': '#2', '3': '#4', '4': '#5', '5': '#6',
                # SHIFT中音区黑键 (C#5-A#5)
                '6': '#1̇', '7': '#2̇', '8': '#4̇', '9': '#5̇', '0': '#6̇',
                # SHIFT高音区黑键 (C#6-A#6)
                'i': '#1̈', 'o': '#2̈', 'p': '#4̈', '[': '#5̈', ']': '#6̈',
            }
        else:
            key_display = {
                # 高音区白键 (C5-B5)
                'q': '1̇', 'w': '2̇', 'e': '3̇', 'r': '4̇', 't': '5̇', 'y': '6̇', 'u': '7̇',
                # 中音区白键 (C4-B4)
                'a': '1', 's': '2', 'd': '3', 'f': '4', 'g': '5', 'h': '6', 'j': '7',
                # 低音区白键 (C3-B3)
                'z': '1̣', 'x': '2̣', 'c': '3̣', 'v': '4̣', 'b': '5̣', 'n': '6̣', 'm': '7̣',
                # 低音区黑键
                '1': '#1̣', '2': '#2̣', '3': '#4̣', '4': '#5̣', '5': '#6̣',
                # 中音区黑键
                '6': '#1', '7': '#2', '8': '#4', '9': '#5', '0': '#6',
                # 高音区黑键
                'i': '#1̇', 'o': '#2̇', 'p': '#4̇', '[': '#5̇', ']': '#6̇',
            }
        return key_display.get(key, key.upper())


# 全局映射器实例
_mapper = None

def get_mapper() -> KeyboardMapper:
    """获取全局映射器实例"""
    global _mapper
    if _mapper is None:
        _mapper = KeyboardMapper()
    return _mapper
