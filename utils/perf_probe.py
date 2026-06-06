"""perf_probe.py — Lightweight per-section profiler for sao_auto.

Goals
-----
* Zero (or near-zero) cost when disabled.
* Pure Python / stdlib only — safe to ship via PyInstaller.
* Drop-in instrumentation for hot paths via context manager or decorator.
* Periodic dump of count / p50 / p95 / p99 / max wall-time and (when
  available) per-section thread-CPU time, plus optional backlog gauges.

Activation
----------
Disabled by default. 

The instrumentation call sites stay in the code permanently; they collapse
to a couple of attribute checks when the probe is disabled.

Usage
-----
    from utils.perf_probe import probe, gauge

    with probe('parser.process_packet'):
        ...

    @probe.decorate('boss.on_damage_event')
    def on_damage_event(self, event): ...

    gauge('parser.delta_batch_size', len(batch))

The dump runs on a daemon thread; it is started lazily on first use.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Callable, Deque, Dict, List, Optional, Tuple, TypeVar

# ── config (read lazily from settings.json on first use) ─────────────────────
# Keys recognised in settings.json:
#   perf_probe_enabled   : bool   (default false)
#   perf_probe_dump_sec  : float  (default 5.0)
#   perf_probe_window    : int    (default 4096)
#   perf_probe_log       : str    (default "" → stdout)
#   perf_probe_phase_window : int (default 512)
#   perf_probe_phase_immediate : bool (default false)
#   perf_probe_phase_log  : str    (default perf_probe_log)
#   perf_probe_faulthandler_log : str (default "" = disabled)

_ENABLED: Optional[bool] = None   # None = not yet loaded
_DUMP_SEC: float = 5.0
_WINDOW: int = 4096
_LOG_PATH: str = ''
_PHASE_WINDOW: int = 512
_PHASE_IMMEDIATE = False
_PHASE_LOG_PATH: str = ''
_FAULT_LOG_PATH: str = ''


def _load_config() -> None:
    """Lazy one-time read from SettingsManager (config.py / settings.json).

    Deferred import avoids circular-import issues because perf_probe.py is
    imported by packet_parser and other modules that themselves import config.
    Calling this on first probe/gauge use instead of at module load time keeps
    the import graph clean.
    """
    global _ENABLED, _DUMP_SEC, _WINDOW, _LOG_PATH, _PHASE_WINDOW
    global _PHASE_IMMEDIATE, _PHASE_LOG_PATH, _FAULT_LOG_PATH
    if _ENABLED is not None:
        return
    try:
        from config import SettingsManager  # noqa: PLC0415
        _sm = SettingsManager()
        _ENABLED = bool(_sm.get('perf_probe_enabled', False))
        try:
            _DUMP_SEC = max(1.0, float(_sm.get('perf_probe_dump_sec', 5.0) or 5.0))
        except (TypeError, ValueError):
            _DUMP_SEC = 5.0
        try:
            _WINDOW = max(64, int(_sm.get('perf_probe_window', 4096) or 4096))
        except (TypeError, ValueError):
            _WINDOW = 4096
        _LOG_PATH = str(_sm.get('perf_probe_log', '') or '')
        try:
            _PHASE_WINDOW = max(
                64,
                int(_sm.get('perf_probe_phase_window', 512) or 512),
            )
        except (TypeError, ValueError):
            _PHASE_WINDOW = 512
        _PHASE_IMMEDIATE = bool(_sm.get('perf_probe_phase_immediate', False))
        _PHASE_LOG_PATH = str(_sm.get('perf_probe_phase_log', '') or '')
        if not _PHASE_LOG_PATH:
            _PHASE_LOG_PATH = _LOG_PATH
        _FAULT_LOG_PATH = str(_sm.get('perf_probe_faulthandler_log', '') or '')
    except Exception:
        _ENABLED = False


# ── thread CPU time fallback for old interpreters ────────────────────
try:
    _thread_time_ns = time.thread_time_ns  # type: ignore[attr-defined]
except AttributeError:                      # pragma: no cover
    def _thread_time_ns() -> int:
        return 0


def is_enabled() -> bool:
    if _ENABLED is None:
        _load_config()
    return bool(_ENABLED)


class _Section:
    """Per-name bounded ring buffers for wall + CPU time samples."""

    __slots__ = ('name', 'wall_ns', 'cpu_ns', 'count', '_lock')

    def __init__(self, name: str) -> None:
        self.name = name
        self.wall_ns: Deque[int] = deque(maxlen=_WINDOW)
        self.cpu_ns: Deque[int] = deque(maxlen=_WINDOW)
        self.count = 0
        self._lock = threading.Lock()

    def record(self, wall_ns: int, cpu_ns: int) -> None:
        with self._lock:
            self.wall_ns.append(wall_ns)
            self.cpu_ns.append(cpu_ns)
            self.count += 1

    def snapshot(self) -> Optional[Dict[str, float]]:
        with self._lock:
            if not self.wall_ns:
                return None
            wall = sorted(self.wall_ns)
            cpu = sorted(self.cpu_ns) if self.cpu_ns else None
            count = self.count
            self.count = 0
            self.wall_ns.clear()
            self.cpu_ns.clear()

        n = len(wall)

        def q(arr, p):
            if not arr:
                return 0
            idx = min(n - 1, max(0, int(round(p * (n - 1)))))
            return arr[idx]

        out = {
            'name': self.name,
            'count': count,
            'wall_p50_us': q(wall, 0.50) / 1000.0,
            'wall_p95_us': q(wall, 0.95) / 1000.0,
            'wall_p99_us': q(wall, 0.99) / 1000.0,
            'wall_max_us': wall[-1] / 1000.0,
            'wall_sum_ms': sum(wall) / 1_000_000.0,
        }
        if cpu and any(cpu):
            out['cpu_p50_us'] = q(cpu, 0.50) / 1000.0
            out['cpu_p95_us'] = q(cpu, 0.95) / 1000.0
            out['cpu_sum_ms'] = sum(cpu) / 1_000_000.0
        return out


class _Gauge:
    __slots__ = ('name', 'last', 'max', 'sum', 'count', '_lock')

    def __init__(self, name: str) -> None:
        self.name = name
        self.last = 0.0
        self.max = 0.0
        self.sum = 0.0
        self.count = 0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self.last = float(value)
            if self.last > self.max:
                self.max = self.last
            self.sum += self.last
            self.count += 1

    def snapshot(self) -> Optional[Dict[str, float]]:
        with self._lock:
            if self.count == 0:
                return None
            out = {
                'name': self.name,
                'count': self.count,
                'last': self.last,
                'max': self.max,
                'avg': self.sum / max(1, self.count),
            }
            self.max = self.last
            self.sum = 0.0
            self.count = 0
            return out


_sections: Dict[str, _Section] = {}
_gauges: Dict[str, _Gauge] = {}
_registry_lock = threading.Lock()
_dumper_started = False
_phase_lock = threading.Lock()
_phase_events: Optional[Deque[Tuple[int, int, int, str, str]]] = None
_phase_seq = 0
_phase_dump_seq = 0
_emit_lock = threading.Lock()
_fault_handler_enabled = False
_fault_handler_file = None


def _phase_buffer() -> Deque[Tuple[int, int, int, str, str]]:
    global _phase_events
    if _phase_events is None:
        _phase_events = deque(maxlen=_PHASE_WINDOW)
    return _phase_events


def _section(name: str) -> _Section:
    sec = _sections.get(name)
    if sec is not None:
        return sec
    with _registry_lock:
        sec = _sections.get(name)
        if sec is None:
            sec = _Section(name)
            _sections[name] = sec
        return sec


def _gauge_obj(name: str) -> _Gauge:
    g = _gauges.get(name)
    if g is not None:
        return g
    with _registry_lock:
        g = _gauges.get(name)
        if g is None:
            g = _Gauge(name)
            _gauges[name] = g
        return g


def gauge(name: str, value: float) -> None:
    if _ENABLED is None:
        _load_config()
    if not _ENABLED:
        return
    _ensure_dumper()
    _gauge_obj(name).set(value)


def phase(name: str, detail: str = '') -> None:
    """Record a low-overhead phase marker into an in-memory ring buffer.

    Intended for crash diagnosis around state transitions and native
    boundaries (click dispatch, worker submit, GL init, present path).
    The marker is dumped by :func:`dump_now` when probing is enabled.
    """
    global _phase_seq
    if _ENABLED is None:
        _load_config()
    if not _ENABLED:
        return
    _ensure_dumper()
    safe_name = str(name or '')[:80]
    safe_detail = str(detail or '').replace('\n', ' ')[:160]
    now_ns = time.perf_counter_ns()
    thread_name = threading.current_thread().name[:40]
    with _phase_lock:
        _phase_seq += 1
        event = (_phase_seq, now_ns, threading.get_ident(), thread_name,
                 f'{safe_name}|{safe_detail}')
        _phase_buffer().append(event)
    if _PHASE_IMMEDIATE:
        _emit(_format_phase_event(event), path=_PHASE_LOG_PATH)


@contextmanager
def probe(name: str):
    if _ENABLED is None:
        _load_config()
    if not _ENABLED:
        yield
        return
    _ensure_dumper()
    sec = _section(name)
    t0 = time.perf_counter_ns()
    c0 = _thread_time_ns()
    try:
        yield
    finally:
        sec.record(time.perf_counter_ns() - t0, _thread_time_ns() - c0)


F = TypeVar('F', bound=Callable[..., object])


def decorate(name: str) -> Callable[[F], F]:
    """Decorator form of probe()."""
    def wrap(fn: F) -> F:
        # NOTE: do NOT check _ENABLED here — it may not be loaded yet at
        # decoration time (module import).  The check is deferred to inner().
        def inner(*args, **kwargs):
            if _ENABLED is None:
                _load_config()
            if not _ENABLED:
                return fn(*args, **kwargs)
            _ensure_dumper()
            sec = _section(name)
            t0 = time.perf_counter_ns()
            c0 = _thread_time_ns()
            try:
                return fn(*args, **kwargs)
            finally:
                sec.record(time.perf_counter_ns() - t0,
                           _thread_time_ns() - c0)

        inner.__name__ = getattr(fn, '__name__', name)
        inner.__doc__ = getattr(fn, '__doc__', None)
        inner.__wrapped__ = fn  # type: ignore[attr-defined]
        return inner  # type: ignore[return-value]
    return wrap


# Allow `probe.decorate('name')` style for symmetry with the context API.
probe.decorate = decorate  # type: ignore[attr-defined]


def _format_dump(sections, gauges) -> str:
    parts = ['[perf] ── snapshot ──']
    for snap in sorted(sections, key=lambda s: -s['wall_sum_ms']):
        line = (f"  {snap['name']:<48} "
                f"n={snap['count']:>6}  "
                f"sum={snap['wall_sum_ms']:>7.2f}ms  "
                f"p50={snap['wall_p50_us']:>7.1f}us  "
                f"p95={snap['wall_p95_us']:>7.1f}us  "
                f"p99={snap['wall_p99_us']:>7.1f}us  "
                f"max={snap['wall_max_us']:>7.1f}us")
        if 'cpu_sum_ms' in snap:
            line += (f"  cpu_sum={snap['cpu_sum_ms']:>6.2f}ms"
                     f"  cpu_p95={snap['cpu_p95_us']:>6.1f}us")
        parts.append(line)
    if gauges:
        parts.append('[perf] ── gauges ──')
        for snap in sorted(gauges, key=lambda s: s['name']):
            parts.append(f"  {snap['name']:<48} "
                         f"n={snap['count']:>6}  "
                         f"last={snap['last']:>10.2f}  "
                         f"max={snap['max']:>10.2f}  "
                         f"avg={snap['avg']:>10.2f}")
    return '\n'.join(parts)


def _phase_snapshot_since(last_seq: int,
                          limit: int = 96) -> Tuple[int, List[Tuple[int, int, int, str, str]]]:
    with _phase_lock:
        events = list(_phase_buffer())
        newest_seq = events[-1][0] if events else last_seq
    if not events:
        return newest_seq, []
    out = [ev for ev in events if ev[0] > last_seq]
    if len(out) > limit:
        out = out[-limit:]
    return newest_seq, out


def _format_phase_dump(events: List[Tuple[int, int, int, str, str]]) -> str:
    parts = ['[perf] ── recent phases ──']
    for event in events:
        parts.append('  ' + _format_phase_event(event, prefix='').lstrip())
    return '\n'.join(parts)


def _format_phase_event(event: Tuple[int, int, int, str, str],
                        prefix: str = '[perf][phase] ') -> str:
    seq, now_ns, tid, thread_name, payload = event
    name, _, detail = payload.partition('|')
    return (
        f'{prefix}#{seq:>5}  t={now_ns / 1_000_000.0:>12.3f}ms  '
        f'tid={tid:>8}  thr={thread_name:<20}  '
        f'{name:<32}  {detail}'
    )


def dump_recent_phases(limit: int = 96) -> None:
    if _ENABLED is None:
        _load_config()
    if not _ENABLED:
        return
    _latest_seq, events = _phase_snapshot_since(0, limit=limit)
    if not events:
        return
    _emit(_format_phase_dump(events))


def _emit(text: str, path: Optional[str] = None) -> None:
    target_path = _LOG_PATH if path is None else str(path or '')
    with _emit_lock:
        if target_path:
            try:
                with open(target_path, 'a', encoding='utf-8') as fh:
                    fh.write(text)
                    fh.write('\n')
                return
            except Exception:
                pass
        try:
            sys.stdout.write(text + '\n')
            sys.stdout.flush()
        except Exception:
            pass


def _ensure_fault_handler() -> None:
    global _fault_handler_enabled, _fault_handler_file
    if _fault_handler_enabled or not _FAULT_LOG_PATH:
        return
    try:
        _fault_handler_file = open(_FAULT_LOG_PATH, 'a', encoding='utf-8')
        faulthandler.enable(_fault_handler_file, all_threads=True)
        _fault_handler_enabled = True
        _emit(f'[perf] faulthandler enabled -> {_FAULT_LOG_PATH}')
    except Exception as exc:
        _emit(f'[perf] faulthandler enable failed: {exc}')


def dump_now() -> None:
    """Force a snapshot dump (also used by the periodic thread)."""
    global _phase_dump_seq
    if _ENABLED is None:
        _load_config()
    if not _ENABLED:
        return
    sec_snaps = []
    gauge_snaps = []
    with _registry_lock:
        sections = list(_sections.values())
        gauges = list(_gauges.values())
    for sec in sections:
        snap = sec.snapshot()
        if snap is not None:
            sec_snaps.append(snap)
    for g in gauges:
        snap = g.snapshot()
        if snap is not None:
            gauge_snaps.append(snap)
    phase_latest_seq, phase_events = _phase_snapshot_since(_phase_dump_seq)
    if not sec_snaps and not gauge_snaps and not phase_events:
        return
    parts = []
    if sec_snaps or gauge_snaps:
        parts.append(_format_dump(sec_snaps, gauge_snaps))
    if phase_events:
        parts.append(_format_phase_dump(phase_events))
        _phase_dump_seq = phase_latest_seq
    _emit('\n'.join(parts))


def _dumper_loop() -> None:
    while True:
        time.sleep(_DUMP_SEC)
        try:
            dump_now()
        except Exception as exc:           # pragma: no cover
            try:
                sys.stderr.write(f'[perf] dump error: {exc}\n')
            except Exception:
                pass


def _ensure_dumper() -> None:
    global _dumper_started
    if _dumper_started or not _ENABLED:
        return
    with _registry_lock:
        if _dumper_started:
            return
        t = threading.Thread(target=_dumper_loop, name='sao-perf-probe',
                             daemon=True)
        t.start()
        _dumper_started = True
        _ensure_fault_handler()
        _emit(f'[perf] enabled (dump every {_DUMP_SEC:.1f}s, '
              f'window={_WINDOW}, log={_LOG_PATH or "stdout"})')
        _emit('[perf] settings keys: perf_probe_enabled, perf_probe_dump_sec, '
              'perf_probe_window, perf_probe_phase_window, '
              'perf_probe_phase_immediate, perf_probe_phase_log, '
              'perf_probe_faulthandler_log, perf_probe_log '
              '(in settings.json)')
