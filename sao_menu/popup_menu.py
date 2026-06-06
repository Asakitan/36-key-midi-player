# -*- coding: utf-8 -*-
"""SAOPopUpMenu (legacy; split from sao_theme.py — verbatim)."""
import tkinter as tk
import time
from typing import Optional, Callable, List, Dict, Tuple
from PIL import Image, ImageDraw, ImageFilter, ImageTk
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from render.overlay_scheduler import get_scheduler as _get_scheduler
from utils.perf_probe import phase as _phase_trace, probe as _probe
from gui_modules.sao_menu_hud import MenuHudSpriteRenderer
try:
    # GPU-required HUD layer. Canvas-native HUD fallback is disabled.
    from gui_modules.sao_gui_menu_hud import MenuHudOverlay, gpu_menu_hud_enabled
except Exception as _gpu_hud_import_error:
    _GPU_HUD_IMPORT_ERROR = _gpu_hud_import_error
    MenuHudOverlay = None  # type: ignore[assignment]
    def gpu_menu_hud_enabled() -> bool:  # type: ignore[no-redef]
        raise RuntimeError('MenuHudOverlay GPU module is required') from _GPU_HUD_IMPORT_ERROR
from sao_menu.animator import Animator
from sao_menu.utils import ease_out
from sao_menu.menu_bar import SAOMenuBar
from sao_menu.left_info import SAOLeftInfo
from sao_menu.child_bar import SAOChildBar

# Win32: is the OS foreground window owned by THIS process? The interactive menu
# bar / child bar are GLFW overlay windows with WS_EX_NOACTIVATE cleared, so
# clicking them steals OS focus from the Tk overlay → <FocusOut> → the menu would
# close the instant you click a category. We treat focus moving to one of our OWN
# windows as "still inside the menu" and keep it open. (Private WinDLL instance so
# we never mutate the shared windll.user32 argtypes — see the pynput pollution fix.)
try:
    import ctypes as _ctypes
    import os as _os
    _U32_FG = _ctypes.WinDLL('user32')
    _U32_FG.GetForegroundWindow.restype = _ctypes.c_void_p
    _U32_FG.GetWindowThreadProcessId.argtypes = [
        _ctypes.c_void_p, _ctypes.POINTER(_ctypes.c_ulong)]
    _U32_FG.GetWindowThreadProcessId.restype = _ctypes.c_ulong
    _OWN_PID = _os.getpid()

    def _foreground_in_own_process() -> bool:
        try:
            hwnd = _U32_FG.GetForegroundWindow()
            if not hwnd:
                return False
            pid = _ctypes.c_ulong(0)
            _U32_FG.GetWindowThreadProcessId(_ctypes.c_void_p(hwnd),
                                             _ctypes.byref(pid))
            return pid.value == _OWN_PID
        except Exception:
            return False
except Exception:
    def _foreground_in_own_process() -> bool:
        return False

