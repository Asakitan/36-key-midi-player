"""
SAO-UI WebView GUI (Hybrid)
- HP 悬浮窗: pywebview (transparent=True 原生透明)
- SAO 菜单: pywebview (全屏, 含鱼眼特效)
- LinkStart: SAOLinkStart (tkinter, GPU渲染)
- 音效: sao_sound (pygame.mixer)
- 3-UI 热切换: WebView / SAO Entity / Old School
"""

import os
import sys
import time
import threading
import json
import ctypes
from typing import Optional

# ── 延迟导入 pywebview ──
webview = None


def _ensure_webview():
    global webview
    if webview is None:
        import webview as wv
        webview = wv


def is_webview_available() -> bool:
    try:
        _ensure_webview()
        return True
    except ImportError:
        return False


# ════════════════════════════════════════════════
#  Win32 透明窗口工具
# ════════════════════════════════════════════════
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_LWA_COLORKEY = 0x00000001
_COLORREF_KEY = 0x00010001  # RGB(1,0,1) → COLORREF 0x00BBGGRR


def _make_transparent_ctypes(hwnd: int):
    """Win32 LWA_COLORKEY 透明 (ctypes 降级方案)"""
    try:
        u = ctypes.windll.user32
        ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_LAYERED)
        u.SetLayeredWindowAttributes(hwnd, _COLORREF_KEY, 0, _LWA_COLORKEY)
    except Exception as e:
        print(f"[SAO] ctypes transparency failed: {e}")


def _setup_dotnet_transparency(form):
    """用 .NET / WinForms 设置色键透明 + WebView2 透明背景.

    TransparencyKey 让颜色 rgb(1,0,1) 的区域桌面穿透;
    DefaultBackgroundColor=Transparent 让 WebView2 不遮盖 Form 背景.
    """
    try:
        import clr  # pythonnet — pywebview EdgeChromium 已加载
        from System.Drawing import Color

        key = Color.FromArgb(255, 1, 0, 1)
        form.BackColor = key
        form.TransparencyKey = key

        # WebView2 控件 — 找到并设置透明背景
        for i in range(form.Controls.Count):
            ctrl = form.Controls[i]
            if hasattr(ctrl, 'DefaultBackgroundColor'):
                ctrl.DefaultBackgroundColor = Color.Transparent
                break
        return True
    except Exception as e:
        print(f"[SAO] .NET transparency: {e}")
        return False


