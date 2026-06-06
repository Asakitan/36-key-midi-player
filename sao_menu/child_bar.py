# -*- coding: utf-8 -*-
"""SAOChildBar (split from sao_theme.py — verbatim)."""
import tkinter as tk
import time
from typing import Any, Optional, Callable, List, Dict, Tuple
import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from utils.sao_sound import get_sao_font as _sao_font, get_cjk_font as _cjk_font
from render.overlay_scheduler import get_scheduler as _get_scheduler
from utils.perf_probe import phase as _phase_trace, probe as _probe
try:
    # v2.3.0 Phase 3+++: GPU-presented child (popup submenu) bar.
    from gui_modules.sao_child_bar_gpu import (
        ChildBarGpuPainter,
        _ChildBarSnapshot,
        _RowSnapshot as _ChildRowSnapshot,
        BarColors as _ChildBarColors,
        gpu_child_bar_enabled,
    )
except Exception as _child_gpu_import_error:
    _CHILD_GPU_IMPORT_ERROR = _child_gpu_import_error
    ChildBarGpuPainter = None  # type: ignore[assignment]
    _ChildBarSnapshot = None  # type: ignore[assignment]
    _ChildRowSnapshot = None  # type: ignore[assignment]
    _ChildBarColors = None  # type: ignore[assignment]
    def gpu_child_bar_enabled() -> bool:  # type: ignore[no-redef]
        raise RuntimeError('ChildBarGpuPainter GPU module is required') from _CHILD_GPU_IMPORT_ERROR
from sao_menu.colors import SAOColors
from sao_menu.animator import Animator
from sao_menu.utils import ease_in_out, lerp, lerp_color

