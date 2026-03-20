# -*- coding: utf-8 -*-
"""
全面MIDI测试 - 加载所有MIDI文件并分析以下问题：
1. SHIFT切换频率（快切卡顿）
2. 延音踏板秒开秒关
3. 音符映射超出范围
4. 音符映射覆盖率
5. 连续同键快速按下
"""

import os
import sys
import time

# 加载项目模块
sys.path.insert(0, os.path.dirname(__file__))

from midi_parser import MidiParser, NoteEvent, SustainPedalEvent
from keyboard_mapper import KeyboardMapper
from config import MIDI_TO_KEY, MIDI_TO_KEY_SHIFT

def collect_midi_files(base_dir):
    """递归收集所有MIDI文件"""
    midi_files = []
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(('.mid', '.midi')):
                midi_files.append(os.path.join(root, f))
    return midi_files

def analyze_shift_switches(events, mapper):
    """分析SHIFT切换模式 - 检测快切问题（模拟防抖后的行为）"""
    MIN_DWELL_S = 0.400  # 400ms dwell time matching MIN_SHIFT_DWELL_MS
    shift_active = False
    last_switch_time = -999.0
    switches = []  # (time, target_state)
    
    for event in events:
        # 模拟 _play_events 的SHIFT决策逻辑
        midi_notes = []
        if isinstance(event.original_event, NoteEvent):
            midi_notes = [event.original_event.note]
        elif hasattr(event.original_event, 'midi_notes'):
            midi_notes = event.original_event.midi_notes
        
        if not midi_notes:
            continue
        
        # 48-59: 仅普通模式
        needs_normal = any(48 <= n <= 59 for n in midi_notes)
        # 84-95: 仅SHIFT模式
        needs_shift = any(84 <= n <= 95 for n in midi_notes)
        
        if needs_shift and not needs_normal:
            target = True
        elif needs_normal and not needs_shift:
            target = False
        elif needs_shift and needs_normal:
            # 冲突 - 看数量
            low = sum(1 for n in midi_notes if n < 60)
            high = sum(1 for n in midi_notes if n > 83)
            target = high >= low
        else:
            # 全在重叠区 -> 维持当前
            target = shift_active
        
        # 防抖：与上次切换间隔太短则放弃切换
        if target != shift_active:
            if event.time - last_switch_time >= MIN_DWELL_S:
                switches.append((event.time, target))
                shift_active = target
                last_switch_time = event.time
            # else: would fold, no switch
    
    return switches

def analyze_sustain_events(sustain_events):
    """分析延音踏板事件 - 检测秒开秒关"""
    problems = []
    for i in range(len(sustain_events) - 1):
        evt = sustain_events[i]
        next_evt = sustain_events[i + 1]
        gap = next_evt.time - evt.time
        
        # 秒开秒关：ON后极短时间OFF
        if evt.is_on and not next_evt.is_on and gap < 0.1:
            problems.append({
                'type': 'quick_off',
                'time': evt.time,
                'gap_ms': gap * 1000,
                'desc': f"t={evt.time:.2f}s: ON后{gap*1000:.0f}ms就OFF"
            })
        
        # 秒关秒开：OFF后极短时间ON
        if not evt.is_on and next_evt.is_on and gap < 0.06:
            problems.append({
                'type': 'quick_on', 
                'time': evt.time,
                'gap_ms': gap * 1000,
                'desc': f"t={evt.time:.2f}s: OFF后{gap*1000:.0f}ms就ON"
            })
    
    return problems

def analyze_note_mapping(events, mapper):
    """分析音符映射 - 检测无法映射的音符"""
    unmapped = {}  # note -> count
    mapped_count = 0
    total_count = 0
    out_of_range = {}  # note -> count
    
    for event in events:
        midi_notes = []
        if isinstance(event.original_event, NoteEvent):
            midi_notes = [event.original_event.note]
        elif hasattr(event.original_event, 'midi_notes'):
            midi_notes = event.original_event.midi_notes
        
        for note in midi_notes:
            total_count += 1
            # 检查是否在48-95范围内
            if note < 48 or note > 95:
                out_of_range[note] = out_of_range.get(note, 0) + 1
            
            # 检查映射
            mapped_note = note
            while mapped_note < 48:
                mapped_note += 12
            while mapped_note > 95:
                mapped_note -= 12
            
            key_normal = MIDI_TO_KEY.get(mapped_note)
            key_shift = MIDI_TO_KEY_SHIFT.get(mapped_note)
            
            if key_normal or key_shift:
                mapped_count += 1
            else:
                unmapped[mapped_note] = unmapped.get(mapped_note, 0) + 1
    
    return {
        'total': total_count,
        'mapped': mapped_count,
        'unmapped': unmapped,
        'out_of_range': out_of_range,
        'coverage': mapped_count / total_count * 100 if total_count > 0 else 0
    }

