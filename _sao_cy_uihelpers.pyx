# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
"""Cython UI helpers extracted from `sao_gui.py`.

These are pure-logic / pure-arithmetic hot paths that the recognition loop
and panel-float scheduler hit at 30-60 Hz. They have no Tk/PIL dependency,
so moving them out of Python avoids per-call attribute lookups, exception
machinery, and `int(...)` boxing.

Functions:
    pick_burst_trigger_slot — 9-slot burst-anchor state machine
    panel_float_offsets — sinusoidal dx/dy for the panel-float tick
    format_level_text — Lv display ('33' or '33(+5)')
    normalize_watched_skill_slots — dedupe/clip skill slot list
    is_dead_state — gs HP-based death predicate
    boss_monster_usable — boss-bar candidate predicate
    format_session_power — '12,345' or '--'
    session_int — defensive int parse
"""

from libc.math cimport exp, floor, sin, pow


cdef inline long long _safe_i64(object value, long long default=0):
    if value is None:
        return default
    try:
        return <long long>int(value)
    except Exception:
        try:
            text = str(value).strip()
            if text.isdigit():
                return <long long>int(text)
            return default
        except Exception:
            return default


cdef inline double _safe_f64(object value, double default=0.0):
    if value is None:
        return default
    try:
        return <double>float(value)
    except Exception:
        return default


cdef inline double _abs_f64(double value):
    return -value if value < 0.0 else value


cpdef long long session_int(object value, long long default=0):
    """Defensive int parse used everywhere session player rows are touched."""
    return _safe_i64(value, default)


cpdef tuple stamina_filter_step(object raw_pct_obj, object confidence_obj,
                                double now, object stable_obj,
                                object pending_obj, double pending_since,
                                double drop_lock_until,
                                double large_delta_threshold,
                                double large_delta_confirm_s,
                                double large_delta_stable_epsilon):
    """Advance the recognition stamina filter state machine by one sample."""
    cdef double raw_pct = _safe_f64(raw_pct_obj, 0.0)
    cdef double confidence = _safe_f64(confidence_obj, 0.0)
    cdef bint has_stable = stable_obj is not None
    cdef double stable = _safe_f64(stable_obj, 0.0)
    cdef bint has_pending = pending_obj is not None
    cdef double pending = _safe_f64(pending_obj, 0.0)
    cdef double delta
    cdef double pending_delta
    if raw_pct < 0.0:
        raw_pct = 0.0
    elif raw_pct > 1.0:
        raw_pct = 1.0

    if not has_stable:
        if raw_pct >= 0.98:
            raw_pct = 1.0
        return (raw_pct, raw_pct, None, 0.0, drop_lock_until)

    if confidence < 0.20:
        return (stable, stable, pending_obj, pending_since, drop_lock_until)

    if raw_pct > stable and now < drop_lock_until:
        return (stable, stable, pending_obj, pending_since, drop_lock_until)

    delta = raw_pct - stable
    if _abs_f64(delta) > large_delta_threshold:
        if not has_pending:
            return (stable, stable, raw_pct, now, drop_lock_until)

        pending_delta = raw_pct - pending
        if _abs_f64(pending_delta) <= large_delta_stable_epsilon:
            if (now - pending_since) >= large_delta_confirm_s:
                if raw_pct >= 0.98:
                    raw_pct = 1.0
                if raw_pct < (stable - 0.001):
                    if drop_lock_until < (now + 0.30):
                        drop_lock_until = now + 0.30
                return (raw_pct, raw_pct, None, 0.0, drop_lock_until)
            return (stable, stable, pending, pending_since, drop_lock_until)

        if _abs_f64(raw_pct - stable) <= large_delta_stable_epsilon:
            return (stable, stable, None, 0.0, drop_lock_until)

        return (stable, stable, raw_pct, now, drop_lock_until)

    if raw_pct >= 0.98:
        raw_pct = 1.0
    if raw_pct < (stable - 0.001):
        if drop_lock_until < (now + 0.30):
            drop_lock_until = now + 0.30
    return (raw_pct, raw_pct, None, 0.0, drop_lock_until)


