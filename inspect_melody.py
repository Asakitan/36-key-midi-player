# -*- coding: utf-8 -*-
"""检查改编后旋律是否忠实于原曲顶线：melody_accuracy = 改编旋律落在原顶线同槽且音高一致的比例。"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from midi_parser import MidiParser

NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def nm(p): return f"{NAMES[p%12]}{p//12-1}"

def load(f, arr):
    p = MidiParser(); p.press_rate_limit_enabled = arr
    return p if p.load_file(f) else None

def topline_at(notes, step, t0):
    """每槽顶音 {slot: pitch}"""
    d = {}
    for n in sorted(notes, key=lambda x: x.time):
        s = int((n.time - t0)/step + 0.5)
        if s not in d or n.note > d[s]: d[s] = n.note
    return d

def main():
    f = sys.argv[1]
    win = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    b = load(f, False); a = load(f, True)
    beat = 60.0/max(b.bpm,1); step = beat/4
    t0 = min(n.time for n in b.notes)
    bt = topline_at(b.notes, step, t0)
    at = topline_at(a.notes, step, t0)
    # accuracy: 改编每槽顶音是否=原曲该槽(或相邻槽)顶音
    ok = 0; tot = 0
    for s, p in at.items():
        tot += 1
        cands = [bt.get(s-1), bt.get(s), bt.get(s+1)]
        if p in cands: ok += 1
    print(f"{os.path.basename(f)}  BPM={b.bpm:.0f} step={step*1000:.0f}ms")
    print(f"旋律忠实度(改编顶音∈原顶音±1槽) = {ok}/{tot} = {ok/max(tot,1)*100:.0f}%")
    # 打印前 win 秒的对照
    nslot = int(win/step)
    print(f"槽 |原顶线           |改编旋律")
    for s in range(nslot):
        bp = bt.get(s); ap = at.get(s)
        print(f"{s:3d}| {nm(bp) if bp else '-':14s}| {nm(ap) if ap else '-'}")

if __name__ == '__main__':
    main()
