"""GpuOverlayWindow — Phase 2 (v2.3.0) overlay infrastructure.

Provides a borderless transparent always-on-top click-through GLFW window
that hosts a moderngl context. Designed as a drop-in alternative to the
``tk.Toplevel`` + ``UpdateLayeredWindow`` (ULW) presentation path used by
SkillFX / HP / BossHP today.

Why bother:
- ULW costs ~1-2 ms per commit (BGRA premultiply roundtrip + Win32 GDI
  copy of the entire bitmap). For a panel that's already on the GPU
  (SkillFX SDF, BossHP burst), that's a wasted GPU→CPU→GPU bounce; a
  GLFW window with ``TRANSPARENT_FRAMEBUFFER`` lets the DWM compositor
  pull the framebuffer directly.
- Cleanly separates "compose" (worker thread) from "present" (Tk main
  thread): the present cost drops to a texture upload + one shader draw
  + ``swap_buffers``.

Constraints:
- GLFW init / window create / poll_events / swap_buffers must all run
    on the same thread. We pin everything to the Tk main thread by
    driving ``glfw.poll_events`` from a ``root.after`` pump and demanding
    callers schedule render from the same thread.
- Master-gated via ``config.USE_GPU_OVERLAY`` only.
    Callers may temporarily suspend *window creation* during startup
    animations (for example LinkStart) via
    ``suspend_gpu_overlay_creation()`` / ``resume_gpu_overlay_creation()``.
- Each window owns its own moderngl context; resource sharing across
    windows is a Phase 2c concern (atlas, shared blur kernel).

Public API:
    glfw_supported() -> bool
    get_glfw_pump(root: tk.Misc) -> GlfwPump
    GpuOverlayWindow(pump, w, h, x, y, render_fn=None, click_through=True)
        .show() / .hide() / .destroy()
        .set_geometry(x, y, w, h)
        .set_render_fn(fn)  # fn(ctx: moderngl.Context, t: float) -> None
        .request_redraw()   # mark dirty; will render on next pump tick
        .ctx                # moderngl.Context (lazy)
"""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Callable, Dict, List, Optional

try:
    from utils.perf_probe import phase as _phase_trace  # type: ignore
    from utils.perf_probe import gauge as _perf_gauge  # type: ignore
except Exception:  # pragma: no cover
    def _phase_trace(_name: str, _detail: str = '') -> None:  # type: ignore
        return
    def _perf_gauge(_name: str, _value: float) -> None:  # type: ignore
        return


# Set to True from popup so the next pump tick emits per-line markers.
# Auto-resets after one tick. Kept module-global so it can be toggled
# without touching any class instance.
_trace_pump_armed = False
_trace_pump_remaining_ticks = 0


def arm_pump_trace() -> None:
    """Arm one-shot fine-grained tracing for the next pump tick."""
    global _trace_pump_armed, _trace_pump_remaining_ticks
    _trace_pump_armed = True
    _trace_pump_remaining_ticks = 8


# ─── Win32 hwnd-filtered message pump ────────────────────────────
# CRITICAL: glfw.poll_events() on Windows calls
# ``PeekMessage(NULL, NULL, 0, 0, PM_REMOVE)`` in a loop. Passing
# NULL for the hwnd filter drains EVERY message destined for ANY
# window owned by the current thread — including Tk's window handles.
# DispatchMessage then routes those messages to Tk's WndProc, which
# fires queued ``after()`` / ``WM_TIMER`` callbacks INSIDE the GLFW
# message-pump call. Because our pump tick is itself driven by Tk's
# ``root.after(N, _tick)``, the next ``_tick`` reentrantly executes
# inside the current tick's poll_events. Reentrant ``_tick`` →
# reentrant ``moderngl`` context switching + reentrant
# ``glfw.poll_events`` → tstate corruption →
#   Fatal Python error: PyEval_RestoreThread: ... GIL is released,
#   the current Python thread state is NULL
# at the next Tcl checkpoint inside ``mainloop``.
#
# We replace ``glfw.poll_events()`` with a pump that calls
# ``PeekMessage(hwnd, ...)`` for ONLY our GLFW window handles, so
# Tk's WM_TIMER messages stay queued and only fire in Tk's own
# mainloop iteration between our ``after`` ticks.
class _PUMP_MSG(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('message', wintypes.UINT),
        ('wParam', wintypes.WPARAM),
        ('lParam', wintypes.LPARAM),
        ('time', wintypes.DWORD),
        ('pt_x', wintypes.LONG),
        ('pt_y', wintypes.LONG),
    ]