cpdef bint dps_overlay_animating(object hide_after_fade,
                                 object fade_alpha, object fade_target,
                                 object panel_fx_tier, object rows,
                                 object disp_total_damage,
                                 object target_total_damage,
                                 object disp_total_dps,
                                 object target_total_dps,
                                 object disp_total_heal,
                                 object target_total_heal,
                                 object disp_total_hps,
                                 object target_total_hps):
    """Animation predicate for the DPS overlay."""
    cdef object row
    if bool(hide_after_fade):
        return True
    if _abs_f64(_safe_f64(fade_alpha, 0.0) - _safe_f64(fade_target, 0.0)) > 1e-3:
        return True
    if bool(panel_fx_tier):
        return True
    if rows:
        for row in rows.values():
            if _abs_f64(_safe_f64(getattr(row, 'disp_dps', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_dps', 0.0), 0.0)) > 0.5:
                return True
            if _abs_f64(_safe_f64(getattr(row, 'disp_damage', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_damage', 0.0), 0.0)) > 0.5:
                return True
            if _abs_f64(_safe_f64(getattr(row, 'disp_hps', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_hps', 0.0), 0.0)) > 0.5:
                return True
            if _abs_f64(_safe_f64(getattr(row, 'disp_heal', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_heal', 0.0), 0.0)) > 0.5:
                return True
            if _abs_f64(_safe_f64(getattr(row, 'disp_bar_pct', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_bar_pct', 0.0), 0.0)) > 1e-3:
                return True
            if _abs_f64(_safe_f64(getattr(row, 'disp_y', 0.0), 0.0)
                        - _safe_f64(getattr(row, 'target_y', 0.0), 0.0)) > 5e-4:
                return True
            if bool(getattr(row, 'fx_tier', '')):
                return True
    if _abs_f64(_safe_f64(disp_total_damage, 0.0)
                - _safe_f64(target_total_damage, 0.0)) > 0.5:
        return True
    if _abs_f64(_safe_f64(disp_total_dps, 0.0)
                - _safe_f64(target_total_dps, 0.0)) > 0.5:
        return True
    if _abs_f64(_safe_f64(disp_total_heal, 0.0)
                - _safe_f64(target_total_heal, 0.0)) > 0.5:
        return True
    if _abs_f64(_safe_f64(disp_total_hps, 0.0)
                - _safe_f64(target_total_hps, 0.0)) > 0.5:
        return True
    return False


cpdef bint bosshp_overlay_animating(object visible,
                                    object fade_alpha, object fade_target,
                                    object disp_hp_pct, object target_hp_pct,
                                    object disp_trail_pct, object target_trail_pct,
                                    object disp_shield_pct, object target_shield_pct,
                                    object disp_break_pct, object target_break_pct,
                                    bint shield_active, bint in_overdrive,
                                    object breaking_stage, object now,
                                    object damage_flash_start, object damage_flash_dur,
                                    object break_burst_start, object break_burst_dur,
                                    object shield_break_start, object shield_break_dur,
                                    object shield_vfx_mode, object shield_vfx_start,
                                    object shield_vfx_dur, object root_pulse_mode,
                                    object root_pulse_start, object root_pulse_dur):
    """Animation predicate for the BossHP overlay."""
    cdef double now_f = _safe_f64(now, 0.0)
    if not bool(visible):
        return False
    if _abs_f64(_safe_f64(fade_alpha, 0.0) - _safe_f64(fade_target, 0.0)) > 1e-3:
        return True
    if _abs_f64(_safe_f64(disp_hp_pct, 0.0) - _safe_f64(target_hp_pct, 0.0)) > 4e-4:
        return True
    if _abs_f64(_safe_f64(disp_trail_pct, 0.0) - _safe_f64(target_trail_pct, 0.0)) > 4e-4:
        return True
    if _abs_f64(_safe_f64(disp_shield_pct, 0.0) - _safe_f64(target_shield_pct, 0.0)) > 4e-4:
        return True
    if _abs_f64(_safe_f64(disp_break_pct, 0.0) - _safe_f64(target_break_pct, 0.0)) > 4e-4:
        return True
    if shield_active and _safe_f64(disp_shield_pct, 0.0) > 0.01:
        return True
    if in_overdrive:
        return True
    if _safe_i64(breaking_stage, 0) > 0:
        return True
    if _fx_age_q(_safe_f64(damage_flash_start, 0.0),
                 _safe_f64(damage_flash_dur, 0.0), now_f) >= 0:
        return True
    if _fx_age_q(_safe_f64(break_burst_start, 0.0),
                 _safe_f64(break_burst_dur, 0.0), now_f) >= 0:
        return True
    if _fx_age_q(_safe_f64(shield_break_start, 0.0),
                 _safe_f64(shield_break_dur, 0.0), now_f) >= 0:
        return True
    if bool(shield_vfx_mode) and _fx_age_q(_safe_f64(shield_vfx_start, 0.0),
                                           _safe_f64(shield_vfx_dur, 0.0),
                                           now_f) >= 0:
        return True
    if bool(root_pulse_mode) and _fx_age_q(_safe_f64(root_pulse_start, 0.0),
                                           _safe_f64(root_pulse_dur, 0.0),
                                           now_f) >= 0:
        return True
    return False


cpdef bint hp_overlay_animating(object visible, bint exiting,
                                object fade_alpha, object fade_target,
                                object hp_pct_disp, object hp_pct_target,
                                object sta_pct_disp, object sta_pct_target,
                                bint sta_offline_pending,
                                object offline_hide_t,
                                object hp_group_fade_t,
                                object hp_group_fade_duration,
                                object hp_group_restore_t,
                                object hp_group_restore_duration,
                                bint boss_timer_active,
                                object hp_flash_start,
                                object hp_last_update_t,
                                object sta_last_update_t,
                                bint hover_pending,
                                bint press_flash_pending,
                                object enter_scale_t,
                                object now):
    """Animation predicate for the HP overlay.

    H1: replaces the 35-line Python ``HpOverlay._is_animating``. Caller
    precomputes ``hover_pending`` (any zone has |hover_t - hover_target|>1e-3
    OR |press_t - press_target|>1e-3) and ``press_flash_pending`` (any zone
    press_flash_t > now) before calling. ``boss_timer_active`` is
    ``bool(self._boss_timer_urgent and self._boss_timer_text)``. The
    final ``visible AND fade_target>=1.0 AND not exiting`` short-circuit is
    kept inside cython so steady-visible always returns True.
    """
    cdef double now_f = _safe_f64(now, 0.0)
    cdef double fa = _safe_f64(fade_alpha, 0.0)
    cdef double ft = _safe_f64(fade_target, 0.0)
    cdef double gfade_t
    cdef double grest_t
    cdef double flash_t
    cdef double last_hp
    cdef double last_sta
    cdef double hide_t

    if _abs_f64(fa - ft) > 1e-3:
        return True
    if _abs_f64(_safe_f64(hp_pct_disp, 0.0) - _safe_f64(hp_pct_target, 0.0)) > 4e-4:
        return True
    if _abs_f64(_safe_f64(sta_pct_disp, 0.0) - _safe_f64(sta_pct_target, 0.0)) > 4e-4:
        return True
    hide_t = _safe_f64(offline_hide_t, 0.0)
    if sta_offline_pending or hide_t > 0.0:
        return True
    gfade_t = _safe_f64(hp_group_fade_t, 0.0)
    if gfade_t > 0.0 and (now_f - gfade_t) < _safe_f64(hp_group_fade_duration, 0.0):
        return True
    grest_t = _safe_f64(hp_group_restore_t, 0.0)
    if grest_t > 0.0 and (now_f - grest_t) < _safe_f64(hp_group_restore_duration, 0.0):
        return True
    if boss_timer_active:
        return True
    flash_t = _safe_f64(hp_flash_start, 0.0)
    if flash_t > 0.0 and (now_f - flash_t) < 0.45:
        return True
    last_hp = _safe_f64(hp_last_update_t, 0.0)
    if last_hp > 0.0 and (now_f - last_hp) < 0.55:
        return True
    last_sta = _safe_f64(sta_last_update_t, 0.0)
    if last_sta > 0.0 and (now_f - last_sta) < 0.55:
        return True
    if hover_pending or press_flash_pending:
        return True
    if ft >= 1.0 and _safe_f64(enter_scale_t, 0.0) < 0.999:
        return True
    if bool(visible) and ft >= 1.0 and not exiting:
        return True
    return False


cdef inline double _decay_toward_value(double cur, double tgt,
                                       double tick_ms, double tween,
                                       double eps):
    cdef double clamped_tween
    cdef double k
    if _abs_f64(cur - tgt) < eps:
        return tgt
    clamped_tween = tween if tween >= 0.05 else 0.05
    k = 1.0 - pow(0.05, tick_ms / 1000.0 / clamped_tween)
    return cur + (tgt - cur) * k


cpdef tuple dps_step_totals(object disp_total_damage,
                            object target_total_damage,
                            object disp_total_dps, object target_total_dps,
                            object disp_total_heal, object target_total_heal,
                            object disp_total_hps, object target_total_hps,
                            object disp_elapsed, object target_elapsed,
                            double tick_ms, double num_tween):
    """Advance the DPS overlay header totals by one tick."""
    cdef double old_damage = _safe_f64(disp_total_damage, 0.0)
    cdef double old_dps = _safe_f64(disp_total_dps, 0.0)
    cdef double old_heal = _safe_f64(disp_total_heal, 0.0)
    cdef double old_hps = _safe_f64(disp_total_hps, 0.0)
    cdef double new_damage = _decay_toward_value(
        old_damage, _safe_f64(target_total_damage, 0.0), tick_ms, num_tween, 0.5)
    cdef double new_dps = _decay_toward_value(
        old_dps, _safe_f64(target_total_dps, 0.0), tick_ms, num_tween, 0.5)
    cdef double new_heal = _decay_toward_value(
        old_heal, _safe_f64(target_total_heal, 0.0), tick_ms, num_tween, 0.5)
    cdef double new_hps = _decay_toward_value(
        old_hps, _safe_f64(target_total_hps, 0.0), tick_ms, num_tween, 0.5)
    cdef long long new_elapsed = _safe_i64(target_elapsed, 0)
    cdef bint changed = (
        new_damage != old_damage or
        new_dps != old_dps or
        new_heal != old_heal or
        new_hps != old_hps or
        new_elapsed != _safe_i64(disp_elapsed, 0)
    )
    return (new_damage, new_dps, new_heal, new_hps, new_elapsed, changed)


cpdef bint dps_step_row_state(object row, double now, double tick_ms,
                              double num_tween, double bar_tween,
                              double row_tween, double fx_duration):
    """Advance one DPS row by one tick and return whether it is still animating."""
    cdef double before_damage = _safe_f64(getattr(row, 'disp_damage', 0.0), 0.0)
    cdef double before_dps = _safe_f64(getattr(row, 'disp_dps', 0.0), 0.0)
    cdef double before_heal = _safe_f64(getattr(row, 'disp_heal', 0.0), 0.0)
    cdef double before_hps = _safe_f64(getattr(row, 'disp_hps', 0.0), 0.0)
    cdef double before_bar = _safe_f64(getattr(row, 'disp_bar_pct', 0.0), 0.0)
    cdef double before_y = _safe_f64(getattr(row, 'disp_y', 0.0), 0.0)
    cdef double after_damage
    cdef double after_dps
    cdef double after_heal
    cdef double after_hps
    cdef double after_bar
    cdef double after_y
    after_damage = _decay_toward_value(
        before_damage, _safe_f64(getattr(row, 'target_damage', 0.0), 0.0),
        tick_ms, num_tween, 0.5)
    after_dps = _decay_toward_value(
        before_dps, _safe_f64(getattr(row, 'target_dps', 0.0), 0.0),
        tick_ms, num_tween, 0.5)
    after_heal = _decay_toward_value(
        before_heal, _safe_f64(getattr(row, 'target_heal', 0.0), 0.0),
        tick_ms, num_tween, 0.5)
    after_hps = _decay_toward_value(
        before_hps, _safe_f64(getattr(row, 'target_hps', 0.0), 0.0),
        tick_ms, num_tween, 0.5)
    after_bar = _decay_toward_value(
        before_bar, _safe_f64(getattr(row, 'target_bar_pct', 0.0), 0.0),
        tick_ms, bar_tween, 5e-4)
    after_y = _decay_toward_value(
        before_y, _safe_f64(getattr(row, 'target_y', 0.0), 0.0),
        tick_ms, row_tween, 5e-4)
    row.disp_damage = after_damage
    row.disp_dps = after_dps
    row.disp_heal = after_heal
    row.disp_hps = after_hps
    row.disp_bar_pct = after_bar
    row.disp_y = after_y
    if bool(getattr(row, 'fx_tier', '')) and (
            now - _safe_f64(getattr(row, 'fx_start', 0.0), 0.0)) > fx_duration:
        row.fx_tier = ''
    return bool(getattr(row, 'fx_tier', '')) or (
        after_damage != before_damage or
        after_dps != before_dps or
        after_heal != before_heal or
        after_hps != before_hps or
        after_bar != before_bar or
        after_y != before_y
    )


cpdef str format_session_power(object value):
    """Render the Power column. Empty / non-positive renders as '--'."""
    cdef long long v = _safe_i64(value, 0)
    if v <= 0:
        return '--'
    return f'{v:,}'


cpdef str format_level_text(object level_base, object level_extra,
                            object fallback_level=None):
    """Mirror `_format_level_text`: 'Lv' or 'Lv(+extra)'."""
    cdef long long lb = _safe_i64(level_base, 0)
    cdef long long le = _safe_i64(level_extra, 0)
    cdef long long fb
    if lb <= 0:
        fb = _safe_i64(fallback_level, 1)
        lb = fb if fb > 0 else 1
    if le > 0 and lb > 0:
        return f'{lb}(+{le})'
    return str(lb)


cpdef list normalize_watched_skill_slots(object slots):
    """Mirror `_normalize_watched_skill_slots`. Keep order, dedupe, clip 1-9."""
    cdef list normalized = []
    cdef set seen = set()
    cdef long long slot
    if not slots:
        return normalized
    for raw in slots:
        try:
            slot = <long long>int(raw)
        except Exception:
            continue
        if 1 <= slot <= 9 and slot not in seen:
            seen.add(slot)
            normalized.append(<int>slot)
    return normalized


cpdef bint is_dead_state(object hp_max, object hp_current, object hp_pct):
    """Death predicate used by the HP/vision lifecycle gating."""
    cdef long long mx = _safe_i64(hp_max, 0)
    cdef long long cur = _safe_i64(hp_current, 0)
    cdef double pct = _safe_f64(hp_pct, 1.0)
    return mx > 0 and cur <= 0 and pct <= 0.001


cpdef tuple boss_monster_usable(object hp, object max_hp, bint is_dead):
    """Decide whether a monster can drive the boss bar.

    Returns ``(usable, revive)``. ``revive`` is True when the caller should
    flip ``monster.is_dead`` from True to False because HP > 0 was observed
    on a "dead" entity (server reused the UUID for a respawn).
    """
    cdef long long h = _safe_i64(hp, 0)
    cdef long long mh = _safe_i64(max_hp, 0)
    cdef bint revive = False
    cdef bint dead = is_dead
    if dead and h > 0:
        revive = True
        dead = False
    if dead:
        return (False, revive)
    return ((mh > 0 or h > 0), revive)


cpdef tuple panel_float_offsets(double t, double phase, double amp):
    """Return ``(dx, dy)`` integer offsets for the panel-float idle wobble.

    Same constants as the original Python tick: phases 0.82 / 0.61 with a
    1.2 rad relative offset on the y axis.
    """
    cdef int dx = <int>(amp * sin(t * 0.82 + phase))
    cdef int dy = <int>(amp * sin(t * 0.61 + phase + 1.2))
    return (dx, dy)


cpdef tuple breath_offsets(double t):
    """Return ``(dx, dy)`` integer offsets for the floating widget idle breath.

    Mirrors `_breath_step`'s ``int(round(sin(t*1.25)*3.0))`` /
    ``int(round(sin(t*2.1)*2.0))``. Runs at 60 fps so the avoided per-call
    Python overhead (math.sin → builtin int → round) adds up.
    """
    cdef double dx_f = sin(t * 1.25) * 3.0
    cdef double dy_f = sin(t * 2.1) * 2.0
    # Match Python's built-in round() (banker's rounding to nearest even is
    # close enough for whole-pixel deltas; use simple truncation toward
    # nearest with explicit add 0.5 / sub 0.5 for sign).
    cdef int dx
    cdef int dy
    if dx_f >= 0.0:
        dx = <int>(dx_f + 0.5)
    else:
        dx = <int>(dx_f - 0.5)
    if dy_f >= 0.0:
        dy = <int>(dy_f + 0.5)
    else:
        dy = <int>(dy_f - 0.5)
    return (dx, dy)


cpdef tuple player_panel_anim_size(object width, object height, double t):
    """Scale a panel rect by animation progress, clamped to at least 1px."""
    cdef int w = <int>_safe_i64(width, 1)
    cdef int h = <int>_safe_i64(height, 1)
    cdef int out_w = <int>(<double>w * t)
    cdef int out_h = <int>(<double>h * t)
    if out_w < 1:
        out_w = 1
    if out_h < 1:
        out_h = 1
    return (out_w, out_h)


cpdef double scan_phase(double now):
    """HUD scan phase matching ``(sin(time.time()*1.5)+1)/2``."""
    return (sin(now * 1.5) + 1.0) / 2.0


cpdef int scan_x(object width, double now):
    """Tk scan-bar x coordinate for the player info panel."""
    cdef int w = <int>_safe_i64(width, 0)
    return 10 + <int>((<double>(w - 20)) * scan_phase(now))


cpdef str short_session_name(object name):
    """Trim session-player names to the compact roster column width."""
    cdef str text = str(name or '').strip()
    if not text:
        return '--'
    if len(text) <= 14:
        return text
    return text[:13] + '…'


cpdef tuple session_rows_signature(list rows):
    """Build the roster change signature used by ``update_rows``."""
    cdef list sig = []
    cdef object row
    if not rows:
        return ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sig.append((
            str(row.get('uid') or ''),
            str(row.get('name') or ''),
            <int>_safe_i64(row.get('fight_power_value'), 0),
            bool(row.get('is_self')),
        ))
    return tuple(sig)


cpdef str session_self_uid(list rows):
    """Return the UID for the self row, or an empty string."""
    cdef object row
    if not rows:
        return ''
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get('is_self'):
            return str(row.get('uid') or '')
    return ''


cpdef int clamp_session_first_index(object first, object total, object visible_count):
    """Clamp the first visible GPU roster row to the valid range."""
    cdef int f = <int>_safe_i64(first, 0)
    cdef int t = <int>_safe_i64(total, 0)
    cdef int vc = <int>_safe_i64(visible_count, 1)
    cdef int max_first = t - vc
    if max_first < 0:
        max_first = 0
    if f < 0:
        return 0
    if f > max_first:
        return max_first
    return f


cpdef int session_scroll_delta(object num, object delta_obj):
    """Normalize Windows/X11 mouse-wheel events to roster scroll units."""
    cdef long long n = _safe_i64(num, 0)
    cdef long long raw_delta
    cdef int delta
    if n == 4:
        return -3
    if n == 5:
        return 3
    raw_delta = _safe_i64(delta_obj, 0)
    delta = <int>(-1.0 * (<double>raw_delta / 120.0))
    if delta == 0:
        return -1 if raw_delta > 0 else 1
    return delta


cpdef int session_scroll_first_index(object first, object total,
                                     object visible_count, object delta):
    """Apply a scroll delta and clamp the GPU roster first row."""
    return clamp_session_first_index(
        _safe_i64(first, 0) + _safe_i64(delta, 0), total, visible_count)


cpdef list session_visible_rows(list rows, object first, object visible_count):
    """Build compact GPU roster rows from the source row dictionaries."""
    cdef int total = <int>len(rows) if rows is not None else 0
    cdef int vc = <int>_safe_i64(visible_count, 1)
    cdef int start = clamp_session_first_index(first, total, vc)
    cdef int end = start + vc
    cdef list out = []
    cdef object row
    cdef int idx
    if end > total:
        end = total
    for idx in range(start, end):
        row = rows[idx]
        if not isinstance(row, dict):
            continue
        out.append((
            short_session_name(row.get('name') or ''),
            str(row.get('uid') or '--'),
            str(row.get('fight_power') or '--'),
            bool(row.get('is_self')),
        ))
    return out


cpdef double cubic_open_reveal(double elapsed, double duration):
    """Ease-out cubic reveal used by the session-player open animation."""
    cdef double t
    if duration <= 0.0:
        return 1.0
    t = elapsed / duration
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return 1.0 - ((1.0 - t) * (1.0 - t) * (1.0 - t))


cpdef tuple session_open_anim_geometry(object panel_h, double elapsed,
                                       double duration):
    """Return ``(t, ease, height, offset, highlight_on)`` for list open."""
    cdef double t
    cdef double ease
    cdef int ph = <int>_safe_i64(panel_h, 1)
    cdef int height
    cdef int offset
    if duration <= 0.0:
        t = 1.0
    else:
        t = elapsed / duration
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
    ease = 1.0 - ((1.0 - t) * (1.0 - t) * (1.0 - t))
    height = <int>((<double>ph * ease) + 0.5)
    if height < 1:
        height = 1
    offset = <int>((64.0 * (1.0 - ease)) + 0.5)
    return (t, ease, height, offset, t < 0.55)


cpdef tuple sao_fx_coords(double tt, object panel_id, object width):
    """Integer SAO HUD decoration coordinates for the shared panel tick."""
    cdef long long pid = _safe_i64(panel_id, 0)
    cdef int pw = <int>_safe_i64(width, 80)
    cdef double t = tt + <double>(pid % 17) * 0.13
    cdef int left_far = <int>(10.0 + 5.0 * sin(t * 0.66))
    cdef int left_near = <int>(20.0 + 12.0 * sin(t * 1.35 + 0.8))
    cdef int right_far = <int>(<double>pw - 18.0 + 7.0 * sin(t * 0.72 + 1.1))
    cdef int right_near = <int>(<double>pw - 34.0 + 12.0 * sin(t * 1.45 + 2.1))
    return (left_far, left_near, right_far, right_near)


cpdef int popup_visible_count(object menu_count, object max_visible):
    """Visible menu-button count for the GPU entity popup."""
    cdef int n = <int>_safe_i64(menu_count, 0)
    cdef int m = <int>_safe_i64(max_visible, 7)
    if n < 0:
        n = 0
    if m < 0:
        m = 0
    return n if n < m else m


cpdef int popup_column_height(object menu_count, object max_visible, object slot):
    """Menu column height for the GPU entity popup."""
    cdef int visible = popup_visible_count(menu_count, max_visible)
    cdef int s = <int>_safe_i64(slot, 70)
    if visible < 1:
        visible = 1
    return s * visible


cpdef tuple popup_content_shift(object fade_alpha):
    """Small master slide used during popup open/close."""
    cdef double alpha = _safe_f64(fade_alpha, 1.0)
    if alpha < 0.0:
        alpha = 0.0
    elif alpha > 1.0:
        alpha = 1.0
    cdef int shift_x = <int>(-((1.0 - alpha) * 14.0 + 0.5))
    cdef int shift_y = <int>(((1.0 - alpha) * 10.0) + 0.5)
    return (shift_x, shift_y)


cpdef tuple popup_origins(object fade_alpha, object hud_pad,
                          object menu_x, object child_x):
    """Return menu/child origins after applying popup content shift."""
    cdef int dx, dy
    dx, dy = popup_content_shift(fade_alpha)
    cdef int pad = <int>_safe_i64(hud_pad, 24)
    cdef int mx = <int>_safe_i64(menu_x, 24)
    cdef int cx = <int>_safe_i64(child_x, 119)
    return ((mx + dx, pad + dy), (cx + dx, pad + dy))


cpdef tuple popup_content_size(object menu_count, object child_count,
                               object max_visible, object slot,
                               object row_stride, object menu_width,
                               object gap, object child_width):
    """Return ``(content_w, content_h)`` for the GPU popup frame."""
    cdef int menu_h = popup_column_height(menu_count, max_visible, slot)
    cdef int cc = <int>_safe_i64(child_count, 0)
    cdef int rs = <int>_safe_i64(row_stride, 47)
    cdef int child_h = cc * rs if cc > 0 else 0
    cdef int inner_h = menu_h
    if child_h > inner_h:
        inner_h = child_h
    if inner_h < 1:
        inner_h = 1
    cdef int inner_w = (<int>_safe_i64(menu_width, 70)
                        + <int>_safe_i64(gap, 25)
                        + <int>_safe_i64(child_width, 267))
    return (inner_w, inner_h)


cpdef tuple popup_window_size(object menu_count, object child_count,
                              object reserved_rows, object max_visible,
                              object slot, object row_stride,
                              object menu_width, object gap,
                              object child_width, object hud_pad):
    """Return reserved GPU popup window size."""
    cdef int iw, ih
    iw, ih = popup_content_size(menu_count, child_count, max_visible, slot,
                                row_stride, menu_width, gap, child_width)
    cdef int rr = <int>_safe_i64(reserved_rows, 0)
    cdef int rs = <int>_safe_i64(row_stride, 47)
    cdef int reserved_h = rr * rs if rr > 0 else 0
    cdef int menu_h = popup_column_height(menu_count, max_visible, slot)
    if reserved_h > ih:
        ih = reserved_h
    if menu_h > ih:
        ih = menu_h
    cdef int pad = <int>_safe_i64(hud_pad, 24)
    return (iw + pad * 2, ih + pad * 2)


cpdef tuple popup_menu_button_frame(object size_value, object slot,
                                    object max_size, object index):
    """Return ``(size_f, size_px, ox, oy)`` for a fisheye menu button."""
    cdef double size_f = _safe_f64(size_value, 54.0)
    cdef double mx = _safe_f64(max_size, 70.0)
    cdef double sl = _safe_f64(slot, 70.0)
    cdef int idx = <int>_safe_i64(index, 0)
    if size_f < 1.0:
        size_f = 1.0
    if size_f > mx:
        size_f = mx
    cdef int size_px = <int>size_f
    if size_f > <double>size_px:
        size_px += 1
    if size_px < 1:
        size_px = 1
    cdef int ox = <int>(((sl - size_f) / 2.0) + 0.5)
    cdef int oy = <int>(((<double>idx * sl + (sl - size_f) / 2.0)) + 0.5)
    return (size_f, size_px, ox, oy)


cpdef bint popup_advance_menu_animation(object btn_size, object btn_hover_t,
                                        object hover_idx, object menu_count,
                                        object max_visible, double base_size,
                                        double size_eps, double size_lerp,
                                        double hover_lerp):
    """Advance entity popup menu fisheye + hover arrays in-place."""
    cdef int n = popup_visible_count(menu_count, max_visible)
    if n <= 0:
        return False
    while len(btn_size) < n:
        btn_size.append(base_size)
    while len(btn_hover_t) < n:
        btn_hover_t.append(0.0)
    cdef bint has_hover = hover_idx is not None
    cdef int hi = <int>_safe_i64(hover_idx, -1)
    cdef bint keep = False
    cdef int i, dist
    cdef double target, delta, ht_target, ht_delta
    for i in range(n):
        if has_hover:
            dist = hi - i
            if dist < 0:
                dist = -dist
            target = base_size * (1.0 + 0.22 * exp(-0.9 * <double>(dist * dist)))
        else:
            target = base_size
        delta = target - _safe_f64(btn_size[i], base_size)
        if delta < 0.0:
            if -delta > size_eps:
                btn_size[i] = _safe_f64(btn_size[i], base_size) + delta * size_lerp
                keep = True
            else:
                btn_size[i] = target
        else:
            if delta > size_eps:
                btn_size[i] = _safe_f64(btn_size[i], base_size) + delta * size_lerp
                keep = True
            else:
                btn_size[i] = target
        ht_target = 1.0 if (has_hover and hi == i) else 0.0
        ht_delta = ht_target - _safe_f64(btn_hover_t[i], 0.0)
        if ht_delta < 0.0:
            if -ht_delta > 0.01:
                btn_hover_t[i] = _safe_f64(btn_hover_t[i], 0.0) + ht_delta * hover_lerp
                keep = True
            else:
                btn_hover_t[i] = ht_target
        else:
            if ht_delta > 0.01:
                btn_hover_t[i] = _safe_f64(btn_hover_t[i], 0.0) + ht_delta * hover_lerp
                keep = True
            else:
                btn_hover_t[i] = ht_target
    return keep


cpdef list popup_menu_hit_rects(object menu_count, object max_visible,
                                object slot, object x_off, object y_off):
    """Return menu button hit rects for the GPU popup."""
    cdef int n = popup_visible_count(menu_count, max_visible)
    cdef int s = <int>_safe_i64(slot, 70)
    cdef int x = <int>_safe_i64(x_off, 0)
    cdef int y = <int>_safe_i64(y_off, 0)
    cdef list out = []
    cdef int i, y1
    for i in range(n):
        y1 = y + i * s
        out.append(((x, y1, x + s, y1 + s), i))
    return out


cpdef int popup_child_height(object child_count, object row_stride):
    """Child row column height for the GPU popup."""
    cdef int n = <int>_safe_i64(child_count, 0)
    if n <= 0:
        return 0
    return n * <int>_safe_i64(row_stride, 47)


cpdef bint popup_advance_child_animation(object row_hover_t, object row_anim_w,
                                         object hover_idx, object child_count,
                                         double now, double row_anim_t0,
                                         double target_row_w, double duration,
                                         double stagger, double hover_lerp):
    """Advance entity popup child-row slide/hover arrays in-place."""
    cdef int n = <int>_safe_i64(child_count, 0)
    while len(row_hover_t) < n:
        row_hover_t.append(0.0)
    while len(row_anim_w) < n:
        row_anim_w.append(0)
    cdef bint has_hover = hover_idx is not None
    cdef int hi = <int>_safe_i64(hover_idx, -1)
    cdef bint keep = False
    cdef int i, target_w
    cdef double local_t, st, ht_target, delta
    for i in range(n):
        if duration <= 0.0:
            local_t = 1.0
        else:
            local_t = (now - row_anim_t0 - <double>i * stagger) / duration
        if local_t < 0.0:
            local_t = 0.0
        elif local_t > 1.0:
            local_t = 1.0
        st = 1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t))
        target_w = <int>(target_row_w * st + 0.5)
        if _safe_i64(row_anim_w[i], 0) != target_w:
            row_anim_w[i] = target_w
            keep = True
        if local_t < 1.0:
            keep = True
        ht_target = 1.0 if (has_hover and hi == i) else 0.0
        delta = ht_target - _safe_f64(row_hover_t[i], 0.0)
        if delta < 0.0:
            if -delta > 0.01:
                row_hover_t[i] = _safe_f64(row_hover_t[i], 0.0) + delta * hover_lerp
                keep = True
            else:
                row_hover_t[i] = ht_target
        else:
            if delta > 0.01:
                row_hover_t[i] = _safe_f64(row_hover_t[i], 0.0) + delta * hover_lerp
                keep = True
            else:
                row_hover_t[i] = ht_target
    return keep


cpdef list popup_child_hit_rects(object child_count, object row_anim_w,
                                 object x_off, object y_off, object list_x,
                                 object row_stride, object row_h,
                                 object target_row_w):
    """Return child row hit rects for the GPU popup."""
    cdef int n = <int>_safe_i64(child_count, 0)
    cdef int x1 = <int>_safe_i64(x_off, 0) + <int>_safe_i64(list_x, 27)
    cdef int y = <int>_safe_i64(y_off, 0)
    cdef int rs = <int>_safe_i64(row_stride, 47)
    cdef int rh = <int>_safe_i64(row_h, 36)
    cdef int target_w = <int>_safe_i64(target_row_w, 240)
    cdef int i, y1, rw
    cdef list out = []
    for i in range(n):
        rw = <int>_safe_i64(row_anim_w[i] if i < len(row_anim_w) else target_w, target_w)
        if rw < 1:
            rw = 1
        y1 = y + i * rs
        out.append(((x1, y1, x1 + rw, y1 + rh), i))
    return out


cpdef object popup_pick_hit(list regions, tuple bounds, object x, object y):
    """Pick a region from cached GPU popup hit rectangles."""
    cdef int ix = <int>_safe_i64(x, 0)
    cdef int iy = <int>_safe_i64(y, 0)
    cdef object item
    cdef object rect
    cdef int x1, y1, x2, y2
    for item in regions:
        rect = item[0]
        x1 = <int>rect[0]; y1 = <int>rect[1]
        x2 = <int>rect[2]; y2 = <int>rect[3]
        if x1 <= ix < x2 and y1 <= iy < y2:
            return (item[1], item[2])
    x1 = <int>bounds[0]; y1 = <int>bounds[1]
    x2 = <int>bounds[2]; y2 = <int>bounds[3]
    if x1 <= ix < x2 and y1 <= iy < y2:
        return ('background', -1)
    return None


cpdef tuple popup_hud_dynamic(object content_w, object content_h,
                              double phase, object plate_pad,
                              object hud_margin, object bracket_len):
    """Return dynamic HUD frame coordinates shared by Canvas/PIL paths."""
    cdef int cw = <int>_safe_i64(content_w, 260)
    cdef int ch = <int>_safe_i64(content_h, 180)
    cdef int pp = <int>_safe_i64(plate_pad, 16)
    cdef int hm = <int>_safe_i64(hud_margin, 6)
    cdef int bl = <int>_safe_i64(bracket_len, 16)
    cdef int cx1 = pp - hm
    cdef int cy1 = pp - hm
    cdef int cx2 = pp + cw + hm
    cdef int cy2 = pp + ch + hm
    cdef double scan_period = 6.0
    cdef double scan_pos = (phase % scan_period) / scan_period
    cdef int scan_y = <int>(<double>cy1 + <double>(cy2 - cy1) * scan_pos)
    cdef int dot_travel = cy2 - cy1 - bl * 2
    if dot_travel < 1:
        dot_travel = 1
    cdef int dot_y_l = cy1 + bl + <int>(<double>dot_travel * ((sin(phase * 0.8) + 1.0) * 0.5))
    cdef int dot_y_r = cy1 + bl + <int>(<double>dot_travel * ((sin(phase * 0.8 + 3.141592653589793) + 1.0) * 0.5))
    return (cx1, cy1, cx2, cy2, scan_y, dot_y_l, dot_y_r)


cpdef tuple popup_tick_dt(double tick_now, object last_tick_t):
    """Return ``(dt, tick_now)`` for popup's 60Hz animation clock."""
    cdef double last = _safe_f64(last_tick_t, 0.0)
    cdef double dt
    if last > 0.0:
        dt = tick_now - last
    else:
        dt = 1.0 / 60.0
    if dt < 0.0:
        dt = 0.0
    elif dt > 0.10:
        dt = 0.10
    return (dt, tick_now)


cpdef tuple popup_fade_alpha(double tick_now, object fade_t0,
                             object fade_duration, object fade_target):
    """Return ``(alpha, done, t)`` for popup fade in/out."""
    cdef double dur = _safe_f64(fade_duration, 0.0)
    cdef double target = _safe_f64(fade_target, 1.0)
    if dur <= 0.0:
        dur = 0.45 if target > 0.0 else 0.30
    cdef double t = (tick_now - _safe_f64(fade_t0, tick_now)) / dur
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cdef double alpha = t if target > 0.0 else 1.0 - t
    return (alpha, t >= 1.0, t)


cpdef tuple popup_child_phase_step(object phase, object fade_t, double dt):
    """Advance child fade phase. Returns ``(phase, fade_t, completed)``."""
    cdef str ph = str(phase or 'idle')
    cdef double ft = _safe_f64(fade_t, 1.0)
    cdef bint completed = False
    if ph == 'fadeout':
        ft += dt / 0.16
        if ft > 1.0:
            ft = 1.0
        if ft >= 0.999:
            completed = True
    elif ph == 'fadein':
        ft -= dt / 0.22
        if ft < 0.0:
            ft = 0.0
        if ft <= 0.001:
            ft = 0.0
            ph = 'idle'
            completed = True
    return (ph, ft, completed)


cpdef int popup_max_child_rows(object child_menus):
    """Find the largest child-menu row count."""
    cdef int max_rows = 0
    cdef object items
    try:
        iterable = child_menus.values()
    except Exception:
        return 0
    for items in iterable:
        try:
            if len(items) > max_rows:
                max_rows = <int>len(items)
        except Exception:
            continue
    return max_rows


cpdef object menu_bar_slot_index(object x, object y, object max_size,
                                 object slot, object button_count):
    """Map GPU menubar cursor coords to a button slot index."""
    cdef double fx = _safe_f64(x, -1.0)
    cdef double fy = _safe_f64(y, -1.0)
    cdef int mx = <int>_safe_i64(max_size, 0)
    cdef int sl = <int>_safe_i64(slot, 1)
    cdef int count = <int>_safe_i64(button_count, 0)
    cdef int idx
    if count <= 0 or sl <= 0:
        return None
    if fx < 0.0 or fy < 0.0 or fx >= <double>mx:
        return None
    idx = <int>(fy / <double>sl)
    if idx < 0 or idx >= count:
        return None
    return idx


cpdef tuple menu_bar_snapshot_sig(object strip_w, object strip_h, object snapshots):
    """Build the visual dedup signature for the GPU menu-bar painter."""
    cdef list sig_buttons = []
    cdef object s
    cdef double size_q, hover_q
    if snapshots is None:
        return (<int>_safe_i64(strip_w, 0), <int>_safe_i64(strip_h, 0), 0, ())
    for s in snapshots:
        size_q = <double>(<int>(_safe_f64(getattr(s, 'size', 0.0), 0.0) * 4.0 + 0.5)) / 4.0
        hover_q = <double>(<int>(_safe_f64(getattr(s, 'hover_t', 0.0), 0.0) * 20.0 + 0.5)) / 20.0
        sig_buttons.append((
            size_q,
            hover_q,
            bool(getattr(s, 'active', False)),
            str(getattr(s, 'icon', '') or ''),
        ))
    return (<int>_safe_i64(strip_w, 0), <int>_safe_i64(strip_h, 0),
            <int>len(sig_buttons), tuple(sig_buttons))


cpdef tuple popup_child_snapshot_sig(object out_w, object out_h,
                                     object line_w, object line_h,
                                     object arrow_w, object fade_t,
                                     object bg_hex, object rows):
    """Build the dedup signature for the GPU popup child-bar painter."""
    cdef list row_sig = []
    cdef object row
    cdef int hover_q
    if rows is not None:
        for row in rows:
            hover_q = <int>(_safe_f64(getattr(row, 'hover_t', 0.0), 0.0) * 16.0)
            row_sig.append((
                str(getattr(row, 'icon', '') or ''),
                str(getattr(row, 'label', '') or ''),
                hover_q,
                <int>_safe_i64(getattr(row, 'row_w', 0), 0),
            ))
    return (
        <int>_safe_i64(out_w, 0),
        <int>_safe_i64(out_h, 0),
        <int>_safe_i64(line_w, 0),
        <int>_safe_i64(line_h, 0),
        <int>_safe_i64(arrow_w, 0),
        <int>(_safe_f64(fade_t, 0.0) * 16.0),
        str(bg_hex or ''),
        tuple(row_sig),
    )


cpdef tuple left_info_snapshot_sig(object username, object description,
                                   object top_w, object top_h,
                                   object bottom_w, object bottom_h,
                                   object sweep_phase,
                                   object sweep_strength):
    """Build the dedup signature for the GPU left-info painter."""
    cdef double strength = _safe_f64(sweep_strength, 0.0)
    cdef double phase = _safe_f64(sweep_phase, 0.0)
    cdef double sp_q = 0.0
    cdef double ss_q = 0.0
    if strength > 0.005:
        sp_q = <double>_round_pos(phase * 16.0) / 16.0
        ss_q = <double>_round_pos(strength * 16.0) / 16.0
    return (
        str(username or ''),
        str(description or ''),
        <int>_safe_i64(top_w, 0),
        <int>_safe_i64(top_h, 0),
        <int>_safe_i64(bottom_w, 0),
        <int>_safe_i64(bottom_h, 0),
        sp_q,
        ss_q,
    )


cpdef tuple session_players_snapshot_sig(object rows, object total,
                                         object self_uid,
                                         object first_index,
                                         object width, object height,
                                         object reveal):
    """Build the dedup signature for the GPU session-player list painter."""
    cdef double reveal_q = <double>_round_pos(_safe_f64(reveal, 0.0) * 24.0) / 24.0
    return (
        rows if rows is not None else (),
        <int>_safe_i64(total, 0),
        str(self_uid or ''),
        <int>_safe_i64(first_index, 0),
        <int>_safe_i64(width, 0),
        <int>_safe_i64(height, 0),
        reveal_q,
    )


cpdef tuple player_panel_snapshot_sig(object username, object level,
                                      object level_extra,
                                      object season_exp, object hp,
                                      object sta, object shift_mode,
                                      object top_w, object top_h,
                                      object bottom_w, object bottom_h,
                                      object scan_phase, object out_w,
                                      object out_h):
    """Build the dedup signature for the GPU player-panel painter."""
    cdef int top_height = <int>_safe_i64(top_h, 0)
    cdef double scan_q = 0.0
    if top_height > 185:
        scan_q = <double>_round_pos(_safe_f64(scan_phase, 0.0) * 32.0) / 32.0
    return (
        str(username or ''),
        <int>_safe_i64(level, 0),
        <int>_safe_i64(level_extra, 0),
        <int>_safe_i64(season_exp, 0),
        hp if hp is not None else (),
        sta if sta is not None else (),
        str(shift_mode or ''),
        <int>_safe_i64(top_w, 0),
        top_height,
        <int>_safe_i64(bottom_w, 0),
        <int>_safe_i64(bottom_h, 0),
        scan_q,
        <int>_safe_i64(out_w, 0),
        <int>_safe_i64(out_h, 0),
    )


cpdef tuple dps_rows_signature(object rows):
    """Build the coarse row signature for the DPS overlay."""
    cdef list row_sig = []
    cdef object item
    cdef object row
    cdef object uid
    if not rows:
        return ()
    try:
        for item in rows.items():
            uid = item[0]
            row = item[1]
            row_sig.append((
                uid,
                <int>_safe_i64(getattr(row, 'target_damage', 0), 0),
                <int>_safe_i64(getattr(row, 'target_dps', 0), 0),
                <int>_safe_i64(getattr(row, 'target_heal', 0), 0),
                <int>_safe_i64(getattr(row, 'target_hps', 0), 0),
                round(_safe_f64(getattr(row, 'target_bar_pct', 0.0), 0.0), 4),
                <int>(_safe_f64(getattr(row, 'target_y', 0.0), 0.0) * 1000.0),
            ))
    except Exception:
        return ()
    return tuple(row_sig)


cpdef object dps_detail_signature(object entity):
    """Build the detail-panel signature for the DPS overlay."""
    cdef object skills
    cdef list skill_sig = []
    cdef object skill
    cdef int kept = 0
    if not isinstance(entity, dict):
        return None
    skills = entity.get('skills') or []
    for skill in skills:
        if kept >= 16:
            break
        if not isinstance(skill, dict):
            continue
        skill_sig.append((
            <int>_safe_i64(skill.get('skill_id'), 0),
            <int>_safe_i64(skill.get('total'), 0),
            <int>_safe_i64(skill.get('heal_total'), 0),
            <int>_safe_i64(skill.get('hits'), 0),
            <int>_safe_i64(skill.get('heal_hits'), 0),
        ))
        kept += 1
    return (
        <int>_safe_i64(entity.get('uid'), 0),
        <int>_safe_i64(entity.get('damage_total'), 0),
        <int>_safe_i64(entity.get('heal_total'), 0),
        <int>_safe_i64(entity.get('max_hit'), 0),
        len(skills),
        tuple(skill_sig),
    )


cpdef tuple hp_idle_signature(object y_off, object fade_alpha,
                              object hp_group_alpha, object profession,
                              object name, object uid, object level,
                              object hp_max, object hp_pct,
                              object sta_pct, object sta_text,
                              bint sta_offline, object boss_timer_text,
                              bint boss_timer_urgent, object clock_q,
                              object link_q, object tl_pulse_q,
                              object br_pulse_q, object scan_q,
                              object outer_q, object cover_q,
                              object cover_sweep_q, object hover_id,
                              object hover_hp, object press_id,
                              object press_hp, object flash_id,
                              object flash_hp):
    """Build the steady-state dirty-skip signature for the HP overlay."""
    cdef double hp_p = _safe_f64(hp_pct, 0.0)
    cdef double sta_p = _safe_f64(sta_pct, 0.0)
    cdef int max_int = <int>_round_even(_safe_f64(hp_max, 0.0))
    cdef int bucket = 1
    cdef int hp_int
    cdef int sta_pct_q
    if hp_p < 0.0:
        hp_p = 0.0
    elif hp_p > 1.0:
        hp_p = 1.0
    if sta_p < 0.0:
        sta_p = 0.0
    elif sta_p > 1.0:
        sta_p = 1.0
    if max_int > 0:
        bucket = max(1, max_int // 1000)
    hp_int = (<int>_round_even(_safe_f64(hp_max, 0.0) * hp_p) // bucket) * bucket
    sta_pct_q = <int>_round_even(sta_p * 100.0)
    return (
        <int>_safe_i64(y_off, 0),
        <int>_round_even(_safe_f64(fade_alpha, 0.0) * 100.0),
        <int>(_safe_f64(hp_group_alpha, 0.0) * 24.0),
        profession,
        name,
        uid,
        level,
        hp_int,
        max_int,
        sta_pct_q,
        sta_text,
        bool(sta_offline),
        boss_timer_text,
        bool(boss_timer_urgent),
        <int>_safe_i64(clock_q, 0),
        <int>_safe_i64(link_q, 0),
        <int>_safe_i64(tl_pulse_q, 0),
        <int>_safe_i64(br_pulse_q, 0),
        <int>_safe_i64(scan_q, 0),
        <int>_safe_i64(outer_q, 0),
        <int>_safe_i64(cover_q, 0),
        <int>_safe_i64(cover_sweep_q, 0),
        <int>_safe_i64(hover_id, 0),
        <int>_safe_i64(hover_hp, 0),
        <int>_safe_i64(press_id, 0),
        <int>_safe_i64(press_hp, 0),
        <int>_safe_i64(flash_id, 0),
        <int>_safe_i64(flash_hp, 0),
    )


cdef inline int _fx_age_q(double start, double dur, double now):
    cdef double age
    if start <= 0.0 or dur <= 0.0:
        return -1
    age = now - start
    if age < 0.0 or age >= dur:
        return -1
    return <int>(age * 33.3)


cpdef object bosshp_frame_signature(object visible, object width,
                                    object height, object y_off,
                                    object boss_name, object hp_source,
                                    object current_hp, object total_hp,
                                    object disp_hp_pct,
                                    object disp_trail_pct,
                                    object disp_shield_pct,
                                    object disp_break_pct,
                                    bint shield_active,
                                    object breaking_stage,
                                    bint in_overdrive,
                                    bint invincible,
                                    object fade_alpha, object now,
                                    object damage_flash_start,
                                    object damage_flash_dur,
                                    object break_burst_start,
                                    object break_burst_dur,
                                    object shield_break_start,
                                    object shield_break_dur,
                                    object shield_vfx_mode,
                                    object shield_vfx_start,
                                    object shield_vfx_dur,
                                    object break_vfx_mode,
                                    object break_vfx_start,
                                    object break_vfx_dur,
                                    object root_pulse_mode,
                                    object root_pulse_start,
                                    object root_pulse_dur,
                                    object additional_units):
    """Build the cached frame signature for the BossHP overlay."""
    cdef int w = <int>_safe_i64(width, 0)
    cdef int h = <int>_safe_i64(height, 0)
    cdef int stage = <int>_safe_i64(breaking_stage, 0)
    cdef double now_f = _safe_f64(now, 0.0)
    cdef int damage_q
    cdef int burst_q
    cdef int sbreak_q
    cdef int svfx_q
    cdef int bvfx_q
    cdef int rpulse_q
    cdef int shield_sweep_q = -1
    cdef int od_q = -1
    cdef int br_phase_q = -1
    cdef list add_sig = []
    cdef object unit
    if not bool(visible) or w <= 0 or h <= 0:
        return None

    damage_q = _fx_age_q(_safe_f64(damage_flash_start, 0.0),
                         _safe_f64(damage_flash_dur, 0.0), now_f)
    burst_q = _fx_age_q(_safe_f64(break_burst_start, 0.0),
                        _safe_f64(break_burst_dur, 0.0), now_f)
    sbreak_q = _fx_age_q(_safe_f64(shield_break_start, 0.0),
                         _safe_f64(shield_break_dur, 0.0), now_f)
    if shield_vfx_mode:
        svfx_q = _fx_age_q(_safe_f64(shield_vfx_start, 0.0),
                           _safe_f64(shield_vfx_dur, 0.0), now_f)
    else:
        svfx_q = -1
    if break_vfx_mode:
        bvfx_q = _fx_age_q(_safe_f64(break_vfx_start, 0.0),
                           _safe_f64(break_vfx_dur, 0.0), now_f)
    else:
        bvfx_q = -1
    if root_pulse_mode:
        rpulse_q = _fx_age_q(_safe_f64(root_pulse_start, 0.0),
                             _safe_f64(root_pulse_dur, 0.0), now_f)
    else:
        rpulse_q = -1
    if shield_active and _safe_f64(disp_shield_pct, 0.0) > 0.01:
        shield_sweep_q = <int>(((now_f * 0.71) % 1.0) * 28.0)
    if in_overdrive:
        od_q = <int>(((now_f * 4.0) % 1.0) * 32.0)
    if stage > 0:
        br_phase_q = <int>(((now_f * 1.6) % 1.0) * 24.0)

    if additional_units is not None:
        for unit in additional_units:
            add_sig.append((
                str(unit.get('name') or ''),
                <int>_round_even(_safe_f64(unit.get('hp_pct'), 0.0) * 100.0),
                <int>_round_even(_safe_f64(unit.get('extinction_pct'), 0.0) * 100.0),
                bool(unit.get('has_break_data', False)),
                <int>_safe_i64(unit.get('breaking_stage'), -1),
                bool(unit.get('shield_active', False)),
                <int>_round_even(_safe_f64(unit.get('shield_pct'), 0.0) * 100.0),
            ))

    return (
        w, h, <int>_safe_i64(y_off, 0),
        boss_name, hp_source,
        <int>_safe_i64(current_hp, 0), <int>_safe_i64(total_hp, 0),
        <int>_round_even(_safe_f64(disp_hp_pct, 0.0) * 200.0),
        <int>_round_even(_safe_f64(disp_trail_pct, 0.0) * 200.0),
        <int>_round_even(_safe_f64(disp_shield_pct, 0.0) * 200.0),
        <int>_round_even(_safe_f64(disp_break_pct, 0.0) * 200.0),
        bool(shield_active),
        stage,
        bool(in_overdrive),
        bool(invincible),
        <int>_round_even(_safe_f64(fade_alpha, 0.0) * 100.0),
        damage_q, burst_q, sbreak_q,
        svfx_q, bvfx_q, rpulse_q,
        shield_vfx_mode, break_vfx_mode, root_pulse_mode,
        shield_sweep_q, od_q, br_phase_q,
        tuple(add_sig),
    )


cdef inline long _round_even(double v):
    cdef double fl = floor(v)
    cdef double frac = v - fl
    cdef long base = <long>fl
    if frac > 0.5:
        return base + 1
    if frac < 0.5:
        return base
    if base & 1:
        return base + 1
    return base


cpdef tuple hp_layout_metrics(object screen_w, double hud_vw_pct,
                              double stage_width_pct, double shadow_gutter,
                              object cover_w, object box_w, object sta_w):
    """Compute HP overlay CSS-derived layout metrics."""
    cdef int sw = <int>_safe_i64(screen_w, 1920)
    if sw < 1:
        sw = 1
    cdef int viewport_w = <int>_round_even(<double>sw * hud_vw_pct)
    cdef int stage_w = <int>_round_even(<double>viewport_w * stage_width_pct)
    cdef int id_x = <int>_round_even(<double>stage_w * 0.032 - 25.0)
    cdef int id_w = <int>_round_even(<double>stage_w * 0.396 + 55.0)
    cdef int cover_x = <int>_round_even(<double>stage_w * 0.452 + 25.0)
    cdef int box_x = <int>_round_even(<double>stage_w * 0.47 + 25.0)
    cdef int sta_x = box_x
    cdef int right_edge = id_x + id_w
    cdef int tmp = cover_x + <int>_safe_i64(cover_w, 0)
    if tmp > right_edge:
        right_edge = tmp
    tmp = box_x + <int>_safe_i64(box_w, 0)
    if tmp > right_edge:
        right_edge = tmp
    tmp = sta_x + <int>_safe_i64(sta_w, 0)
    if tmp > right_edge:
        right_edge = tmp
    cdef int panel_w = <int>(<double>right_edge + shadow_gutter)
    if (<double>panel_w) < (<double>right_edge + shadow_gutter):
        panel_w += 1
    return (stage_w, panel_w, id_x, id_w, cover_x, box_x, sta_x)


cpdef int hp_stage_screen_x(object screen_w, double window_left_pct,
                            double hud_vw_pct, double stage_left_pct):
    """Screen X for the HP stage anchor."""
    cdef int sw = <int>_safe_i64(screen_w, 1920)
    return <int>_round_even(<double>sw * window_left_pct
                            + <double>sw * hud_vw_pct * stage_left_pct)


cpdef str hp_fmt_int(object value):
    """Comma-format a rounded HP/STA numeric value."""
    try:
        return f'{_round_even(float(value)):,}'
    except Exception:
        return str(value)


cdef inline long _round_half_up_nonneg(double value):
    if value <= 0.0:
        return 0
    return <long>(value + 0.5)


cpdef str dps_to_fixed_half_up(object value, int digits):
    """Fast non-negative half-up fixed formatter for DPS UI numbers."""
    cdef double v
    cdef double scale = 1.0
    cdef long rounded
    cdef long whole
    cdef long frac
    cdef int i
    try:
        v = float(value)
    except Exception:
        v = 0.0
    if digits <= 0:
        return str(_round_half_up_nonneg(v))
    for i in range(digits):
        scale *= 10.0
    rounded = _round_half_up_nonneg(v * scale)
    whole = rounded // <long>scale
    frac = rounded - whole * <long>scale
    return f'{whole}.{frac:0{digits}d}'


cpdef long dps_round_half_up_int(object value):
    try:
        return _round_half_up_nonneg(float(value))
    except Exception:
        return 0


cpdef str dps_fmt_num(object value):
    cdef double v
    try:
        v = float(value or 0)
    except Exception:
        v = 0.0
    if v >= 1000000.0:
        return f'{dps_to_fixed_half_up(v / 1000000.0, 0 if v >= 10000000.0 else 1)}M'
    if v >= 1000.0:
        return f'{dps_to_fixed_half_up(v / 1000.0, 0 if v >= 100000.0 else 1)}K'
    return f'{_round_half_up_nonneg(v):,}'


cpdef str dps_fmt_fp(object value):
    cdef double fp
    try:
        fp = float(value or 0)
    except Exception:
        fp = 0.0
    if fp <= 0.0:
        return ''
    if fp >= 1000000.0:
        return f'{dps_to_fixed_half_up(fp / 1000000.0, 2)}M'
    if fp >= 1000.0:
        return f'{dps_to_fixed_half_up(fp / 1000.0, 0 if fp >= 100000.0 else 1)}K'
    return f'{_round_half_up_nonneg(fp):,}'


cpdef str dps_fmt_time(object seconds):
    cdef long s
    try:
        s = <long>float(seconds or 0)
    except Exception:
        s = 0
    if s < 0:
        s = 0
    return f'{s // 60:02d}:{s % 60:02d}'


cpdef double ease_out_cubic(double t):
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t)


cpdef double lerp_clamped(double a, double b, double t):
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return a + (b - a) * t


cdef inline str _normalize_hex_rgb(object color):
    cdef str raw = str(color or '').strip()
    if raw.startswith('#'):
        raw = raw[1:]
    if len(raw) == 8:
        raw = raw[:6]
    elif len(raw) == 3:
        raw = raw[0] * 2 + raw[1] * 2 + raw[2] * 2
    if len(raw) != 6:
        return ''
    return raw.lower()


cpdef str lerp_hex_color(object c1, object c2, double t):
    """RGB hex lerp with support for #rgb / #rrggbb / #rrggbbaa inputs."""
    cdef str raw1
    cdef str raw2
    cdef int r1
    cdef int g1
    cdef int b1
    cdef int r2
    cdef int g2
    cdef int b2
    cdef int r
    cdef int g
    cdef int b
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    raw1 = _normalize_hex_rgb(c1)
    raw2 = _normalize_hex_rgb(c2)
    if not raw1 or not raw2:
        return str(c1 or '#000000')
    try:
        r1 = int(raw1[0:2], 16)
        g1 = int(raw1[2:4], 16)
        b1 = int(raw1[4:6], 16)
        r2 = int(raw2[0:2], 16)
        g2 = int(raw2[2:4], 16)
        b2 = int(raw2[4:6], 16)
    except Exception:
        return str(c1 or '#000000')
    r = <int>(r1 + (r2 - r1) * t)
    g = <int>(g1 + (g2 - g1) * t)
    b = <int>(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


cpdef tuple menu_circle_palette(bint active, double hover_t,
                                object circle_border, object active_border,
                                object circle_bg, object hover_bg,
                                object circle_icon, object hover_icon,
                                object active_bg, object active_icon):
    """Return ``(border, fill, icon)`` for the CPU menu-circle path."""
    if active:
        return (str(active_border or ''),
                str(active_bg or ''),
                str(active_icon or ''))
    if hover_t < 0.0:
        hover_t = 0.0
    elif hover_t > 1.0:
        hover_t = 1.0
    return (
        lerp_hex_color(circle_border, active_border, hover_t),
        lerp_hex_color(circle_bg, hover_bg, hover_t),
        lerp_hex_color(circle_icon, hover_icon, hover_t),
    )


cpdef tuple popup_child_hover_palette(double hover_t,
                                      object child_bg, object child_hover,
                                      object child_text,
                                      object child_hover_fg,
                                      object child_icon,
                                      object active_border):
    """Return ``(bg, fg, icon_fg, ind_color, arr_fg)`` for CPU child-row hover."""
    if hover_t < 0.0:
        hover_t = 0.0
    elif hover_t > 1.0:
        hover_t = 1.0
    return (
        lerp_hex_color(child_bg, child_hover, hover_t),
        lerp_hex_color(child_text, child_hover_fg, hover_t),
        lerp_hex_color(child_icon, child_hover_fg, hover_t),
        lerp_hex_color(child_bg, active_border, hover_t),
        lerp_hex_color(child_bg, child_hover_fg, hover_t),
    )


cpdef tuple popup_child_fade_palette(double hover_t, double fade_t,
                                     object fade_bg, object child_bg,
                                     object child_hover, object child_text,
                                     object child_hover_fg,
                                     object child_icon,
                                     object active_border):
    """Return ``(bg, fg, icon_fg, ind_color, arr_fg)`` for CPU child-row fade."""
    cdef str bg_now
    cdef str fg_now
    cdef str icon_now
    cdef str ind_now
    cdef str arr_now
    if fade_t < 0.0:
        fade_t = 0.0
    elif fade_t > 1.0:
        fade_t = 1.0
    bg_now, fg_now, icon_now, ind_now, arr_now = popup_child_hover_palette(
        hover_t, child_bg, child_hover, child_text,
        child_hover_fg, child_icon, active_border)
    return (
        lerp_hex_color(bg_now, fade_bg, fade_t),
        lerp_hex_color(fg_now, fade_bg, fade_t),
        lerp_hex_color(icon_now, fade_bg, fade_t),
        lerp_hex_color(ind_now, fade_bg, fade_t),
        lerp_hex_color(arr_now, fade_bg, fade_t),
    )


cpdef tuple popup_child_row_anim_step(double now, double anim_t0,
                                      object index, double stagger_s,
                                      double duration_s, object start_w,
                                      object target_w):
    """Return ``(width, keep_animating)`` for the CPU child-row width tween."""
    cdef int idx = <int>_safe_i64(index, 0)
    cdef int sw = <int>_safe_i64(start_w, 72)
    cdef int tw = <int>_safe_i64(target_w, 240)
    cdef double local_t
    cdef double eased
    if sw < 1:
        sw = 1
    if tw < 1:
        tw = 1
    if duration_s <= 0.0:
        return (tw, False)
    local_t = (now - anim_t0 - idx * stagger_s) / duration_s
    if local_t < 0.0:
        local_t = 0.0
    elif local_t > 1.0:
        local_t = 1.0
    eased = 1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t))
    return (<int>_round_even(sw + (tw - sw) * eased), local_t < 1.0)


cpdef tuple menu_hud_breath_offsets(double elapsed, bint force_zero):
    """Return 2px-quantized HUD drift for the CPU menu overlay."""
    cdef double raw_dx
    cdef double raw_dy
    if force_zero:
        return (0, 0)
    raw_dx = 4.8 * sin(elapsed * 0.44) + 1.8 * sin(elapsed * 0.96)
    raw_dy = 3.8 * sin(elapsed * 0.32 + 1.0) + 1.4 * sin(elapsed * 0.79)
    return (
        <int>(_round_even(raw_dx / 2.0) * 2),
        <int>(_round_even(raw_dy / 2.0) * 2),
    )


cpdef double menu_hud_phase_quantized(double elapsed, bint force_full_rate):
    """Return a cache-friendly HUD phase for the CPU canvas path."""
    if force_full_rate:
        return elapsed
    if elapsed <= 0.0:
        return 0.0
    return _round_even(elapsed * 30.0) / 30.0


cpdef tuple menu_bar_button_size_step(double now, object current_size,
                                      bint enter_active, double enter_t0,
                                      object index, double enter_delay_s,
                                      double enter_duration_s, object hover_idx,
                                      double base_size, double size_eps,
                                      double size_lerp):
    """Return ``(new_size, keep_animating, cursor_ready)`` for one CPU menu button."""
    cdef int idx = <int>_safe_i64(index, 0)
    cdef double cur = _safe_f64(current_size, base_size)
    cdef double local_t
    cdef double target
    cdef double delta
    cdef int dist
    if enter_active:
        if enter_duration_s <= 0.0:
            local_t = 1.0
        else:
            local_t = (now - enter_t0 - idx * enter_delay_s) / enter_duration_s
        if local_t < 0.0:
            local_t = 0.0
        elif local_t > 1.0:
            local_t = 1.0
        return (
            <double>(1 if _round_even(base_size * (1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t)))) < 1
                     else _round_even(base_size * (1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t))))),
            local_t < 1.0,
            local_t >= 1.0,
        )
    if hover_idx is not None:
        dist = <int>_safe_i64(hover_idx, -1) - idx
        if dist < 0:
            dist = -dist
        target = base_size * (1.0 + 0.22 * exp(-0.9 * <double>(dist * dist)))
    else:
        target = base_size
    delta = target - cur
    if delta < 0.0:
        if -delta > size_eps:
            return (cur + delta * size_lerp, True, False)
        return (target, False, False)
    if delta > size_eps:
        return (cur + delta * size_lerp, True, False)
    return (target, False, False)


cpdef tuple menu_bar_advance_buttons(object buttons, double now,
                                     bint enter_active, double enter_t0,
                                     double enter_delay_s,
                                     double enter_duration_s,
                                     object hover_idx, double base_size,
                                     double size_eps, double size_lerp):
    """Advance ``btn._size`` across the whole CPU menu bar in one pass.

    Returns ``(keep_animating, ready_indices_tuple)`` where
    ``ready_indices_tuple`` contains buttons whose enter animation has just
    reached the steady cursor-ready state.
    """
    cdef object btn
    cdef list ready = []
    cdef bint keep = False
    cdef int idx = 0
    cdef int hi = <int>_safe_i64(hover_idx, -1)
    cdef int dist
    cdef double cur
    cdef double target
    cdef double delta
    cdef double local_t
    cdef double new_size
    if not buttons:
        return (False, ())
    for btn in buttons:
        cur = _safe_f64(getattr(btn, '_size', base_size), base_size)
        if enter_active:
            if enter_duration_s <= 0.0:
                local_t = 1.0
            else:
                local_t = (now - enter_t0 - <double>idx * enter_delay_s) / enter_duration_s
            if local_t < 0.0:
                local_t = 0.0
            elif local_t > 1.0:
                local_t = 1.0
            new_size = <double>(1 if _round_even(base_size * (1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t)))) < 1
                               else _round_even(base_size * (1.0 - ((1.0 - local_t) * (1.0 - local_t) * (1.0 - local_t)))))
            btn._size = new_size
            if local_t < 1.0:
                keep = True
            else:
                ready.append(idx)
        else:
            if hover_idx is not None:
                dist = hi - idx
                if dist < 0:
                    dist = -dist
                target = base_size * (1.0 + 0.22 * exp(-0.9 * <double>(dist * dist)))
            else:
                target = base_size
            delta = target - cur
            if delta < 0.0:
                if -delta > size_eps:
                    btn._size = cur + delta * size_lerp
                    keep = True
                else:
                    btn._size = target
            elif delta > size_eps:
                btn._size = cur + delta * size_lerp
                keep = True
            else:
                btn._size = target
        idx += 1
    return (keep, tuple(ready))


cpdef tuple menu_circle_visual_metrics(double size_f, double max_size):
    """Return clamped size/offset/signature helpers for CPU menu-circle draw."""
    cdef int size_px
    cdef double size_q
    cdef double off
    cdef int ioff
    cdef bint snap
    if size_f < 1.0:
        size_f = 1.0
    if size_f > max_size:
        size_f = max_size
    size_px = <int>size_f
    if size_f > <double>size_px:
        size_px += 1
    if size_px < 1:
        size_px = 1
    size_q = _round_even(size_f * 4.0) / 4.0
    off = (max_size - size_f) / 2.0
    ioff = <int>_round_even(off)
    snap = _abs_f64(off - <double>ioff) < 0.25
    return (size_f, size_px, size_q, off, ioff, snap)


cpdef tuple menu_plate_sweep_quantized(object sweep_phase,
                                       object sweep_strength,
                                       double strength_scale=1.0):
    """Return quantized ``(phase, strength)`` for CPU menu plate sweeps."""
    cdef double phase = _safe_f64(sweep_phase, 0.0)
    cdef double strength = _safe_f64(sweep_strength, 0.0) * strength_scale
    if strength <= 0.005:
        return (0.0, 0.0)
    return (
        _round_even(phase * 16.0) / 16.0,
        _round_even(strength * 16.0) / 16.0,
    )


cpdef tuple left_panel_progress_dims(double top_t, double bottom_t,
                                     object target_w, object top_h,
                                     object bottom_h, object sweep_phase,
                                     object sweep_strength):
    """Return clamped panel progresses, sweep inputs, and pixel sizes."""
    cdef double tt = top_t
    cdef double bt = bottom_t
    cdef double sp = _safe_f64(sweep_phase, 0.0)
    cdef double ss = _safe_f64(sweep_strength, 0.0)
    cdef int tw = <int>_safe_i64(target_w, 1)
    cdef int th = <int>_safe_i64(top_h, 1)
    cdef int bh = <int>_safe_i64(bottom_h, 1)
    cdef int out_top_w
    cdef int out_top_h
    cdef int out_bottom_w
    cdef int out_bottom_h
    cdef double bottom_ref
    if tt < 0.0:
        tt = 0.0
    elif tt > 1.0:
        tt = 1.0
    if bt < 0.0:
        bt = 0.0
    elif bt > 1.0:
        bt = 1.0
    if sp < 0.0:
        sp = 0.0
    elif sp > 1.0:
        sp = 1.0
    if ss < 0.0:
        ss = 0.0
    elif ss > 1.0:
        ss = 1.0
    bottom_ref = tt
    if bt * 0.94 > bottom_ref:
        bottom_ref = bt * 0.94
    out_top_w = <int>_round_even(<double>tw * tt)
    out_top_h = <int>_round_even(<double>th * tt)
    out_bottom_w = <int>_round_even(<double>tw * bottom_ref)
    out_bottom_h = <int>_round_even(<double>bh * bt)
    if out_top_w < 1:
        out_top_w = 1
    if out_top_h < 1:
        out_top_h = 1
    if out_bottom_w < 1:
        out_bottom_w = 1
    if out_bottom_h < 1:
        out_bottom_h = 1
    return (tt, bt, sp, ss, out_top_w, out_top_h, out_bottom_w, out_bottom_h)


cpdef str bosshp_fmt_hp(object value):
    cdef double v
    try:
        v = float(value or 0)
    except Exception:
        v = 0.0
    if v >= 1000000000.0:
        return f'{v / 1000000000.0:.2f}B'
    if v >= 1000000.0:
        return f'{v / 1000000.0:.2f}M'
    if v >= 10000.0:
        return f'{v / 1000.0:.1f}K'
    return f'{_round_even(v):,}'


cpdef tuple mix_rgba(object a, object b, double t):
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return (
        <int>(int(a[0]) + (int(b[0]) - int(a[0])) * t),
        <int>(int(a[1]) + (int(b[1]) - int(a[1])) * t),
        <int>(int(a[2]) + (int(b[2]) - int(a[2])) * t),
        <int>(int(a[3]) + (int(b[3]) - int(a[3])) * t),
    )


cpdef list offset_poly(object points, int dx, int dy):
    cdef list out = []
    cdef object p
    for p in points:
        out.append((int(p[0]) + dx, int(p[1]) + dy))
    return out


cdef inline int _max_int(int a, int b):
    return a if a > b else b


cdef inline int _round_pos(double v):
    if v >= 0.0:
        return <int>(v + 0.5)
    return <int>(v - 0.5)


cpdef object compute_skillfx_layout(object client_rect, list slot_rects,
                                    list fallback_slot_rects=None):
    """Compute the SkillFX overlay window/viewport/slot layout.

    Inputs:
        client_rect: ``(left, top, right, bottom)`` of the game client.
        slot_rects: list of dicts ``{'index': int, 'screen_rect': {...}}``
            already mapped into screen coords. Pass empty when not yet
            available; we'll fall back to the static layout below.
        fallback_slot_rects: precomputed default ``{'index', 'screen_rect'}``
            list (e.g. from ``get_skill_slot_rects``). Used only when
            ``slot_rects`` is empty.

    Returns ``None`` when no slots are available, otherwise the same dict
    shape ``_get_skillfx_layout`` produced previously (window / viewport /
    slots).
    """
    if not client_rect:
        return None
    cdef int client_left, client_top, client_right, client_bottom
    try:
        client_left = <int>client_rect[0]
        client_top = <int>client_rect[1]
        client_right = <int>client_rect[2]
        client_bottom = <int>client_rect[3]
    except Exception:
        return None
    cdef int client_w = _max_int(1, client_right - client_left)
    cdef int client_h = _max_int(1, client_bottom - client_top)

    cdef list slots = []
    cdef object item
    cdef object rect
    cdef int sx, sy, sw, sh, idx

    if slot_rects:
        for item in slot_rects:
            rect = item.get('screen_rect') if isinstance(item, dict) else None
            if rect is None:
                continue
            try:
                sx = <int>int(rect.get('x', 0))
                sy = <int>int(rect.get('y', 0))
                sw = <int>int(rect.get('w', 0))
                sh = <int>int(rect.get('h', 0))
                idx = <int>int(item.get('index', 0) or 0)
            except Exception:
                continue
            if idx <= 0 or sw <= 0 or sh <= 0:
                continue
            slots.append({
                'index': idx,
                'screen_rect': {'x': sx, 'y': sy, 'w': sw, 'h': sh},
            })

    if not slots and fallback_slot_rects:
        for item in fallback_slot_rects:
            try:
                idx = <int>int(item.get('index', 0) or 0)
                rect = item.get('screen_rect') if isinstance(item, dict) else None
                if rect is None:
                    continue
                sx = <int>int(rect.get('x', 0))
                sy = <int>int(rect.get('y', 0))
                sw = <int>int(rect.get('w', 0))
                sh = <int>int(rect.get('h', 0))
            except Exception:
                continue
            if idx <= 0 or sw <= 0 or sh <= 0:
                continue
            slots.append({
                'index': idx,
                'screen_rect': {'x': sx, 'y': sy, 'w': sw, 'h': sh},
            })

    if not slots:
        return None

    cdef int min_x = (<dict>slots[0])['screen_rect']['x']
    cdef int max_y = (<dict>slots[0])['screen_rect']['y'] + (<dict>slots[0])['screen_rect']['h']
    cdef object s
    cdef int sxx, syy, shh
    for s in slots:
        sxx = (<dict>s)['screen_rect']['x']
        syy = (<dict>s)['screen_rect']['y']
        shh = (<dict>s)['screen_rect']['h']
        if sxx < min_x:
            min_x = sxx
        if syy + shh > max_y:
            max_y = syy + shh

    cdef int pad_x = _max_int(18, _round_pos(<double>client_w * 0.012))
    cdef int pad_y = _max_int(18, _round_pos(<double>client_h * 0.016))
    cdef int pad_left = _max_int(96, _round_pos(<double>client_w * 0.055))
    cdef int pad_right = _max_int(84, _round_pos(<double>client_w * 0.044))
    cdef int win_x = min_x - pad_left
    if win_x < 0:
        win_x = 0
    cdef int win_y = client_top
    if win_y < 0:
        win_y = 0
    cdef int width = (client_right - win_x) + pad_right
    if width < 420:
        width = 420
    cdef int height = (max_y - win_y) + pad_y
    if height < 220:
        height = 220
    cdef int callout_w = _max_int(440, _round_pos(<double>client_w * 0.29))
    cdef int callout_h = _max_int(128, _round_pos(<double>client_h * 0.115))
    cdef int callout_margin_x = _max_int(28, _round_pos(<double>client_w * 0.022))
    cdef int callout_margin_y = _max_int(24, _round_pos(<double>client_h * 0.040))
    cdef int callout_x = width - callout_w - callout_margin_x
    if callout_x < callout_margin_x:
        callout_x = callout_margin_x
    cdef int callout_y = callout_margin_y

    cdef list payload_slots = []
    cdef int rxw, ryw, rww, rhw
    for s in slots:
        rxw = (<dict>s)['screen_rect']['x']
        ryw = (<dict>s)['screen_rect']['y']
        rww = (<dict>s)['screen_rect']['w']
        rhw = (<dict>s)['screen_rect']['h']
        idx = (<dict>s)['index']
        payload_slots.append({
            'index': idx,
            'rect': {'x': rxw - win_x, 'y': ryw - win_y, 'w': rww, 'h': rhw},
        })
    payload_slots.sort(key=_slot_index_key)

    cdef int padding_x_final = pad_x
    if pad_left > padding_x_final:
        padding_x_final = pad_left
    if pad_right > padding_x_final:
        padding_x_final = pad_right

    return {
        'window': {'x': win_x, 'y': win_y, 'w': width, 'h': height},
        'viewport': {
            'width': width, 'height': height,
            'padding_x': padding_x_final, 'padding_y': pad_y,
            'callout': {'x': callout_x, 'y': callout_y,
                        'w': callout_w, 'h': callout_h},
        },
        'slots': payload_slots,
    }


cdef inline object _slot_index_key(dict s):
    return s['index']


cpdef long long pick_burst_trigger_slot(object slots, object watched,
                                        long long prev_slot):
    """Burst-anchor selection state machine.

    Inputs:
        slots: list of dicts (gs.skill_slots)
        watched: iterable of int slot indices (already normalized)
        prev_slot: last anchored slot for stability heuristic

    Returns the chosen slot index (long long); 0 means "no anchor".
    Selection priority matches the original Python:
        edge → prev (still ok) → first ready → first active → first low_cd
    """
    cdef set watched_set = set()
    cdef long long s
    for raw in (watched or []):
        try:
            s = <long long>int(raw)
        except Exception:
            continue
        if s > 0:
            watched_set.add(s)
    if not watched_set:
        watched_set.add(1)

    cdef long long edge_slot = 0
    cdef long long first_ready = 0
    cdef long long first_active = 0
    cdef long long first_low_cd = 0
    cdef bint prev_still_ok = False
    cdef long long idx
    cdef double cd
    cdef bint is_ready
    cdef str state
    cdef object slot
    cdef object state_obj
    cdef object cd_obj

    for slot in (slots or []):
        if not isinstance(slot, dict):
            continue
        try:
            idx = <long long>int(slot.get('index', 0) or 0)
        except Exception:
            continue
        if idx <= 0 or idx not in watched_set:
            continue

        state_obj = slot.get('state', '')
        if state_obj is None:
            state = ''
        else:
            state = str(state_obj).strip().lower()
        cd_obj = slot.get('cooldown_pct', 1.0)
        cd = _safe_f64(cd_obj, 1.0)
        is_ready = (state == 'ready') or (state == 'active') or cd <= 0.02

        if slot.get('ready_edge') and edge_slot == 0:
            edge_slot = idx
        if state == 'ready' and first_ready == 0:
            first_ready = idx
        if state == 'active' and first_active == 0:
            first_active = idx
        if cd <= 0.02 and first_low_cd == 0:
            first_low_cd = idx
        if idx == prev_slot and is_ready:
            prev_still_ok = True

    if edge_slot != 0:
        return edge_slot
    if prev_still_ok and prev_slot != 0:
        return prev_slot
    if first_ready != 0:
        return first_ready
    if first_active != 0:
        return first_active
    if first_low_cd != 0:
        return first_low_cd
    return 0


# ══════════════════════════════════════════════════════════
#  Phase 4: ULW RGBA → premultiplied BGRA (uint8, no float)
# ══════════════════════════════════════════════════════════

cpdef void premultiply_rgba_to_bgra(
    const unsigned char[:, :, :] rgba,
    unsigned char[:, :, :] bgra,
) noexcept:
    """Convert RGBA uint8 image to premultiplied-alpha BGRA uint8 in-place.

    Parameters
    ----------
    rgba : memoryview (h, w, 4) uint8 — source RGBA pixels.
    bgra : memoryview (h, w, 4) uint8 — destination buffer (must be same shape).

    The caller is responsible for allocating ``bgra`` with the correct shape.
    This function runs with the GIL released for maximum throughput.
    """
    cdef Py_ssize_t h = rgba.shape[0]
    cdef Py_ssize_t w = rgba.shape[1]
    cdef Py_ssize_t y, x
    cdef unsigned int r, g, b, a
    with nogil:
        for y in range(h):
            for x in range(w):
                r = rgba[y, x, 0]
                g = rgba[y, x, 1]
                b = rgba[y, x, 2]
                a = rgba[y, x, 3]
                # premultiply: channel = channel * alpha / 255
                # Use (c * a + 127) / 255 for better rounding
                bgra[y, x, 0] = <unsigned char>((b * a + 127) // 255)  # B
                bgra[y, x, 1] = <unsigned char>((g * a + 127) // 255)  # G
                bgra[y, x, 2] = <unsigned char>((r * a + 127) // 255)  # R
                bgra[y, x, 3] = <unsigned char>a


# ══════════════════════════════════════════════════════════
#  Phase 5: Batch signature building (replaces Python sorted+tuple)
# ══════════════════════════════════════════════════════════

cpdef tuple build_batch_sig(list batch):
    """Build a sorted signature tuple from a player roster batch.

    Each element of *batch* is a tuple ``(uid, name, prof, fp, lv)``.
    Returns ``tuple(sorted(batch))`` — equivalent to the Python code in
    ``_push_packet_overlays`` but avoids Python-level sort overhead for
    the common case of small rosters (4-8 players).
    """
    if not batch:
        return ()
    cdef list copy = list(batch)
    copy.sort()
    return tuple(copy)


cpdef tuple build_boss_bar_sig(dict data, list additional):
    """Build the boss-bar overlay signature tuple.

    Mirrors the ``_bb_sig`` construction in ``_push_packet_overlays``.
    Moves the many ``int()/float()/bool()/round()`` calls into Cython
    to reduce per-tick Python overhead.
    """
    cdef bint active = bool(data.get('active', False))
    cdef double hp_pct = _safe_f64(data.get('hp_pct'), 0.0)
    cdef str hp_source = str(data.get('hp_source') or '')
    cdef long long current_hp = _safe_i64(data.get('current_hp'), 0)
    cdef long long total_hp = _safe_i64(data.get('total_hp'), 0)
    cdef bint shield_active = bool(data.get('shield_active', False))
    cdef double shield_pct = _safe_f64(data.get('shield_pct'), 0.0)
    cdef long long breaking_stage = _safe_i64(data.get('breaking_stage'), 0)
    cdef bint has_break_data = bool(data.get('has_break_data', False))
    cdef double extinction_pct = _safe_f64(data.get('extinction_pct'), 0.0)
    cdef long long extinction = _safe_i64(data.get('extinction'), 0)
    cdef long long max_extinction = _safe_i64(data.get('max_extinction'), 0)
    cdef bint stop_breaking_ticking = bool(data.get('stop_breaking_ticking', False))
    cdef bint in_overdrive = bool(data.get('in_overdrive', False))
    cdef bint invincible = bool(data.get('invincible', False))
    cdef str boss_name = str(data.get('boss_name') or '')

    # Build additional sub-tuple
    cdef list add_items = []
    cdef dict u
    for u_obj in (additional or []):
        u = <dict>u_obj
        add_items.append((
            str(u.get('name') or ''),
            round(_safe_f64(u.get('hp_pct'), 0.0), 3),
            round(_safe_f64(u.get('extinction_pct'), 0.0), 3),
            bool(u.get('has_break_data', False)),
            <int>_safe_i64(u.get('breaking_stage'), -1),
            bool(u.get('shield_active', False)),
            round(_safe_f64(u.get('shield_pct'), 0.0), 3),
        ))

    return (
        active,
        hp_pct,
        hp_source,
        current_hp,
        total_hp,
        shield_active,
        shield_pct,
        breaking_stage,
        has_break_data,
        extinction_pct,
        extinction,
        max_extinction,
        stop_breaking_ticking,
        in_overdrive,
        invincible,
        boss_name,
        tuple(add_items),
    )


cdef inline tuple _f2_tuple(object value):
    """Coerce a 2-component vec input to (double, double). Accepts tuple/list."""
    cdef double a = 0.0
    cdef double b = 0.0
    if value is None:
        return (0.0, 0.0)
    try:
        a = <double>float(value[0])
        b = <double>float(value[1])
    except Exception:
        return (0.0, 0.0)
    return (a, b)


cpdef tuple unpack_skillfx_params(dict params):
    """D5/E5: typed unpack of the 21 GL uniforms read per skillfx frame.

    Replaces the 21 ``params.get`` + 6 ``tuple(map(float, ...))`` + 13
    ``float(...)`` calls in ``SkillFXShaderPipeline.render`` /
    ``render_premultiplied_bytes`` with one cython call that produces a
    pre-typed tuple. moderngl Uniform.value still drives the GL driver
    set — that part stays — but the per-frame Python boxing on the way in
    moves out of the GIL-heavy hot path.

    Returns a 16-tuple, order matches the call sites:
        (u_time, u_alpha_mul, u_anchor, u_r_out, u_r_in, u_r_core,
         u_pulse, u_beam_a, u_beam_b, u_beam_h, u_show_age, u_exiting,
         u_glfx_intensity, u_seed, u_gl_anchor, u_gl_label, u_gl_panel_size)
    """
    cdef double u_time = _safe_f64(params.get('time', 0.0), 0.0)
    cdef double u_alpha_mul = _safe_f64(params.get('alpha_mul', 1.0), 1.0)
    cdef tuple u_anchor = _f2_tuple(params.get('anchor', (0.0, 0.0)))
    cdef double u_r_out = _safe_f64(params.get('r_out', 0.0), 0.0)
    cdef double u_r_in = _safe_f64(params.get('r_in', 0.0), 0.0)
    cdef double u_r_core = _safe_f64(params.get('r_core', 0.0), 0.0)
    cdef double u_pulse = _safe_f64(params.get('pulse', 0.5), 0.5)
    cdef tuple u_beam_a = _f2_tuple(params.get('beam_a', (0.0, 0.0)))
    cdef tuple u_beam_b = _f2_tuple(params.get('beam_b', (0.0, 0.0)))
    cdef double u_beam_h = _safe_f64(params.get('beam_h', 30.0), 30.0)
    cdef double u_show_age = _safe_f64(params.get('show_age', 0.0), 0.0)
    cdef double u_exiting = 1.0 if params.get('exiting') else 0.0
    cdef double u_glfx_intensity = _safe_f64(params.get('glfx_intensity', 0.0), 0.0)
    cdef double u_seed = _safe_f64(params.get('seed', 1.0), 1.0)
    cdef tuple u_gl_anchor = _f2_tuple(params.get('gl_anchor', (0.0, 0.0)))
    cdef tuple u_gl_label = _f2_tuple(params.get('gl_label', (0.0, 0.0)))
    cdef tuple u_gl_panel_size = _f2_tuple(params.get('gl_panel_size', (0.0, 0.0)))
    return (u_time, u_alpha_mul, u_anchor, u_r_out, u_r_in, u_r_core,
            u_pulse, u_beam_a, u_beam_b, u_beam_h, u_show_age, u_exiting,
            u_glfx_intensity, u_seed, u_gl_anchor, u_gl_label, u_gl_panel_size)


cpdef list sort_recent_monsters(list monsters, dict recent_targets):
    """Sort monster list by (hp_pct DESC, last_damage_ts DESC).

    Mirrors the ``_sort_key`` lambda in ``_push_packet_overlays``.
    Each element is a monster object with ``.hp``, ``.max_hp``, ``.uuid``
    attributes.
    """
    if not monsters:
        return []
    cdef list decorated = []
    cdef object m
    cdef long long hp, maxhp
    cdef double hp_pct, last_ts
    for m in monsters:
        hp = _safe_i64(getattr(m, 'hp', 0), 0)
        maxhp = _safe_i64(getattr(m, 'max_hp', 0), 0)
        if maxhp <= 0:
            maxhp = hp if hp > 0 else 1
        hp_pct = <double>hp / <double>maxhp if maxhp > 0 else 0.0
        last_ts = _safe_f64(recent_targets.get(getattr(m, 'uuid', 0), 0), 0.0)
        decorated.append((-hp_pct, -last_ts, m))
    decorated.sort()
    cdef list result = []
    for item in decorated:
        result.append(item[2])
    return result