def analyze_rapid_same_key(events, mapper):
    """分析快速同键按下 - 可能导致吞音"""
    # 模拟按键时间
    last_key_time = {}
    rapid_presses = []
    
    for event in events:
        midi_notes = []
        if isinstance(event.original_event, NoteEvent):
            midi_notes = [event.original_event.note]
        elif hasattr(event.original_event, 'midi_notes'):
            midi_notes = event.original_event.midi_notes
        
        for note in midi_notes:
            mapped_note = note
            while mapped_note < 48:
                mapped_note += 12
            while mapped_note > 95:
                mapped_note -= 12
            
            key = MIDI_TO_KEY.get(mapped_note) or MIDI_TO_KEY_SHIFT.get(mapped_note)
            if key:
                if key in last_key_time:
                    gap = event.time - last_key_time[key]
                    if 0 < gap < 0.167:  # PER_KEY_MIN_INTERVAL_LOW  
                        rapid_presses.append({
                            'key': key,
                            'note': mapped_note,
                            'time': event.time,
                            'gap_ms': gap * 1000,
                        })
                last_key_time[key] = event.time
    
    return rapid_presses

def analyze_shift_rapid_switching(switches):
    """分析SHIFT快速来回切换 - 这是卡顿的根源"""
    rapid_pairs = []
    for i in range(len(switches) - 1):
        t1, s1 = switches[i]
        t2, s2 = switches[i + 1]
        gap = t2 - t1
        if gap < 0.3:  # 300ms内来回切换
            rapid_pairs.append({
                'time': t1,
                'gap_ms': gap * 1000,
                'desc': f"t={t1:.2f}s: {'→SHIFT' if s1 else '→Normal'}后{gap*1000:.0f}ms又{'→Normal' if s1 else '→SHIFT'}"
            })
    return rapid_pairs


def test_midi_file(filepath, mapper):
    """测试单个MIDI文件"""
    parser = MidiParser()
    
    try:
        success = parser.load_file(filepath)
        if not success:
            return {'error': '加载失败'}
    except Exception as e:
        return {'error': str(e)}
    
    events = parser.get_play_events()
    if not events:
        return {'error': '无播放事件'}
    
    results = {}
    results['total_time'] = parser.total_time
    results['note_count'] = len(events)
    
    # 1. SHIFT切换分析
    switches = analyze_shift_switches(events, mapper)
    results['shift_switches'] = len(switches)
    results['shift_rapid'] = analyze_shift_rapid_switching(switches)
    
    # 如果存在事件，计算切换频率
    if parser.total_time > 0:
        results['shift_rate'] = len(switches) / parser.total_time  # 次/秒
    else:
        results['shift_rate'] = 0
    
    # 2. 延音踏板分析
    sustain_events = parser.sustain_events if hasattr(parser, 'sustain_events') else []
    results['sustain_event_count'] = len(sustain_events)
    results['sustain_problems'] = analyze_sustain_events(sustain_events)
    
    # 3. 音符映射分析
    results['mapping'] = analyze_note_mapping(events, mapper)
    
    # 4. 快速同键分析
    rapid = analyze_rapid_same_key(events, mapper)
    results['rapid_same_key_count'] = len(rapid)
    
    # 5. 检查原始音域范围
    all_notes = []
    for event in events:
        if isinstance(event.original_event, NoteEvent):
            all_notes.append(event.original_event.note)
        elif hasattr(event.original_event, 'midi_notes'):
            all_notes.extend(event.original_event.midi_notes)
    
    if all_notes:
        results['note_range'] = (min(all_notes), max(all_notes))
        results['octaves_used'] = (max(all_notes) - min(all_notes)) // 12 + 1
    
    return results