_PM_REMOVE = 0x0001
try:
    _u32 = ctypes.windll.user32  # type: ignore[attr-defined]
    _PeekMessageW = _u32.PeekMessageW
    _PeekMessageW.argtypes = [ctypes.POINTER(_PUMP_MSG), wintypes.HWND,
                              wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _PeekMessageW.restype = wintypes.BOOL
    _TranslateMessage = _u32.TranslateMessage
    _TranslateMessage.argtypes = [ctypes.POINTER(_PUMP_MSG)]
    _TranslateMessage.restype = wintypes.BOOL
    _DispatchMessageW = _u32.DispatchMessageW
    _DispatchMessageW.argtypes = [ctypes.POINTER(_PUMP_MSG)]
    _DispatchMessageW.restype = ctypes.c_long
    _WIN32_PUMP_AVAILABLE = True
except Exception:  # pragma: no cover - non-Windows build
    _WIN32_PUMP_AVAILABLE = False


def _pump_glfw_messages(hwnds: List[int]) -> None:
    """Drain pending Win32 messages ONLY for the given GLFW HWNDs.

    Runs at most 64 messages per hwnd to bound work per tick.
    Falls back to ``glfw.poll_events()`` if PeekMessage isn't
    available (non-Windows test runs).
    """
    if not _WIN32_PUMP_AVAILABLE or _glfw is None:
        try:
            _glfw.poll_events()  # type: ignore[union-attr]
        except Exception:
            pass
        return
    msg = _PUMP_MSG()
    armed_local = _trace_pump_armed
    for hwnd in hwnds:
        if not hwnd:
            continue
        hwnd_w = wintypes.HWND(hwnd)
        # 64 messages per hwnd is plenty: GLFW posts at most a few
        # input messages per frame per window.
        for _ in range(64):
            if not _PeekMessageW(ctypes.byref(msg), hwnd_w, 0, 0, _PM_REMOVE):
                break
            if armed_local or _trace_pump_armed:
                _phase_trace(
                    'gow.pump.peek.dispatch',
                    f'hwnd={int(msg.hwnd) if msg.hwnd else 0} msg=0x{msg.message:04X} wp={int(msg.wParam)} lp={int(msg.lParam)}',
                )
            _TranslateMessage(ctypes.byref(msg))
            _DispatchMessageW(ctypes.byref(msg))
            if armed_local or _trace_pump_armed:
                _phase_trace(
                    'gow.pump.peek.done',
                    f'hwnd={int(msg.hwnd) if msg.hwnd else 0} msg=0x{msg.message:04X}',
                )
    # Also drain thread messages (hwnd == NULL in queue, posted via
    # PostThreadMessage) by passing -1 as the hwnd filter — but ONLY
    # if absolutely necessary. GLFW doesn't use thread messages, so
    # we skip this entirely to avoid pulling Tk's queue.


# Lazy imports — keep module import cost zero when GPU overlay disabled.
_glfw = None  # type: ignore[assignment]
_moderngl = None  # type: ignore[assignment]
_import_error: Optional[str] = None


def _try_imports() -> bool:
    """Import glfw + moderngl on first use. Returns True on success."""
    global _glfw, _moderngl, _import_error
    if _glfw is not None and _moderngl is not None:
        return True
    if _import_error is not None:
        return False
    try:
        import glfw as _g  # type: ignore[import-not-found]
        import moderngl as _m  # type: ignore[import-not-found]
    except Exception as exc:
        _import_error = f'{type(exc).__name__}: {exc}'
        return False
    _glfw = _g
    _moderngl = _m
    return True


def glfw_supported() -> bool:
    """True if GPU overlay path is available AND opted in.

    Default-ON in v2.3.0 (2026-04 fix). Environment variables do not
    disable the GPU overlay path; startup animations rely on this window
    being created whenever GLFW/ModernGL are available.
    """
    try:
        from config import USE_GPU_OVERLAY  # type: ignore
        if not USE_GPU_OVERLAY:
            return False
    except Exception:
        pass
    if sys.platform != 'win32':
        return False
    return _try_imports()


# ── Win32 ex-style helpers (click-through reinforcement) ───────────────────
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

if sys.platform == 'win32':
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    _user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4


def _apply_click_through(hwnd: int) -> None:
    """Belt-and-suspenders: GLFW 3.4 ``MOUSE_PASSTHROUGH`` already sets
    ``WS_EX_TRANSPARENT`` on Windows, but some drivers/DWM configs miss
    the layered-attributes call. Re-apply explicitly so DWM treats the
    framebuffer alpha as the per-pixel mask."""
    if sys.platform != 'win32':
        return
    cur = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = (cur | WS_EX_LAYERED | WS_EX_TRANSPARENT
           | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE)
    _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    _user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def _apply_interactive(hwnd: int) -> None:
    if sys.platform != 'win32':
        return
    cur = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = ((cur | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
           & ~WS_EX_TRANSPARENT & ~WS_EX_NOACTIVATE)
    _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    _user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


_overlay_creation_lock = threading.Lock()
_overlay_creation_suspended = 0


def suspend_gpu_overlay_creation() -> None:
    """Temporarily block new GLFW overlay windows from being created.

    Existing windows keep rendering; only *new* window creation is
    deferred. Used to keep startup animations such as LinkStart from
    paying GLFW/ModernGL init cost on the Tk main thread.
    """
    global _overlay_creation_suspended
    with _overlay_creation_lock:
        _overlay_creation_suspended += 1


def resume_gpu_overlay_creation() -> None:
    """Release one startup-time creation block."""
    global _overlay_creation_suspended
    with _overlay_creation_lock:
        if _overlay_creation_suspended > 0:
            _overlay_creation_suspended -= 1


def gpu_overlay_creation_allowed() -> bool:
    """True when new GLFW overlay windows may be created."""
    with _overlay_creation_lock:
        return _overlay_creation_suspended <= 0


def _show_no_activate(hwnd: int) -> None:
    if sys.platform != 'win32' or not hwnd:
        return
    _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    _user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


# ── GlfwPump ────────────────────────────────────────────────────────────────
class _PumpCmd:
    """Command queued from any thread to be executed on the pump thread.

    The pump thread drains its command queue between poll_events and
    render. Commands carry a callable (with bound args) and an optional
    Event for blocking callers; result/exception are stored on the
    instance so the caller can re-raise after wait().
    """
    __slots__ = ('fn', 'done', 'result', 'exc')

    def __init__(self, fn: Callable[[], Any], blocking: bool):
        self.fn = fn
        self.done: Optional[threading.Event] = (
            threading.Event() if blocking else None)
        self.result: Any = None
        self.exc: Optional[BaseException] = None


class GlfwPump:
    """Dedicated GLFW pump running on its own thread (v2.3.14).

    Previously the pump was driven by ``root.after`` on the Tk main
    thread, which meant every GL upload + render + swap_buffers for N
    visible overlay windows was serialized on the same thread that
    runs the SAO scheduler, HP STA tween, SkillFX scheduler tick, etc.
    Heavy multi-panel combat scenes blocked Tk for tens of milliseconds
    per frame.
    
    v2.3.14: pump now owns a single ``threading.Thread`` that:
    - calls ``glfw.init()`` from this thread (required: WGL contexts
      have thread affinity)
    - drains a ``queue.Queue`` of commands (window create/destroy/
      geometry/show/hide/input-callback installation) so all GLFW calls
      happen on this same thread
    - pumps Win32 messages for all GLFW hwnds + renders dirty windows
    - sleeps on a ``threading.Event`` (``_wake``) when idle so
      ``request_redraw`` from any thread reacts immediately

    Tk main thread → pump: enqueue commands via ``exec_on_pump`` /
    fire-and-forget via ``post_cmd``.
    Pump → Tk main thread: marshal user callbacks via ``post_to_tk``
    (uses ``root.after(0, fn)``).
    """

    def __init__(self, root: Any):
        self._root = root
        self._lock = threading.Lock()
        self._windows: List['GpuOverlayWindow'] = []
        self._tick_hz = 60
        self._tick_ms = max(1, int(round(1000.0 / self._tick_hz)))
        self._idle_ms = 60
        self._t0 = time.perf_counter()
        self._inited = False
        # Thread + sync primitives.
        self._thread: Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._cmd_q: 'queue.Queue[_PumpCmd]' = queue.Queue()
        self._running = False
        self._stopping = False
        # Tk-side dispatch queue (v2.3.14): pump → Tk callbacks via
        # ``post_to_tk`` are appended here and drained by
        # ``_drain_tk_q`` running under Tk's after loop. Direct
        # ``root.after(0, ...)`` from a non-Tk thread is NOT
        # thread-safe (Tcl_Eval re-entrancy → fast crash).
        self._tk_q: 'queue.Queue[Callable[[], Any]]' = queue.Queue()
        self._tk_poller_id: Optional[str] = None
        self._tk_poller_ms = 8  # ~125 Hz dispatch latency
        self._start_tk_poller()

    # ── Thread lifecycle ────────────────────────────────────────────
    def _start_thread(self) -> None:
        """Lazy-start the pump thread. Idempotent + thread-safe."""
        if self._running:
            return
        with self._lock:
            if self._running:
                return
            if self._stopping:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run, name='GlfwPump', daemon=True)
            self._thread.start()

    def _ensure_init(self) -> None:
        """Initialize GLFW. MUST be called from the pump thread."""
        if self._inited:
            return
        if not _try_imports():
            raise RuntimeError(
                f'glfw/moderngl unavailable: {_import_error}')
        if not _glfw.init():  # type: ignore[union-attr]
            raise RuntimeError('glfw.init() failed')
        self._refresh_tick_hz_from_monitor()
        self._inited = True

    def _refresh_tick_hz_from_monitor(self) -> None:
        """Use the primary monitor refresh rate for animated GPU windows."""
        hz = 60
        try:
            monitor = _glfw.get_primary_monitor()  # type: ignore[union-attr]
            mode = _glfw.get_video_mode(monitor) if monitor else None  # type: ignore[union-attr]
            raw_hz = int(getattr(mode, 'refresh_rate', 0) or 0) if mode else 0
            if 30 <= raw_hz <= 360:
                hz = raw_hz
        except Exception:
            hz = 60
        self._tick_hz = hz
        self._tick_ms = max(1, int(round(1000.0 / float(hz))))

    # ── Command marshaling (Tk → pump) ─────────────────────────────
    def exec_on_pump(self, fn: Callable[[], Any], timeout: float = 5.0) -> Any:
        """Run ``fn`` on the pump thread, blocking the caller until
        completion or timeout. Re-raises any exception ``fn`` produced.
        Safe from any thread, including the pump thread itself (in
        which case ``fn`` is invoked inline).
        """
        if threading.current_thread() is self._thread:
            return fn()
        self._start_thread()
        cmd = _PumpCmd(fn, blocking=True)
        self._cmd_q.put(cmd)
        self._wake.set()
        if not cmd.done.wait(timeout):  # type: ignore[union-attr]
            raise TimeoutError(f'pump cmd timed out after {timeout}s')
        if cmd.exc is not None:
            raise cmd.exc
        return cmd.result

    def post_cmd(self, fn: Callable[[], Any]) -> None:
        """Fire-and-forget: queue ``fn`` to run on the pump thread."""
        if threading.current_thread() is self._thread:
            try:
                fn()
            except Exception:
                pass
            return
        self._start_thread()
        cmd = _PumpCmd(fn, blocking=False)
        self._cmd_q.put(cmd)
        self._wake.set()

    def post_to_tk(self, fn: Callable[[], Any]) -> None:
        """Marshal ``fn`` to the Tk main thread.

        Pushes onto a thread-safe queue drained by ``_drain_tk_q``
        running under Tk's ``after`` loop. Direct ``root.after(0, fn)``
        from a non-Tk thread is NOT thread-safe (Tcl interp Eval is
        single-threaded; cross-thread calls cause hard crashes / NULL
        tstate). Latency: ``_tk_poller_ms`` (~8ms typical).
        """
        self._tk_q.put(fn)

    def _start_tk_poller(self) -> None:
        """Schedule the Tk-main-thread queue drainer. Idempotent.
        MUST be called from the Tk thread (it is — pump __init__ runs
        on Tk thread via ``get_glfw_pump``)."""
        if self._tk_poller_id is not None:
            return
        try:
            self._tk_poller_id = self._root.after(
                self._tk_poller_ms, self._drain_tk_q)
        except Exception:
            self._tk_poller_id = None

    def _drain_tk_q(self) -> None:
        """Run all pending Tk callbacks queued by ``post_to_tk``.
        Bounded per tick so a callback storm cannot starve other Tk
        events."""
        self._tk_poller_id = None
        for _ in range(64):
            try:
                fn = self._tk_q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        if not self._stopping:
            try:
                self._tk_poller_id = self._root.after(
                    self._tk_poller_ms, self._drain_tk_q)
            except Exception:
                self._tk_poller_id = None

    # ── Window registry ────────────────────────────────────────────
    def register(self, win: 'GpuOverlayWindow') -> None:
        with self._lock:
            if win not in self._windows:
                self._windows.append(win)
        self._wake.set()
        self._start_thread()

    def unregister(self, win: 'GpuOverlayWindow') -> None:
        with self._lock:
            try:
                self._windows.remove(win)
            except ValueError:
                pass
        self._wake.set()

    def kick_redraw(self) -> None:
        """Wake the pump immediately so a freshly marked-dirty window
        is rendered on the next loop iteration. Safe from any thread.
        """
        self._wake.set()

    # ── Pump loop body ─────────────────────────────────────────────
    def _drain_commands(self) -> None:
        """Run all queued commands on the pump thread."""
        while True:
            try:
                cmd = self._cmd_q.get_nowait()
            except queue.Empty:
                return
            try:
                cmd.result = cmd.fn()
            except BaseException as exc:  # noqa: BLE001 - propagate verbatim
                cmd.exc = exc
            if cmd.done is not None:
                cmd.done.set()

    def _run(self) -> None:
        """Pump thread entry point."""
        try:
            self._ensure_init()
        except Exception:
            self._running = False
            return
        while self._running:
            # Drain any pending commands (window create/destroy/etc.).
            self._drain_commands()
            global _trace_pump_armed, _trace_pump_remaining_ticks
            if _trace_pump_remaining_ticks > 0:
                _trace_pump_armed = True
                _trace_pump_remaining_ticks -= 1
            armed_at_start = _trace_pump_armed
            if armed_at_start:
                _phase_trace('gow.pump.poll.begin',
                             f'remaining={_trace_pump_remaining_ticks}')
            with self._lock:
                hwnds_for_pump = [w._hwnd for w in self._windows
                                  if w._hwnd and w._visible]
            try:
                _pump_glfw_messages(hwnds_for_pump)
            except Exception:
                pass
            armed = _trace_pump_armed
            if armed or armed_at_start:
                _phase_trace('gow.pump.poll.end',
                             f'armed={int(armed)} start={int(armed_at_start)}')
            cb_fired_this_tick = (not armed_at_start) and armed
            now = time.perf_counter()
            t = now - self._t0
            with self._lock:
                wins = list(self._windows)
            any_visible = False
            any_dirty = False
            any_vsync_dirty = False
            for w in wins:
                if not w._visible:
                    continue
                any_visible = True
                if w._dirty:
                    any_dirty = True
                    if getattr(w, '_vsync', False):
                        any_vsync_dirty = True
                if armed:
                    _phase_trace(
                        'gow.pump.render.begin',
                        f'hwnd={getattr(w, "_hwnd", 0)} '
                        f'dirty={int(bool(w._dirty))}',
                    )
                # Pump owns the WGL context but worker threads may have
                # private moderngl contexts; serialize against them.
                try:
                    _rt0 = time.perf_counter()
                    with _wgl_serialize_lock:
                        w._render_once(t)
                    _perf_gauge('gow.window.render_ms',
                                (time.perf_counter() - _rt0) * 1000.0)
                except Exception:
                    pass
                if armed:
                    _phase_trace(
                        'gow.pump.render.end',
                        f'hwnd={getattr(w, "_hwnd", 0)}',
                    )
            if armed:
                _phase_trace('gow.pump.tick.end')
                if _trace_pump_remaining_ticks <= 0:
                    _trace_pump_armed = False
            if armed_at_start or cb_fired_this_tick or armed:
                _phase_trace('gow.pump.lock.released')
            # Wait for next tick (or wake) — animating panels run at
            # tick_hz, idle pumps at ~16 Hz.
            target_ms = self._tick_ms if any_dirty else self._idle_ms
            if any_vsync_dirty:
                # swap_buffers(vsync=1) already waits for the monitor.
                # Do not sleep another software frame or a fullscreen
                # animation falls to half refresh rate.
                target_ms = 1
            if not any_visible:
                # Nobody to draw — long idle until a register/wake.
                target_ms = 250
            elapsed_ms = (time.perf_counter() - now) * 1000.0
            wait_s = max(0.001, (target_ms - elapsed_ms) / 1000.0)
            self._wake.wait(timeout=wait_s)
            self._wake.clear()
        # Loop exited — drain any pending commands so blocking callers
        # don't hang during shutdown, then terminate GLFW.
        self._drain_commands()
        if self._inited:
            try:
                _glfw.terminate()  # type: ignore[union-attr]
            except Exception:
                pass
            self._inited = False

    def shutdown(self) -> None:
        """Stop the pump thread and tear down all windows.

        Must be called from a thread other than the pump thread (e.g.
        Tk main during application shutdown). Marshals destruction of
        every registered window onto the pump thread first, then signals
        the pump to exit and joins.
        """
        self._stopping = True
        # Cancel Tk-side poller (we're on Tk main during shutdown).
        if self._tk_poller_id is not None:
            try:
                self._root.after_cancel(self._tk_poller_id)
            except Exception:
                pass
            self._tk_poller_id = None
        with self._lock:
            wins = list(self._windows)
            self._windows.clear()
        for w in wins:
            try:
                w.destroy()
            except Exception:
                pass
        self._running = False
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass
        self._thread = None


_pump_lock = threading.Lock()
_pump: Optional[GlfwPump] = None

# ── WGL driver serialization ────────────────────────────────────────────────
# Process-wide RLock that any thread doing native WGL/moderngl work must
# acquire briefly. Required to keep worker threads with their own moderngl
# context (e.g. fisheye standalone context, gpu_renderer worker GL blocks)
# from racing the main-thread GLFW pump's poll_events / make_context_current /
# swap_buffers / set_window_pos / set_window_size ctypes calls.
#
# All those calls release the GIL via Py_BEGIN_ALLOW_THREADS. When two
# threads issue concurrent GIL-released WGL ops on the same GPU driver,
# Windows GL drivers corrupt the Py_END_ALLOW_THREADS thread-state
# restoration on the main thread, producing:
#     Fatal Python error: PyEval_RestoreThread: ... GIL is released
#     (the current Python thread state is NULL)
# RLock so the pump's _tick (poll_events) and per-window _render_once
# (make_context_current/swap_buffers) can both nest safely.
_wgl_serialize_lock = threading.RLock()


def get_wgl_serialize_lock() -> threading.RLock:
    """Return the process-wide WGL/moderngl serialization RLock.

    Worker threads owning a private moderngl context (e.g. fisheye
    full-screen overlay worker, gpu_renderer worker GL blocks) must
    acquire this lock around every block of GL calls they issue, so
    the main-thread GLFW pump cannot race them on the WGL driver.
    """
    return _wgl_serialize_lock


def get_glfw_pump(root: Any) -> GlfwPump:
    """Singleton pump bound to the Tk root. First call must pass root."""
    global _pump
    with _pump_lock:
        if _pump is None:
            _pump = GlfwPump(root)
        return _pump


# ── GpuOverlayWindow ────────────────────────────────────────────────────────
class GpuOverlayWindow:
    """Borderless transparent click-through GLFW window.

    Lifecycle:
      ow = GpuOverlayWindow(pump, w=800, h=200, x=100, y=100)
      ow.set_render_fn(lambda ctx, t: ...)   # required before show()
      ow.show()
      ...
      ow.set_geometry(x, y, w, h)
      ow.hide()
      ow.destroy()

    Threading: ALL methods must be called from the Tk main thread (same
    thread that owns the pump). ``request_redraw()`` is safe to call
    from any thread (just sets a flag).
    """

    def __init__(self, pump: GlfwPump, w: int, h: int,
                 x: int = 100, y: int = 100,
                 render_fn: Optional[Callable[[Any, float], None]] = None,
                 click_through: bool = True,
                 title: str = 'sao_overlay',
                 vsync: bool = False):
        self._pump = pump
        self._w = max(1, int(w))
        self._h = max(1, int(h))
        self._x = int(x)
        self._y = int(y)
        self._render_fn = render_fn
        self._click_through = bool(click_through)
        self._title = title
        self._vsync = bool(vsync)
        self._win = None  # GLFW window handle
        self._ctx: Any = None  # moderngl.Context
        self._hwnd = 0
        self._visible = False
        self._dirty = True
        self._rendering = False
        self._redraw_requested_during_render = False
        self._created = False
        self._create_pending = False
        self._shown = False
        self._show_pending = False
        self._cursor_pos_fn: Optional[Callable[[float, float], None]] = None
        self._cursor_leave_fn: Optional[Callable[[], None]] = None
        self._mouse_button_fn: Optional[
            Callable[[int, int, int, float, float], None]] = None
        self._scroll_fn: Optional[Callable[[float, float], None]] = None

    # ---- lifecycle ----

    def _create(self) -> None:
        """Marshal window creation to the pump thread (v2.3.14).

        All GLFW calls have thread affinity to the pump thread; this
        method blocks the caller until creation completes (or raises).
        Safe to call from Tk main; if already on pump thread, runs
        inline.
        """
        if self._created:
            return
        if self._create_pending:
            try:
                self._pump.exec_on_pump(lambda: None, timeout=10.0)
            except Exception:
                pass
            if self._created:
                return
        if not gpu_overlay_creation_allowed():
            raise RuntimeError('gpu overlay creation suspended')
        self._pump.exec_on_pump(self._create_on_pump, timeout=10.0)

    def prepare_async(self) -> bool:
        """Queue window creation on the pump thread without blocking.

        The window stays hidden until a frame is staged and the normal
        render path shows it. This is used to prewarm GPU panels before
        the first visible menu interaction needs them.
        """
        if self._created or self._create_pending:
            return True
        if not gpu_overlay_creation_allowed():
            return False
        self._create_pending = True

        def _run() -> None:
            try:
                self._create_on_pump()
            except Exception:
                pass
            finally:
                self._create_pending = False

        try:
            self._pump.post_cmd(_run)
            return True
        except Exception:
            self._create_pending = False
            return False

    def _create_on_pump(self) -> None:
        """Pump-thread half of _create. Wraps WGC pause/resume around
        the GIL-releasing ctypes calls so the WGC pyo3 callback can't
        race ``_PyThreadState_Current``."""
        if self._created:
            return
        self._pump._ensure_init()
        # ============================================================
        # WGC pyo3 race avoidance — pause for the WHOLE _create() body.
        # ============================================================
        # Every GLFW / WGL / moderngl call below goes through ctypes
        # (pyglfw + moderngl both use ctypes.CDLL), which RELEASES the
        # Python GIL for the duration of the foreign call.  The biggest
        # offenders are:
        #   * glfw.create_window  → wglCreateContext (100–500 ms first time)
        #   * moderngl.create_context() → GL driver init, shader cache,
        #     program object setup (tens of ms)
        #   * glfw.make_context_current → wglMakeCurrent
        # During ANY of those GIL-released windows the windows_capture
        # pyo3 callback thread can fire.  Due to a pyo3
        # ``assume_gil_acquired()`` corner case the callback thread
        # sometimes runs with ``_PyThreadState_Current == NULL`` — the
        # very next ``Py_BEGIN_ALLOW_THREADS`` checkpoint then aborts
        # with "PyEval_RestoreThread: NULL tstate" (fatal).
        try:
            from render import gpu_capture as _gc
        except Exception:
            _gc = None  # type: ignore[assignment]
        if _gc is not None:
            try:
                _gc.pause_capture()
            except Exception:
                pass
        try:
            self._create_inner()
        finally:
            if _gc is not None:
                try:
                    _gc.resume_capture()
                except Exception:
                    pass

    def _create_inner(self) -> None:
        glfw = _glfw
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)  # type: ignore[union-attr]
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)  # type: ignore[union-attr]
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)  # type: ignore[union-attr]
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)  # type: ignore[union-attr]
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)  # type: ignore[union-attr]
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)  # type: ignore[union-attr]
        glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)  # type: ignore[union-attr]
        glfw.window_hint(glfw.SAMPLES, 0)  # type: ignore[union-attr]
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)  # type: ignore[union-attr]
        if self._click_through:
            try:
                glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)  # type: ignore[union-attr]
            except Exception:
                # Older GLFW (<3.4): fall back to Win32 ex-style only.
                pass
        else:
            # CRITICAL: glfw.window_hint() values are sticky across
            # create_window() calls. If a previous click_through=True
            # window (e.g. fisheye / HP / DPS panel) set
            # MOUSE_PASSTHROUGH=TRUE, that hint persists until we
            # explicitly clear it. Without this reset, an interactive
            # window (popup / saomenu) created AFTER any click-through
            # window inherits MOUSE_PASSTHROUGH and silently swallows
            # all clicks (they pass through to the window below). This
            # caused "second saomenu open can't be clicked" once the
            # fisheye GLFW window had been instantiated.
            try:
                glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.FALSE)  # type: ignore[union-attr]
            except Exception:
                pass
        win = glfw.create_window(  # type: ignore[union-attr]
            self._w, self._h, self._title, None, None)
        if not win:
            raise RuntimeError('glfw.create_window failed for GpuOverlayWindow')
        glfw.set_window_pos(win, self._x, self._y)  # type: ignore[union-attr]
        glfw.make_context_current(win)  # type: ignore[union-attr]
        # Default overlays keep swap_interval(0) to avoid blocking the
        # pump on every panel. Full-screen LinkStart can opt into vsync
        # so DWM/display refresh paces the animation instead of a fixed
        # software 60Hz cap.
        glfw.swap_interval(1 if self._vsync else 0)  # type: ignore[union-attr]

        if sys.platform == 'win32':
            try:
                self._hwnd = int(glfw.get_win32_window(win) or 0)  # type: ignore[union-attr]
                if self._click_through and self._hwnd:
                    _apply_click_through(self._hwnd)
                elif self._hwnd:
                    _apply_interactive(self._hwnd)
            except Exception:
                pass

        self._ctx = _moderngl.create_context()  # type: ignore[union-attr]
        self._ctx.enable(_moderngl.BLEND)  # type: ignore[union-attr]
        # Render targets must output PREMULTIPLIED alpha for DWM.
        self._ctx.blend_func = (
            _moderngl.ONE, _moderngl.ONE_MINUS_SRC_ALPHA)  # type: ignore[union-attr]

        self._win = win
        self._created = True
        self._install_input_callbacks()

    def show(self, async_create: bool = False) -> None:
        if not self._created:
            if async_create:
                if not self.prepare_async():
                    return
            else:
                self._create()
        if self._win is None and not async_create:
            return
        self._visible = True
        self._show_pending = True
        self._shown = False
        # Hidden-first: don't render/show until the caller actually
        # stages a frame and calls request_redraw(). This avoids a
        # blank transparent GLFW window flashing into existence and
        # removes focus churn during menu open.
        self._dirty = False
        self._pump.register(self)

    def hide(self) -> None:
        self._visible = False
        self._show_pending = False
        self._shown = False
        if self._win is not None:
            win = self._win
            self._pump.post_cmd(lambda: self._safe_hide_window(win))
        self._pump.unregister(self)

    @staticmethod
    def _safe_hide_window(win: Any) -> None:
        try:
            _glfw.hide_window(win)  # type: ignore[union-attr]
        except Exception:
            pass

    def destroy(self) -> None:
        self._visible = False
        self._show_pending = False
        self._shown = False
        self._pump.unregister(self)
        if self._win is None:
            return
        # Marshal teardown to pump thread; it owns the GL context.
        try:
            self._pump.exec_on_pump(self._destroy_on_pump, timeout=5.0)
        except Exception:
            # Best-effort: drop refs so GC can reclaim.
            self._win = None
            self._hwnd = 0
            self._created = False
            self._ctx = None

    def _destroy_on_pump(self) -> None:
        if self._win is None:
            return
        with _wgl_serialize_lock:
            try:
                _glfw.make_context_current(self._win)  # type: ignore[union-attr]
            except Exception:
                pass
            if self._ctx is not None:
                try:
                    self._ctx.release()
                except Exception:
                    pass
                self._ctx = None
            try:
                _glfw.make_context_current(None)  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                _glfw.destroy_window(self._win)  # type: ignore[union-attr]
            except Exception:
                pass
        self._win = None
        self._hwnd = 0
        self._created = False

    # ---- mutators ----

    def set_geometry(self, x: int, y: int, w: int, h: int) -> None:
        self._x, self._y = int(x), int(y)
        nw, nh = max(1, int(w)), max(1, int(h))
        size_changed = (nw, nh) != (self._w, self._h)
        self._w, self._h = nw, nh
        win = self._win
        if win is not None:
            new_x, new_y, new_w, new_h = self._x, self._y, self._w, self._h

            def _apply() -> None:
                try:
                    _glfw.set_window_pos(win, new_x, new_y)  # type: ignore[union-attr]
                    if size_changed:
                        _glfw.set_window_size(win, new_w, new_h)  # type: ignore[union-attr]
                except Exception:
                    pass
            self._pump.post_cmd(_apply)
        self._dirty = True

    def set_click_through(self, click_through: bool) -> None:
        """Toggle WS_EX_TRANSPARENT (mouse pass-through) at runtime so
        a panel that has faded to alpha=0 can stop swallowing clicks
        meant for the game window underneath, then start receiving
        them again on fade-in.

        v3.0.3: apply the Win32 ex-style change synchronously from the
        calling (Tk) thread — ``SetWindowLongPtrW`` is thread-safe and
        the previous pump-marshalled path could let a fade_in/fade_out
        toggle race with the pump's command queue, leaving the second
        hide pulse visible-but-faded and still grabbing clicks.
        ``GLFW_MOUSE_PASSTHROUGH`` still has thread affinity to the
        pump, so only that attribute call is queued, fire-and-forget,
        purely to keep GLFW's internal mirror of the ex-style in sync
        for the next focus/activation event.

        v3.0.4: this method previously lived (by accident) on
        ``BgraPresenter``, which has no ``_win``/``_hwnd``/``_pump``.
        ``DpsOverlay._gpu_window`` is a ``GpuOverlayWindow``, so the call
        raised ``AttributeError`` (swallowed by the caller) and the
        faded-out panel never actually became click-through — it kept
        eating clicks meant for the game. It belongs here.
        """
        click = bool(click_through)
        self._click_through = click
        win = self._win
        hwnd = self._hwnd
        if not hwnd:
            return

        # Fast path: Win32 ex-style toggle, synchronous, thread-safe.
        try:
            if click:
                _apply_click_through(hwnd)
            else:
                _apply_interactive(hwnd)
        except Exception:
            pass

        # Belt: keep GLFW's MOUSE_PASSTHROUGH attribute mirrored so
        # GLFW does not re-clear our WS_EX_TRANSPARENT on the next
        # focus/activation event it processes on the pump thread.
        if win is None or _glfw is None:
            return
        attr = getattr(_glfw, 'MOUSE_PASSTHROUGH', None)
        if attr is None:
            return

        glfw_value = _glfw.TRUE if click else _glfw.FALSE  # type: ignore[union-attr]

        def _set_attrib_on_pump() -> None:
            try:
                _glfw.set_window_attrib(win, attr, glfw_value)  # type: ignore[union-attr]
            except Exception:
                pass

        try:
            self._pump.post_cmd(_set_attrib_on_pump)
        except Exception:
            pass

    def set_render_fn(self, fn: Callable[[Any, float], None]) -> None:
        self._render_fn = fn
        self._dirty = True

    def set_input_callbacks(
            self,
            cursor_pos_fn: Optional[Callable[[float, float], None]] = None,
            cursor_leave_fn: Optional[Callable[[], None]] = None,
            mouse_button_fn: Optional[
                Callable[[int, int, int, float, float], None]] = None,
            scroll_fn: Optional[Callable[[float, float], None]] = None) -> None:
        """Attach optional GLFW input callbacks.

        Used by interactive GPU overlays such as the SAO menu bar. The
        GLFW callbacks fire on the pump thread and are marshaled to
        the Tk main thread before user code runs (see ``_on_*`` below).
        """
        self._cursor_pos_fn = cursor_pos_fn
        self._cursor_leave_fn = cursor_leave_fn
        self._mouse_button_fn = mouse_button_fn
        self._scroll_fn = scroll_fn
        if self._win is not None:
            self._pump.post_cmd(self._install_input_callbacks)

    def request_redraw(self) -> None:
        """Thread-safe: mark dirty so next pump tick draws even if the
        scheduler has been throttling idle frames."""
        if getattr(self, '_rendering', False):
            self._redraw_requested_during_render = True
        self._dirty = True
        try:
            self._pump.kick_redraw()
        except Exception:
            pass

    def _install_input_callbacks(self) -> None:
        if self._win is None or _glfw is None:
            return
        try:
            _glfw.set_cursor_pos_callback(self._win, self._on_cursor_pos)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            _glfw.set_cursor_enter_callback(self._win, self._on_cursor_enter)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            _glfw.set_mouse_button_callback(self._win, self._on_mouse_button)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            _glfw.set_scroll_callback(self._win, self._on_scroll)  # type: ignore[union-attr]
        except Exception:
            pass

    def _cursor_pos(self) -> tuple[float, float]:
        if self._win is None or _glfw is None:
            return (0.0, 0.0)
        try:
            x, y = _glfw.get_cursor_pos(self._win)  # type: ignore[union-attr]
            return (float(x), float(y))
        except Exception:
            return (0.0, 0.0)

    def _on_cursor_pos(self, _win, x: float, y: float) -> None:
        cb = self._cursor_pos_fn
        if cb is None:
            return
        if _trace_pump_armed:
            _phase_trace('gow.cursor.pos.begin', f'hwnd={self._hwnd} x={x:.0f} y={y:.0f}')
        # Marshal to Tk main: cb may touch tk widgets.
        fx, fy = float(x), float(y)
        self._pump.post_to_tk(lambda: cb(fx, fy))
        if _trace_pump_armed:
            _phase_trace('gow.cursor.pos.end', f'hwnd={self._hwnd}')

    def _on_cursor_enter(self, _win, entered: bool) -> None:
        if _trace_pump_armed:
            _phase_trace('gow.cursor.enter', f'hwnd={self._hwnd} entered={int(bool(entered))}')
        if entered:
            return
        cb = self._cursor_leave_fn
        if cb is None:
            return
        self._pump.post_to_tk(cb)

    def _on_mouse_button(self, _win, button: int, action: int, mods: int) -> None:
        cb = self._mouse_button_fn
        if cb is None:
            return
        # _cursor_pos() calls _glfw.get_cursor_pos — must run on pump
        # thread, which is exactly where this callback already fires.
        x, y = self._cursor_pos()
        global _trace_pump_armed, _trace_pump_remaining_ticks
        _trace_pump_armed = True
        _trace_pump_remaining_ticks = 6
        _phase_trace(
            'gow.mouse.cb.begin',
            f'hwnd={self._hwnd} btn={button} act={action} x={x:.1f} y={y:.1f}',
        )
        b, a, m = int(button), int(action), int(mods)
        # Marshal to Tk main: user click handlers touch widgets.
        self._pump.post_to_tk(lambda: cb(b, a, m, x, y))
        _phase_trace('gow.mouse.cb.return', f'hwnd={self._hwnd}')

    def _on_scroll(self, _win, xoff: float, yoff: float) -> None:
        if _trace_pump_armed:
            _phase_trace('gow.scroll', f'hwnd={self._hwnd} x={xoff:.2f} y={yoff:.2f}')
        cb = self._scroll_fn
        if cb is None:
            return
        fx, fy = float(xoff), float(yoff)
        self._pump.post_to_tk(lambda: cb(fx, fy))

    # ---- internal ----

    def _render_once(self, t: float) -> None:
        if self._win is None or self._ctx is None or self._render_fn is None:
            return
        # v2.3.0: dirty-gate. Double-buffered GL keeps showing the last
        # swapped frame indefinitely under DWM, so we can skip the entire
        # make-current → clear → render → swap chain whenever nothing
        # changed. Painters call request_redraw() (which sets _dirty=True)
        # whenever they have a new bitmap to upload.
        if not self._dirty:
            return
        glfw = _glfw
        armed = _trace_pump_armed
        try:
            if armed:
                _phase_trace('gow.render.makecur', f'hwnd={self._hwnd}')
            glfw.make_context_current(self._win)  # type: ignore[union-attr]
        except Exception:
            return
        ctx = self._ctx
        try:
            self._rendering = True
            self._redraw_requested_during_render = False
            if armed:
                _phase_trace('gow.render.use', f'hwnd={self._hwnd}')
            ctx.screen.use()
            ctx.viewport = (0, 0, self._w, self._h)
            # Always clear to fully transparent before user draws so old
            # frame doesn't bleed through under DWM transparency.
            if armed:
                _phase_trace('gow.render.clear', f'hwnd={self._hwnd}')
            ctx.clear(0.0, 0.0, 0.0, 0.0)
            if armed:
                _phase_trace('gow.render.fn.begin', f'hwnd={self._hwnd}')
            self._render_fn(ctx, t)
            if armed:
                _phase_trace('gow.render.fn.end', f'hwnd={self._hwnd}')
            rendered = True
        except Exception:
            rendered = False
        finally:
            self._rendering = False
        try:
            if armed:
                _phase_trace('gow.render.swap', f'hwnd={self._hwnd}')
            glfw.swap_buffers(self._win)  # type: ignore[union-attr]
        except Exception:
            rendered = False
        if rendered and self._show_pending and not self._shown:
            try:
                if sys.platform == 'win32' and self._hwnd:
                    _show_no_activate(self._hwnd)
                else:
                    glfw.show_window(self._win)  # type: ignore[union-attr]
                self._shown = True
                self._show_pending = False
            except Exception:
                pass
        self._dirty = bool(getattr(self, '_redraw_requested_during_render', False))
        self._redraw_requested_during_render = False


