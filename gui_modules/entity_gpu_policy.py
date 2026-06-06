# -*- coding: utf-8 -*-
"""GPU-required policy helpers for Entity overlays.

Entity rendering is GPU-only for the 3.x path.  Do not add Tk/ULW
fallbacks here: missing GLFW/ModernGL is a hard runtime error so the
caller can fail loudly instead of silently selecting a CPU renderer.
"""

from __future__ import annotations

from typing import Any


class EntityGpuRequiredError(RuntimeError):
    """Raised when an Entity overlay is requested without usable GPU support."""


def _gpu_unavailable_reason(gow: Any) -> str:
    if gow is None:
        return 'render.gpu_overlay_window could not be imported'
    try:
        import_error = getattr(gow, '_import_error', '')
    except Exception:
        import_error = ''
    if import_error:
        return str(import_error)
    return 'GLFW/ModernGL overlay backend is unavailable'


def require_entity_gpu(panel_name: str, gow: Any) -> bool:
    """Return True only when the shared Entity GPU backend is usable.

    Raises:
        EntityGpuRequiredError: if GPU support is unavailable.  This is
            intentional: Entity panels must not fall back to Tk/ULW.
    """
    try:
        supported = bool(gow is not None and gow.glfw_supported())
    except Exception as exc:
        raise EntityGpuRequiredError(
            f'{panel_name} requires GPU overlay support; backend probe failed: '
            f'{type(exc).__name__}: {exc}'
        ) from exc
    if supported:
        return True
    reason = _gpu_unavailable_reason(gow)
    raise EntityGpuRequiredError(
        f'{panel_name} requires GPU overlay support. No Tk/ULW fallback is available. '
        f'Reason: {reason}'
    )
