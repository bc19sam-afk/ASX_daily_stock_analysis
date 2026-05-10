# -*- coding: utf-8 -*-
"""Display-only historical stats for similar analysis signals.

The service is intentionally read-only and never participates in current
decision generation. It uses trusted historical basis dates to evaluate what
happened after prior reports with the same internal signal grouping.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from datetime import date, datetime
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import desc, select

from src.core.validator import normalize_validation_status
from src.repositories.stock_repo import StockRepository
from src.storage import AnalysisHistory, DatabaseManager

logger = logging.getLogger(__name__)

SIGNAL_HISTORY_CONTRACT_VERSION = "similar_signal_history_v1"
DISPLAY_NOTE = "仅供历史参考，不改变当前建议。"
SIMILARITY_LABEL = "同类历史信号"
DEFAULT_FORWARD_WINDOWS = (5, 10, 20)
LOW_SAMPLE_THRESHOLD = 20


class SignalHistoryStatsService:
    """Build display-only forward-return stats for similar historical signals."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        *,
        windows: Iterable[int] = DEFAULT_FORWARD_WINDOWS,
        max_samples: int = 1000,
    ) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.windows = tuple(sorted({int(window) for window in windows if int(window) > 0}))
        self.max_samples = max_samples
        self.stock_repo = StockRepository(self.db)

    def build_for_record(self, record: AnalysisHistory, raw_result: Any = None) -> Dict[str, Any]:
        """Build stats for a history record without changing its action fields."""
        raw = _safe_mapping(raw_result if raw_result is not None else _parse_json(record.raw_result))
        context = _safe_mapping(_parse_json(record.context_snapshot))
        basis_date, basis_source = _resolve_basis_date(raw=raw, context=context)
        classification = _record_classification(record, raw)

        if basis_date is None:
            return self._empty_payload(
                status="insufficient_data",
                reason="missing_trusted_analysis_basis_date",
                basis_date=None,
                basis_source=None,
            )

        return self.build_for_classification(
            classification=classification,
            current_basis_date=basis_date,
            current_basis_source=basis_source,
            exclude_query_id=record.query_id,
        )

    def build_for_classification(
        self,
        *,
        classification: Mapping[str, str],
        current_basis_date: date,
        current_basis_source: Optional[str],
        exclude_query_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build stats for records matching a deterministic display classification."""
        normalized = {
            "final_decision": _normalized_text(classification.get("final_decision"), "HOLD"),
            "position_action": _normalized_text(classification.get("position_action"), "HOLD"),
            "validation_status": normalize_validation_status(classification.get("validation_status")),
        }
        prepared_samples: List[Dict[str, Any]] = []
        top_level_skips: Counter[str] = Counter()

        for sample in self._load_matching_samples(classification=normalized, exclude_query_id=exclude_query_id):
            if sample.get("skip_reason"):
                top_level_skips[str(sample["skip_reason"])] += 1
                prepared_samples.append(sample)
                continue

            record = sample["record"]
            basis_date = sample["basis_date"]
            basis_close, basis_price_source = self._resolve_basis_close(record.code, basis_date)
            if basis_close is None:
                top_level_skips["missing_basis_price"] += 1
                prepared_samples.append({**sample, "skip_reason": "missing_basis_price"})
                continue

            bars = self.stock_repo.get_forward_bars(
                code=record.code,
                analysis_date=basis_date,
                eval_window_days=max(self.windows),
            )
            if not bars:
                top_level_skips["missing_forward_bars"] += 1
                prepared_samples.append(
                    {
                        **sample,
                        "basis_price": basis_close,
                        "basis_price_source": basis_price_source,
                        "bars": [],
                        "skip_reason": "missing_forward_bars",
                    }
                )
                continue

            prepared_samples.append(
                {
                    **sample,
                    "basis_price": basis_close,
                    "basis_price_source": basis_price_source,
                    "bars": bars,
                    "skip_reason": None,
                }
            )

        windows = [
            self._build_window_stats(prepared_samples, horizon_days=window)
            for window in self.windows
        ]
        sample_size = windows[0]["sample_size"] if windows else 0
        low_sample = sample_size < LOW_SAMPLE_THRESHOLD

        return {
            "contract_version": SIGNAL_HISTORY_CONTRACT_VERSION,
            "display_only": True,
            "note": DISPLAY_NOTE,
            "status": "ok",
            "similarity_label": SIMILARITY_LABEL,
            "analysis_basis_date": current_basis_date.isoformat(),
            "basis_date_source": current_basis_source,
            "sample_size": sample_size,
            "low_sample": low_sample,
            "warning": "样本较少，参考价值有限" if low_sample else None,
            "skipped_count": sum(top_level_skips.values()),
            "skip_reasons": dict(top_level_skips),
            "windows": windows,
        }

    def _load_matching_samples(
        self,
        *,
        classification: Mapping[str, str],
        exclude_query_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        with self.db.get_session() as session:
            records = session.execute(
                select(AnalysisHistory)
                .order_by(desc(AnalysisHistory.created_at))
                .limit(self.max_samples)
            ).scalars().all()

        samples: List[Dict[str, Any]] = []
        for record in records:
            if exclude_query_id and record.query_id == exclude_query_id:
                continue

            raw = _safe_mapping(_parse_json(record.raw_result))
            if _record_classification(record, raw) != classification:
                continue

            context = _safe_mapping(_parse_json(record.context_snapshot))
            basis_date, basis_source = _resolve_basis_date(raw=raw, context=context)
            if basis_date is None:
                samples.append(
                    {
                        "record": record,
                        "raw_result": raw,
                        "basis_date": None,
                        "basis_source": None,
                        "skip_reason": "missing_trusted_analysis_basis_date",
                    }
                )
                continue

            samples.append(
                {
                    "record": record,
                    "raw_result": raw,
                    "basis_date": basis_date,
                    "basis_source": basis_source,
                }
            )
        return samples

    def _resolve_basis_close(self, code: str, basis_date: Optional[date]) -> Tuple[Optional[float], Optional[str]]:
        if basis_date is None:
            return None, None
        row = self.stock_repo.get_start_daily(code=code, analysis_date=basis_date)
        close = _positive_float(getattr(row, "close", None)) if row is not None else None
        if close is None:
            return None, None
        source = "technical_basis_date.close"
        row_date = getattr(row, "date", None)
        if row_date and row_date != basis_date:
            source = "previous_available_close"
        return close, source

    def _build_window_stats(self, samples: List[Dict[str, Any]], *, horizon_days: int) -> Dict[str, Any]:
        returns: List[float] = []
        drawdowns: List[float] = []
        skip_reasons: Counter[str] = Counter()
        source_counts: Counter[str] = Counter()

        for sample in samples:
            skip_reason = sample.get("skip_reason")
            if skip_reason:
                skip_reasons[skip_reason] += 1
                continue

            bars = sample.get("bars") or []
            if len(bars) < horizon_days:
                skip_reasons["insufficient_horizon"] += 1
                continue

            window_bars = bars[:horizon_days]
            horizon_close = _positive_float(getattr(window_bars[-1], "close", None))
            lows = [_positive_float(getattr(bar, "low", None)) for bar in window_bars]
            if horizon_close is None:
                skip_reasons["missing_future_price"] += 1
                continue
            if any(low is None for low in lows):
                skip_reasons["missing_ohlcv"] += 1
                continue

            basis_price = sample["basis_price"]
            returns.append(round((horizon_close / basis_price - 1.0) * 100.0, 6))
            drawdowns.append(round((min(lows) / basis_price - 1.0) * 100.0, 6))
            source_counts[str(sample.get("basis_price_source") or "unknown")] += 1

        sample_size = len(returns)
        low_sample = sample_size < LOW_SAMPLE_THRESHOLD
        return {
            "horizon_days": horizon_days,
            "sample_size": sample_size,
            "low_sample": low_sample,
            "confidence_label": "样本较少，参考价值有限" if low_sample else "样本相对充足",
            "win_rate": round(sum(1 for value in returns if value > 0) / sample_size * 100.0, 4)
            if sample_size
            else None,
            "average_return": round(mean(returns), 4) if sample_size else None,
            "median_return": round(median(returns), 4) if sample_size else None,
            "max_drawdown": round(min(drawdowns), 4) if drawdowns else None,
            "skipped_count": sum(skip_reasons.values()),
            "skip_reasons": dict(skip_reasons),
            "basis_price_sources": dict(source_counts),
        }

    def _empty_payload(
        self,
        *,
        status: str,
        reason: str,
        basis_date: Optional[date],
        basis_source: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "contract_version": SIGNAL_HISTORY_CONTRACT_VERSION,
            "display_only": True,
            "note": DISPLAY_NOTE,
            "status": status,
            "reason": reason,
            "similarity_label": SIMILARITY_LABEL,
            "analysis_basis_date": basis_date.isoformat() if basis_date else None,
            "basis_date_source": basis_source,
            "sample_size": 0,
            "low_sample": True,
            "warning": "样本较少，参考价值有限",
            "skipped_count": 0,
            "skip_reasons": {reason: 1},
            "windows": [
                {
                    "horizon_days": window,
                    "sample_size": 0,
                    "low_sample": True,
                    "confidence_label": "样本较少，参考价值有限",
                    "win_rate": None,
                    "average_return": None,
                    "median_return": None,
                    "max_drawdown": None,
                    "skipped_count": 0,
                    "skip_reasons": {},
                    "basis_price_sources": {},
                }
                for window in self.windows
            ],
        }


def _record_classification(record: AnalysisHistory, raw: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "final_decision": _normalized_text(getattr(record, "final_decision", None) or raw.get("final_decision"), "HOLD"),
        "position_action": _normalized_text(getattr(record, "position_action", None) or raw.get("position_action"), "HOLD"),
        "validation_status": normalize_validation_status(raw.get("validation_status")),
    }


def _resolve_basis_date(*, raw: Mapping[str, Any], context: Mapping[str, Any]) -> Tuple[Optional[date], Optional[str]]:
    candidates = (
        (("technical_basis_date",), raw, "raw.technical_basis_date"),
        (("market_basis_date",), raw, "raw.market_basis_date"),
        (("snapshot_basis_date",), raw, "raw.snapshot_basis_date"),
        (("market_snapshot", "date"), raw, "raw.market_snapshot.date"),
        (("summary", "technical_basis_date"), raw, "raw.summary.technical_basis_date"),
        (("technical_basis_date",), context, "context.technical_basis_date"),
        (("market_basis_date",), context, "context.market_basis_date"),
        (("snapshot_basis_date",), context, "context.snapshot_basis_date"),
        (("enhanced_context", "technical_basis_date"), context, "context.enhanced_context.technical_basis_date"),
        (("enhanced_context", "market_basis_date"), context, "context.enhanced_context.market_basis_date"),
        (("enhanced_context", "date"), context, "context.enhanced_context.date"),
        (("market_snapshot", "date"), context, "context.market_snapshot.date"),
    )
    for path, source, label in candidates:
        parsed = _parse_date(_nested_get(source, path))
        if parsed is not None:
            return parsed, label
    return None, None


def _nested_get(source: Mapping[str, Any], path: Tuple[str, ...]) -> Any:
    value: Any = source
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.debug("history payload is not valid JSON; skipping structured extraction")
            return {}
    return value


def _safe_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalized_text(value: Any, default: str) -> str:
    text = str(value or default).strip().upper()
    return text or default


def _positive_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return numeric
