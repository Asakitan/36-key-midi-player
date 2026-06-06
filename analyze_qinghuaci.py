# -*- coding: utf-8 -*-
"""
验证"按键限速/抽稀重编曲"：对比开/关限速后，每个 MIDI 经 midiplayer 解析管线后的
实际按键节奏。确认抽稀后最快按键间隔 >= 上限，并报告音符保留率与旋律线保留率。

用法: python analyze_qinghuaci.py [可选:单个mid路径]
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from midi_parser import MidiParser
from config import MIN_PRESS_INTERVAL_S

FILES = [
    r"E:\弹琴\MID\01676-青花瓷简单版-EOP教学曲.mid",
    r"E:\弹琴\MID\00193-青花瓷.mid",
    r"E:\弹琴\MID\07364-青花瓷-完美演奏版--周杰伦.mid",
]
if len(sys.argv) > 1:
    FILES = [sys.argv[1]]


def press_onsets(notes, window=0.05):
    """把音符按 50ms 归并成按键时刻，返回起音时间列表（升序）。"""
    ns = sorted(notes, key=lambda n: n.time)
    onsets = []
    i, n = 0, len(ns)
    while i < n:
        t0 = ns[i].time
        onsets.append(t0)
        j = i + 1
        while j < n and ns[j].time - t0 < window:
            j += 1
        i = j
    return onsets


def min_ioi(onsets):
    if len(onsets) < 2:
        return None
    return min(onsets[k] - onsets[k - 1] for k in range(1, len(onsets))) * 1000


def load(path, limit):
    p = MidiParser()
    p.press_rate_limit_enabled = limit
    ok = p.load_file(path)
    return p if ok else None


def main():
    G_ms = MIN_PRESS_INTERVAL_S * 1000
    print(f"speed limit = {G_ms:.1f} ms  (>= {1000.0/G_ms:.2f} presses/sec)\n")
    all_ok = True
    for f in FILES:
        name = f.split("\\")[-1]
        print(f"==== {name} ====")
        before = load(f, limit=False)
        after = load(f, limit=True)
        if not before or not after:
            print("  加载失败"); continue

        on_b = press_onsets(before.notes)
        on_a = press_onsets(after.notes)
        ioi_b = min_ioi(on_b)
        ioi_a = min_ioi(on_a)
        rate_b = len(on_b) / before.total_time
        rate_a = len(on_a) / after.total_time

        # 旋律线保留率
        bpm = after.bpm or 120
        mel = before._extract_skyline_melody(sorted(before.notes, key=lambda n: n.time), 60.0 / max(bpm, 1))
        # 用 (note,round(time,3)) 作为身份在 before/after 间匹配（after 是 before 的子集，时间未变）
        after_key = set((round(n.time, 3), n.note) for n in after.notes)
        mel_total = len(mel)
        mel_kept = sum(1 for n in mel if (round(n.time, 3), n.note) in after_key)

        ok = (ioi_a is None) or (ioi_a >= G_ms - 3)
        all_ok = all_ok and ok
        print(f"  BPM={before.bpm:.0f}  时长={before.total_time:.0f}s")
        print(f"  音符  : {len(before.notes):5d} -> {len(after.notes):5d}  (保留{len(after.notes)/len(before.notes)*100:4.0f}%)")
        print(f"  按键组: {len(on_b):5d} -> {len(on_a):5d}  (按键率 {rate_b:.2f} -> {rate_a:.2f} 组/秒)")
        print(f"  最快按键间隔: {ioi_b:.1f}ms -> {ioi_a:.1f}ms   {'[OK >=上限]' if ok else '[!! 仍超限]'}")
        print(f"  旋律线保留: {mel_kept}/{mel_total} ({mel_kept/max(mel_total,1)*100:.0f}%)")
        print()
    print("==== 全部满足上限 ====" if all_ok else "==== 有文件仍超限, 需检查 ====")


if __name__ == '__main__':
    main()
