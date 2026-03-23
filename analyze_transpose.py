# -*- coding: utf-8 -*-
"""
调性检测模块
-----------
analyze_key(midi_path) -> dict | None

优先读取 MIDI 文件内嵌的 key_signature meta 事件;
若无标记则使用 Krumhansl-Schmuckler 音高类分布算法推测调性.

返回字典:
    key          : 完整调名 (如 "C大调", "A小调")
    raw          : 原始符号 (如 "C", "Am")
    is_major     : bool
    root         : 根音名 (C / C# / D …)
    semitones    : 根音距 C 的半音数 (0-11)
    suggested_semitones : 推荐 transpose 值 (移到 C 大调/A 小调所需半音数)
    source       : "meta" | "analysis"
"""

from __future__ import annotations
import os
from typing import Optional

# ── 音高名 ──────────────────────────────────────────────────────────
_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F',
               'F#', 'G', 'G#', 'A', 'A#', 'B']

# mido key_signature 字符串 → (根音半音, is_major)
_KEY_MAP: dict[str, tuple[int, bool]] = {
    'Cb': (11, True),  'C': ( 0, True),  'C#': ( 1, True),
    'Db': ( 1, True),  'D': ( 2, True),  'D#': ( 3, True),
    'Eb': ( 3, True),  'E': ( 4, True),  'F':  ( 5, True),
    'F#': ( 6, True),  'Gb': ( 6, True), 'G':  ( 7, True),
    'G#': ( 8, True),  'Ab': ( 8, True), 'A':  ( 9, True),
    'A#': (10, True),  'Bb': (10, True), 'B':  (11, True),
    'Abm': ( 8, False),'Am': ( 9, False),'A#m': (10, False),
    'Bbm': (10, False),'Bm': (11, False),'Cbm': (11, False),
    'C#m': ( 1, False),'Cm': ( 0, False),'Dbm': ( 1, False),
    'Dm': ( 2, False), 'D#m': ( 3, False),'Ebm': ( 3, False),
    'Em': ( 4, False), 'Fm': ( 5, False),'F#m': ( 6, False),
    'Gbm': ( 6, False),'Gm': ( 7, False),'G#m': ( 8, False),
}

# mido 有时用 'm' 结尾表示小调, 有时含空格
def _parse_mido_key(raw: str) -> tuple[int, bool] | None:
    s = raw.strip()
    if s.endswith('m'):
        root = s[:-1]
        if root in _KEY_MAP:
            r, _ = _KEY_MAP[root]
            return r, False
    if s in _KEY_MAP:
        return _KEY_MAP[s]
    # 尝试加 'm'
    sm = s + 'm'
    if sm in _KEY_MAP:
        return _KEY_MAP[sm]
    return None

# ── Krumhansl-Schmuckler 音高类轮廓 ────────────────────────────────
# 大调轮廓 (Krumhansl 1990)
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                  2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
# 小调轮廓 (Krumhansl 1990)
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                  2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

def _pearson_r(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den = (sum((v - mx) ** 2 for v in x) *
           sum((v - my) ** 2 for v in y)) ** 0.5
    return num / den if den else 0.0

def _detect_by_profile(pitch_counts: list[float]) -> tuple[int, bool, float]:
    """返回 (root_semitone, is_major, correlation)"""
    best_r = -2.0
    best_root = 0
    best_major = True
    for root in range(12):
        rotated = pitch_counts[root:] + pitch_counts[:root]
        r_maj = _pearson_r(rotated, _MAJOR_PROFILE)
        r_min = _pearson_r(rotated, _MINOR_PROFILE)
        if r_maj > best_r:
            best_r, best_root, best_major = r_maj, root, True
        if r_min > best_r:
            best_r, best_root, best_major = r_min, root, False
    return best_root, best_major, best_r

# ── 中文调名 ─────────────────────────────────────────────────────────
_CN_SUFFIX = {True: '大调', False: '小调'}

def _make_result(root: int, is_major: bool, source: str, raw: str = '') -> dict:
    note_name = _NOTE_NAMES[root % 12]
    if not raw:
        raw = note_name + ('' if is_major else 'm')
    suggested = (-root) % 12
    if suggested > 6:
        suggested -= 12
    return {
        'key': f'{note_name}{_CN_SUFFIX[is_major]}',
        'raw': raw,
        'is_major': is_major,
        'root': note_name,
        'semitones': root,
        'suggested_semitones': suggested,
        'source': source,
    }

# ── 主入口 ───────────────────────────────────────────────────────────
def analyze_key(midi_path: str) -> Optional[dict]:
    """分析 MIDI 文件调性.

    Returns:
        dict with fields: key, raw, is_major, root, semitones,
                          suggested_semitones, source
        None if file unreadable.
    """
    if not midi_path or not os.path.isfile(midi_path):
        return None
    try:
        import mido
    except ImportError:
        return None

    try:
        mid = mido.MidiFile(midi_path)
    except Exception:
        return None

    # ── 1. 尝试 meta key_signature ──────────────────────────────────
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'key_signature':
                raw_key = getattr(msg, 'key', '')
                if raw_key:
                    parsed = _parse_mido_key(raw_key)
                    if parsed:
                        root, is_major = parsed
                        return _make_result(root, is_major, 'meta', raw_key)

    # ── 2. Krumhansl-Schmuckler 分析 ────────────────────────────────
    pitch_counts: list[float] = [0.0] * 12
    ticks_per_beat = mid.ticks_per_beat or 480

    for track in mid.tracks:
        # 简单计算每个音符的 tick 时值 (note_on velocity>0 → note_off)
        active: dict[int, int] = {}   # note → tick_on
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                active[msg.note] = tick
            elif msg.type in ('note_off',) or (
                    msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active:
                    duration = tick - active.pop(msg.note)
                    pitch_counts[msg.note % 12] += duration

    total = sum(pitch_counts)
    if total < 1:
        return None

    pitch_norm = [v / total for v in pitch_counts]
    root, is_major, _ = _detect_by_profile(pitch_norm)
    return _make_result(root, is_major, 'analysis')