# ── BgraPresenter ───────────────────────────────────────────────────────────
# Helper that turns a GpuOverlayWindow into a "present already-composed
# BGRA bytes" surface. The compose worker still produces premultiplied
# BGRA bytes (same as the ULW path); we just upload them to a moderngl
# texture and draw a fullscreen quad. Zero visual change vs ULW —
# this is purely a presentation-layer swap that eliminates the per-frame
# Win32 GDI bitmap copy.
#
# Texture format note: moderngl's RGBA8 texture sampled as ``texture(...)``
# returns the bytes in (R, G, B, A) order. Our worker emits BGRA, so the
# fragment shader swizzles ``c.bgra`` to recover (R, G, B, A). The bytes
# are already premultiplied so we leave them as-is.

_BGRA_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    // Flip Y: BGRA buffer is top-down (matches Windows DIB), but GL
    // sampling has bottom-left origin. Map UV vertically to get
    // pixel-perfect orientation without any CPU-side flipud.
    v_uv = vec2(in_pos.x * 0.5 + 0.5,
                1.0 - (in_pos.y * 0.5 + 0.5));
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_BGRA_FS = """
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D u_tex;
uniform float u_alpha;
void main() {
    vec4 c = texture(u_tex, v_uv);
    // Bytes packed as BGRA — swizzle to (R, G, B, A). Already premult.
    // u_alpha (default 1.0) lets callers fade the whole frame without
    // re-premultiplying the BGRA bytes on every frame.
    fragColor = c.bgra * u_alpha;
}
"""


