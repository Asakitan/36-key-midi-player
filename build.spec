# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
使用方法: pyinstaller build.spec
"""

import sys
import os

block_cipher = None

# 获取当前目录
spec_dir = os.path.dirname(os.path.abspath(SPEC))

# pywebview 自带 PyInstaller hook (自动打包 WebView2 DLL 和 JS 文件)
import webview as _wv
_wv_hook = os.path.join(os.path.dirname(_wv.__file__), '__pyinstaller')

main_hiddenimports = [
    # MIDI
    'mido',
    'mido.backends',
    'mido.backends.rtmidi',
    # 键盘
    'keyboard',
    'pynput',
    'pynput.keyboard',
    'pynput.keyboard._win32',
    'pynput.mouse',
    'pynput.mouse._win32',
    # 图像
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',
    'PIL.ImageFilter',
    'mss',
    'mss.windows',
    # 音频
    'pygame',
    'pygame.mixer',
    'winsound',
    # OpenGL
    'moderngl',
    'moderngl.mgl',
    # WebView
    'webview',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'webview.guilib',
    'webview.http',
    # .NET / pythonnet (pywebview EdgeChromium 依赖)
    'clr',
    'clr_loader',
    'pythonnet',
    # numpy
    'numpy',
    'numpy.core',
    # 排行榜
    'leaderboard',
    # 项目模块
    'sao_gui',
    'sao_webview',
    'sao_theme',
    'sao_sound',
    'character_profile',
    'midi_controller',
    'midi_parser',
    'keyboard_mapper',
    'player',
    'config',
    'gui',
    # 标准库
    'json',
    'ctypes',
    'threading',
    'http.server',
    'http.client',
]

server_hiddenimports = [
    'flask',
    'flask.json',
    'flask.logging',
    'werkzeug',
    'werkzeug.serving',
    'werkzeug.routing',
    'jinja2',
    'markupsafe',
    'itsdangerous',
    'click',
    'cryptography',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.padding',
    'cryptography.hazmat.backends',
    'hashlib',
    'hmac',
    'base64',
    'threading',
    'datetime',
    'json',
    'http.server',
]

a = Analysis(
    ['main.py'],
    pathex=[spec_dir],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('web', 'web'),
        ('assets', 'assets'),
        ('soundfonts', 'soundfonts'),
    ],
    hiddenimports=main_hiddenimports,
    hookspath=[_wv_hook],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='36键MIDI播放器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version=None,
    uac_admin=True,
)

server_a = Analysis(
    ['leaderboard_server.py'],
    pathex=[spec_dir],
    binaries=[],
    datas=[],
    hiddenimports=server_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'webview',
        'pygame',
        'moderngl',
        'keyboard',
        'pynput',
        'mss',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

server_pyz = PYZ(server_a.pure, server_a.zipped_data, cipher=block_cipher)

server_exe = EXE(
    server_pyz,
    server_a.scripts,
    server_a.binaries,
    server_a.zipfiles,
    server_a.datas,
    [],
    name='leaderboard_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version=None,
    uac_admin=False,
)
