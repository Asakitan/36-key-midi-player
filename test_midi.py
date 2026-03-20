# -*- coding: utf-8 -*-
"""测试MIDI解析和快捷键"""
from player import MidiPlayer
from midi_parser import MidiParser

# 测试1: 检查MIDI解析
print("=" * 50)
print("测试: 众神眷恋的幻想乡 MIDI解析")
print("=" * 50)

midi_path = r'E:\VC\28midi\Midi\02371-神々が恋した幻想郷-众神眷恋的幻想乡-东方Project.mid'

# 直接用解析器测试
parser = MidiParser()
success = parser.load_file(midi_path)
print(f'解析器加载: {success}')
print(f'总音符数: {len(parser.notes)}')
print(f'总时长: {parser.total_time:.1f}秒 ({parser.total_time/60:.1f}分钟)')
print(f'BPM: {parser.bpm}')

# 检查音域分布
notes = [n.note for n in parser.notes]
if notes:
    print(f'\n音域: MIDI {min(notes)}-{max(notes)}')
    
    # 统计各八度的音符数
    octave_counts = {}
    for n in notes:
        octave = n // 12
        octave_counts[octave] = octave_counts.get(octave, 0) + 1
    
    print('\n各八度音符分布:')
    for octave in sorted(octave_counts.keys()):
        midi_start = octave * 12
        midi_end = octave * 12 + 11
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        print(f'  八度{octave} (MIDI {midi_start}-{midi_end}): {octave_counts[octave]}个音符')

# 用播放器测试
print('\n' + '=' * 50)
print('播放器加载测试')
print('=' * 50)

p = MidiPlayer()
success = p.load_midi(midi_path)
print(f'播放器加载: {success}')
print(f'播放事件数: {len(p.parser.play_events)}')

# 检查重映射
remap = getattr(p, '_note_remap', {})
print(f'\n重映射音符数: {len(remap)}')
if remap:
    print('重映射详情:')
    for orig, new in sorted(remap.items()):
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        orig_name = f"{note_names[orig % 12]}{orig // 12 - 1}"
        new_name = f"{note_names[new % 12]}{new // 12 - 1}"
        print(f'  {orig_name}(MIDI {orig}) -> {new_name}(MIDI {new})')

# 检查前10个播放事件
print('\n前10个播放事件:')
for i, event in enumerate(p.parser.play_events[:10]):
    print(f'  {i+1}. 时间={event.time:.3f}s, 音符={event.note}, 时长={event.duration:.3f}s')
