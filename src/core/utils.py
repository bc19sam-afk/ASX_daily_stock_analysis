# -*- coding: utf-8 -*-
"""Shared small utility helpers for core report builders."""

from __future__ import annotations

import math
from typing import Any, Optional


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """Convert value to float, returning default on failure."""
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def is_failed_analysis(result: Any) -> bool:
    """Check if an analysis result represents a failure."""
    if not getattr(result, "success", True):
        return True
    status = str(getattr(result, "analysis_status", "") or "").strip().upper()
    return status == "FAILED"