# ════════════════════════════════════════════════
#  鱼眼特效 (截图 → barrel distortion → base64)
# ════════════════════════════════════════════════
def _capture_fisheye_base64(strength: float = 0.25, quality: int = 60) -> Optional[str]:
    """截取桌面, 做一次 barrel distortion, 返回 base64 JPEG.

    依赖: PIL, numpy (可选 mss).
    如果依赖不满足返回 None.
    """
    try:
        import numpy as np
        from PIL import Image
        import base64, io

        # ── 截图 ──
        try:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[0]
                raw = sct.grab(mon)
                img = Image.frombytes('RGB', raw.size, raw.rgb)
        except Exception:
            from PIL import ImageGrab
            img = ImageGrab.grab()

        # 缩小以加快处理 (960p 已足够做背景)
        w, h = img.size
        scale = min(960 / w, 540 / h, 1.0)
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        w, h = img.size

        # ── Barrel distortion (numpy) ──
        arr = np.array(img)
        cy, cx = h / 2, w / 2
        Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
        X -= cx
        Y -= cy
        r = np.sqrt(X * X + Y * Y)
        max_r = np.sqrt(cx * cx + cy * cy)
        rn = r / max_r
        barrel = 1.0 + strength * rn * rn
        src_x = (X * barrel + cx).clip(0, w - 1).astype(np.int32)
        src_y = (Y * barrel + cy).clip(0, h - 1).astype(np.int32)
        out = arr[src_y, src_x]

        result = Image.fromarray(out)

        buf = io.BytesIO()
        result.save(buf, format='JPEG', quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        return b64
    except Exception as e:
        print(f"[SAO] fisheye capture failed: {e}")
        return None


# ════════════════════════════════════════════════
#  Settings (共用)
# ════════════════════════════════════════════════
class SettingsManager:
    def __init__(self):
        # 打包后使用 exe 所在目录, 开发时使用脚本目录
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        self._path = os.path.join(base, 'settings.json')
        self._data = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        try:
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


# ════════════════════════════════════════════════
#  JS API Bridge
# ════════════════════════════════════════════════
class SAOWebAPI:
    """pywebview js_api — 暴露给 JavaScript 的 Python 接口."""

    def __init__(self, gui: 'SAOWebViewGUI'):
        self._g = gui

    def toggle_menu(self):
        # 必须在新线程中执行，不能阻塞 pywebview JS 回调线程
        threading.Thread(target=self._g._toggle_menu, daemon=True).start()

    def context_action(self, action: str):
        threading.Thread(target=self._g._context_action, args=(action,), daemon=True).start()

    def menu_action(self, action: str):
        threading.Thread(target=self._g._menu_action, args=(action,), daemon=True).start()

    def alert_ok(self):
        pass

    def play_sound(self, name: str):
        threading.Thread(target=self._g._play_sound, args=(name,), daemon=True).start()

    def window_drag(self, dx, dy):
        """JS→Python drag bridge: move HP window by (dx, dy)"""
        try:
            x = self._g.hp_win.x + int(dx)
            y = self._g.hp_win.y + int(dy)
            self._g.hp_win.move(x, y)
        except Exception:
            pass

    def set_ctx_menu_active(self, active):
        """控制 HP 窗口 click-through 区域 (右键菜单开关)"""
        self._g._ctx_menu_active = bool(active)
        self._g._set_hp_region(expanded=bool(active))

    def get_state(self):
        """供 JS 查询当前状态 (JSON 格式)"""
        return json.dumps({
            'playing': self._g._playing,
            'paused': self._g._paused,
            'speed': self._g._speed,
            'file': os.path.basename(self._g._current_file) if self._g._current_file else '',
        })


# ════════════════════════════════════════════════
#  面板 JS API Bridge
# ════════════════════════════════════════════════
class PanelAPI:
    """pywebview js_api for panel windows (control/piano/status/viz)."""

    def __init__(self, gui: 'SAOWebViewGUI', panel_type: str):
        self._g = gui
        self._type = panel_type

    def window_drag(self, dx, dy):
        try:
            win = self._g._panel_wins.get(self._type)
            if win:
                x = win.x + int(dx)
                y = win.y + int(dy)
                win.move(x, y)
        except Exception:
            pass

    def close_panel(self):
        threading.Thread(target=self._g._toggle_panel, args=(self._type,), daemon=True).start()

    def panel_action(self, action):
        threading.Thread(target=self._g._menu_action, args=(action,), daemon=True).start()

    def play_sound(self, name):
        threading.Thread(target=self._g._play_sound, args=(name,), daemon=True).start()


# ════════════════════════════════════════════════
#  主类
# ════════════════════════════════════════════════
class SAOWebViewGUI:
    """基于 pywebview 的 SAO-UI MIDI 播放器.

    窗口:
      hp_win  — 悬浮 HP 栏 (430×500, 色键透明, 上部 60px 可见)
      menu_win — 全屏 SAO 菜单 (初始隐藏)
    LinkStart 使用 SAOLinkStart (tkinter / ModernGL) 在 webview 启动前运行.
    """

    def __init__(self):
        _ensure_webview()

        from player import MidiPlayer
        from character_profile import load_profile, calc_level

        self.settings = SettingsManager()
        # 记录当前 UI 模式
        self.settings.set('ui_mode', 'webview')
        self.settings.save()
        self.player = MidiPlayer()
        self.player.set_mode_system(self.settings.get('mode_system', 'classic'))

        # 音效
        self._sound_ok = False
        try:
            import sao_sound
            self._sao_sound = sao_sound
            self._sound_ok = True
        except Exception:
            self._sao_sound = None

        # 角色
        profile = load_profile()
        self._username = profile.get('username', '') or 'Player'
        self._profession = profile.get('profession', '剑士')
        self._level = profile.get('level', 1)
        self._xp = profile.get('xp', 0)
        self._songs_played = profile.get('songs_played', 0)
        self._play_time = profile.get('play_time', 0)
        lv, cur_xp, need_xp = calc_level(self._xp)
        self._level = lv
        self._xp_pct = (cur_xp / max(1, need_xp)) * 100

        # 播放状态
        self._current_file: Optional[str] = None
        self._playing = False
        self._paused = False
        self._speed = self.settings.get('speed', 1.0)
        self._transpose = self.settings.get('transpose', 0)
        self._melody_on = True
        self._bass_on = True
        self._direct_c = False
        self._glissando = False
        self._folder_loop_active = False
        self._folder_loop_files = []
        self._folder_loop_index = 0

        # 菜单
        self._menu_visible = False

        # 窗口
        self.hp_win = None
        self.menu_win = None

        # 热切换目标 (run() 返回后检查)
        self._pending_switch: Optional[str] = None

        # JS API
        self._api = SAOWebAPI(self)

        # 窗口 click-through
        self._hp_hwnd = 0
        self._ctx_menu_active = False
        self._fisheye_active = False
        self._fisheye_gen = 0  # 鱼眼循环代数 (防止多线程重复)
        self._panel_wins = {}  # panel_type -> webview window

        # 回调
        self.player.on_progress = self._on_progress
        self.player.on_playback_end = self._on_playback_end
        self.player.on_note_play = self._on_note_play

    # ─── 音符回调 → 面板 ───
    def _on_note_play(self, key, note, is_chord=False):
        """Player 触发音符 → 推送到 piano / viz 面板."""
        try:
            dur = int(min(2000, max(100, note.duration * 1000)))
            vel = note.velocity / 127.0 if hasattr(note, 'velocity') else 0.8
            midi_note = note.note
            piano_win = self._panel_wins.get('piano')
            if piano_win:
                try:
                    piano_win.evaluate_js(f'Panel.noteOn({midi_note},{vel:.2f},{dur})')
                except Exception:
                    pass
            viz_win = self._panel_wins.get('viz')
            if viz_win:
                try:
                    viz_win.evaluate_js(f'Panel.vizTrigger("{self._safe_js(key)}",{vel:.2f})')
                except Exception:
                    pass
        except Exception:
            pass

    # ─── 音效 ───
    def _play_sound(self, name: str):
        if self._sound_ok and self._sao_sound:
            try:
                self._sao_sound.play_sound(name)
            except Exception:
                pass

    # ════════════════════════════════════════
    #  入口
    # ════════════════════════════════════════
    def run(self):
        # ── Phase 1: LinkStart (tkinter, 阻塞) ──
        self._run_tkinter_link_start()

        # ── Phase 2: pywebview ──
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
        hp_url = os.path.join(web_dir, 'hp.html')
        menu_url = os.path.join(web_dir, 'menu.html')

        fx = self.settings.get('float_x', 100)
        fy = self.settings.get('float_y', 50)

        # HP 悬浮窗 — transparent=True 由 pywebview 原生处理透明
        self.hp_win = webview.create_window(
            '♪ SAO HP', hp_url,
            width=430, height=280,
            x=fx, y=fy,
            frameless=True,
            easy_drag=False,           # 自行处理拖拽 (CSS app-region)
            transparent=True,
            on_top=True,
            js_api=self._api,
        )

        # 菜单 (全屏, 初始隐藏)
        self.menu_win = webview.create_window(
            'SAO Menu', menu_url,
            frameless=True,
            transparent=True,
            hidden=True,
            js_api=self._api,
        )

        webview.start(self._on_webview_started, debug=False)

        # ── Phase 3: 热切换 (webview.start 返回后) ──
        if self._pending_switch:
            self._do_hot_switch(self._pending_switch)

    # ─── LinkStart (tkinter) ───
    def _run_tkinter_link_start(self):
        """在 WebView 启动前运行 SAOLinkStart 动画 (tkinter + ModernGL)"""
        try:
            import tkinter as tk
            from sao_theme import SAOLinkStart

            ls_root = tk.Tk()
            ls_root.withdraw()

            done = threading.Event()

            def on_done():
                done.set()
                try:
                    ls_root.after(50, ls_root.destroy)
                except Exception:
                    pass

            ls = SAOLinkStart(ls_root, on_done=on_done)
            ls.play()
            ls_root.mainloop()
        except Exception as e:
            print(f"[SAO] LinkStart skipped: {e}")

    # ─── 透明设置 (pywebview transparent=True 自动处理) ───

    # ─── WebView2 透明背景 ───
    def _apply_webview2_transparency(self):
        """Win32: 为 HP 窗口设置 LWA_COLORKEY 透明 + .NET WebView2 透明背景,
        消除白色底色."""
        # 方案 1: .NET (pythonnet) — 最可靠
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, '♪ SAO HP')
            if hwnd:
                _make_transparent_ctypes(hwnd)
        except Exception:
            pass
        # 方案 2: 通过 pywebview 内部 Form 设置 WebView2 DefaultBackgroundColor
        try:
            gui = getattr(self.hp_win, 'gui', None)
            form = getattr(gui, 'BrowserForm', None) if gui else None
            if form:
                _setup_dotnet_transparency(form)
        except Exception:
            pass

    # ─── 任务栏图标 ───
    def _set_window_icon(self, title: str):
        """通过 Win32 为指定窗口设置任务栏/标题栏图标."""
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico')
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x10
            LR_DEFAULTSIZE = 0x40
            WM_SETICON = 0x80
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            if not hwnd:
                return
            hicon = ctypes.windll.user32.LoadImageW(
                None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)  # ICON_SMALL
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)  # ICON_BIG
        except Exception as e:
            print(f'[SAO] set icon: {e}')

    # ─── 点击穿透 ───
    def _setup_click_through(self):
        """限制 HP 窗口可交互区域 — 只保留 HP 条, 透明区域鼠标穿透."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, '♪ SAO HP')
            if not hwnd:
                return
            self._hp_hwnd = hwnd
            self._set_hp_region(False)
        except Exception as e:
            print(f"[SAO] click-through setup failed: {e}")

    def _set_hp_region(self, expanded=False):
        """设置 HP 窗口 Region — 限制点击/渲染区域."""
        if not self._hp_hwnd:
            return
        try:
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            if expanded:
                # 右键菜单打开: 扩展到全窗口 (含菜单空间)
                hrgn = gdi32.CreateRectRgn(0, 0, 430, 280)
            else:
                # 默认: 只保留 HP 条 (body pad=8 + XTBox=40 + number=20 = 68px)
                hrgn = gdi32.CreateRectRgn(0, 0, 420, 68)
            user32.SetWindowRgn(self._hp_hwnd, hrgn, True)
        except Exception:
            pass

    def _ensure_hp_on_top(self):
        """Win32: re-assert HP window as TOPMOST above fullscreen menu."""
        if not self._hp_hwnd:
            return
        try:
            HWND_TOPMOST = ctypes.c_void_p(-1)
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(
                self._hp_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _set_window_alpha(self, title, alpha):
        """Win32 LWA_ALPHA — 设置窗口整体透明度 (0.0~1.0)."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, title)
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            LWA_ALPHA = 0x00000002
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (ex & WS_EX_LAYERED):
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
            alpha_byte = int(max(0, min(255, alpha * 255)))
            user32.SetLayeredWindowAttributes(hwnd, 0, alpha_byte, LWA_ALPHA)
        except Exception:
            pass

    # ─── WebView 就绪 ───
    def _on_webview_started(self):
        # 初始化 HP
        def _init():
            from character_profile import calc_level
            self._eval_hp(f'setUsername("{self._safe_js(self._username)}")')
            lv, cur_xp, need_xp = calc_level(self._xp)
            self._eval_hp(f'updateHP({cur_xp}, {need_xp}, {lv})')
            self._sync_menu_info()
            # 设置 click-through (延迟确保窗口已完全创建)
            time.sleep(0.3)
            self._setup_click_through()
            # WebView2 透明背景 (防止白底)
            self._apply_webview2_transparency()
            # 任务栏图标
            self._set_window_icon('♪ SAO HP')
            self._set_window_icon('SAO Menu')
        threading.Timer(0.5, _init).start()

        # 后台线程
        threading.Thread(target=self._progress_loop, daemon=True).start()
        threading.Thread(target=self._save_position_loop, daemon=True).start()

        # 全局快捷键
        self._setup_hotkeys()

    # F键虚拟键码表 (Windows VK codes)
    _FKEY_VK = {
        'F1': 112, 'F2': 113, 'F3': 114, 'F4': 115,
        'F5': 116, 'F6': 117, 'F7': 118, 'F8': 119,
        'F9': 120, 'F10': 121, 'F11': 122, 'F12': 123,
    }

    def _setup_hotkeys(self):
        """注册全局快捷键 — 与普通模式/SAO Entity 保持一致 (pynput + settings.json)."""
        # 动作映射
        self._hk_actions = {
            'play_pause': self._toggle_play,
            'stop': self._stop,
            'speed_up': self._speed_up,
            'speed_down': self._speed_down,
            'toggle_topmost': lambda: None,  # webview 模式无置顶切换
            'hide_panels': lambda: None,     # webview 模式无面板隐藏
        }
        self._hk_pressed = set()
        self._hk_listener = None
        try:
            from pynput.keyboard import Listener as KbListener, Key, KeyCode
            self._hk_Key = Key
            self._hk_KeyCode = KeyCode
            self._hk_listener = KbListener(
                on_press=self._hk_on_press, on_release=self._hk_on_release)
            self._hk_listener.daemon = True
            self._hk_listener.start()
            saved = self.settings.get('hotkeys', {})
            from config import DEFAULT_HOTKEYS
            merged = {**DEFAULT_HOTKEYS, **saved}
            keys_desc = ', '.join(f'{a}={k}' for a, k in merged.items())
            self._hotkeys_ok = True
            print(f'[SAO WebView] Hotkeys (pynput): {keys_desc}')
        except Exception as e:
            self._hotkeys_ok = False
            print(f'[SAO WebView] Hotkeys unavailable: {e}')

    def _hk_on_press(self, key):
        try:
            if isinstance(key, self._hk_KeyCode) and key.vk:
                self._hk_pressed.add(key.vk)
            elif isinstance(key, self._hk_Key):
                self._hk_pressed.add(key.value.vk if hasattr(key.value, 'vk') else str(key))
        except Exception:
            pass
        self._hk_check()

    def _hk_on_release(self, key):
        try:
            if isinstance(key, self._hk_KeyCode) and key.vk:
                self._hk_pressed.discard(key.vk)
            elif isinstance(key, self._hk_Key):
                self._hk_pressed.discard(key.value.vk if hasattr(key.value, 'vk') else str(key))
        except Exception:
            pass

    def _hk_check(self):
        from config import DEFAULT_HOTKEYS
        saved = self.settings.get('hotkeys', DEFAULT_HOTKEYS)
        for action, info in saved.items():
            vk = None
            if isinstance(info, dict):
                vk = info.get('vk')
            elif isinstance(info, str) and info:
                vk = self._FKEY_VK.get(info.upper())
            if vk and vk in self._hk_pressed:
                cb = self._hk_actions.get(action)
                if cb:
                    threading.Thread(target=cb, daemon=True).start()
                    self._hk_pressed.clear()
                    return

    # ════════════════════════════════════════
    #  JS 辅助
    # ════════════════════════════════════════
    def _eval_hp(self, js):
        try:
            self.hp_win.evaluate_js(js)
        except Exception:
            pass

    def _eval_menu(self, js):
        try:
            self.menu_win.evaluate_js(js)
        except Exception:
            pass

    @staticmethod
    def _safe_js(s: str) -> str:
        if not s:
            return ''
        return s.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '\\n')

    # ════════════════════════════════════════
    #  菜单
    # ════════════════════════════════════════
    def _toggle_menu(self):
        # 防抖: 500ms 冷却期
        now = time.time()
        if hasattr(self, '_menu_cd') and now - self._menu_cd < 0.6:
            return
        self._menu_cd = now
        if self._menu_visible:
            self._close_menu()
        else:
            self._open_menu()

    def _open_menu(self):
        self._menu_visible = True
        self._sync_menu_info()
        self._play_sound('menu_open')

        # alpha=0 静默显示窗口, 避免 WebView2 白底闪烁
        try:
            _hwnd2 = ctypes.windll.user32.FindWindowW(None, 'SAO Menu')
            if _hwnd2:
                GWL_EXSTYLE = -20; WS_EX_LAYERED = 0x80000; LWA_ALPHA = 2
                _ex2 = ctypes.windll.user32.GetWindowLongW(_hwnd2, GWL_EXSTYLE)
                if not (_ex2 & WS_EX_LAYERED):
                    ctypes.windll.user32.SetWindowLongW(_hwnd2, GWL_EXSTYLE, _ex2 | WS_EX_LAYERED)
                ctypes.windll.user32.SetLayeredWindowAttributes(_hwnd2, 0, 0, LWA_ALPHA)
        except Exception:
            pass
        try:
            self.menu_win.show()
        except Exception:
            pass
        try:
            self.menu_win.maximize()
        except Exception:
            pass
        # HP 栏保持在菜单窗口上方
        self._ensure_hp_on_top()

        # window 已显示后推送鱼眼背景 (JS 现在可执行)
        self._push_fisheye_background()

        # 实时鱼眼背景循环 (非阻塞, 代数防重复)
        self._fisheye_active = True
        self._fisheye_gen += 1
        gen = self._fisheye_gen
        threading.Thread(target=self._fisheye_loop, args=(gen,), daemon=True).start()

        # 延迟开菜单动画, 再渐显窗口 (此时鱼眼已在渲染)
        def _init_menu():
            time.sleep(0.12)
            self._eval_menu('SAO.openMenu(500, 300)')
            time.sleep(0.04)  # 让鱼眼 canvas 先渲染一帧
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, 'SAO Menu')
                if hwnd:
                    LWA_ALPHA = 2
                    for step in range(1, 9):   # ~120ms 渐显
                        ctypes.windll.user32.SetLayeredWindowAttributes(
                            hwnd, 0, int(255 * step / 8), LWA_ALPHA)
                        time.sleep(0.015)
            except Exception:
                pass
        threading.Thread(target=_init_menu, daemon=True).start()

    def _close_menu(self):
        self._menu_visible = False
        self._fisheye_active = False  # 停止鱼眼刷新
        self._play_sound('menu_close')
        self._eval_menu('SAO.closeMenu()')

        # 等 TV 动画播完 (~550ms) 再淡出隐藏窗口, 否则立刻 alpha=0 会遮住动画
        def _hide():
            time.sleep(0.52)  # TV动画时长 0.55s, 稍早一点开始淡出
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, 'SAO Menu')
                GWL_EXSTYLE = -20; WS_EX_LAYERED = 0x80000; LWA_ALPHA = 2
                if hwnd:
                    _ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    if not (_ex & WS_EX_LAYERED):
                        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, _ex | WS_EX_LAYERED)
                    # 快速淡出 (3帧)
                    for a in [120, 30, 0]:
                        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, a, LWA_ALPHA)
                        time.sleep(0.03)
            except Exception:
                pass
            time.sleep(0.05)
            try:
                self.menu_win.restore()  # 取消最大化
            except Exception:
                pass
            time.sleep(0.05)
            try:
                self.menu_win.hide()
            except Exception:
                pass
            # Win32: 确保菜单窗口彻底隐藏, 不拦截点击
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, 'SAO Menu')
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            except Exception:
                pass
            # 恢复 HP 窗口焦点 & 置顶
            self._ensure_hp_on_top()
        threading.Thread(target=_hide, daemon=True).start()

    def _capture_current_monitor_b64(self, quality=100):
        """截取 HP 窗口所在显示器 → JPEG base64 (低分辨率快速截图,
        distortion 由浏览器端 WebGL shader 实时 60fps 渲染)."""
        try:
            import base64 as b64mod, io
            from PIL import Image

            hx = self.hp_win.x if self.hp_win else 0
            hy = self.hp_win.y if self.hp_win else 0

            try:
                import mss
                with mss.mss() as sct:
                    target = sct.monitors[1]
                    for m in sct.monitors[1:]:
                        if (m['left'] <= hx < m['left'] + m['width'] and
                                m['top'] <= hy < m['top'] + m['height']):
                            target = m
                            break
                    raw = sct.grab(target)
                    img = Image.frombytes('RGB', raw.size, raw.rgb)
            except Exception:
                from PIL import ImageGrab
                img = ImageGrab.grab()

            # 缩到 540p 以保持鱼眼清晰度 (WebGL 拉伸至全屏)
            w, h = img.size
            scale = min(960 / w, 540 / h, 1.0)
            if scale < 1.0:
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality)
            return b64mod.b64encode(buf.getvalue()).decode('ascii')
        except Exception as e:
            print(f"[SAO] monitor capture: {e}")
            return None

    # ── GPU barrel distortion (moderngl) ──
    _gl_ctx = None
    _gl_prog = None
    _gl_vao = None
    _gl_tex = None
    _gl_fbo = None
    _gl_size = (0, 0)

    def _init_gl(self, w: int, h: int):
        """初始化 / 重建 moderngl standalone context for barrel distortion."""
        import moderngl
        if self._gl_ctx is None:
            self._gl_ctx = moderngl.create_standalone_context()
        ctx = self._gl_ctx

        vert_src = '''
        #version 330
        in vec2 in_vert;
        in vec2 in_texcoord;
        out vec2 uv;
        void main() {
            gl_Position = vec4(in_vert, 0.0, 1.0);
            uv = in_texcoord;
        }
        '''
        frag_src = '''
        #version 330
        uniform sampler2D tex;
        uniform float strength;
        in vec2 uv;
        out vec4 fragColor;
        void main() {
            vec2 c = uv - 0.5;
            float r2 = dot(c, c);
            vec2 d = uv + c * strength * r2;
            fragColor = texture(tex, d);
        }
        '''
        self._gl_prog = ctx.program(vertex_shader=vert_src, fragment_shader=frag_src)
        self._gl_prog['strength'] = 0.35

        verts = np.array([
            -1, -1, 0, 0,
             1, -1, 1, 0,
            -1,  1, 0, 1,
             1,  1, 1, 1,
        ], dtype='f4')
        vbo = ctx.buffer(verts)
        self._gl_vao = ctx.simple_vertex_array(self._gl_prog, vbo, 'in_vert', 'in_texcoord')

        self._gl_tex = ctx.texture((w, h), 3)
        self._gl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._gl_fbo = ctx.framebuffer(color_attachments=[ctx.texture((w, h), 3)])
        self._gl_size = (w, h)

    def _apply_barrel_distortion(self, img):
        """Apply barrel distortion via moderngl GPU, fallback to numpy if unavailable."""
        import numpy as np
        from PIL import Image
        w, h = img.size

        # ── GPU path ──
        try:
            import moderngl  # noqa: F811
            if self._gl_ctx is None or self._gl_size != (w, h):
                self._init_gl(w, h)
            arr = np.array(img)  # (H, W, 3)
            arr_flip = np.flipud(arr)  # OpenGL expects bottom-up
            self._gl_tex.write(arr_flip.tobytes())
            self._gl_tex.use(0)
            self._gl_fbo.use()
            self._gl_ctx.clear()
            self._gl_vao.render(mode=6)  # TRIANGLE_STRIP
            raw = self._gl_fbo.color_attachments[0].read()
            out = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
            out = np.flipud(out)
            return Image.fromarray(out)
        except Exception:
            pass

        # ── numpy fallback (simple polynomial, matches SAO_GUI) ──
        try:
            strength = 0.35
            arr = np.array(img, dtype=np.float32)
            cy, cx = h / 2.0, w / 2.0
            Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
            nx = (X - cx) / cx
            ny = (Y - cy) / cy
            r2 = nx * nx + ny * ny
            f = 1.0 + strength * r2
            sx = np.clip(cx + nx * f * cx, 0.0, w - 1.001).astype(np.float32)
            sy = np.clip(cy + ny * f * cy, 0.0, h - 1.001).astype(np.float32)
            x0 = sx.astype(np.int32); x1 = x0 + 1
            y0 = sy.astype(np.int32); y1 = y0 + 1
            x1 = np.clip(x1, 0, w - 1); y1 = np.clip(y1, 0, h - 1)
            fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
            out = (arr[y0, x0] * (1 - fx) * (1 - fy) +
                   arr[y0, x1] * fx * (1 - fy) +
                   arr[y1, x0] * (1 - fx) * fy +
                   arr[y1, x1] * fx * fy)
            return Image.fromarray(out.clip(0, 255).astype(np.uint8))
        except Exception:
            return img  # 无畸变 fallback

    def _push_fisheye_background(self):
        """截图当前屏幕 → 推送到菜单 JS (WebGL 做 60fps 鱼眼渲染)"""
        b64 = self._capture_current_monitor_b64()  # 使用默认 quality=55
        if b64:
            js = f'SAO.setFisheyeBg("data:image/jpeg;base64,{b64}")'
            self._eval_menu(js)

    def _fisheye_loop(self, gen: int):
        """后台截屏循环 — ~15fps 截屏推送, 浏览器 WebGL 以 60fps 实时渲染."""
        import time as _time
        while self._fisheye_active and self._menu_visible and gen == self._fisheye_gen:
            t0 = _time.time()
            self._push_fisheye_background()
            elapsed = _time.time() - t0
            sleep_t = max(0.01, 0.066 - elapsed)   # ~15fps 截屏刷新
            _time.sleep(sleep_t)

    # ─── 面板管理 ───
    def _toggle_panel(self, panel_type):
        """切换面板窗口 (control/piano/status/viz)."""
        if panel_type in self._panel_wins:
            win = self._panel_wins.pop(panel_type, None)
            if win:
                try:
                    win.evaluate_js('document.documentElement.style.opacity="0"')
                except Exception:
                    pass
                time.sleep(0.15)
                try:
                    win.destroy()
                except Exception:
                    pass
            return
        self._create_panel_window(panel_type)

    def _create_panel_window(self, panel_type):
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
        url = os.path.join(web_dir, 'panel.html')

        sizes = {
            'control': (280, 240),
            'piano': (700, 120),
            'status': (220, 240),
            'viz': (240, 400),
        }
        w, h = sizes.get(panel_type, (280, 200))

        try:
            hx, hy = self.hp_win.x or 100, self.hp_win.y or 100
        except Exception:
            hx, hy = 100, 100

        key_x = f'wv_{panel_type}_x'
        key_y = f'wv_{panel_type}_y'
        sx = self.settings.get(key_x, max(0, hx - w - 20))
        sy = self.settings.get(key_y, hy)

        api = PanelAPI(self, panel_type)
        win = webview.create_window(
            f'SAO {panel_type}', url,
            width=w, height=h,
            x=int(sx), y=int(sy),
            frameless=True,
            transparent=True,
            on_top=True,
            js_api=api,
        )
        self._panel_wins[panel_type] = win

        def _init():
            time.sleep(1.0)
            try:
                state = self._get_panel_state()
                win.evaluate_js(f'Panel.init("{panel_type}", {json.dumps(state)})')
            except Exception:
                pass
            # 面板窗口 0.95 透明度 (Win32 LWA_ALPHA)
            self._set_window_alpha(f'SAO {panel_type}', 0.95)
        threading.Thread(target=_init, daemon=True).start()

    def _get_panel_state(self):
        mode_sys = self.settings.get('mode_system', 'classic')
        mode_label = {'classic': '经典60键', 'full88': '完整88键', 'hyper': '超级键位'}.get(mode_sys, mode_sys)
        return {
            'speed': self._speed,
            'transpose': self._transpose,
            'melody': self._melody_on,
            'bass': self._bass_on,
            'directc': self._direct_c,
            'glissando': self._glissando,
            'sustain': False,
            'play_state': '播放中' if self._playing else ('已暂停' if self._paused else '就绪'),
            'mode': mode_label,
            'bpm': 0,
            'kb_mode': {'normal': '正常', 'shift': 'SHIFT ↑', 'ctrl': 'CTRL ↓'}.get(
                getattr(getattr(self.player, 'simulator', None), '_current_mode', 'normal'), '正常'),
        }

    def _sync_all_panels(self):
        """同步所有打开的面板的状态."""
        state = self._get_panel_state()
        for pt, win in list(self._panel_wins.items()):
            try:
                win.evaluate_js(f'Panel.update({json.dumps(state)})')
            except Exception:
                pass

    def _destroy_all_panels(self):
        for win in list(self._panel_wins.values()):
            try:
                win.evaluate_js('document.documentElement.style.opacity="0"')
            except Exception:
                pass
        time.sleep(0.15)
        for win in list(self._panel_wins.values()):
            try:
                win.destroy()
            except Exception:
                pass
        self._panel_wins.clear()

    # ─── 同步信息 ───
    def _sync_menu_info(self):
        pt = self._play_time
        time_str = (f'{int(pt // 3600)}:{int((pt % 3600) // 60):02d}:{int(pt % 60):02d}'
                    if pt >= 3600 else f'{int(pt // 60)}:{int(pt % 60):02d}')
        fname = os.path.basename(self._current_file) if self._current_file else ''
        info = {
            'username': self._username, 'level': self._level,
            'xp_pct': round(self._xp_pct, 1), 'profession': self._profession,
            'songs': self._songs_played, 'time': time_str,
            'speed': self._speed, 'transpose': self._transpose,
            'des': f'当前文件: {fname}' if fname else 'Welcome to SAO MIDI Player',
            'file': fname,
        }
        self._eval_menu(f'SAO.updateInfo({json.dumps(info, ensure_ascii=False)})')
        for k, v in [('melody', self._melody_on), ('bass', self._bass_on),
                      ('directc', self._direct_c), ('glissando', self._glissando)]:
            self._eval_menu(f'SAO.updateBadge("{k}", {"true" if v else "false"})')
        self._sync_all_panels()

    # ════════════════════════════════════════
    #  动作分发
    # ════════════════════════════════════════
    def _context_action(self, action: str):
        _map = {
            'menu': self._toggle_menu,
            'play': self._toggle_play,
            'stop': self._stop,
            'open': self._open_file,
            'folder': self._open_folder,
            'speedup': self._speed_up,
            'speeddown': self._speed_down,
            'panel_control': lambda: self._toggle_panel('control'),
            'panel_piano': lambda: self._toggle_panel('piano'),
            'panel_status': lambda: self._toggle_panel('status'),
            'panel_viz': lambda: self._toggle_panel('viz'),
            'midi_channel': self._show_channel_settings,
            'switch_sao': self._switch_to_sao_ui,
            'switch_old': self._switch_to_old_ui,
            'exit': self._exit,
        }
        fn = _map.get(action)
        if fn:
            threading.Thread(target=fn, daemon=True).start()

    def _menu_action(self, action: str):
        _map = {
            'play': self._toggle_play,
            'stop': self._stop,
            'speedup': self._speed_up,
            'speeddown': self._speed_down,
            'restart': self._restart,
            'open': self._open_file,
            'folder': self._open_folder,
            'toggle_melody': self._toggle_melody,
            'toggle_bass': self._toggle_bass,
            'toggle_directc': self._toggle_direct_c,
            'toggle_glissando': self._toggle_glissando,
            'transpose_up': self._transpose_up,
            'transpose_down': self._transpose_down,
            'panel_control': lambda: self._toggle_panel('control'),
            'panel_piano': lambda: self._toggle_panel('piano'),
            'panel_status': lambda: self._toggle_panel('status'),
            'panel_viz': lambda: self._toggle_panel('viz'),
            'midi_channel': self._show_channel_settings,
            'switch_sao': self._switch_to_sao_ui,
            'switch_old': self._switch_to_old_ui,
            'exit': self._exit,
        }
        fn = _map.get(action)
        if fn:
            threading.Thread(target=fn, daemon=True).start()

    # ════════════════════════════════════════
    #  播放控制
    # ════════════════════════════════════════
    def _toggle_play(self):
        if self._playing and not self._paused:
            self.player.pause()
            self._paused = True
            self._eval_hp('setPlayState("paused")')
            self._eval_menu('SAO.showToast("已暂停")')
            self._sync_all_panels()
            return
        if self._paused:
            self.player.resume()
            self._paused = False
            self._eval_hp('setPlayState("playing")')
            self._eval_menu('SAO.showToast("继续播放")')
            self._sync_all_panels()
            return
        if not self._current_file:
            self._eval_menu('SAO.showAlert("提示", "请先打开 MIDI 文件", false)')
            return
        try:
            ok = self.player.load_midi(self._current_file)
        except Exception as e:
            self._eval_menu(f'SAO.showAlert("错误", "{self._safe_js(str(e))}", false)')
            return
        if not ok:
            self._eval_menu('SAO.showAlert("提示", "文件中没有可用音符", false)')
            return
        self.player.set_speed(self._speed)
        self.player.set_transpose(self._transpose)
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self.player.stop()
        self.player.play()
        self._playing = True
        self._paused = False
        self._eval_hp('setPlayState("playing")')
        self._sync_all_panels()

    def _stop(self):
        self._folder_loop_active = False
        self.player.stop()
        self._playing = False
        self._paused = False
        self._eval_hp('setPlayState("idle")')
        self._eval_hp(f'updateHP(0, 100, {self._level})')
        self._sync_all_panels()

    def _restart(self):
        if self._current_file:
            self._stop()
            time.sleep(0.1)
            self._toggle_play()

    # ─── 速度 / 移调 ───
    def _speed_up(self):
        self._speed = min(2.0, round(self._speed + 0.1, 2))
        self.player.set_speed(self._speed)
        self.settings.set('speed', self._speed)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("速度: {self._speed}x")')
        self._sync_menu_info()
        self._sync_all_panels()

    def _speed_down(self):
        self._speed = max(0.3, round(self._speed - 0.1, 2))
        self.player.set_speed(self._speed)
        self.settings.set('speed', self._speed)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("速度: {self._speed}x")')
        self._sync_menu_info()
        self._sync_all_panels()

    def _transpose_up(self):
        self._transpose = min(12, self._transpose + 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("移调: {self._transpose:+d}")')
        self._sync_menu_info()
        self._sync_all_panels()

    def _transpose_down(self):
        self._transpose = max(-12, self._transpose - 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("移调: {self._transpose:+d}")')
        self._sync_menu_info()
        self._sync_all_panels()

    # ─── Toggle 开关 ───
    def _toggle_melody(self):
        self._melody_on = not self._melody_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._eval_menu(f'SAO.updateBadge("melody", {"true" if self._melody_on else "false"})')
        self._eval_menu(f'SAO.showToast("主旋律: {"ON" if self._melody_on else "OFF"}")')
        self._sync_all_panels()

    def _toggle_bass(self):
        self._bass_on = not self._bass_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._eval_menu(f'SAO.updateBadge("bass", {"true" if self._bass_on else "false"})')
        self._eval_menu(f'SAO.showToast("伴奏: {"ON" if self._bass_on else "OFF"}")')
        self._sync_all_panels()

    def _toggle_direct_c(self):
        self._direct_c = not self._direct_c
        self.player.set_direct_c_mode(self._direct_c)
        self._eval_menu(f'SAO.updateBadge("directc", {"true" if self._direct_c else "false"})')
        self._eval_menu(f'SAO.showToast("C调直转: {"ON" if self._direct_c else "OFF"}")')
        self._sync_all_panels()

    def _toggle_glissando(self):
        self._glissando = not self._glissando
        self.player._play_ending_glissando = self._glissando
        self._eval_menu(f'SAO.updateBadge("glissando", {"true" if self._glissando else "false"})')
        self._eval_menu(f'SAO.showToast("结尾滑奏: {"ON" if self._glissando else "OFF"}")')
        self._sync_all_panels()

    def _show_channel_settings(self):
        """打开 MIDI 通道控制器对话框."""
        if self._menu_visible:
            self._close_menu()
            time.sleep(0.5)
        try:
            import tkinter as tk
            _tmp = tk.Tk()
            _tmp.withdraw()
            from midi_controller import MIDIControllerDialog
            MIDIControllerDialog(_tmp, self.player, self.settings,
                                 midi_path=self._current_file or '')
            _tmp.mainloop()
        except ImportError:
            self._eval_menu('SAO.showAlert("错误", "MIDI控制器模块不可用", false)')
        except Exception as e:
            print(f"[SAO] channel settings: {e}")

    # ════════════════════════════════════════
    #  文件管理
    # ════════════════════════════════════════
    def _open_file(self):
        if self._menu_visible:
            self._close_menu()
            time.sleep(0.6)
        last = self.settings.get('last_file', '')
        init_dir = (os.path.dirname(last) if last and os.path.isdir(os.path.dirname(last))
                    else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Midi'))
        result = self.hp_win.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=init_dir,
            file_types=('MIDI Files (*.mid;*.midi)', 'All Files (*.*)'),
        )
        if result and len(result) > 0:
            self._load_file(result[0])

    def _load_file(self, path: str):
        self._current_file = path
        self.settings.set('last_file', path)
        self.settings.save()
        fname = os.path.basename(path)
        self._eval_menu(f'SAO.updateInfo({{file: "{self._safe_js(fname)}", '
                        f'des: "当前文件: {self._safe_js(fname)}"}})')
        self._eval_menu(f'SAO.showToast("已加载: {self._safe_js(fname)}")')

    def _open_folder(self):
        if self._menu_visible:
            self._close_menu()
            time.sleep(0.6)
        result = self.hp_win.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            folder = result[0]
            files = sorted([os.path.join(folder, f) for f in os.listdir(folder)
                            if f.lower().endswith(('.mid', '.midi'))])
            if files:
                self._folder_loop_files = files
                self._folder_loop_index = 0
                self._folder_loop_active = True
                self._load_file(files[0])
                self._toggle_play()
                self._eval_menu(f'SAO.showToast("文件夹循环: {len(files)} 首")')
            else:
                self._eval_menu('SAO.showAlert("提示", "文件夹中没有 MIDI 文件", false)')

    # ════════════════════════════════════════
    #  进度 / 播放结束
    # ════════════════════════════════════════
    def _on_progress(self, current: float, total: float):
        self._progress_current = current
        self._progress_total = total

    def _on_playback_end(self):
        self._playing = False
        self._paused = False
        self._eval_hp('setPlayState("idle")')

        # 经验值
        try:
            from character_profile import load_profile, add_song_xp, calc_level
            profile = load_profile()
            duration = getattr(self, '_progress_total', 0)
            profile, leveled_up, old_lv, new_lv = add_song_xp(profile, duration)
            self._level = new_lv
            self._xp = profile.get('xp', 0)
            self._songs_played = profile.get('songs_played', 0)
            lv, cur, need = calc_level(self._xp)
            self._xp_pct = (cur / max(1, need)) * 100
            # 更新 HP 条显示 XP (空闲时显示经验值)
            self._eval_hp(f'updateHP({cur}, {need}, {lv})')
            if leveled_up:
                # 升级音效 (与 sao_gui.py 一致)
                if self._sound_ok:
                    try:
                        self._sao_sound.play_levelup_sfx()
                    except Exception:
                        self._play_sound('alert')
                else:
                    self._play_sound('alert')
                # HP 悬浮窗升级特效: 展开 Region + CSS 动画 overlay
                self._set_hp_region(True)
                self._eval_hp(f'showLevelUp({old_lv}, {new_lv})')
                def _restore_region():
                    time.sleep(2.8)
                    self._set_hp_region(False)
                threading.Thread(target=_restore_region, daemon=True).start()
                # 若菜单开着, 同时在菜单中显示 Toast
                if self._menu_visible:
                    self._eval_menu(f'SAO.showToast("LEVEL UP!  Lv.{old_lv} → Lv.{new_lv}", 3000)')
            self._sync_menu_info()
        except Exception:
            pass

        # 文件夹循环
        if self._folder_loop_active and self._folder_loop_files:
            self._folder_loop_index = (self._folder_loop_index + 1) % len(self._folder_loop_files)
            self._load_file(self._folder_loop_files[self._folder_loop_index])
            time.sleep(1.0)
            self._toggle_play()

    # ─── 后台线程 ───
    def _progress_loop(self):
        self._progress_current = 0.0
        self._progress_total = 0.0
        _panel_tick = 0
        while True:
            time.sleep(0.15)
            try:
                # 检查窗口是否还活着
                if self.hp_win is None:
                    return
                _ = self.hp_win.x  # 如果窗口已销毁会抛异常
            except Exception:
                return
            if self._playing and not self._paused:
                cur, total = self._progress_current, self._progress_total
                if total > 0:
                    try:
                        self._eval_hp(f'updateHP({cur:.0f}, {total:.0f}, {self._level})')
                    except Exception:
                        pass
            # 每 ~2 秒同步一次状态面板 (kb_mode 等动态字段)
            _panel_tick += 1
            if _panel_tick >= 14 and self._panel_wins:
                _panel_tick = 0
                self._sync_all_panels()

    def _save_position_loop(self):
        while True:
            time.sleep(5)
            try:
                if self.hp_win is None:
                    return
                x, y = self.hp_win.x, self.hp_win.y
                if x is not None and y is not None:
                    self.settings.set('float_x', x)
                    self.settings.set('float_y', y)
                # 保存面板位置
                for pt, win in list(self._panel_wins.items()):
                    try:
                        px, py = win.x, win.y
                        if px is not None and py is not None:
                            self.settings.set(f'wv_{pt}_x', px)
                            self.settings.set(f'wv_{pt}_y', py)
                    except Exception:
                        pass
                self.settings.save()
            except Exception:
                return  # 窗口已销毁, 退出循环

    # ════════════════════════════════════════
    #  3-UI 热切换
    # ════════════════════════════════════════
    def _switch_to_sao_ui(self):
        """切换到 SAO Entity UI (sao_gui.py)"""
        self.settings.set('ui_mode', 'sao')
        self.settings.save()
        self._pending_switch = 'sao'
        self.player.stop()
        self._destroy_all_panels()
        try:
            self.hp_win.destroy()
        except Exception:
            pass
        try:
            self.menu_win.destroy()
        except Exception:
            pass

    def _switch_to_old_ui(self):
        """切换到 Old School UI (gui.py)"""
        self.settings.set('ui_mode', 'old')
        self.settings.save()
        self._pending_switch = 'old'
        self.player.stop()
        self._destroy_all_panels()
        try:
            self.hp_win.destroy()
        except Exception:
            pass
        try:
            self.menu_win.destroy()
        except Exception:
            pass

    def _do_hot_switch(self, target: str):
        """webview.start() 结束后执行热切换"""
        if target == 'sao':
            from sao_gui import SAOPlayerGUI
            app = SAOPlayerGUI()
            app.run()
        elif target == 'old':
            from gui import MidiPlayerGUI
            app = MidiPlayerGUI()
            app.run()

    def _exit(self):
        self.player.stop()
        self._destroy_all_panels()
        try:
            self.hp_win.destroy()
        except Exception:
            pass
        try:
            self.menu_win.destroy()
        except Exception:
            pass