# ──────────────────── 子菜单 (ChildBar) ────────────────────
class SAOChildBar(tk.Frame):
    """
    SAO 风格子菜单
    - 列表项: 160px宽, 40px高, 白色半透明
    - 悬停: 金色背景
    - 左侧连接线
    - 下拉动画
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg='', highlightthickness=0, **kw)
        self.configure(bg=parent.cget('bg'))
        self._menus: Dict[str, List[Dict]] = {}
        self._menu_signatures: Dict[str, Tuple] = {}
        self._current_name = None
        self._items: List[tk.Frame] = []
        self._content_wrap = None
        self._line_cv = None
        self._arrow_cv = None
        self._line_item_specs = []
        self._arrow_item_specs = []
        self._line_item_last: Dict[int, str] = {}
        self._arrow_item_last: Dict[Tuple[int, str], str] = {}
        self._transition_serial = 0
        self._row_anim_registered = False
        self._row_anim_active = False
        self._row_anim_t0 = 0.0
        self._row_anim_duration_s = 0.24
        self._row_anim_stagger_s = 0.028
        self._row_anim_sched_ident = f'sao_child_bar_{id(self)}'
        self._locked_size: Optional[Tuple[int, int]] = None
        self._size_anim_active = False
        self._layout_commit_job = None
        self._anim = Animator(self)
        self._gpu_painter: Optional[Any] = None
        self._gpu_managed: bool = False
        self._gpu_hover_idx: Optional[int] = None  # row hovered via GPU dispatch
        self._gpu_colors: Optional[Any] = None
        self._gpu_chroma_bg: str = '#010101'
        self._gpu_fade_t: float = 0.0
        # v2.3.0 Phase A1: cached painter inputs so the per-frame
        # tick stays Tk-free in GPU mode. Widths are populated by
        # animation step closures; screen_xy is invalidated on
        # <Configure> of self or _content_wrap.
        self._cached_screen_xy: Optional[Tuple[int, int]] = None
        self._anim_line_w: Optional[int] = None
        self._anim_arrow_w: Optional[int] = None
        self._setup_gpu_painter()
        self.bind('<Destroy>', lambda e: self._on_destroy(), add='+')
        self.bind('<Configure>',
                  lambda e: setattr(self, '_cached_screen_xy', None),
                  add='+')

    @staticmethod
    def _menu_signature(items: List[Dict]) -> Tuple:
        sig = []
        for item in list(items or []):
            if not isinstance(item, dict):
                sig.append((str(item), '', False))
                continue
            sig.append((
                str(item.get('icon', '') or ''),
                str(item.get('label', '') or ''),
                bool(item.get('command')),
            ))
        return tuple(sig)

    def register_menu(self, name: str, items: List[Dict], force: bool = False):
        normalized = list(items or [])
        new_sig = self._menu_signature(normalized)
        if not force and self._menu_signatures.get(name) == new_sig:
            return False
        self._menus[name] = normalized
        self._menu_signatures[name] = new_sig
        return True

    def unregister_menu(self, name: str):
        self._menus.pop(name, None)
        self._menu_signatures.pop(name, None)

    def show_menu(self, name: str, force: bool = False):
        _phase_trace('menu.child.show_menu', f'name={name} force={int(bool(force))}')
        target_sig = self._menu_signatures.get(name)
        current_sig = self._menu_signatures.get(self._current_name) if self._current_name else None
        if not force and name == self._current_name and self._items and current_sig == target_sig:
            return False
        items = self._menus.get(name, [])
        if self._items and items and self._current_name and name != self._current_name:
            self._current_name = name
            self._rebuild(items, animate_rows=False)
            return True
        self._transition_to(name, items)
        return True

    def hide_menu(self):
        if self._current_name is None and not self._items:
            return False
        self._transition_to(None, [])
        return True

    def _transition_to(self, name: Optional[str], items: List[Dict]):
        _phase_trace(
            'menu.child.transition',
            f'name={name or "<none>"} has_items={int(bool(self._items))} n={len(items)}',
        )
        self._transition_serial += 1
        serial = self._transition_serial

        def _swap_in():
            if serial != self._transition_serial or not self.winfo_exists():
                return
            self._current_name = name
            self._rebuild(items, animate_rows=not bool(self._items))

        if self._items:
            self._animate_out_current(_swap_in)
        else:
            _swap_in()

    def _animate_out_current(self, on_done: Callable[[], None]):
        _phase_trace('menu.child.animate_out', f'rows={len(self._items)}')
        self._stop_row_anim()
        rows = [getattr(outer, '_row_body', None) for outer in self._items]
        rows = [row for row in rows if row is not None and row.winfo_exists()]
        if not rows:
            for w in self.winfo_children():
                w.destroy()
            self._items.clear()
            self._content_wrap = None
            self._line_cv = None
            self._arrow_cv = None
            self._line_item_specs = []
            self._arrow_item_specs = []
            self._line_item_last = {}
            self._arrow_item_last = {}
            on_done()
            return

        start_widths = []
        for row in rows:
            try:
                start_widths.append(max(1, row.winfo_width(), int(row.cget('width'))))
            except Exception:
                start_widths.append(240)

        line_start = 10
        arrow_start = 12
        try:
            if self._line_cv is not None and self._line_cv.winfo_exists():
                line_start = max(1, self._line_cv.winfo_width(), int(self._line_cv.cget('width')))
        except Exception:
            pass
        try:
            if self._arrow_cv is not None and self._arrow_cv.winfo_exists():
                arrow_start = max(1, self._arrow_cv.winfo_width(), int(self._arrow_cv.cget('width')))
        except Exception:
            pass

        def _step(t: float):
            gpu = self._gpu_managed
            for outer, row, start_w in zip(self._items, rows, start_widths):
                w = max(1, int(round(lerp(start_w, 1, t))))
                if gpu:
                    outer._anim_row_w = w
                elif row.winfo_exists():
                    if getattr(outer, '_anim_row_w', None) != w:
                        row.configure(width=w)
                        outer._anim_row_w = w
            fade_t = ease_in_out(t)
            self._apply_line_arrow_fade(fade_t)
            for outer in self._items:
                apply_visual = getattr(outer, '_apply_fade_visual', None)
                if apply_visual:
                    apply_visual(fade_t)
            line_w = max(1, int(round(lerp(line_start, 1, t))))
            arrow_w = max(1, int(round(lerp(arrow_start, 1, t))))
            if gpu:
                self._anim_line_w = line_w
                self._anim_arrow_w = arrow_w
                self._dispatch_gpu_paint()
            else:
                if self._line_cv is not None and self._line_cv.winfo_exists():
                    if self._anim_line_w != line_w:
                        self._line_cv.configure(width=line_w)
                        self._anim_line_w = line_w
                if self._arrow_cv is not None and self._arrow_cv.winfo_exists():
                    if self._anim_arrow_w != arrow_w:
                        self._arrow_cv.configure(width=arrow_w)
                        self._anim_arrow_w = arrow_w

        def _finish():
            for w in self.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            self._items.clear()
            self._content_wrap = None
            self._line_cv = None
            self._arrow_cv = None
            self._line_item_specs = []
            self._arrow_item_specs = []
            self._line_item_last = {}
            self._arrow_item_last = {}
            on_done()

        self._anim.animate('switch_out', 140, _step, on_done=_finish, easing=ease_in_out)

    def _apply_line_arrow_fade(self, fade_t: float):
        fade_t = max(0.0, min(1.0, fade_t))
        self._gpu_fade_t = fade_t
        if self._gpu_managed:
            self._dispatch_gpu_paint()
            return
        bg = self.cget('bg')
        if self._line_cv is not None and self._line_cv.winfo_exists():
            for item_id, base_color in self._line_item_specs:
                new_color = lerp_color(base_color, bg, fade_t)
                if self._line_item_last.get(item_id) == new_color:
                    continue
                try:
                    self._line_cv.itemconfigure(item_id, fill=new_color)
                    self._line_item_last[item_id] = new_color
                except Exception:
                    pass
        if self._arrow_cv is not None and self._arrow_cv.winfo_exists():
            for item_id, base_color, channel in self._arrow_item_specs:
                new_color = lerp_color(base_color, bg, fade_t)
                cache_key = (item_id, channel)
                if self._arrow_item_last.get(cache_key) == new_color:
                    continue
                try:
                    self._arrow_cv.itemconfigure(item_id, **{channel: new_color})
                    self._arrow_item_last[cache_key] = new_color
                except Exception:
                    pass

    def _rebuild(self, items: List[Dict], animate_rows: bool = True):
        _phase_trace(
            'menu.child.rebuild',
            f'n={len(items)} animate={int(bool(animate_rows))}',
        )
        self._stop_row_anim()
        self._cancel_layout_commit()
        # Reset anim-driven painter inputs; new items will populate.
        self._anim_line_w = None
        self._anim_arrow_w = None
        # Keep _cached_screen_xy across rebuilds as last-known-good: the render
        # path reads the origin fresh each frame and only falls back to this when
        # a freshly-packed frame briefly reports (0,0). Wiping it here would flash
        # the submenu to the top-left for one frame on a category switch.
        old_w = max(0, self.winfo_width(), self.winfo_reqwidth()) if self.winfo_exists() else 0
        old_h = max(0, self.winfo_height(), self.winfo_reqheight()) if self.winfo_exists() else 0
        if old_w > 1 or old_h > 1:
            try:
                self.pack_propagate(False)
                self.configure(width=old_w, height=old_h)
                self._locked_size = (old_w, old_h)
            except Exception:
                self._locked_size = None
        for w in self.winfo_children():
            w.destroy()
        self._items.clear()
        self._content_wrap = None
        self._line_cv = None
        self._arrow_cv = None
        self._line_item_specs = []
        self._arrow_item_specs = []
        self._line_item_last = {}
        self._arrow_item_last = {}

        if not items:
            self._anim.cancel('size_shift')
            self._size_anim_active = False
            self._locked_size = None
            if self._gpu_managed and self._gpu_painter is not None:
                try:
                    self._gpu_painter.clear()
                except Exception:
                    pass
            try:
                self.configure(width=0, height=0)
            except Exception:
                pass
            return

        content = tk.Frame(self, bg=self.cget('bg'), highlightthickness=0)
        content.pack(anchor='nw')
        self._content_wrap = content

        # 连接线 (带微弱辉光)
        line_h = len(items) * 47 - 3
        line_cv = tk.Canvas(content, width=10, height=max(1, line_h),
                            bg=self.cget('bg'), highlightthickness=0)
        # 辉光层
        glow_line = line_cv.create_line(5, 5, 5, line_h - 5, fill='#d4d0d0', width=4)
        # 主线
        main_line = line_cv.create_line(5, 5, 5, line_h - 5, fill='#9c9999', width=2)
        # 顶部高光点
        top_dot = line_cv.create_oval(3, 3, 7, 7, fill='#b0b0b0', outline='')
        # 底部高光点
        bottom_dot = line_cv.create_oval(3, line_h - 7, 7, line_h - 3, fill='#b0b0b0', outline='')
        line_cv.pack(side=tk.LEFT, padx=(0, 3), anchor='n', pady=5)
        self._line_cv = line_cv
        self._line_item_specs = [
            (glow_line, '#d4d0d0'),
            (main_line, '#9c9999'),
            (top_dot, '#b0b0b0'),
            (bottom_dot, '#b0b0b0'),
        ]
        self._line_item_last = {
            glow_line: '#d4d0d0',
            main_line: '#9c9999',
            top_dot: '#b0b0b0',
            bottom_dot: '#b0b0b0',
        }

        # 箭头指示器 (微弱金色点)
        arrow_cv = tk.Canvas(content, width=12, height=max(1, line_h),
                             bg=self.cget('bg'), highlightthickness=0)
        # 辉光
        for gr in range(6, 0, -2):
            ga = int(15 * (1 - gr / 6))
            gc = f'#{int(ga * 3.5):02x}{int(ga * 2.2):02x}{int(ga * 0.3):02x}'
            oid = arrow_cv.create_oval(6 - gr, line_h // 2 - gr,
                                       6 + gr, line_h // 2 + gr,
                                       fill=gc, outline='')
            self._arrow_item_specs.append((oid, gc, 'fill'))
        core_dot = arrow_cv.create_oval(4, line_h // 2 - 2, 9, line_h // 2 + 3,
                                        fill='#c9b896', outline='#d4c8a8')
        self._arrow_item_specs.extend([
            (core_dot, '#c9b896', 'fill'),
            (core_dot, '#d4c8a8', 'outline'),
        ])
        self._arrow_item_last = {}
        for item_id, base_color, channel in self._arrow_item_specs:
            self._arrow_item_last[(item_id, channel)] = base_color
        arrow_cv.pack(side=tk.LEFT, padx=(0, 2), anchor='n', pady=5)
        self._arrow_cv = arrow_cv

        list_frame = tk.Frame(content, bg=self.cget('bg'), highlightthickness=0)
        list_frame.pack(side=tk.LEFT, anchor='n')

        for i, item in enumerate(items):
            row = self._create_item(list_frame, item, i)
            self._items.append(row)
        # Pre-size every row to its final width BEFORE we measure the
        # content frame. _create_item leaves rows shrunk to 88px so the
        # row-anim can grow them in; if we measure target_w with rows
        # still at 88px we lock child-bar at ~118px wide, then later
        # the rows expand back to 240 and bleed past the locked frame
        # (the right-side cut the user sees after switching menus a few
        # times — show_menu(name, force=False) calls _rebuild with
        # animate_rows=False, which never runs the row-anim fixup).
        for outer in self._items:
            row = getattr(outer, '_row_body', None)
            if row is not None and row.winfo_exists():
                try:
                    row.configure(width=240)
                    outer._anim_row_w = 240
                except Exception:
                    pass
        self._schedule_rebuild_layout(content)
        if animate_rows:
            self._start_row_anim()
        else:
            for outer in self._items:
                row = getattr(outer, '_row_body', None)
                if row is not None and row.winfo_exists():
                    if self._gpu_managed:
                        outer._anim_row_w = 240
                    else:
                        row.configure(width=240)
        # GPU mode: blank every Tk widget so only the painter draws.
        if self._gpu_managed:
            self._gpu_force_chroma()
            self._dispatch_gpu_paint()

    def _start_row_anim(self):
        if not self._items:
            return
        self._row_anim_active = True
        self._row_anim_t0 = time.time()
        if self._row_anim_registered:
            return
        try:
            _get_scheduler().register(
                self._row_anim_sched_ident,
                self._tick_row_anim,
                self._row_animating,
            )
            self._row_anim_registered = True
        except Exception:
            self._row_anim_registered = False

    def _stop_row_anim(self):
        self._row_anim_active = False
        if self._row_anim_registered:
            try:
                _get_scheduler().unregister(self._row_anim_sched_ident)
            except Exception:
                pass
            self._row_anim_registered = False

    def _cancel_layout_commit(self) -> None:
        if self._layout_commit_job is None:
            return
        try:
            self.after_cancel(self._layout_commit_job)
        except Exception:
            pass
        self._layout_commit_job = None

    def _commit_rebuild_layout(self, content: Optional[tk.Frame]) -> None:
        self._layout_commit_job = None
        if not self.winfo_exists() or content is None:
            return
        if content is not self._content_wrap or not content.winfo_exists():
            return
        try:
            target_w = max(1, content.winfo_reqwidth())
            target_h = max(1, content.winfo_reqheight())
            start_w = self._locked_size[0] if self._locked_size is not None else target_w
            start_h = self._locked_size[1] if self._locked_size is not None else target_h
            self.configure(width=start_w, height=start_h)
            self._animate_size_to(target_w, target_h)
        except Exception:
            pass

    def _schedule_rebuild_layout(self, content: Optional[tk.Frame]) -> None:
        self._cancel_layout_commit()
        try:
            self._layout_commit_job = self.after_idle(
                lambda c=content: self._commit_rebuild_layout(c))
        except Exception:
            self._layout_commit_job = None
            self._commit_rebuild_layout(content)

    def _row_animating(self) -> bool:
        return self._row_anim_active and self.winfo_exists()

    @_probe.decorate('ui.menu.child_row_anim')
    def _tick_row_anim(self, now: float):
        if not self.winfo_exists() or not self._items:
            self._stop_row_anim()
            return
        keep_animating = False
        gpu = self._gpu_managed
        for idx, outer in enumerate(self._items):
            row = getattr(outer, '_row_body', None)
            if row is None or not row.winfo_exists():
                continue
            start_w = max(1, int(getattr(outer, '_row_start_w', 72)))
            width, row_active = _CY_UI.popup_child_row_anim_step(
                now, self._row_anim_t0, idx,
                self._row_anim_stagger_s, self._row_anim_duration_s,
                start_w, 240,
            )
            if gpu:
                # GPU path: stash the animated width on outer; Tk row
                # frame is invisible (chroma keyed) and its inner
                # width doesn't drive any hit-testing, so skip the
                # expensive .configure entirely.
                outer._anim_row_w = width
            else:
                if getattr(outer, '_anim_row_w', None) != width:
                    row.configure(width=width)
                    outer._anim_row_w = width
            if row_active:
                keep_animating = True
        if gpu:
            self._dispatch_gpu_paint()
        if not keep_animating:
            try:
                if (not self._size_anim_active and
                        self._content_wrap is not None and self._content_wrap.winfo_exists()):
                    self.configure(
                        width=max(1, self._content_wrap.winfo_reqwidth()),
                        height=max(1, self._content_wrap.winfo_reqheight()),
                    )
            except Exception:
                pass
            if not self._size_anim_active:
                self._locked_size = None
            self._stop_row_anim()

    def _animate_size_to(self, target_w: int, target_h: int, duration_ms: int = 180):
        target_w = max(1, int(target_w))
        target_h = max(1, int(target_h))
        try:
            start_w = max(1, self.winfo_width(), int(self.cget('width') or 0), self.winfo_reqwidth())
            start_h = max(1, self.winfo_height(), int(self.cget('height') or 0), self.winfo_reqheight())
        except Exception:
            start_w = target_w
            start_h = target_h
        if abs(start_w - target_w) <= 1 and abs(start_h - target_h) <= 1:
            try:
                self.configure(width=target_w, height=target_h)
            except Exception:
                pass
            self._size_anim_active = False
            self._locked_size = None
            return

        self._size_anim_active = True

        def _step(t: float):
            try:
                self.configure(
                    width=max(1, int(round(lerp(start_w, target_w, t)))),
                    height=max(1, int(round(lerp(start_h, target_h, t)))),
                )
            except Exception:
                pass
            if self._gpu_managed:
                self._dispatch_gpu_paint()

        def _finish():
            self._size_anim_active = False
            self._locked_size = None
            try:
                self.configure(width=target_w, height=target_h)
            except Exception:
                pass

        self._anim.animate('size_shift', duration_ms, _step, on_done=_finish, easing=ease_in_out)

    def _create_item(self, parent, item: Dict, index: int) -> tk.Frame:
        # 外容器: 包含阴影层 + 主体
        outer = tk.Frame(parent, bg=self.cget('bg'), highlightthickness=0)
        outer.pack(fill=tk.X, pady=(0, 3))

        row = tk.Frame(outer, bg=SAOColors.CHILD_BG, highlightthickness=0,
                       width=240, height=44)
        row.pack(fill=tk.X)
        row.pack_propagate(False)
        outer._row_body = row

        # 左侧激活指示条 (2px, 初始透明)
        indicator = tk.Frame(row, bg=SAOColors.CHILD_BG, width=2, height=44)
        indicator.pack(side=tk.LEFT, fill=tk.Y)
        indicator.pack_propagate(False)

        icon_lbl = tk.Label(row, text=item.get('icon', ''),
                    bg=SAOColors.CHILD_BG, fg=SAOColors.CHILD_ICON,
                            font=_sao_font(12))
        icon_lbl.pack(side=tk.LEFT, padx=(8, 5))

        text_lbl = tk.Label(row, text=item.get('label', ''),
                    bg=SAOColors.CHILD_BG, fg=SAOColors.CHILD_TEXT,
                            font=_cjk_font(10), anchor='w')
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 右侧箭头 (hover 时显示)
        arrow_lbl = tk.Label(row, text='›', bg=SAOColors.CHILD_BG, fg=SAOColors.CHILD_BG,
                             font=('Consolas', 14))
        arrow_lbl.pack(side=tk.RIGHT, padx=(0, 8))

        # 平滑悬停过渡
        _anim = Animator(row)
        _hover_state = {'t': 0.0}
        fade_bg = self.cget('bg') or '#010101'

        def _apply_row_visual(bg: str, fg: str, icon_fg: str,
                              ind_color: str, arr_fg: str):
            last = getattr(outer, '_visual_colors', None)
            current = (bg, fg, icon_fg, ind_color, arr_fg)
            if last == current:
                return
            if last is None or last[0] != bg:
                row.configure(bg=bg)
                icon_lbl.configure(bg=bg)
                text_lbl.configure(bg=bg)
                arrow_lbl.configure(bg=bg)
            if last is None or last[1] != fg:
                text_lbl.configure(fg=fg)
            if last is None or last[2] != icon_fg:
                icon_lbl.configure(fg=icon_fg)
            if last is None or last[3] != ind_color:
                indicator.configure(bg=ind_color)
            if last is None or last[4] != arr_fg:
                arrow_lbl.configure(fg=arr_fg)
            outer._visual_colors = current

        def _update_hover(t, r=row, il=icon_lbl, tl=text_lbl,
                          ind=indicator, arr=arrow_lbl):
            _hover_state['t'] = t
            if self._gpu_managed:
                self._dispatch_gpu_paint()
                return
            bg, fg, icon_fg, ind_color, arr_fg = _CY_UI.popup_child_hover_palette(
                t,
                SAOColors.CHILD_BG, SAOColors.CHILD_HOVER,
                SAOColors.CHILD_TEXT, SAOColors.CHILD_HOVER_FG,
                SAOColors.CHILD_ICON, SAOColors.ACTIVE_BORDER,
            )
            _apply_row_visual(bg, fg, icon_fg, ind_color, arr_fg)

        def _apply_fade_visual(fade_t, r=row, il=icon_lbl, tl=text_lbl,
                               ind=indicator, arr=arrow_lbl):
            fade_t = max(0.0, min(1.0, fade_t))
            if self._gpu_managed:
                # GPU path: fade is global to the bar (handled by
                # _apply_line_arrow_fade which already dispatched).
                # We only need to keep _hover_state coherent — no-op.
                return
            ht = _hover_state['t']
            bg, fg, icon_fg, ind_color, arr_fg = _CY_UI.popup_child_fade_palette(
                ht, fade_t, fade_bg,
                SAOColors.CHILD_BG, SAOColors.CHILD_HOVER,
                SAOColors.CHILD_TEXT, SAOColors.CHILD_HOVER_FG,
                SAOColors.CHILD_ICON, SAOColors.ACTIVE_BORDER,
            )
            _apply_row_visual(bg, fg, icon_fg, ind_color, arr_fg)

        def enter(e, a=_anim):
            a.animate('hover', 150, lambda t: _update_hover(t))
            try:
                from utils.sao_sound import play_sound as _ps
                _ps('click', volume=0.3)
            except Exception:
                pass

        def leave(e, a=_anim, hs=_hover_state):
            start = hs['t']
            a.animate('hover', 200, lambda t: _update_hover(lerp(start, 0, t)))

        for widget in [outer, row, icon_lbl, text_lbl, indicator, arrow_lbl]:
            widget.bind('<Enter>', enter)
            widget.bind('<Leave>', leave)
            cmd = item.get('command')
            if cmd:
                row_label = getattr(outer, '_label_text', '')

                def _click_with_sound(e, c=cmd, label=row_label):
                    try:
                        from utils.sao_sound import play_sound as _ps
                        _ps('click', volume=0.5)
                    except Exception:
                        pass
                    _phase_trace('menu.child.row.schedule', label)
                    try:
                        self.after_idle(
                            lambda cb=c, row_name=label:
                            (_phase_trace('menu.child.row.cb', row_name), cb())
                        )
                    except Exception:
                        c()
                widget.bind('<Button-1>', _click_with_sound)

        # 入场动画: 从右侧滑入
        outer._apply_fade_visual = _apply_fade_visual
        outer._row_start_w = 88
        outer._hover_state = _hover_state
        # For GPU interactive dispatch (click_through windows don't deliver to
        # the Tk rows in this app): fire/hover this row by index.
        outer._command = item.get('command')
        outer._enter_fn = enter
        outer._leave_fn = leave
        outer._icon_text = item.get('icon', '') or ''
        outer._label_text = item.get('label', '') or ''
        outer._anim_row_w = outer._row_start_w
        outer._visual_colors = None
        row.configure(width=outer._row_start_w)

        return outer

    # ── v2.3.0 Phase 3+++: GPU painter wiring ─────────────────────
    def _setup_gpu_painter(self):
        if ChildBarGpuPainter is None:
            raise RuntimeError('ChildBarGpuPainter GPU module is required')
        gpu_child_bar_enabled()
        try:
            top = self.winfo_toplevel()
            self._gpu_painter = ChildBarGpuPainter(
                top,
                click_cb=self._gpu_fire_row,
                hover_cb=self._gpu_hover_row,
                leave_cb=self._gpu_leave_rows,
            )
            if _ChildBarColors is not None:
                self._gpu_colors = _ChildBarColors(
                    SAOColors.CHILD_BG, SAOColors.CHILD_HOVER,
                    SAOColors.CHILD_TEXT, SAOColors.CHILD_HOVER_FG,
                    SAOColors.CHILD_ICON, SAOColors.ACTIVE_BORDER,
                    lerp_color,
                )
            self._gpu_managed = True
            self._gpu_chroma_bg = self.cget('bg') or '#010101'
        except Exception:
            self._gpu_painter = None
            self._gpu_managed = False
            raise

    def _on_destroy(self):
        self._cancel_layout_commit()
        self._stop_row_anim()
        if self._gpu_painter is not None:
            try:
                self._gpu_painter.destroy()
            except Exception:
                pass
            self._gpu_painter = None
        self._gpu_managed = False

    def _gpu_force_chroma(self):
        """Repaint every Tk widget in the bar with chroma-key bg/fg so
        Tk renders nothing visible. Painter draws on top."""
        if not self._gpu_managed:
            return
        chroma = self._gpu_chroma_bg
        wrap = self._content_wrap
        if wrap is None or not wrap.winfo_exists():
            return

        def _walk(w):
            try:
                w.configure(bg=chroma)
            except Exception:
                pass
            if isinstance(w, tk.Label):
                try:
                    w.configure(fg=chroma)
                except Exception:
                    pass
            for child in w.winfo_children():
                _walk(child)

        _walk(wrap)
        # Canvases: force every drawn item to chroma fill so the
        # itemconfigure calls in _apply_line_arrow_fade don't matter.
        if self._line_cv is not None and self._line_cv.winfo_exists():
            for item_id, _base in self._line_item_specs:
                try:
                    self._line_cv.itemconfigure(item_id, fill=chroma)
                except Exception:
                    pass
        if self._arrow_cv is not None and self._arrow_cv.winfo_exists():
            for item_id, _base, channel in self._arrow_item_specs:
                try:
                    self._arrow_cv.itemconfigure(item_id, **{channel: chroma})
                except Exception:
                    pass

    # ── GPU interactive dispatch (called from ChildBarGpuPainter) ──
    def _gpu_fire_row(self, idx: int) -> None:
        """Run row `idx`'s command. The child bar's GPU window captures the
        click directly now (the old click-through + Tk-overlay path didn't
        reach the rows in this app's window z-order, so submenu items were
        dead / clicks fell through)."""
        try:
            if not (0 <= idx < len(self._items)):
                return
            cmd = getattr(self._items[idx], '_command', None)
            if not cmd:
                return
            try:
                from utils.sao_sound import play_sound as _ps
                _ps('click', volume=0.5)
            except Exception:
                pass
            self.after_idle(cmd)
        except Exception:
            pass

    def _gpu_hover_row(self, idx: int) -> None:
        try:
            if idx == self._gpu_hover_idx:
                return
            self._gpu_leave_rows()
            if 0 <= idx < len(self._items):
                fn = getattr(self._items[idx], '_enter_fn', None)
                if fn:
                    fn(None)
                self._gpu_hover_idx = idx
        except Exception:
            pass

    def _gpu_leave_rows(self) -> None:
        try:
            idx = self._gpu_hover_idx
            self._gpu_hover_idx = None
            if idx is not None and 0 <= idx < len(self._items):
                fn = getattr(self._items[idx], '_leave_fn', None)
                if fn:
                    fn(None)
        except Exception:
            pass

    def _dispatch_gpu_paint(self):
        if not self._gpu_managed or self._gpu_painter is None:
            return
        if not self.winfo_exists() or not self._items:
            try:
                self._gpu_painter.clear()
            except Exception:
                pass
            return
        if _ChildBarSnapshot is None or _ChildRowSnapshot is None:
            return
        try:
            wrap = self._content_wrap
            if wrap is None or not wrap.winfo_exists():
                return
            # Read the wrapper's screen origin FRESH every frame. The child bar
            # MOVES when you switch categories (it re-aligns to the clicked
            # circle) and during the open/size animation, so a cached origin goes
            # stale: 1st click positions fine, 2nd click renders at the previous
            # spot. The GPU window only re-geometries on an actual change (see the
            # geom != _last_geom guard), so reading every frame is cheap.
            # _cached_screen_xy is kept ONLY as last-known-good to avoid a 1-frame
            # flash to (0,0) before Tk lays a freshly-created frame out.
            try:
                rx, ry = wrap.winfo_rootx(), wrap.winfo_rooty()
            except Exception:
                return
            if rx > 0 or ry > 0:
                self._cached_screen_xy = (rx, ry)
                sx, sy = rx, ry
            elif self._cached_screen_xy is not None:
                sx, sy = self._cached_screen_xy
            else:
                sx, sy = rx, ry
            line_w = 1
            line_h = 1
            arrow_w = 1
            if self._anim_line_w is not None:
                line_w = max(1, int(self._anim_line_w))
                # line_h is fixed per rebuild; still need it from canvas
                if self._line_cv is not None and self._line_cv.winfo_exists():
                    try:
                        line_h = max(1, int(self._line_cv.cget('height')))
                    except Exception:
                        pass
            elif self._line_cv is not None and self._line_cv.winfo_exists():
                try:
                    line_w = max(1, int(self._line_cv.cget('width')))
                    line_h = max(1, int(self._line_cv.cget('height')))
                except Exception:
                    pass
            if self._anim_arrow_w is not None:
                arrow_w = max(1, int(self._anim_arrow_w))
            elif self._arrow_cv is not None and self._arrow_cv.winfo_exists():
                try:
                    arrow_w = max(1, int(self._arrow_cv.cget('width')))
                except Exception:
                    pass
            rows: List[Any] = []
            for outer in self._items:
                row = getattr(outer, '_row_body', None)
                if row is None or not row.winfo_exists():
                    continue
                anim_w = getattr(outer, '_anim_row_w', None)
                if anim_w is not None:
                    rw = max(1, int(anim_w))
                else:
                    try:
                        rw = max(1, int(row.cget('width')))
                    except Exception:
                        rw = 240
                hs = getattr(outer, '_hover_state', None)
                ht = float(hs['t']) if hs else 0.0
                rows.append(_ChildRowSnapshot(
                    getattr(outer, '_icon_text', ''),
                    getattr(outer, '_label_text', ''),
                    ht, rw,
                ))
            if not rows:
                self._gpu_painter.clear()
                return
            snap = _ChildBarSnapshot(
                line_w=line_w, line_h=line_h, arrow_w=arrow_w,
                fade_t=self._gpu_fade_t,
                rows=rows,
                bg_hex=self._gpu_chroma_bg,
                colors=self._gpu_colors,
            )
            self._gpu_painter.tick(sx, sy, snap)
        except Exception:
            pass


