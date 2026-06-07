# -*- coding: utf-8 -*-
"""
自动改编质量评估：对多 BPM/调性/织体的曲子，对比改编前后的客观指标。
指标：音符数、密度、最大织体厚度、最快按键间隔、按键率、网格对齐率、旋律轮廓保真。
用法: python eval_arrange.py [可选:单文件]
"""
import sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from midi_parser import MidiParser

DIRS = [
    r'E:\弹琴\MID\啾啾音乐\古典乐\巴赫',
    r'E:\弹琴\MID\啾啾音乐\古典乐\多米尼克·史卡拉蒂 545',
    r'E:\弹琴\MID\啾啾音乐\古典乐\古典音乐 738',
    r'E:\弹琴\MID\啾啾音乐\流行音乐\周杰伦',
    r'E:\弹琴\MID\啾啾音乐\流行音乐\港台歌曲 592',
    r'E:\弹琴\MID\啾啾音乐\流行音乐\欧美流行\欧美流行 216',
    r'E:\弹琴\MID\淘宝卖的midi_2\2.二次元\Animenz',
    r'E:\弹琴\MID\淘宝卖的midi_2\2.二次元\MIKU初音',
    r'E:\弹琴\MID\淘宝卖的midi_2\1.中文流行\林俊杰',
    r'E:\弹琴\MID\淘宝卖的midi_2\日语\YOASOBI',
    r'E:\弹琴\MID\啾啾音乐\游戏音乐\东方幻想乡',
    r'E:\弹琴\MID\啾啾音乐\游戏音乐\FF\FF7',
    r'E:\弹琴\MID\啾啾音乐\久石让(推荐）',
    r'E:\弹琴\MID\淘宝卖的midi_2\儿歌',
    r'E:\弹琴\MID\啾啾音乐\爵士乐',
    r'E:\弹琴\MID\啾啾音乐\影视音乐113',
    r'E:\弹琴\MID\淘宝卖的midi_2\钢琴曲',
    r'E:\弹琴\MID\啾啾音乐\流行音乐\民族音乐 98',
]


def onsets(notes, w=0.05):
    ns = sorted(notes, key=lambda n: n.time)
    out = []; i = 0; N = len(ns)
    while i < N:
        t0 = ns[i].time; out.append(t0); j = i + 1
        while j < N and ns[j].time - t0 < w: j += 1
        i = j
    return out


def maxpoly(notes, w=0.03):
    t = sorted(n.time for n in notes); mp = 1; j = 0
    for i in range(len(t)):
        while t[i] - t[j] > w: j += 1
        mp = max(mp, i - j + 1)
    return mp


def topline(notes, w=0.05):
    """每个起音簇的最高音 = 旋律轮廓(粗)"""
    ns = sorted(notes, key=lambda n: n.time); out = []; i = 0; N = len(ns)
    while i < N:
        t0 = ns[i].time; top = ns[i].note; j = i + 1
        while j < N and ns[j].time - t0 < w:
            top = max(top, ns[j].note); j += 1
        out.append(top); i = j
    return out


def topslots(notes, step, t0):
    """每网格槽的顶音 {slot: pitch}"""
    d = {}
    for n in sorted(notes, key=lambda x: x.time):
        s = int((n.time - t0) / step + 0.5)
        if s not in d or n.note > d[s]:
            d[s] = n.note
    return d


def melody_accuracy(before, after, beat):
    """改编旋律忠实度：改编每槽顶音 ∈ 原曲该槽±1 顶音 的比例(不因抽稀而失真)。
    以拍格原点 t=0 为基准(与改编量化一致)，原曲也剔除鼓通道ch9(改编已剔除)。"""
    step = beat / 4.0
    t0 = 0.0
    before = [n for n in before if n.channel != 9]
    bt = topslots(before, step, t0)
    at = topslots(after, step, t0)
    if not at:
        return 0.0
    ok = sum(1 for s, p in at.items()
             if p in (bt.get(s - 1), bt.get(s), bt.get(s + 1)))
    return ok / len(at)


def load(path, arrange):
    p = MidiParser(); p.press_rate_limit_enabled = arrange
    p.enable_humanize = False   # 关掉极速段时间拉伸，让 before/after 在同一拍格上比较
    return p if p.load_file(path) else None


def evalfile(f):
    b = load(f, False); a = load(f, True)
    if not b or not a or not b.notes or not a.notes: return None
    ob, oa = onsets(b.notes), onsets(a.notes)
    iob = min((ob[k]-ob[k-1] for k in range(1, len(ob))), default=9)*1000
    ioa = min((oa[k]-oa[k-1] for k in range(1, len(oa))), default=9)*1000
    beat = 60.0/max(b.bpm, 1); g = beat/4
    aligned = sum(1 for t in oa if abs(((t/g)-round(t/g)))*g < 0.012)/max(len(oa), 1)
    contour = melody_accuracy(b.notes, a.notes, beat)
    return dict(bpm=b.bpm, dur=b.total_time,
                nb=len(b.notes), na=len(a.notes),
                pb=maxpoly(b.notes), pa=maxpoly(a.notes),
                rb=len(ob)/b.total_time, ra=len(oa)/a.total_time,
                iob=iob, ioa=ioa, align=aligned, contour=contour)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"{'file':36s} {'BPM':>4s} | {'note b>a':>11s} {'poly':>6s} {'rate b>a':>10s} {'minIOI a':>8s} {'grid%':>5s} {'轮廓':>5s}")
    print('-'*108)
    rows = []
    if arg and os.path.isdir(arg):
        # 目录模式：递归取样 N 个文件（默认6）
        nper = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        fs = sorted(glob.glob(os.path.join(arg, '**', '*.mid'), recursive=True))
        step = max(1, len(fs) // nper)
        items = [(os.path.basename(arg), f) for f in fs[::step][:nper]]
    elif arg and os.path.isfile(arg):
        items = [(os.path.basename(arg), arg)]
    else:
        items = []
        for d in DIRS:
            for f in sorted(glob.glob(os.path.join(d, '*.mid')))[:3]:
                items.append((os.path.basename(d), f))
    cur = None
    for tag, f in items:
        if tag != cur: print(f'--- {tag} ---'); cur = tag
        try:
            r = evalfile(f)
        except Exception as e:
            print(f'  ERR {os.path.basename(f)[:32]:32s} {str(e)[:40]}'); continue
        if not r: continue
        rows.append(r)
        flag = '' if (r['ioa'] >= 100 and r['pa'] <= 2 and r['contour'] >= 0.75) else '  <-- check'
        print(f"  {os.path.basename(f)[:34]:34s} {r['bpm']:4.0f} | "
              f"{r['nb']:5d}>{r['na']:<4d} {r['pb']:2d}>{r['pa']:<2d} "
              f"{r['rb']:4.1f}>{r['ra']:<4.1f} {r['ioa']:7.0f}ms {r['align']*100:4.0f}% {r['contour']*100:4.0f}%{flag}")
    if rows:
        import statistics as st
        print('-'*108)
        print(f"均值: 织体后={st.mean(r['pa'] for r in rows):.1f}  按键率后={st.mean(r['ra'] for r in rows):.1f}/s  "
              f"minIOI后={st.mean(r['ioa'] for r in rows):.0f}ms  网格对齐={st.mean(r['align'] for r in rows)*100:.0f}%  "
              f"轮廓保真={st.mean(r['contour'] for r in rows)*100:.0f}%")
        bad = [r for r in rows if r['ioa'] < 100 or r['pa'] > 2 or r['contour'] < 0.6]
        print(f"需检查: {len(bad)}/{len(rows)}")


if __name__ == '__main__':
    main()
