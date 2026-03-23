# -*- coding: utf-8 -*-
"""
咲 Midi Player — 一键安装依赖脚本
自动检测并安装所需 Python 包
"""

import subprocess
import sys
import os

# ═══════════════════════════════════════════════
#  依赖列表
# ═══════════════════════════════════════════════

REQUIRED = [
    ('mido', 'mido>=1.2.10', '解析 MIDI 文件'),
    ('keyboard', 'keyboard>=0.13.5', '键盘模拟 (需管理员权限)'),
]

OPTIONAL = [
    ('moderngl', 'moderngl>=5.8', 'Link Start 3D 动画 (OpenGL 渲染)'),
    ('numpy', 'numpy>=1.20', '鱼眼特效 / 3D 动画计算'),
    ('requests', 'requests>=2.20', '角色自动识别 (连接本地服务)'),
]

OPTIONAL_AUDIO = [
    ('fluidsynth', 'pyfluidsynth', 'FluidSynth 高品质音色 (需系统安装 FluidSynth)'),
    ('pygame', 'pygame', 'Pygame MIDI 回退方案'),
]


def check_installed(module_name):
    """检查模块是否已安装"""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def install_package(pip_name):
    """安装 pip 包"""
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', pip_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return True
    except subprocess.CalledProcessError:
        return False


def main():
    print('=' * 50)
    print('  咲 Midi Player — 依赖安装工具')
    print('=' * 50)
    print()

    # 检查 pip
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', '--version'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception:
        print('[!] pip 未安装, 请先安装 pip')
        return

    # ── 必需依赖 ──
    print('【必需依赖】')
    missing_required = []
    for mod, pip_name, desc in REQUIRED:
        if check_installed(mod):
            print(f'  ✓ {mod:<15} 已安装  ({desc})')
        else:
            print(f'  ✗ {mod:<15} 未安装  ({desc})')
            missing_required.append((mod, pip_name, desc))

    print()

    # ── 可选依赖 ──
    print('【可选依赖 — 增强功能】')
    missing_optional = []
    for mod, pip_name, desc in OPTIONAL:
        if check_installed(mod):
            print(f'  ✓ {mod:<15} 已安装  ({desc})')
        else:
            print(f'  ○ {mod:<15} 未安装  ({desc})')
            missing_optional.append((mod, pip_name, desc))

    print()
    print('【可选依赖 — 音频增强】')
    for mod, pip_name, desc in OPTIONAL_AUDIO:
        if check_installed(mod):
            print(f'  ✓ {mod:<15} 已安装  ({desc})')
        else:
            print(f'  ○ {mod:<15} 未安装  ({desc})')

    print()
    print('-' * 50)

    # ── 安装必需依赖 ──
    if missing_required:
        print(f'\n发现 {len(missing_required)} 个缺失的必需依赖, 正在安装...\n')
        for mod, pip_name, desc in missing_required:
            print(f'  安装 {pip_name} ...', end=' ', flush=True)
            if install_package(pip_name):
                print('✓ 成功')
            else:
                print('✗ 失败 — 请手动运行: pip install ' + pip_name)

    # ── 安装可选依赖 ──
    if missing_optional:
        print(f'\n是否安装 {len(missing_optional)} 个可选依赖? (推荐)')
        choice = input('  输入 y 安装, n 跳过 [Y/n]: ').strip().lower()
        if choice != 'n':
            for mod, pip_name, desc in missing_optional:
                print(f'  安装 {pip_name} ...', end=' ', flush=True)
                if install_package(pip_name):
                    print('✓ 成功')
                else:
                    print('✗ 失败')

    print()

    # ── SoundFont 检查 ──
    sf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soundfonts')
    sf_files = []
    if os.path.isdir(sf_dir):
        sf_files = [f for f in os.listdir(sf_dir) if f.endswith('.sf2')]

    if sf_files:
        print(f'✓ SoundFont 文件: {", ".join(sf_files)}')
    else:
        print('○ 未找到 SoundFont 文件 (.sf2)')
        print('  推荐下载 GeneralUser GS:')
        print('  https://schristiancollins.com/generaluser.php')
        print(f'  放置到: {sf_dir}/')

    print()
    print('=' * 50)
    print('  安装完成! 运行 main.py 启动程序')
    print('=' * 50)


if __name__ == '__main__':
    main()