class BgraPresenter:
    """Owns the texture+VAO+program needed to blit a BGRA-bytes buffer
    onto a GpuOverlayWindow as a fullscreen quad.

    Usage:
        presenter = BgraPresenter()
        win = GpuOverlayWindow(pump, w, h, x, y,
                                render_fn=presenter.render,
                                click_through=True)
        win.show()
        ...
        # Each frame, on Tk main thread:
        presenter.set_frame(bgra_bytes, w, h)
        win.request_redraw()

    The presenter reuses its texture across frames as long as (w, h)
    doesn't change; resizes trigger a single texture realloc. Safe to
    share one presenter across windows of the same size, but the
    common case is one presenter per window.
    """

    def __init__(self) -> None:
        self._prog = None
        self._vbo = None
        self._vao = None
        self._tex = None
        self._tex_w = 0
        self._tex_h = 0
        self._frame_bytes: Optional[bytes] = None
        self._frame_w = 0
        self._frame_h = 0
        self._dirty = False
        self._alpha = 1.0
        # v2.3.12: id of the bytes object last uploaded to the GPU texture.
        # Used to dedup glTexSubImage2D when alpha-only ticks trigger a
        # redraw without changing frame content.
        self._last_uploaded_id = 0
        self._frame_dirty_id = 0
        # v2.3.13: pump-driven time-based fade. Eliminates Tk after(16)
        # for fade animation — the GLFW pump (which runs independently
        # of Tk's main after queue) drives alpha smoothly even when
        # main thread is busy. Set with start_fade(); render() computes
        # alpha based on perf_counter elapsed.
        self._fade_active = False
        self._fade_t0 = 0.0
        self._fade_dur = 0.0
        self._fade_from = 1.0
        self._fade_to = 1.0
        self._fade_done_cb: Optional[Callable[[], None]] = None

    def start_fade(self, target_alpha: float, duration_s: float,
                   on_done: Optional[Callable[[], None]] = None) -> None:
        """Begin a time-based fade from current alpha to ``target_alpha``
        over ``duration_s``. Driven by ``render`` (pump) timestamps so it
        stays smooth even if Tk is busy. Cancels any previous fade.
        """
        self._fade_from = float(self._alpha)
        self._fade_to = max(0.0, min(1.0, float(target_alpha)))
        self._fade_dur = max(0.001, float(duration_s))
        self._fade_t0 = time.perf_counter()
        self._fade_active = True
        self._fade_done_cb = on_done
        # Mark dirty so pump renders next tick.
        self._dirty = True

    def is_fading(self) -> bool:
        return self._fade_active

    def set_alpha(self, alpha: float) -> None:
        """Optional global alpha multiplier (0..1) applied during
        ``render``. Default 1.0 = no change. Used for cheap fades
        without re-premultiplying the staged BGRA bytes."""
        self._fade_active = False  # cancel any in-flight fade
        self._alpha = max(0.0, min(1.0, float(alpha)))

    def set_frame(self, bgra: bytes, w: int, h: int) -> None:
        """Stage a frame for the next render. Cheap (just stores refs).

        Safe to call from any thread, but typically called from the
        same thread as ``render`` (Tk main).
        """
        # v2.3.12: only mark dirty if the frame actually changed.
        # This prevents alpha-only fade ticks (which also call
        # request_redraw) from re-uploading identical bytes.
        prev_id = id(self._frame_bytes) if self._frame_bytes is not None else 0
        new_id = id(bgra) if bgra is not None else 0
        self._frame_bytes = bgra
        self._frame_w = int(w)
        self._frame_h = int(h)
        if new_id != prev_id:
            self._frame_dirty_id = new_id
        self._dirty = True

    def clear(self) -> None:
        """Stage a transparent frame (drops the cached bytes; next
        ``render`` will just clear to (0,0,0,0))."""
        self._frame_bytes = None
        self._dirty = True

    def render(self, ctx: Any, _t: float) -> None:
        """``GpuOverlayWindow`` render_fn. Uploads + draws latest frame.

        Called on the Tk main thread (pump thread). Cheap when no new
        frame is pending: just re-draws the existing texture.
        """
        if _moderngl is None:
            return
        # v2.3.13: pump-driven fade. Compute alpha from elapsed time.
        if self._fade_active:
            elapsed = time.perf_counter() - self._fade_t0
            if elapsed >= self._fade_dur:
                self._alpha = self._fade_to
                self._fade_active = False
                cb = self._fade_done_cb
                self._fade_done_cb = None
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
            else:
                k = elapsed / self._fade_dur
                self._alpha = self._fade_from + (self._fade_to - self._fade_from) * k
                # Keep dirty so pump re-renders next tick to advance fade.
                self._dirty = True
        bgra = self._frame_bytes
        w = self._frame_w
        h = self._frame_h
        if self._prog is None:
            self._prog = ctx.program(
                vertex_shader=_BGRA_VS, fragment_shader=_BGRA_FS)
            self._prog['u_tex'].value = 0
            try:
                self._prog['u_alpha'].value = 1.0
            except Exception:
                pass
            import numpy as _np
            quad = _np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
            self._vbo = ctx.buffer(quad.tobytes())
            self._vao = ctx.vertex_array(
                self._prog, [(self._vbo, '2f', 'in_pos')])
        try:
            self._prog['u_alpha'].value = float(self._alpha)
        except Exception:
            pass
        if bgra is not None and w > 0 and h > 0:
            if self._tex is None or self._tex_w != w or self._tex_h != h:
                if self._tex is not None:
                    try:
                        self._tex.release()
                    except Exception:
                        pass
                self._tex = ctx.texture((w, h), 4, bgra)
                self._tex_w = w
                self._tex_h = h
                self._last_uploaded_id = id(bgra)
            else:
                # v2.3.12: skip glTexSubImage2D upload when the same
                # bytes object is already on the GPU. Alpha-only ticks
                # (fisheye fade, menu fade) re-render but keep frame
                # identity, saving ~200–800 KB CPU→GPU copy per panel.
                cur_id = id(bgra)
                if cur_id != getattr(self, '_last_uploaded_id', 0):
                    try:
                        self._tex.write(bgra)
                        self._last_uploaded_id = cur_id
                    except Exception:
                        try:
                            self._tex.release()
                        except Exception:
                            pass
                        self._tex = ctx.texture((w, h), 4, bgra)
                        self._tex_w = w
                        self._tex_h = h
                        self._last_uploaded_id = cur_id
            self._tex.use(location=0)
            self._vao.render(_moderngl.TRIANGLE_STRIP)  # type: ignore[union-attr]
        # If no frame staged: ctx.clear in GpuOverlayWindow already
        # produced a fully transparent frame; nothing to draw.
        self._dirty = False

    def release(self) -> None:
        for obj_name in ('_tex', '_vao', '_vbo', '_prog'):
            obj = getattr(self, obj_name, None)
            if obj is None:
                continue
            try:
                obj.release()
            except Exception:
                pass
            setattr(self, obj_name, None)
        self._frame_bytes = None