def main():
    midi_dir = os.path.join(os.path.dirname(__file__), 'Midi')
    midi_files = collect_midi_files(midi_dir)
    
    if not midi_files:
        print("未找到MIDI文件！")
        return
    
    print(f"找到 {len(midi_files)} 个MIDI文件\n")
    print("=" * 100)
    
    mapper = KeyboardMapper()
    
    all_results = {}
    critical_issues = []
    
    for filepath in sorted(midi_files):
        filename = os.path.relpath(filepath, midi_dir)
        print(f"\n{'='*80}")
        print(f"文件: {filename}")
        print(f"{'='*80}")
        
        result = test_midi_file(filepath, mapper)
        all_results[filename] = result
        
        if 'error' in result:
            print(f"  ❌ 错误: {result['error']}")
            continue
        
        # 基本信息
        print(f"  时长: {result['total_time']:.1f}s | 事件数: {result['note_count']}")
        if 'note_range' in result:
            lo, hi = result['note_range']
            print(f"  音域: MIDI {lo}-{hi} ({result['octaves_used']}个八度)")
        
        # SHIFT问题
        print(f"\n  [SHIFT] 总切换: {result['shift_switches']}次, 频率: {result['shift_rate']:.2f}次/秒")
        if result['shift_rapid']:
            print(f"  ⚠️ 快速来回切换: {len(result['shift_rapid'])}次!")
            for p in result['shift_rapid'][:5]:
                print(f"    - {p['desc']}")
            if len(result['shift_rapid']) > 5:
                print(f"    ... 还有{len(result['shift_rapid'])-5}次")
            critical_issues.append(f"{filename}: SHIFT快切{len(result['shift_rapid'])}次")
        
        # 延音问题
        print(f"\n  [延音] 踏板事件: {result['sustain_event_count']}个")
        if result['sustain_problems']:
            print(f"  ⚠️ 异常踏板: {len(result['sustain_problems'])}个!")
            for p in result['sustain_problems'][:5]:
                print(f"    - {p['desc']}")
            if len(result['sustain_problems']) > 5:
                print(f"    ... 还有{len(result['sustain_problems'])-5}个")
            critical_issues.append(f"{filename}: 踏板异常{len(result['sustain_problems'])}次")
        
        # 映射问题
        mapping = result['mapping']
        print(f"\n  [映射] 覆盖率: {mapping['coverage']:.1f}% ({mapping['mapped']}/{mapping['total']})")
        if mapping['unmapped']:
            print(f"  ⚠️ 无法映射: {mapping['unmapped']}")
            critical_issues.append(f"{filename}: 无法映射{sum(mapping['unmapped'].values())}个音符")
        if mapping['out_of_range']:
            print(f"  ⚠️ 超出范围: {mapping['out_of_range']}")
        
        # 速率限制
        if result['rapid_same_key_count'] > 0:
            print(f"\n  [速率] 被限速丢弃: 约{result['rapid_same_key_count']}个音符")
    
    # === 总结 ===
    print(f"\n\n{'='*100}")
    print("总结")
    print(f"{'='*100}")
    
    if critical_issues:
        print(f"\n⚠️ 发现 {len(critical_issues)} 个严重问题:")
        for issue in critical_issues:
            print(f"  - {issue}")
    else:
        print("\n✅ 未发现严重问题")
    
    # SHIFT切换统计
    shift_counts = [(name, r.get('shift_switches', 0), r.get('shift_rate', 0), len(r.get('shift_rapid', [])))
                    for name, r in all_results.items() if 'error' not in r]
    shift_counts.sort(key=lambda x: x[3], reverse=True)
    
    print(f"\nSHIFT切换排名 (快切最多的曲目):")
    for name, total, rate, rapid in shift_counts[:10]:
        flag = " ⚠️" if rapid > 0 else ""
        print(f"  {name}: 总{total}次, {rate:.2f}/s, 快切{rapid}次{flag}")
    
    # 映射覆盖率统计
    coverage_stats = [(name, r.get('mapping', {}).get('coverage', 0))
                      for name, r in all_results.items() if 'error' not in r]
    coverage_stats.sort(key=lambda x: x[1])
    
    print(f"\n映射覆盖率排名 (最差的):")
    for name, cov in coverage_stats[:10]:
        flag = " ⚠️" if cov < 100 else ""
        print(f"  {name}: {cov:.1f}%{flag}")


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