# ──────────────────── 弹出菜单容器 (PopUpMenu) ────────────────────
class SAOPopUpMenu:
    """
    SAO 风格全屏弹出菜单
    - Alt+A 或滑动下拉呼出
    - 半透明深色遮罩 (70% 黑)
    - 居中: MenuBar + LeftInfo + ChildBar
    - 呼吸浮动动画 (8px偏移, 8s周期)
    - fadeIn/fadeOut 过渡
    - 点击空白关闭
    """

    def __init__(self, root: tk.Tk, icon_arr: List[Dict],
                 child_menus: Dict[str, List[Dict]],
                 username: str = 'Player',
                 description: str = 'Welcome to SAO world',
                 on_close: Optional[Callable] = None,
                 on_open: Optional[Callable] = None,
                 key_code: str = 'a',
                 slide_down: bool = True,
                 left_widget_factory: Optional[Callable] = None,
                 anchor_widget=None):
        self.root = root
        self.icon_arr = icon_arr
        self.child_menus = child_menus
        self.username = username
        self.description = description
        self.on_close_callback = on_close
        self.on_open_callback = on_open
        self.key_code = key_code
        self.slide_down = slide_down
        self.left_widget_factory = left_widget_factory
        self.anchor_widget = anchor_widget
        # 锚定位置 (anchor_widget 模式下存储内容左上角坐标)
        self._content_x: Optional[int] = None
        self._content_y: Optional[int] = None

        self._overlay: Optional[tk.Toplevel] = None
        self._left_widget = None
        self._visible = False
        self._throttle_timer = None
        self._breath_job = None
        self._menu_hud_job = None
        self._menu_sched_ident = f'sao_menu_{id(self)}'
        self._menu_anim_t0 = 0.0
        self._menu_anim_registered = False
        self._menu_hud_cv = None
        self._menu_hud_item = None
        self._menu_hud_sprite = None
        self._menu_hud_origin = None
        # Canvas-native items for dynamic HUD elements. Keyed dict so we
        # only call coords/itemconfigure when state actually changed.
        self._menu_hud_items: Dict[str, object] = {}
        self._menu_hud_static_photo = None
        self._menu_hud_last_sig = None
        self._menu_hud_renderer = MenuHudSpriteRenderer()
        self._menu_hud_backdrop = None
        self._menu_hud_backdrop_key = None
        # GPU-required HUD overlay. Canvas-native HUD fallback is disabled.
        if MenuHudOverlay is None:
            raise RuntimeError('MenuHudOverlay GPU module is required')
        self._gpu_hud_enabled = bool(gpu_menu_hud_enabled())
        self._hud_overlay: Optional[object] = None
        self._content_place_sig = None
        self._overlay_size_part = ''
        self._overlay_drift_sig = None
        self._hud_cached_dims: Optional[Tuple[int, int, int, int]] = None
        self._menu_force_60_until = 0.0
        self._menu_open_grace_until = 0.0
        self._root_click_id = None
        self._first_y = 0
        self._first_time = 0
        self._slide_threshold = 250
        self._slide_duration = 666
        self._external_close_prepared = False

    def _refresh_anchor_layout(self) -> None:
        if self.anchor_widget is None or not self._overlay or not self._content:
            return
        try:
            if not self._overlay.winfo_exists() or not self._content.winfo_exists():
                return
            sw = max(1, self._overlay.winfo_width() or self.root.winfo_screenwidth())
            sh = max(1, self._overlay.winfo_height() or self.root.winfo_screenheight())
            cw = max(120, self._content.winfo_reqwidth())
            ch = max(120, self._content.winfo_reqheight())
            margin = 16

            aw = self.anchor_widget
            if aw and aw.winfo_exists():
                anchor_x = aw.winfo_rootx() + aw.winfo_width() - 8
                anchor_y = aw.winfo_rooty() - 8
            else:
                anchor_x = self._content_x or (sw - margin)
                anchor_y = self._content_y or (ch + margin)

            anchor_x = max(cw + margin, min(int(anchor_x), sw - margin))
            anchor_y = max(ch + margin, min(int(anchor_y), sh - margin))

            self._content_x = anchor_x
            self._content_y = anchor_y
            self._content.place(x=anchor_x, y=anchor_y, anchor='se')
            self._content_place_sig = ('abs', anchor_x, anchor_y)
            self._hud_cached_dims = None
        except Exception:
            pass

    def _cancel_menu_layout_refresh(self) -> None:
        if self._menu_hud_job is None:
            return
        try:
            if self._overlay is not None and self._overlay.winfo_exists():
                self._overlay.after_cancel(self._menu_hud_job)
        except Exception:
            pass
        self._menu_hud_job = None

    def _run_menu_layout_refresh(self) -> None:
        self._menu_hud_job = None
        if not self._visible or not self._overlay or not self._content:
            return
        try:
            if not self._overlay.winfo_exists() or not self._content.winfo_exists():
                return
            # Clicking a menu or child-bar item that changes layout used
            # to do update_idletasks() + anchor refresh + HUD redraw
            # inline inside the click callback. That re-entered Tk and the
            # GLFW pump while resize-triggered GPU windows were still in
            # the originating event stack, which is the exact crash path
            # the user reports: any button that causes a resize aborts.
            # Coalesce those updates into one idle turn after the click
            # callback returns, so the resize happens outside the active
            # mouse callback / poll_events stack.
            self._overlay.update_idletasks()
            self._refresh_anchor_layout()
            self._draw_menu_hud(
                0, 0, max(0.0, time.time() - self._menu_anim_t0))
        except Exception:
            pass

    def _schedule_menu_layout_refresh(self) -> None:
        if not self._overlay or not self._content:
            return
        if self._menu_hud_job is not None:
            return
        try:
            self._menu_hud_job = self._overlay.after_idle(
                self._run_menu_layout_refresh)
        except Exception:
            self._menu_hud_job = None
            self._run_menu_layout_refresh()

    def bind_events(self):
        self.root.bind_all('<Alt-KeyPress>', self._on_alt_key)
        if self.slide_down:
            self.root.bind_all('<ButtonPress-1>', self._on_mouse_down)
            self.root.bind_all('<B1-Motion>', self._on_mouse_drag)

    def unbind_events(self):
        try:
            self.root.unbind_all('<Alt-KeyPress>')
            self.root.unbind_all('<ButtonPress-1>')
            self.root.unbind_all('<B1-Motion>')
        except Exception:
            pass

    def _on_alt_key(self, e):
        if e.keysym.lower() == self.key_code.lower():
            if not self._visible:
                self.open()
            else:
                self.close()

    def _on_mouse_down(self, e):
        self._first_y = e.y_root
        self._first_time = time.time() * 1000

    def _on_mouse_drag(self, e):
        if self._visible:
            return
        dy = e.y_root - self._first_y
        dt = time.time() * 1000 - self._first_time
        if dy > self._slide_threshold and dt < self._slide_duration:
            if not self._throttle_timer:
                self.open()
                self._throttle_timer = self.root.after(1000, self._reset_throttle)

    def _reset_throttle(self):
        self._throttle_timer = None

    def open(self):
        if self._visible:
            return
        self._visible = True
        self._external_close_prepared = False
        self._menu_open_grace_until = time.time() + 0.65
        self._create_overlay()

    def close(self):
        if not self._visible:
            return
        self._visible = False
        self._menu_open_grace_until = 0.0
        self._fade_out_and_destroy()

    def toggle(self):
        if self._visible:
            self.close()
        else:
            self.open()

    @property
    def visible(self):
        return self._visible

    _TRANSPARENT_KEY = '#010101'   # 透明色键 (Windows -transparentcolor)

    def _create_overlay(self):
        self._overlay = tk.Toplevel(self.root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes('-topmost', True)
        self._overlay.withdraw()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Oversize the overlay by BREATH_PAD on every side so we can
        # drift it ~1-5 px each tick without exposing missing pixels at
        # the screen edge. Drift is applied to the WINDOW geometry only,
        # so no Tk widget layout runs per frame (no tearing).
        self._breath_pad = 12
        self._overlay_base_x = -self._breath_pad
        self._overlay_base_y = -self._breath_pad
        overlay_w = sw + self._breath_pad * 2
        overlay_h = sh + self._breath_pad * 2
        self._overlay_size_part = f'{overlay_w}x{overlay_h}'
        self._overlay_drift_sig = (self._overlay_base_x, self._overlay_base_y)
        self._overlay.geometry(
            f'{self._overlay_size_part}+{self._overlay_base_x}+{self._overlay_base_y}')
        self._overlay.configure(bg=self._TRANSPARENT_KEY)
        self._overlay.attributes('-alpha', 0.0)
        # 透明色键: 使 overlay 背景完全透明, 只保留 HUD 元素和内容组件
        try:
            self._overlay.attributes('-transparentcolor', self._TRANSPARENT_KEY)
        except Exception:
            pass
        self._overlay.bind('<Escape>', lambda e: self.close())
        self._overlay.bind('<FocusOut>', self._on_overlay_focus_out)

        self._menu_hud_cv = tk.Canvas(
            self._overlay, bg=self._TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self._menu_hud_cv.place(x=0, y=0, relwidth=1, relheight=1)

        # v2.2.12: when the GPU HUD path is enabled, spawn a sibling
        # ULW Toplevel that owns the visual HUD layer (brackets, rails,
        # scan, dots, stamp). The legacy canvas remains in place and
        # empty so the chroma-key window still hosts widgets only.
        if self._gpu_hud_enabled and MenuHudOverlay is not None:
            try:
                self._hud_overlay = MenuHudOverlay(self.root)
            except Exception:
                self._hud_overlay = None

        # 在 root 窗口层检测点击 → 实现 "点击外部关闭" (透明区域点击穿透到 root)
        self._root_click_id = self.root.bind('<Button-1>',
            self._on_root_click_outside, add='+')

        # 内容定位: anchor_widget 模式 → 贴近浮动按钮右上角向左上展开; 否则居中
        self._content = tk.Frame(self._overlay, bg=self._TRANSPARENT_KEY, highlightthickness=0)
        try:
            aw = self.anchor_widget
            if aw and aw.winfo_exists():
                self._overlay.update_idletasks()
                self._content_x = aw.winfo_rootx() + aw.winfo_width() - 8
                self._content_y = aw.winfo_rooty() - 8
                self._content.place(x=self._content_x, y=self._content_y, anchor='se')
            else:
                self._content_x = None
                self._content_y = None
                self._content.place(relx=0.5, rely=0.5, anchor='center')
        except Exception:
            self._content_x = None
            self._content_y = None
            self._content.place(relx=0.5, rely=0.5, anchor='center')

        # 水平: LeftInfo | MenuBar | ChildBar
        if self.left_widget_factory:
            self._left_widget = self.left_widget_factory(self._content)
            self._left_widget.pack(side=tk.LEFT, padx=(0, 25), anchor='n')
            self._left_info = None
        else:
            self._left_info = SAOLeftInfo(self._content, self.username, self.description)
            self._left_info.pack(side=tk.LEFT, padx=(0, 25), anchor='n')
            self._left_widget = self._left_info

        self._menu_bar = SAOMenuBar(self._content, self.icon_arr,
                                    on_activate=self._on_menu_activate)
        self._menu_bar.pack(side=tk.LEFT, anchor='n')

        self._child_bar = SAOChildBar(self._content)
        self._child_bar.pack(side=tk.LEFT, padx=(25, 0), anchor='n')

        for name, items in self.child_menus.items():
            self._child_bar.register_menu(name, items)

        self._overlay.update_idletasks()
        self._refresh_anchor_layout()
        self._draw_menu_hud(0, 0, phase=0.0)
        try:
            _get_scheduler(self.root)
        except Exception:
            pass

        # fadeIn 0.4s + 弹出入场动画
        self._anim = Animator(self._overlay)

        # 内容入场: 在 fade-in 期间从稍高处向下弹入 (spring pop)
        spring_offset = 28  # 入场起始偏移量(px)

        def _spring_ease(t: float) -> float:
            """spring: overshoot 则小弹超, 平滑落地"""
            # 使用近似弹簧曲线: ease-out 加轻微反射
            if t < 0.7:
                return ease_out(t / 0.7) * 1.06
            else:
                return 1.0 + (1.06 - 1.0) * (1.0 - (t - 0.7) / 0.3)  # 回弹到 1.0

        def _anim_frame(t: float):
            self._set_alpha(0.92 * t)
            # 内容各sprite 从偏移位置弹至目标
            st = _spring_ease(t)
            dy = int(spring_offset * (1.0 - st))
            try:
                if self._content_x is not None:
                    self._content.place(
                        x=self._content_x,
                        y=self._content_y - dy,
                        anchor='se')
                else:
                    self._content.place(relx=0.5, rely=0.5, anchor='center',
                                        x=0, y=dy)
            except Exception:
                pass

        def _finish_open():
            self._menu_anim_t0 = time.time()
            self._menu_force_60_until = self._menu_anim_t0 + 0.8
            self._start_menu_hud_anim()

        # 菜单栏入场动画
        self._menu_bar.play_enter_animation()
        try:
            self._overlay.deiconify()
            self._overlay.lift()
        except Exception:
            pass

        self._anim.animate('fade_in', 420, _anim_frame, on_done=_finish_open)
        self._start_breath()

        if self.on_open_callback:
            self.on_open_callback()

        try:
            self._overlay.focus_force()
        except Exception:
            pass

    def _set_alpha(self, a):
        try:
            if self._overlay and self._overlay.winfo_exists():
                # 映射 0..0.92 → 0..1.0, 最终态 alpha=1.0 消除 transparentcolor 黑色描边
                if a <= 0.005:
                    self._overlay.attributes('-alpha', 0.0)
                else:
                    self._overlay.attributes('-alpha', min(1.0, a / 0.92))
        except Exception:
            pass

    def _get_visual_bounds(self):
        """返回当前实际可见菜单区域边界，忽略透明占位区域."""
        if not self._content or not self._content.winfo_exists():
            return None
        try:
            self._content.update_idletasks()
            boxes = []
            for child in self._content.winfo_children():
                w = child.winfo_width() or child.winfo_reqwidth()
                h = child.winfo_height() or child.winfo_reqheight()
                if w <= 4 or h <= 4:
                    continue
                x = child.winfo_x()
                y = child.winfo_y()
                boxes.append((x, y, x + w, y + h))
            if not boxes:
                x = self._content.winfo_x()
                y = self._content.winfo_y()
                w = self._content.winfo_width() or self._content.winfo_reqwidth()
                h = self._content.winfo_height() or self._content.winfo_reqheight()
                return (x, y, x + w, y + h)
            return (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
        except Exception:
            return None

    def _get_menu_backdrop_sprite(self, width: int, height: int):
        width = max(260, int(width))
        height = max(180, int(height))
        key = (width, height)
        if self._menu_hud_backdrop_key == key and self._menu_hud_backdrop is not None:
            return self._menu_hud_backdrop

        pad = 24
        img_w = width + pad * 2
        img_h = height + pad * 2

        shadow = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle((pad + 5, pad + 7, pad + width + 5, pad + height + 7),
            radius=32, fill=(0, 0, 0, 40))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))

        plate = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(plate)
        outer = (pad, pad, pad + width, pad + height)
        inner = (pad + 8, pad + 8, pad + width - 8, pad + height - 8)
        pdraw.rounded_rectangle(outer, radius=32,
                fill=(10, 16, 24, 180), outline=(110, 210, 240, 60), width=1)
        pdraw.rounded_rectangle(inner, radius=26,
                fill=(14, 20, 30, 140), outline=(160, 230, 255, 36), width=1)
        gloss = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(gloss)
        gdraw.rounded_rectangle((pad + 8, pad + 6, pad + width - 10, int(pad + height * 0.36)),
            radius=24, fill=(200, 240, 255, 14))
        gloss = gloss.filter(ImageFilter.GaussianBlur(radius=10))
        plate = Image.alpha_composite(plate, gloss)

        merged = Image.alpha_composite(shadow, plate)
        self._menu_hud_backdrop = ImageTk.PhotoImage(merged)
        self._menu_hud_backdrop_key = key
        return self._menu_hud_backdrop

    @_probe.decorate('ui.menu.draw_main')
    def _draw_menu_hud(self, dx: int = 0, dy: int = 0, phase: float = 0.0):
        if not self._menu_hud_cv or not self._overlay or not self._overlay.winfo_exists():
            return
        # Cache overlay + content dimensions. The overlay is a fullscreen
        # Toplevel and the content frame doesn't change size after the
        # menu is built, so we only need to query Tk when the cache is
        # invalidated (sized None = force refresh on next tick).
        cached = self._hud_cached_dims
        if cached is None:
            try:
                sw = self._overlay.winfo_width()
                sh = self._overlay.winfo_height()
                cw = max(120, self._content.winfo_width() or self._content.winfo_reqwidth())
                ch = max(120, self._content.winfo_height() or self._content.winfo_reqheight())
            except Exception:
                return
            if sw <= 1 or sh <= 1 or cw <= 1 or ch <= 1:
                # Tk hasn't laid out yet; try again next tick without caching.
                return
            self._hud_cached_dims = (sw, sh, cw, ch)
        else:
            sw, sh, cw, ch = cached

        if self._content_x is not None and self._content_y is not None:
            # v2.2.12: anchored-mode breathing — apply dx/dy to HUD sprite
            # only (NOT to the content frame). The widgets stay still and
            # only the brackets/rails/scan visibly drift, which is what
            # users perceive as the SAO HUD breathing. Earlier code moved
            # the entire fullscreen chroma-key Toplevel via geometry()
            # every tick, which forces DWM to recomposite the whole
            # desktop region behind it and is the dominant tearing source.
            left = self._content.winfo_x() + dx
            top = self._content.winfo_y() + dy
        else:
            left = (sw - cw) // 2 + dx
            top = (sh - ch) // 2 + dy

        # v2.2.12: GPU HUD path — route the entire frame through the
        # off-thread layered window, leaving the chroma-key canvas
        # untouched. The widget Toplevel below stays still; only the
        # visual HUD's brackets/rails/scan move with breathing.
        if self._hud_overlay is not None:
            try:
                # MenuHudOverlay.set_geometry expects the content top-left
                # in *screen* coordinates; convert from overlay-local.
                ox_screen = self._overlay.winfo_rootx() + left
                oy_screen = self._overlay.winfo_rooty() + top
                self._hud_overlay.set_geometry(
                    ox_screen, oy_screen,
                    max(120, cw), max(120, ch),
                    sw, sh,
                )
                self._hud_overlay.tick(time.time(), dx, dy, phase)
                self._menu_hud_origin = (left, top)
                self._menu_hud_last_sig = None
                return
            except Exception:
                # Fall through to legacy canvas path on any error so the
                # menu always renders something.
                pass

        cv = self._menu_hud_cv
        frame = self._menu_hud_renderer.render(
            max(120, cw),
            max(120, ch),
            sw,
            sh,
            phase,
        )
        ox, oy = self._menu_hud_renderer.sprite_origin(left, top)
        hud_sig = (ox, oy, id(frame.static_photo), frame.canvas_sig)
        if hud_sig == self._menu_hud_last_sig:
            self._menu_hud_origin = (ox, oy)
            self._menu_hud_sprite = frame.static_photo
            return

        items = self._menu_hud_items
        # ── Static background photo (brackets + rails + labels) ─────────
        if items.get('static') is None:
            items['static'] = cv.create_image(
                ox, oy, image=frame.static_photo, anchor='nw')
            self._menu_hud_static_photo = frame.static_photo
            items['static_origin'] = (ox, oy)
        else:
            if items['static_origin'] != (ox, oy):
                cv.coords(items['static'], ox, oy)
                items['static_origin'] = (ox, oy)
            if frame.static_photo is not self._menu_hud_static_photo:
                cv.itemconfigure(items['static'], image=frame.static_photo)
                self._menu_hud_static_photo = frame.static_photo

        # ── Scan line + 2 trail lines (native Canvas lines) ─────────────
        scan_y = oy + frame.scan_y
        cx1 = ox + frame.cx1
        cx2 = ox + frame.cx2
        self._ensure_line(items, 'scan',
                          cx1, scan_y, cx2, scan_y, frame.scan_color)
        for idx, ty in enumerate(frame.trail_ys):
            ty_abs = oy + ty
            self._ensure_line(items, f'trail{idx}',
                              cx1, ty_abs, cx2, ty_abs,
                              frame.trail_colors[idx])

        # ── Dot glow sprites (image items) + tiny solid dot overlays ────
        gs = frame.dot_glow_size
        glow_off = gs // 2
        self._ensure_image(items, 'glow_l', frame.dot_photo_l,
                           ox + frame.rail_x_l - glow_off,
                           oy + frame.dot_y_l - glow_off)
        self._ensure_image(items, 'glow_r', frame.dot_photo_r,
                           ox + frame.rail_x_r - glow_off,
                           oy + frame.dot_y_r - glow_off)
        r = frame.dot_radius
        self._ensure_oval(items, 'dot_l',
                          ox + frame.rail_x_l - r,
                          oy + frame.dot_y_l - r,
                          ox + frame.rail_x_l + r,
                          oy + frame.dot_y_l + r,
                          frame.dot_color_l)
        self._ensure_oval(items, 'dot_r',
                          ox + frame.rail_x_r - r,
                          oy + frame.dot_y_r - r,
                          ox + frame.rail_x_r + r,
                          oy + frame.dot_y_r + r,
                          frame.dot_color_r)

        # ── Clock stamp text (Canvas text, updates once per second) ─────
        tx, ty = ox + frame.stamp_pos[0], oy + frame.stamp_pos[1]
        self._ensure_text(items, 'stamp', tx, ty,
                          frame.stamp_text, frame.stamp_color,
                          frame.stamp_font)

        self._menu_hud_origin = (ox, oy)
        self._menu_hud_sprite = frame.static_photo
        self._menu_hud_last_sig = hud_sig

    def _ensure_line(self, items, key, x1, y1, x2, y2, color):
        cv = self._menu_hud_cv
        item = items.get(key)
        new_coords = (x1, y1, x2, y2)
        if item is None:
            items[key] = cv.create_line(*new_coords, fill=color, width=1)
            items[key + '_coords'] = new_coords
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != new_coords:
            cv.coords(item, *new_coords)
            items[key + '_coords'] = new_coords
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _ensure_image(self, items, key, photo, x, y):
        cv = self._menu_hud_cv
        item = items.get(key)
        if item is None:
            items[key] = cv.create_image(x, y, image=photo, anchor='nw')
            items[key + '_coords'] = (x, y)
            items[key + '_photo'] = photo
            return
        if items.get(key + '_coords') != (x, y):
            cv.coords(item, x, y)
            items[key + '_coords'] = (x, y)
        if items.get(key + '_photo') is not photo:
            cv.itemconfigure(item, image=photo)
            items[key + '_photo'] = photo

    def _ensure_oval(self, items, key, x1, y1, x2, y2, color):
        cv = self._menu_hud_cv
        item = items.get(key)
        coords = (x1, y1, x2, y2)
        if item is None:
            items[key] = cv.create_oval(*coords, fill=color, outline='')
            items[key + '_coords'] = coords
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != coords:
            cv.coords(item, *coords)
            items[key + '_coords'] = coords
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _ensure_text(self, items, key, x, y, text, color, font):
        cv = self._menu_hud_cv
        item = items.get(key)
        if item is None:
            items[key] = cv.create_text(
                x, y, text=text, fill=color, font=font, anchor='ne')
            items[key + '_coords'] = (x, y)
            items[key + '_text'] = text
            items[key + '_color'] = color
            return
        if items.get(key + '_coords') != (x, y):
            cv.coords(item, x, y)
            items[key + '_coords'] = (x, y)
        if items.get(key + '_text') != text:
            cv.itemconfigure(item, text=text)
            items[key + '_text'] = text
        if items.get(key + '_color') != color:
            cv.itemconfigure(item, fill=color)
            items[key + '_color'] = color

    def _start_menu_hud_anim(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        self._draw_menu_hud(0, 0, phase=0.0)
        if self._menu_anim_registered:
            return
        try:
            _get_scheduler(self.root).register(
                self._menu_sched_ident,
                self._tick_menu_overlay,
                self._menu_overlay_animating,
            )
            self._menu_anim_registered = True
        except Exception:
            self._menu_anim_registered = False

    def _on_root_click_outside(self, e):
        """root 层点击处理: 透明区域的点击穿透到 root, 判断是否在内容区外."""
        if not self._visible or not self._content:
            return
        try:
            bounds = self._get_visual_bounds()
            if bounds is None:
                if time.time() < self._menu_open_grace_until:
                    return
                self.close()
                return
            x1, y1, x2, y2 = bounds
            ox = self._overlay.winfo_rootx()
            oy = self._overlay.winfo_rooty()
            cx1, cy1 = ox + x1 - 12, oy + y1 - 12
            cx2, cy2 = ox + x2 + 12, oy + y2 + 12
            if cx1 <= e.x_root <= cx2 and cy1 <= e.y_root <= cy2:
                if self._menu_bar is not None:
                    try:
                        if self._menu_bar.dispatch_root_click(
                                int(e.x_root), int(e.y_root)):
                            return
                    except Exception:
                        pass
                return  # 点击在内容区内, 不关闭
        except Exception:
            pass
        self.close()

    def _on_overlay_focus_out(self, _e=None):
        if not self._visible or not self._overlay or not self._overlay.winfo_exists():
            return

        def _check():
            if not self._visible or not self._overlay or not self._overlay.winfo_exists():
                return
            now = time.time()
            # Focus moved to one of our own GPU overlay windows (clicking a menu
            # category) — keep the menu open. Keep polling so we still close once
            # the user switches to a different application.
            if _foreground_in_own_process():
                try:
                    self._overlay.after(180, _check)
                except Exception:
                    pass
                return
            try:
                focus = self._overlay.focus_displayof()
                if focus is None or str(focus) == 'None':
                    if now < self._menu_open_grace_until:
                        delay_ms = max(
                            20,
                            int((self._menu_open_grace_until - now) * 1000.0) + 10,
                        )
                        try:
                            self._overlay.after(delay_ms, _check)
                        except Exception:
                            pass
                        return
                    self.close()
                    return
            except Exception:
                if now < self._menu_open_grace_until:
                    delay_ms = max(
                        20,
                        int((self._menu_open_grace_until - now) * 1000.0) + 10,
                    )
                    try:
                        self._overlay.after(delay_ms, _check)
                    except Exception:
                        pass
                    return
                self.close()

        try:
            self._overlay.after(1, _check)
        except Exception:
            self.close()

    def _on_menu_activate(self, item):
        _phase_trace('menu.activate.begin', str(getattr(item, 'get', lambda *_: None)('name', '<none>') if item is not None else '<none>'))
        self._menu_force_60_until = time.time() + 0.95
        lw = self._left_widget
        layout_changed = False
        if item is None:
            if lw and hasattr(lw, 'set_active'):
                lw.set_active(False)
            layout_changed = bool(self._child_bar.hide_menu())
            if layout_changed:
                self._hud_cached_dims = None
                self._content_place_sig = None
                self._menu_hud_renderer.reset()
                self._menu_hud_last_sig = None
                self._schedule_menu_layout_refresh()
            return
        if lw and hasattr(lw, 'set_active'):
            was_active = bool(getattr(lw, '_active', False))
            lw.set_active(True)
            if was_active and hasattr(lw, 'sync_pulse'):
                try:
                    top = getattr(lw, '_top', None)
                    target_w = int(getattr(lw, '_target_w', 0) or 0)
                    if top is None or target_w <= 0 or top.winfo_width() >= int(target_w * 0.90):
                        lw.sync_pulse()
                except Exception:
                    lw.sync_pulse()
        name = item.get('name', '')
        if name in self.child_menus:
            try:
                from utils.sao_sound import play_sound as _ps
                _ps('submenu', volume=0.5)
            except Exception:
                pass
            layout_changed = bool(self._child_bar.show_menu(name))
        else:
            layout_changed = bool(self._child_bar.hide_menu())
        _phase_trace('menu.activate.layout', f'changed={int(bool(layout_changed))}')
        if layout_changed:
            self._hud_cached_dims = None
            self._content_place_sig = None
            self._menu_hud_renderer.reset()
            self._menu_hud_last_sig = None
            self._schedule_menu_layout_refresh()

    def refresh_child_menus(self, menus: Dict[str, List[Dict]], force: bool = False):
        """Batch-refresh child menus and redraw HUD only if the visible menu changed."""
        menus = dict(menus or {})
        self.child_menus = menus
        if not self._child_bar:
            return False

        layout_changed = False
        for name in list(getattr(self._child_bar, '_menus', {}).keys()):
            if name not in menus:
                self._child_bar.unregister_menu(name)
                if getattr(self._child_bar, '_current_name', None) == name:
                    layout_changed = bool(self._child_bar.hide_menu()) or layout_changed

        for name, items in menus.items():
            changed = self._child_bar.register_menu(name, items, force=force)
            if changed and getattr(self._child_bar, '_current_name', None) == name:
                layout_changed = bool(self._child_bar.show_menu(name, force=True)) or layout_changed

        if not layout_changed:
            return False

        self._hud_cached_dims = None
        self._content_place_sig = None
        self._menu_hud_renderer.reset()
        self._menu_hud_last_sig = None
        self._schedule_menu_layout_refresh()
        return True

    def refresh_child_menu(self, name: str, items: List[Dict]):
        """动态更新某个子菜单的内容"""
        menus = dict(self.child_menus or {})
        menus[name] = items
        return self.refresh_child_menus(menus)

    def _clear_menu_hud_items(self) -> None:
        """Drop all canvas-native HUD items so the next frame re-creates
        them at the new positions/photos. Cheaper than re-positioning
        everything when the content size changes."""
        if self._menu_hud_cv is not None:
            try:
                self._menu_hud_cv.delete('all')
            except Exception:
                pass
        self._menu_hud_items = {}
        self._menu_hud_static_photo = None
        self._menu_hud_item = None
        self._menu_hud_sprite = None
        self._menu_hud_origin = None
        self._menu_hud_last_sig = None

    @property
    def left_widget(self):
        return self._left_widget

    def _fade_out_and_destroy(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        self._stop_breath()
        # 解除 root 层点击监听
        try:
            if hasattr(self, '_root_click_id') and self._root_click_id:
                self.root.unbind('<Button-1>', self._root_click_id)
                self._root_click_id = None
        except Exception:
            pass

        def fade(t):
            dy = int(24 * t)
            self._set_alpha(0.92 * (1.0 - t))
            try:
                if self._content and self._content.winfo_exists():
                    if self._content_x is not None:
                        self._content.place(
                            x=self._content_x,
                            y=self._content_y - dy,
                            anchor='se')
                    else:
                        self._content.place(relx=0.5, rely=0.5, anchor='center',
                                            x=0, y=-dy)
            except Exception:
                pass

        def destroy():
            self._destroy_overlay(invoke_callback=True)

        anim = Animator(self._overlay)
        anim.animate('fade_out', 500, fade, on_done=destroy)

    def prepare_external_fade(self):
        if not self._overlay or not self._overlay.winfo_exists():
            return
        self._visible = False
        self._external_close_prepared = True
        self._stop_breath()
        try:
            if hasattr(self, '_root_click_id') and self._root_click_id:
                self.root.unbind('<Button-1>', self._root_click_id)
                self._root_click_id = None
        except Exception:
            pass

    def force_destroy_overlay(self, invoke_callback: bool = False):
        self._visible = False
        self._stop_breath()
        try:
            if hasattr(self, '_root_click_id') and self._root_click_id:
                self.root.unbind('<Button-1>', self._root_click_id)
                self._root_click_id = None
        except Exception:
            pass
        self._destroy_overlay(invoke_callback=invoke_callback)

    def _destroy_overlay(self, invoke_callback: bool = True):
        self._visible = False
        # v2.2.12: tear down the layered HUD window before the parent
        # Toplevel goes away so its async render lane stops cleanly.
        if self._hud_overlay is not None:
            try:
                self._hud_overlay.destroy()
            except Exception:
                pass
            self._hud_overlay = None
        if self._overlay and self._overlay.winfo_exists():
            try:
                self._overlay.destroy()
            except Exception:
                pass
        self._overlay = None
        self._menu_hud_item = None
        self._menu_hud_sprite = None
        self._menu_hud_origin = None
        self._menu_hud_items = {}
        self._menu_hud_static_photo = None
        self._menu_hud_last_sig = None
        self._content_place_sig = None
        self._overlay_size_part = ''
        self._overlay_drift_sig = None
        self._menu_hud_renderer.reset()
        self._hud_cached_dims = None
        self._external_close_prepared = False
        if invoke_callback and self.on_close_callback:
            self.on_close_callback()

    def _start_breath(self):
        self._draw_menu_hud(0, 0, phase=0.0)

    def _stop_breath(self):
        if self._menu_anim_registered:
            try:
                _get_scheduler(self.root).unregister(self._menu_sched_ident)
            except Exception:
                pass
            self._menu_anim_registered = False
        self._menu_force_60_until = 0.0
        self._breath_job = None
        self._cancel_menu_layout_refresh()

    def _menu_overlay_animating(self) -> bool:
        if not self._visible or not self._overlay or not self._overlay.winfo_exists():
            return False
        return True

    @_probe.decorate('ui.menu.tick_main')
    def _tick_menu_overlay(self, now: float) -> None:
        if not self._visible or not self._overlay or not self._overlay.winfo_exists():
            return
        elapsed = max(0.0, now - self._menu_anim_t0)
        phase = _CY_UI.menu_hud_phase_quantized(
            elapsed, now < self._menu_force_60_until)
        # Gentle 2 px-quantized drift used by the HUD canvas only. The content
        # frame itself is NEVER re-placed every tick: doing that re-runs
        # Tk's geometry pass on the whole menu and causes visible tearing
        # and right-edge clipping when the anchored menu is near the
        # screen edge. Drift is now applied purely as a visual offset to
        # the HUD sprite via _draw_menu_hud(dx, dy, ...).
        dx, dy = _CY_UI.menu_hud_breath_offsets(
            elapsed, now < self._menu_force_60_until)
        # v2.2.12: do NOT call overlay.geometry() per tick. Moving a
        # fullscreen chroma-key Toplevel forces DWM to recomposite the
        # entire desktop region under it on every frame, which is the
        # dominant tearing source. Instead the breathing offset is
        # applied purely to the HUD sprite below via _draw_menu_hud(dx,
        # dy, ...), so the chroma-key window stays stationary and DWM
        # only refreshes the small HUD region.
        # IMPORTANT: do not re-.place() the content frame on every tick
        # either — that re-runs Tk's geometry pass on the whole menu and
        # also tears.
        self._draw_menu_hud(dx, dy, phase)


