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
        self._path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'settings.json')
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

    def get_state(self):
        """供 JS 查询当前状态 (JSON 格式)"""
        return json.dumps({
            'playing': self._g._playing,
            'paused': self._g._paused,
            'speed': self._g._speed,
            'file': os.path.basename(self._g._current_file) if self._g._current_file else '',
        })


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

        # 回调
        self.player.on_progress = self._on_progress
        self.player.on_playback_end = self._on_playback_end

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
            transparent=False,
            background_color='#000000',
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

    # ─── WebView 就绪 ───
    def _on_webview_started(self):
        # 初始化 HP
        def _init():
            self._eval_hp(f'setUsername("{self._safe_js(self._username)}")')
            self._eval_hp(f'updateHP(0, 100, {self._level})')
            self._sync_menu_info()
        threading.Timer(0.5, _init).start()

        # 后台线程
        threading.Thread(target=self._progress_loop, daemon=True).start()
        threading.Thread(target=self._save_position_loop, daemon=True).start()

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
        if self._menu_visible:
            self._close_menu()
        else:
            self._open_menu()

    def _open_menu(self):
        self._menu_visible = True
        self._sync_menu_info()
        self._play_sound('menu_open')

        # 鱼眼背景 (非阻塞)
        threading.Thread(target=self._push_fisheye_background, daemon=True).start()

        try:
            self.menu_win.show()
        except Exception:
            pass
        try:
            self.menu_win.maximize()
        except Exception:
            pass
        # 非阻塞延迟初始化菜单动画
        def _init_menu():
            time.sleep(0.15)
            self._eval_menu('SAO.openMenu(500, 300)')
        threading.Thread(target=_init_menu, daemon=True).start()

    def _close_menu(self):
        self._menu_visible = False
        self._play_sound('menu_close')
        self._eval_menu('SAO.closeMenu()')
        # 非阻塞延迟隐藏 — 用 threading.Timer 代替 time.sleep
        def _hide():
            try:
                self.menu_win.hide()
            except Exception:
                pass
        threading.Timer(0.5, _hide).start()

    def _push_fisheye_background(self):
        """截图 → barrel distortion → 推送到菜单 JS 做背景"""
        b64 = _capture_fisheye_base64(strength=0.25, quality=55)
        if b64:
            js = f'SAO.setFisheyeBg("data:image/jpeg;base64,{b64}")'
            self._eval_menu(js)

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
            return
        if self._paused:
            self.player.resume()
            self._paused = False
            self._eval_hp('setPlayState("playing")')
            self._eval_menu('SAO.showToast("继续播放")')
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

    def _stop(self):
        self._folder_loop_active = False
        self.player.stop()
        self._playing = False
        self._paused = False
        self._eval_hp('setPlayState("idle")')
        self._eval_hp(f'updateHP(0, 100, {self._level})')

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

    def _speed_down(self):
        self._speed = max(0.3, round(self._speed - 0.1, 2))
        self.player.set_speed(self._speed)
        self.settings.set('speed', self._speed)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("速度: {self._speed}x")')
        self._sync_menu_info()

    def _transpose_up(self):
        self._transpose = min(12, self._transpose + 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("移调: {self._transpose:+d}")')
        self._sync_menu_info()

    def _transpose_down(self):
        self._transpose = max(-12, self._transpose - 1)
        self.player.set_transpose(self._transpose)
        self.settings.set('transpose', self._transpose)
        self.settings.save()
        self._eval_menu(f'SAO.showToast("移调: {self._transpose:+d}")')
        self._sync_menu_info()

    # ─── Toggle 开关 ───
    def _toggle_melody(self):
        self._melody_on = not self._melody_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._eval_menu(f'SAO.updateBadge("melody", {"true" if self._melody_on else "false"})')
        self._eval_menu(f'SAO.showToast("主旋律: {"ON" if self._melody_on else "OFF"}")')

    def _toggle_bass(self):
        self._bass_on = not self._bass_on
        self.player.set_part_filter(self._melody_on, self._bass_on)
        self._eval_menu(f'SAO.updateBadge("bass", {"true" if self._bass_on else "false"})')
        self._eval_menu(f'SAO.showToast("伴奏: {"ON" if self._bass_on else "OFF"}")')

    def _toggle_direct_c(self):
        self._direct_c = not self._direct_c
        self.player.set_direct_c_mode(self._direct_c)
        self._eval_menu(f'SAO.updateBadge("directc", {"true" if self._direct_c else "false"})')
        self._eval_menu(f'SAO.showToast("C调直转: {"ON" if self._direct_c else "OFF"}")')

    def _toggle_glissando(self):
        self._glissando = not self._glissando
        self.player._play_ending_glissando = self._glissando
        self._eval_menu(f'SAO.updateBadge("glissando", {"true" if self._glissando else "false"})')
        self._eval_menu(f'SAO.showToast("结尾滑奏: {"ON" if self._glissando else "OFF"}")')

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
        self._eval_hp(f'updateHP(0, 100, {self._level})')

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
            if leveled_up:
                self._play_sound('alert')
                self._eval_menu(f'SAO.showAlert("LEVEL UP!", "Lv.{old_lv} → Lv.{new_lv}", false)')
                if self._sound_ok:
                    try:
                        self._sao_sound.play_levelup_sfx()
                    except Exception:
                        pass
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
        try:
            self.hp_win.destroy()
        except Exception:
            pass
        try:
            self.menu_win.destroy()
        except Exception:
            pass
