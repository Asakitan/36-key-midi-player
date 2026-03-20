#!/usr/bin/env python3
"""测试C调直转映射"""
from player import MidiPlayer

def test_mapping(midi_path):
    print(f"测试文件: {midi_path}")
    print("="*60)
    
    p = MidiPlayer()
    p.load_midi(midi_path)
    p.set_direct_c_mode(True, save=False)
    
    names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    WHITE_KEYS = {0, 2, 4, 5, 7, 9, 11}
    
    # 获取移调量
    if p._detected_mode == 'major':
        transpose = (0 - p._detected_key) % 12
        if transpose > 6:
            transpose -= 12
    else:
        transpose = (9 - p._detected_key) % 12
        if transpose > 6:
            transpose -= 12
    
    print(f"\n原调: {p._get_key_name(p._detected_key)} {p._detected_mode}")
    print(f"移调量: {transpose:+d} 半音")
    
    print("\n音符映射详情:")
    sorted_notes = sorted(p._direct_c_note_map.keys())
    for note in sorted_notes:
        info = p._direct_c_note_map[note]
        orig_name = f"{names[note % 12]}{note // 12 - 1}"
        target_midi = info['midi']
        target_name = f"{names[target_midi % 12]}{target_midi // 12 - 1}"
        match = "✓" if info['distance'] == 0 else "~"
        
        # 计算移调后应该是什么音
        transposed_pc = (note + transpose) % 12
        expected_name = names[transposed_pc]
        
        print(f"  {match} {orig_name:4}(M{note:2d}) +{transpose:+d}={expected_name:2} -> {target_name:4}(M{target_midi:2d})")
    
    # 验证映射正确性
    print("\n映射正确性检查:")
    issues = []
    for note in sorted_notes:
        info = p._direct_c_note_map[note]
        transposed_pc = (note + transpose) % 12  # 移调后的音级
        target_pc = info['midi'] % 12  # 目标音级
        
        # 移调后如果是白键，应该映射到相同的白键
        if transposed_pc in WHITE_KEYS:
            if transposed_pc != target_pc:
                issues.append(f"  ❌ {names[note%12]} 移调后是 {names[transposed_pc]}，应映射到 {names[transposed_pc]}，但映射到了 {names[target_pc]}")
    
    if issues:
        print("发现问题:")
        for issue in issues:
            print(issue)
    else:
        print("  ✓ 所有移调后的白键都正确映射到对应白键")

if __name__ == "__main__":
    # 测试天空之城(C大调/A小调)
    test_mapping(r"Midi/C调/01677-天空之城C调完美简单版.mid")
    print("\n")
    # 测试夜曲(F小调)
    test_mapping(r"Midi/13057-夜曲-简单版.mid")
    print("\n")
    # 测试千本樱
    test_mapping(r"Midi/01801-千本樱-初音未来.mid")
