# -*- coding: utf-8 -*-
"""v2.3.0 Phase 3+ — GPU-presented SAOLeftInfo panel.

Mirrors :mod:`sao_menu_bar_gpu`. The popup's left info panel is two
stacked Canvases (top + bottom) that paint cached PIL plates with an
optional sweep highlight on open / close / sync_pulse.

Entity left-info/player/session visuals are GPU-required. The Tk
Canvases are kept at chroma-key bg with no ``create_image`` so they
stay invisible, and panel plates are composed into BGRA frames on the
heavy ``AsyncFrameWorker`` lane. Presentation goes through
``GpuOverlayWindow``; no Tk visual fallback is selected.
"""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from typing import Any, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

import _sao_cy_uihelpers as _CY_UI  # type: ignore[import-not-found]
from render.overlay_render_worker import AsyncFrameWorker
from utils.perf_probe import probe as _probe
from gui_modules.entity_gpu_policy import require_entity_gpu
from gui_modules.sao_menu_hud import MenuLeftInfoRenderer, PlayerPanelRenderer

try:
    from render import gpu_overlay_window as _gow
except Exception:  # pragma: no cover
    _gow = None  # type: ignore[assignment]

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    from config import FONTS_DIR as _FONTS_DIR
except Exception:
    _FONTS_DIR = os.path.join(_BASE_DIR, 'assets', 'fonts')
_FONT_SAO = os.path.join(_FONTS_DIR, 'SAOUI.ttf')
_FONT_CJK = os.path.join(_FONTS_DIR, 'ZhuZiAYuanJWD.ttf')


def _pil_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, max(6, int(size)))
    except Exception:
        try:
            return ImageFont.truetype('arial.ttf', max(6, int(size)))
        except Exception:
            return ImageFont.load_default()


def gpu_left_info_enabled() -> bool:
    return require_entity_gpu('LeftInfoGpuPainter', _gow)


class _LeftInfoSnapshot:
    """Plain-data carrier built on the Tk thread, consumed on worker."""

    __slots__ = (
        'username', 'description',
        'top_w', 'top_h',
        'bottom_w', 'bottom_h',
        'sweep_phase', 'sweep_strength',
    )

    def __init__(self, username: str, description: str,
                 top_w: int, top_h: int,
                 bottom_w: int, bottom_h: int,
                 sweep_phase: float, sweep_strength: float):
        self.username = str(username)
        self.description = str(description)
        self.top_w = int(top_w)
        self.top_h = int(top_h)
        self.bottom_w = int(bottom_w)
        self.bottom_h = int(bottom_h)
        self.sweep_phase = float(sweep_phase)
        self.sweep_strength = float(sweep_strength)


