#!/usr/bin/env python3
"""
测试改进后的调性检测算法
"""
import os
from player import MidiPlayer

def test_key_detection(midi_path: str):
    """测试单个MIDI文件的调性检测"""
    print(f"\n{'='*60}")
    print(f"测试文件: {os.path.basename(midi_path)}")
    print(f"{'='*60}")
    
    player = MidiPlayer()
    success = player.load_midi(midi_path)
    
    if not success:
        print("文件加载失败!")
        return None
    
    # 启用C调直转模式，触发调性检测
    player.set_direct_c_mode(True)
    
    # 获取检测结果
    info = player.get_direct_c_info()
    
    print(f"\n检测结果:")
    print(f"  原曲调性: {info['detected_key_name']} {info['detected_mode']}")
    print(f"  检测置信度: {info.get('confidence', 0):.3f}")
    print(f"  音符映射数: {info['note_count']}")
    print(f"  和弦映射数: {info['chord_count']}")
    
    return info

def main():
    print("=" * 60)
    print("调性检测算法测试")
    print("算法: 综合Aarden-Essen + Krumhansl-Schmuckler + Bellman-Budge")
    print("改进: 时值加权 + 皮尔逊相关系数 + 多算法投票")
    print("=" * 60)
    
    # 测试多个MIDI文件
    test_files = [
        r"Midi/13057-夜曲-简单版.mid",
        r"Midi/好歌/菊次郎的夏天.mid",
        r"Midi/01801-千本樱-初音未来.mid",
        r"Midi/好歌/稻香-简单版.mid",
        r"Midi/《原神》剧情PV-「神女劈观」.mid",
        r"Midi/07030-刚刚好-薛之谦.mid",
        r"Midi/02371-神々が恋した幻想郷-众神眷恋的幻想乡-东方Project.mid"
    ]
    
    results = []
    for file_path in test_files:
        if os.path.exists(file_path):
            info = test_key_detection(file_path)
            if info:
                results.append({
                    'file': os.path.basename(file_path),
                    'key': info['detected_key_name'],
                    'mode': info['detected_mode'],
                    'confidence': info.get('confidence', 0)
                })
        else:
            print(f"\n文件不存在: {file_path}")
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("检测结果汇总")
    print("=" * 60)
    print(f"{'文件名':<40} {'调性':<12} {'置信度'}")
    print("-" * 60)
    for r in results:
        mode_cn = '大调' if r['mode'] == 'major' else '小调'
        conf_stars = "★" * min(3, int(r['confidence'] * 3 + 0.5))
        conf_stars = conf_stars.ljust(3, "☆")
        print(f"{r['file']:<40} {r['key']:<3}{mode_cn:<6} {r['confidence']:.3f} {conf_stars}")

if __name__ == "__main__":
    main()
