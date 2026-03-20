# -*- coding: utf-8 -*-
"""
36键电子琴 MIDI播放器
主程序入口

使用方法:
1. 安装依赖: pip install -r requirements.txt
2. 运行: python main.py
3. 在GUI中选择MIDI文件并播放
4. 播放时确保游戏窗口处于激活状态

模块结构:
- config.py: 配置文件（键盘映射、设置等）
- midi_parser.py: MIDI文件解析
- keyboard_mapper.py: 音符到按键映射
- player.py: 播放控制和键盘模拟
- gui.py: 图形用户界面
"""

import sys
import os

# 确保能找到模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_dependencies():
    """检查依赖是否安装"""
    missing = []
    
    try:
        import mido
    except ImportError:
        missing.append('mido')
        
    try:
        import keyboard
    except ImportError:
        try:
            from pynput import keyboard as pynput_kb
        except ImportError:
            missing.append('keyboard 或 pynput')
            
    if missing:
        print("缺少以下依赖，请安装:")
        print(f"  pip install {' '.join(missing)}")
        print("\n或运行: pip install -r requirements.txt")
        # 不再使用 input() 以支持打包后的GUI程序
        import time
        time.sleep(3)  # 显示3秒后自动退出
        return False
        
    return True


def main():
    """主函数"""
    print("=" * 50)
    print("  36键电子琴 MIDI播放器")
    print("=" * 50)
    
    # 检查依赖
    if not check_dependencies():
        import time
        time.sleep(3)  # 显示3秒后自动退出
        return
        
    # 导入并运行GUI
    try:
        from gui import MidiPlayerGUI
        
        print("\n启动GUI...")
        print("提示: 播放MIDI时请切换到游戏窗口")
        print("提示: 需要管理员权限才能模拟按键")
        
        app = MidiPlayerGUI()
        app.run()
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        # 不再使用 input() 以支持打包后的GUI程序
        import time
        time.sleep(5)  # 显示5秒后自动退出


if __name__ == "__main__":
    main()