class LeftInfoGpuPainter:
    """Owns one ``GpuOverlayWindow`` + ``AsyncFrameWorker`` for the
    full left info panel. Top + bottom plates compose into a single
    sprite each tick on the worker."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._render_worker = AsyncFrameWorker(prefer_isolation=True)
        self._renderer = MenuLeftInfoRenderer()
        self._gpu_window: Optional[Any] = None
        self._presenter: Optional[Any] = None
        self._destroyed = False
        self._last_sig: Optional[tuple] = None
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        self._lock = threading.Lock()

    def _ensure_window(self, w: int, h: int, x: int, y: int) -> bool:
        if self._gpu_window is not None:
            return True
        require_entity_gpu('LeftInfoGpuPainter', _gow)
        try:
            pump = _gow.get_glfw_pump(self._root)
            self._presenter = _gow.BgraPresenter()
            self._gpu_window = _gow.GpuOverlayWindow(
                pump,
                w=max(1, int(w)), h=max(1, int(h)),
                x=int(x), y=int(y),
                render_fn=self._presenter.render,
                click_through=True,
                title='sao_left_info_gpu',
            )
            self._gpu_window.show()
            return True
        except Exception as exc:
            self._presenter = None
            self._gpu_window = None
            raise RuntimeError('LeftInfoGpuPainter requires GPU window support') from exc

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        try:
            self._render_worker.stop()
        except Exception:
            pass
        if self._presenter is not None:
            try:
                self._presenter.release()
            except Exception:
                pass
            self._presenter = None
        if self._gpu_window is not None:
            try:
                self._gpu_window.destroy()
            except Exception:
                pass
            self._gpu_window = None

    @_probe.decorate('ui.menu.left_info_gpu_tick')
    def tick(self, screen_x: int, screen_y: int,
             snap: _LeftInfoSnapshot) -> None:
        if self._destroyed:
            return
        # Combined bounding box: both plates are stacked vertically with
        # left-aligned anchor 'nw'; outer width is max of the two,
        # outer height is sum.
        out_w = max(1, snap.top_w, snap.bottom_w)
        out_h = max(1, snap.top_h + snap.bottom_h)
        if not self._ensure_window(out_w, out_h, screen_x, screen_y):
            return

        # 1) Drain previous result and present.
        fb = self._render_worker.take_result(allow_during_capture=True)
        if fb is not None and self._gpu_window is not None and self._presenter is not None:
            try:
                geom = (fb.x, fb.y, fb.width, fb.height)
                if geom != self._last_geom:
                    self._gpu_window.set_geometry(*geom)
                    self._last_geom = geom
                self._presenter.set_frame(fb.bgra_bytes, fb.width, fb.height)
                self._gpu_window.request_redraw()
            except Exception:
                pass

        # 2) Build dedup signature. Quantize sweep params identically
        #    to MenuLeftInfoRenderer's internal cache so we submit one
        #    frame per visually-distinct state.
        sig = _CY_UI.left_info_snapshot_sig(
            snap.username, snap.description,
            snap.top_w, snap.top_h,
            snap.bottom_w, snap.bottom_h,
            snap.sweep_phase, snap.sweep_strength,
        )
        with self._lock:
            if sig == self._last_sig:
                return
            self._last_sig = sig

        # 3) Submit compose. Capture state by value into closure.
        s = snap
        renderer = self._renderer
        out_w_local = out_w
        out_h_local = out_h

        def compose(_now: float) -> Image.Image:
            img = Image.new('RGBA', (out_w_local, out_h_local), (0, 0, 0, 0))
            if s.top_w >= 20 and s.top_h >= 20:
                top = renderer.render_top_pil(
                    s.username, s.top_w, s.top_h,
                    sweep_phase=s.sweep_phase,
                    sweep_strength=s.sweep_strength,
                )
                img.alpha_composite(top, (0, 0))
            if s.bottom_w >= 20 and s.bottom_h >= 15:
                bot = renderer.render_bottom_pil(
                    s.description, s.bottom_w, s.bottom_h,
                    sweep_phase=s.sweep_phase,
                    sweep_strength=s.sweep_strength,
                )
                img.alpha_composite(bot, (0, s.top_h))
            return img

        try:
            self._render_worker.submit(
                compose, time.perf_counter(),
                0, int(screen_x), int(screen_y),
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  Session players GPU painter (sao_gui.SAOSessionPlayersPanel)
# ══════════════════════════════════════════════════════════════════════

def gpu_session_players_enabled() -> bool:
    return require_entity_gpu('SessionPlayersGpuPainter', _gow)


class _SessionPlayersSnapshot:
    __slots__ = (
        'rows', 'total', 'self_uid', 'first_index',
        'w', 'h', 'reveal',
    )

    def __init__(self, rows, total: int, self_uid: str,
                 first_index: int, w: int, h: int, reveal: float = 1.0):
        self.rows = tuple(
            (str(name or '--'), str(uid or '--'), str(power or '--'), bool(is_self))
            for name, uid, power, is_self in (rows or ())
        )
        self.total = max(0, int(total or 0))
        self.self_uid = str(self_uid or '')
        self.first_index = max(0, int(first_index or 0))
        self.w = max(1, int(w or 1))
        self.h = max(1, int(h or 1))
        self.reveal = max(0.0, min(1.0, float(reveal if reveal is not None else 1.0)))


class _SessionPlayersRenderer:
    def __init__(self):
        self._font_title = _pil_font(_FONT_SAO, 17)
        self._font_sao = _pil_font(_FONT_SAO, 12)
        self._font_sao_small = _pil_font(_FONT_SAO, 10)
        self._font_cjk = _pil_font(_FONT_CJK, 13)
        self._font_cjk_bold = _pil_font(_FONT_CJK, 14)
        self._font_cjk_small = _pil_font(_FONT_CJK, 12)
        self._chrome_cache = {}
        self._row_cache = {}

    @staticmethod
    def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
        try:
            box = draw.textbbox((0, 0), str(text), font=font)
            return int(box[2] - box[0])
        except Exception:
            try:
                return int(draw.textlength(str(text), font=font))
            except Exception:
                return len(str(text)) * 8

    def _fit(self, draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
        text = str(text or '--')
        if self._text_w(draw, text, font) <= max_w:
            return text
        ell = '…'
        base = text.strip()
        for n in range(max(0, len(base) - 1), 0, -1):
            candidate = base[:n] + ell
            if self._text_w(draw, candidate, font) <= max_w:
                return candidate
        return ell

    @staticmethod
    def _uses_sao_font(ch: str) -> bool:
        return bool(ch and ch.isascii())

    def _mixed_segments(self, text: str, base_font, sao_font):
        segments = []
        cur = ''
        cur_font = None
        for ch in str(text or ''):
            font = sao_font if self._uses_sao_font(ch) else base_font
            if cur and font is not cur_font:
                segments.append((cur, cur_font))
                cur = ch
            else:
                cur += ch
            cur_font = font
        if cur:
            segments.append((cur, cur_font or base_font))
        return segments

    def _text_w_mixed(self, draw: ImageDraw.ImageDraw, text: str,
                      base_font, sao_font) -> int:
        return sum(
            self._text_w(draw, part, font)
            for part, font in self._mixed_segments(text, base_font, sao_font)
        )

    def _fit_mixed(self, draw: ImageDraw.ImageDraw, text: str,
                   base_font, sao_font, max_w: int) -> str:
        text = str(text or '--')
        if self._text_w_mixed(draw, text, base_font, sao_font) <= max_w:
            return text
        ell = '...'
        base = text.strip()
        for n in range(max(0, len(base) - 1), 0, -1):
            candidate = base[:n] + ell
            if self._text_w_mixed(draw, candidate, base_font, sao_font) <= max_w:
                return candidate
        return ell

    def _draw_mixed(self, draw: ImageDraw.ImageDraw, xy, text: str,
                    base_font, sao_font, fill, anchor: str = '') -> None:
        text = str(text or '')
        x, y = xy
        if anchor and anchor[0] == 'r':
            x -= self._text_w_mixed(draw, text, base_font, sao_font)
        elif anchor and anchor[0] == 'm':
            x -= self._text_w_mixed(draw, text, base_font, sao_font) // 2
        for part, font in self._mixed_segments(text, base_font, sao_font):
            draw.text((x, y), part, fill=fill, font=font)
            x += self._text_w(draw, part, font)

    @staticmethod
    def _alpha(img: Image.Image, value: float) -> Image.Image:
        value = max(0.0, min(1.0, float(value)))
        if value >= 0.999:
            return img
        out = img.copy()
        alpha = out.getchannel('A').point(lambda a: int(a * value))
        out.putalpha(alpha)
        return out

    def render(self, snap: _SessionPlayersSnapshot) -> Image.Image:
        w = snap.w
        h = snap.h
        header_h = 54
        col_h = 28
        body_y = header_h + col_h
        panel = self._chrome(w, h, snap.total, snap.self_uid).copy()
        draw = ImageDraw.Draw(panel)
        gold = (243, 175, 18, 255)
        cyan = (134, 223, 255, 255)

        rows = snap.rows
        if snap.total > 0:
            range_text = f'{snap.first_index + 1:02d}-{min(snap.total, snap.first_index + len(rows)):02d}/{snap.total:02d}'
            draw.text((w - 14, 31), range_text,
                      anchor='ra', fill=(196, 145, 22, 230),
                      font=self._font_sao_small)

        row_h = 36
        row_gap = 4
        row_y = body_y + 5
        row_left = 8
        row_w = max(40, w - row_left - 14)
        if not rows:
            msg1 = '等待抓包识别玩家'
            msg2 = 'No session players yet'
            draw.text((w // 2, body_y + 96), msg1,
                      anchor='mm', fill=(145, 145, 145, 255),
                      font=self._font_cjk)
            draw.text((w // 2, body_y + 120), msg2,
                      anchor='mm', fill=(175, 175, 175, 255),
                      font=self._font_sao_small)
        else:
            for i, (name, uid, power, is_self) in enumerate(rows):
                y = row_y + i * (row_h + row_gap)
                if y + row_h > h - 8:
                    break
                row_img = self._row_sprite(
                    row_w, row_h, name, uid, power, bool(is_self),
                    bool((snap.first_index + i) % 2),
                )
                panel.alpha_composite(row_img, (row_left, y))

        if snap.total > len(rows) and snap.total > 0:
            track_x = w - 7
            track_y1 = body_y + 6
            track_y2 = h - 8
            draw.rectangle((track_x, track_y1, track_x + 2, track_y2),
                           fill=(214, 214, 214, 180))
            visible = max(1, len(rows))
            ratio = min(1.0, visible / max(1, snap.total))
            thumb_h = max(24, int((track_y2 - track_y1) * ratio))
            max_first = max(1, snap.total - visible)
            thumb_y = track_y1 + int((track_y2 - track_y1 - thumb_h) *
                                     (snap.first_index / max_first))
            draw.rectangle((track_x - 1, thumb_y, track_x + 3, thumb_y + thumb_h),
                           fill=(243, 175, 18, 220))

        reveal = max(0.0, min(1.0, snap.reveal))
        if reveal < 0.999:
            offset = int(round(14 * (1.0 - reveal)))
            moved = Image.new('RGBA', panel.size, (0, 0, 0, 0))
            moved.alpha_composite(self._alpha(panel, reveal), (0, offset))
            return moved
        return panel

    def _chrome(self, w: int, h: int, total: int, self_uid: str) -> Image.Image:
        key = (int(w), int(h), int(total), str(self_uid or ''))
        cached = self._chrome_cache.get(key)
        if cached is not None:
            return cached
        header_h = 54
        col_h = 28
        body_y = header_h + col_h
        gold = (243, 175, 18, 255)
        cyan = (134, 223, 255, 255)
        border = (210, 208, 208, 255)
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, w - 1, h - 1), fill=(247, 247, 246, 244), outline=border)
        draw.rectangle((0, 0, w - 1, header_h), fill=(255, 255, 255, 248))
        draw.rectangle((0, header_h, w - 1, body_y), fill=(232, 236, 240, 248))
        draw.rectangle((0, body_y, w - 1, h - 1), fill=(238, 240, 241, 238))
        draw.line((0, header_h, w, header_h), fill=(178, 178, 178, 255), width=1)
        draw.line((0, body_y, w, body_y), fill=(210, 213, 216, 255), width=1)
        draw.rectangle((0, 0, 3, h - 1), fill=(134, 223, 255, 96))
        draw.rectangle((w - 4, 0, w - 1, h - 1), fill=(243, 175, 18, 86))

        bk = 16
        draw.line((2, 2, 2 + bk, 2), fill=cyan, width=1)
        draw.line((2, 2, 2, 2 + bk), fill=cyan, width=1)
        draw.line((w - 2 - bk, 2, w - 2, 2), fill=gold, width=1)
        draw.line((w - 2, 2, w - 2, 2 + bk), fill=gold, width=1)
        draw.line((2, h - 2, 2 + bk, h - 2), fill=cyan, width=1)
        draw.line((2, h - 2 - bk, 2, h - 2), fill=cyan, width=1)
        draw.line((w - 2 - bk, h - 2, w - 2, h - 2), fill=gold, width=1)
        draw.line((w - 2, h - 2 - bk, w - 2, h - 2), fill=gold, width=1)

        draw.text((16, 8), 'SESSION PLAYERS',
                  fill=(91, 91, 94, 255), font=self._font_title)
        summary = f'本次登录出现过 {total} 人'
        if self_uid:
            summary += f' · SELF {self_uid}'
        self._draw_mixed(
            draw, (16, 31),
            self._fit_mixed(draw, summary, self._font_cjk_small,
                            self._font_sao_small, w - 116),
            self._font_cjk_small, self._font_sao_small,
            fill=(150, 150, 150, 255))

        self._draw_mixed(
            draw, (14, header_h + 8), 'NAME',
            self._font_cjk_small, self._font_sao_small,
            fill=(103, 117, 128, 255))
        self._draw_mixed(
            draw, (w - 118, header_h + 8), 'UID',
            self._font_cjk_small, self._font_sao_small,
            fill=(103, 117, 128, 255))
        self._draw_mixed(
            draw, (w - 52, header_h + 8), 'POWER',
            self._font_cjk_small, self._font_sao_small,
            fill=(103, 117, 128, 255))

        if len(self._chrome_cache) > 16:
            self._chrome_cache.clear()
        self._chrome_cache[key] = img
        return img

    def _row_sprite(self, w: int, h: int, name: str, uid: str, power: str,
                    is_self: bool, odd: bool) -> Image.Image:
        key = (w, h, str(name), str(uid), str(power), bool(is_self), bool(odd))
        cached = self._row_cache.get(key)
        if cached is not None:
            return cached
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bg = (255, 250, 240, 255) if is_self else (
            (248, 248, 248, 250) if not odd else (242, 244, 245, 250)
        )
        gold = (243, 175, 18, 255)
        cyan = (134, 223, 255, 255)
        draw.rectangle((0, 0, w - 1, h - 1), fill=bg)
        draw.rectangle((0, 0, 3, h - 1), fill=gold if is_self else cyan)
        if is_self:
            draw.rectangle((4, 0, w - 1, h - 1), outline=(243, 175, 18, 84), width=1)
            draw.ellipse((9, 14, 13, 18), fill=gold)
        name_font = self._font_cjk_bold if is_self else self._font_cjk
        name_text = self._fit_mixed(
            draw, str(name or '--'), name_font, self._font_sao_small,
            max(58, w - 150))
        self._draw_mixed(
            draw, (18 if is_self else 12, 9), name_text,
            name_font, self._font_sao_small,
            fill=(61, 73, 84, 255))
        draw.text((w - 106, 11),
                  self._fit(draw, str(uid or '--'), self._font_sao_small, 60),
                  fill=(126, 142, 156, 255), font=self._font_sao_small)
        draw.text((w - 6, 10),
                  self._fit(draw, str(power or '--'), self._font_sao, 70),
                  anchor='ra',
                  fill=(217, 152, 14, 255) if is_self else (96, 105, 112, 255),
                  font=self._font_sao)
        if len(self._row_cache) > 192:
            self._row_cache.clear()
        self._row_cache[key] = img
        return img


class SessionPlayersGpuPainter:
    """GPU-presented, worker-composited player list for the left menu column."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._render_worker = AsyncFrameWorker(prefer_isolation=True)
        self._renderer = _SessionPlayersRenderer()
        self._gpu_window: Optional[Any] = None
        self._presenter: Optional[Any] = None
        self._destroyed = False
        self._last_sig: Optional[tuple] = None
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        self._lock = threading.Lock()
        self._create_lock = threading.Lock()
        self._creating = False

    def warmup(self, w: int, h: int, x: int = 0, y: int = 0) -> None:
        """Create the hidden GLFW window off the Tk hot path."""
        if self._destroyed or self._gpu_window is not None or self._creating:
            return
        try:
            self._ensure_window(w, h, x, y, allow_async=True)
        except Exception:
            pass

    def _ensure_window(self, w: int, h: int, x: int, y: int,
                       allow_async: bool = False) -> bool:
        if self._gpu_window is not None:
            return True
        require_entity_gpu('SessionPlayersGpuPainter', _gow)
        if not self._create_lock.acquire(blocking=False):
            return False
        self._creating = True
        try:
            pump = _gow.get_glfw_pump(self._root)
            self._presenter = _gow.BgraPresenter()
            self._gpu_window = _gow.GpuOverlayWindow(
                pump,
                w=max(1, int(w)), h=max(1, int(h)),
                x=int(x), y=int(y),
                render_fn=self._presenter.render,
                click_through=True,
                title='sao_session_players_gpu',
            )
            self._gpu_window.show(async_create=allow_async)
            return True
        except Exception as exc:
            self._presenter = None
            self._gpu_window = None
            raise RuntimeError('SessionPlayersGpuPainter requires GPU window support') from exc
        finally:
            self._creating = False
            try:
                self._create_lock.release()
            except Exception:
                pass

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        try:
            self._render_worker.stop()
        except Exception:
            pass
        if self._presenter is not None:
            try:
                self._presenter.release()
            except Exception:
                pass
            self._presenter = None
        if self._gpu_window is not None:
            try:
                self._gpu_window.destroy()
            except Exception:
                pass
            self._gpu_window = None

    def hide(self) -> None:
        self._last_sig = None
        try:
            self._render_worker.reset()
        except Exception:
            pass
        if self._gpu_window is not None:
            try:
                self._gpu_window.hide()
            except Exception:
                pass

    def show(self) -> None:
        if self._gpu_window is not None:
            try:
                self._gpu_window.show(async_create=True)
            except Exception:
                pass

    @_probe.decorate('ui.menu.session_players_gpu_tick')
    def tick(self, screen_x: int, screen_y: int,
             snap: '_SessionPlayersSnapshot') -> None:
        if self._destroyed:
            return
        out_w = max(1, snap.w)
        out_h = max(1, snap.h)
        if not self._ensure_window(out_w, out_h, screen_x, screen_y,
                                   allow_async=True):
            return
        self.show()

        fb = self._render_worker.take_result(allow_during_capture=True)
        if fb is not None and self._gpu_window is not None and self._presenter is not None:
            try:
                geom = (fb.x, fb.y, fb.width, fb.height)
                if geom != self._last_geom:
                    self._gpu_window.set_geometry(*geom)
                    self._last_geom = geom
                self._presenter.set_frame(fb.bgra_bytes, fb.width, fb.height)
                self._gpu_window.request_redraw()
            except Exception:
                pass

        sig = _CY_UI.session_players_snapshot_sig(
            snap.rows, snap.total, snap.self_uid, snap.first_index,
            snap.w, snap.h, snap.reveal,
        )
        with self._lock:
            if sig == self._last_sig:
                return
            self._last_sig = sig

        s = snap
        renderer = self._renderer

        def compose(_now: float) -> Image.Image:
            return renderer.render(s)

        try:
            self._render_worker.submit(
                compose, time.perf_counter(),
                0, int(screen_x), int(screen_y),
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  SAOPlayerPanel GPU painter (Phase 3++ — sao_gui.SAOPlayerPanel)
# ══════════════════════════════════════════════════════════════════════

def gpu_player_panel_enabled() -> bool:
    """Player panel requires the shared Entity GPU backend."""
    return require_entity_gpu('PlayerPanelGpuPainter', _gow)


class _PlayerPanelSnapshot:
    """Plain-data carrier built on the Tk thread, consumed on worker."""

    __slots__ = (
        'username', 'level', 'level_extra', 'season_exp',
        'hp', 'sta', 'shift_mode',
        'top_w', 'top_h', 'bottom_w', 'bottom_h',
        'scan_phase',
    )

    def __init__(self, username, level, level_extra, season_exp, hp, sta,
                 shift_mode, top_w, top_h, bottom_w, bottom_h, scan_phase):
        self.username = str(username)
        self.level = int(level)
        self.level_extra = int(level_extra)
        self.season_exp = int(season_exp)
        self.hp = (int(hp[0]), int(hp[1]))
        self.sta = (int(sta[0]), int(sta[1]))
        self.shift_mode = str(shift_mode or '普通模式')
        self.top_w = int(top_w)
        self.top_h = int(top_h)
        self.bottom_w = int(bottom_w)
        self.bottom_h = int(bottom_h)
        self.scan_phase = float(scan_phase)


class PlayerPanelGpuPainter:
    """Owns one ``GpuOverlayWindow`` + ``AsyncFrameWorker`` for the
    full SAOPlayerPanel (user / level / EXP / HP / STA / shift_mode).
    Top + bottom plates compose into one sprite each tick on the worker.

    GPU-required painter for ``SAOPlayerPanel``.
    """

    def __init__(self, root: tk.Tk):
        self._root = root
        self._render_worker = AsyncFrameWorker(prefer_isolation=True)
        self._renderer = PlayerPanelRenderer()
        self._gpu_window: Optional[Any] = None
        self._presenter: Optional[Any] = None
        self._destroyed = False
        self._last_sig: Optional[tuple] = None
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        self._lock = threading.Lock()
        self._create_lock = threading.Lock()
        self._creating = False

    def warmup(self, w: int, h: int, x: int = 0, y: int = 0) -> None:
        """Create the hidden GLFW window before the menu animation needs it."""
        if self._destroyed or self._gpu_window is not None or self._creating:
            return
        try:
            self._ensure_window(w, h, x, y, allow_async=True)
        except Exception:
            pass

    def _ensure_window(self, w: int, h: int, x: int, y: int,
                       allow_async: bool = False) -> bool:
        if self._gpu_window is not None:
            return True
        require_entity_gpu('PlayerPanelGpuPainter', _gow)
        if not self._create_lock.acquire(blocking=False):
            return False
        self._creating = True
        try:
            pump = _gow.get_glfw_pump(self._root)
            self._presenter = _gow.BgraPresenter()
            self._gpu_window = _gow.GpuOverlayWindow(
                pump,
                w=max(1, int(w)), h=max(1, int(h)),
                x=int(x), y=int(y),
                render_fn=self._presenter.render,
                click_through=True,
                title='sao_player_panel_gpu',
            )
            self._gpu_window.show(async_create=allow_async)
            return True
        except Exception as exc:
            self._presenter = None
            self._gpu_window = None
            raise RuntimeError('PlayerPanelGpuPainter requires GPU window support') from exc
        finally:
            self._creating = False
            try:
                self._create_lock.release()
            except Exception:
                pass

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        try:
            self._render_worker.stop()
        except Exception:
            pass
        if self._presenter is not None:
            try:
                self._presenter.release()
            except Exception:
                pass
            self._presenter = None
        if self._gpu_window is not None:
            try:
                self._gpu_window.destroy()
            except Exception:
                pass
            self._gpu_window = None

    def hide(self) -> None:
        if self._gpu_window is not None:
            try:
                self._gpu_window.hide()
            except Exception:
                pass

    def show(self) -> None:
        if self._gpu_window is not None:
            try:
                self._gpu_window.show(async_create=True)
            except Exception:
                pass

    @_probe.decorate('ui.menu.player_panel_gpu_tick')
    def tick(self, screen_x: int, screen_y: int,
             snap: '_PlayerPanelSnapshot') -> None:
        if self._destroyed:
            return
        out_w = max(1, snap.top_w, snap.bottom_w)
        out_h = max(1, snap.top_h + snap.bottom_h)
        if not self._ensure_window(out_w, out_h, screen_x, screen_y,
                                   allow_async=True):
            return

        # 1) Drain previous result and present.
        fb = self._render_worker.take_result(allow_during_capture=True)
        if (fb is not None and self._gpu_window is not None
                and self._presenter is not None):
            try:
                geom = (fb.x, fb.y, fb.width, fb.height)
                if geom != self._last_geom:
                    self._gpu_window.set_geometry(*geom)
                    self._last_geom = geom
                self._presenter.set_frame(fb.bgra_bytes, fb.width, fb.height)
                self._gpu_window.request_redraw()
            except Exception:
                pass

        # 2) Dedup signature. Quantize scan_phase only when the rail
        #    is visible (top_h > 185); static otherwise.
        sig = _CY_UI.player_panel_snapshot_sig(
            snap.username, snap.level, snap.level_extra, snap.season_exp,
            snap.hp, snap.sta, snap.shift_mode,
            snap.top_w, snap.top_h, snap.bottom_w, snap.bottom_h,
            snap.scan_phase, out_w, out_h,
        )
        with self._lock:
            if sig == self._last_sig:
                return
            self._last_sig = sig

        # 3) Submit compose. Capture state by value into closure.
        s = snap
        renderer = self._renderer
        out_w_l = out_w
        out_h_l = out_h
        # Signature slot 11 stores the quantized scan phase so the
        # compose path reuses the exact dedup granularity.
        scan_phase_l = float(sig[11])

        def compose(_now: float) -> Image.Image:
            img = Image.new('RGBA', (out_w_l, out_h_l), (0, 0, 0, 0))
            if s.top_w >= 40 and s.top_h >= 20:
                top = renderer.render_top_pil(
                    s.username, s.level, s.level_extra, s.season_exp,
                    s.hp, s.sta, s.top_w, s.top_h,
                    scan_phase=scan_phase_l,
                )
                img.alpha_composite(top, (0, 0))
            if s.bottom_w >= 40 and s.bottom_h >= 15:
                bot = renderer.render_bottom_pil(
                    s.shift_mode, s.bottom_w, s.bottom_h,
                )
                img.alpha_composite(bot, (0, s.top_h))
            return img

        try:
            self._render_worker.submit(
                compose, time.perf_counter(),
                0, int(screen_x), int(screen_y),
            )
        except Exception:
            pass
