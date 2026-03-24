# -*- coding: utf-8 -*-
"""
60键电子琴 MIDI播放器
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


def _load_ui_mode():
    """从 settings.json 读取 ui_mode"""
    import json
    try:
        # 打包后 __file__ 指向 exe 内部临时目录, 必须用 sys.executable 所在目录
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        cfg = os.path.join(base, 'settings.json')
        if os.path.exists(cfg):
            with open(cfg, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('ui_mode', 'sao')
    except Exception:
        pass
    return 'sao'  # 默认 SAO 模式


def main():
    """主函数"""
    # 设置 DPI 感知 — 减少 Tkinter 控件模糊 / 锯齿
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    print("=" * 50)
    print("  60键电子琴 MIDI播放器")
    print("=" * 50)
    
    # 检查依赖
    if not check_dependencies():
        import time
        time.sleep(3)  # 显示3秒后自动退出
        return

    ui_mode = _load_ui_mode()
    print(f"\nUI 模式: {ui_mode}")

    # 导入并运行GUI — 支持 3 种 UI 模式
    try:
        if ui_mode == 'webview':
            # 最新 WebView UI (pywebview + HTML/CSS)
            try:
                from sao_webview import SAOWebViewGUI, is_webview_available
                if is_webview_available():
                    print("\n启动 SAO WebView GUI (HTML/CSS 渲染)...")
                    print("提示: 点击 HP 栏打开 SAO 菜单")
                    app = SAOWebViewGUI()
                else:
                    raise ImportError("pywebview not available")
            except ImportError:
                print("pywebview 不可用, 回退到 SAO Entity UI...")
                from sao_gui import SAOPlayerGUI
                app = SAOPlayerGUI()
        elif ui_mode == 'sao':
            # SAO Entity UI (tkinter SAO 主题)
            # 兼容旧配置: 'sao' 曾经是 webview 优先, 现在直接启动 tkinter SAO
            from sao_gui import SAOPlayerGUI
            print("\n启动 SAO Entity GUI (tkinter)...")
            print("提示: Alt+A 打开 SAO 菜单")
            app = SAOPlayerGUI()
        elif ui_mode == 'old':
            from gui import MidiPlayerGUI
            print("\n启动 Old School GUI...")
            print("提示: 播放MIDI时请切换到游戏窗口")
            app = MidiPlayerGUI()
        else:
            # 未知模式 — 默认尝试 webview → sao → old
            try:
                from sao_webview import SAOWebViewGUI, is_webview_available
                if is_webview_available():
                    app = SAOWebViewGUI()
                else:
                    raise ImportError
            except ImportError:
                try:
                    from sao_gui import SAOPlayerGUI
                    app = SAOPlayerGUI()
                except ImportError:
                    from gui import MidiPlayerGUI
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
