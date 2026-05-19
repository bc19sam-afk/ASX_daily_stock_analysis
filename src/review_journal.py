# -*- coding: utf-8 -*-
"""Daily review journal artifact helpers.

The journal records morning plans and user-provided notes. It does not connect
to brokers, infer real fills, update portfolios, or mutate daily decision
summaries.
"""

from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.stock_code import canonical_stock_code


SCHEMA_VERSION = "review_journal.v1"
WEEKLY_SUMMARY_SCHEMA_VERSION = "review_weekly_summary.v1"
MANUAL_NOTE_STATUSES = {"executed", "skipped", "partial", "unknown"}


def build_review_journal_from_summary(
    summary: Mapping[str, Any],
    *,
    source_summary_path: str,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Initialize a review journal from an existing daily decision summary."""
    timestamp = str(created_at or _now_iso())
    return {
        "review_journal": {
            "schema_version": SCHEMA_VERSION,
            "report_date": str(summary.get("report_date") or ""),
            "created_at": timestamp,
            "updated_at": timestamp,
            "source_summary_path": str(source_summary_path or ""),
            "morning_actions": _morning_actions_from_summary(summary),
            "manual_execution_notes": [],
            "post_trade_notes": [],
        }
    }


def append_manual_execution_note(
    journal: Mapping[str, Any],
    *,
    code: str,
    note: str,
    status: str = "unknown",
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a user-provided execution note without inferring real trades."""
    updated = _copy_journal_payload(journal)
    payload = _journal_payload(updated)
    note_timestamp = str(timestamp or _now_iso())
    payload["updated_at"] = note_timestamp
    payload.setdefault("manual_execution_notes", []).append(
        {
            "code": canonical_stock_code(code),
            "note": str(note or ""),
            "status": _manual_note_status(status),
            "timestamp": note_timestamp,
            "user_provided": True,
        }
    )
    return updated


def write_review_journal_file(journal: Mapping[str, Any], *, output_dir: str | Path) -> Path:
    """Write a review journal artifact, preserving existing user notes if present."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    path = output_path / f"review_journal_{_date_slug(_journal_payload(journal).get('report_date'))}.json"
    payload = _copy_journal_payload(journal)
    if path.exists():
        payload = merge_review_journals(load_review_journal_file(path), payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def bootstrap_review_journal_from_artifacts(
    *,
    summary_path: str | Path,
    output_dir: Optional[str | Path] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or merge a review journal from a local daily summary artifact."""
    summary_file = Path(summary_path)
    summary = _read_json_object(summary_file)
    output_path = Path(output_dir) if output_dir is not None else summary_file.parent
    journal = build_review_journal_from_summary(
        summary,
        source_summary_path=str(summary_file),
        created_at=created_at,
    )
    journal_path = write_review_journal_file(journal, output_dir=output_path)
    return {
        "journal_path": str(journal_path),
        "source_summary_path": str(summary_file),
        "preserves_manual_notes": True,
        "infers_real_fills": False,
    }


def load_review_journal_file(path: str | Path) -> Dict[str, Any]:
    """Load a review journal artifact from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("review_journal"), dict):
        raise ValueError("Review journal file must contain a review_journal object.")
    return payload


def build_weekly_review_summary(
    journals: Iterable[Mapping[str, Any]],
    *,
    week_start: str,
    week_end: str,
    source_journal_paths: Optional[List[str]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a weekly review summary from local journal artifacts only."""
    journal_payloads = [_journal_payload(journal) for journal in journals]
    action_counts: Counter[str] = Counter()
    manual_note_counts: Counter[str] = Counter()
    followups: Dict[str, set[str]] = defaultdict(set)

    for payload in journal_payloads:
        for action in payload.get("morning_actions") or []:
            code = canonical_stock_code(action.get("code"))
            morning_action = str(action.get("morning_action") or "UNKNOWN").strip().upper()
            validation_status = str(action.get("validation_status") or "").strip().upper()
            action_counts[morning_action] += 1
            if validation_status == "BLOCK" or morning_action == "BLOCK":
                followups[code].add("morning_block")
        for note in payload.get("manual_execution_notes") or []:
            code = canonical_stock_code(note.get("code"))
            status = _manual_note_status(str(note.get("status") or "unknown"))
            manual_note_counts[status] += 1
            if status in {"skipped", "partial", "unknown"}:
                followups[code].add(f"manual_{status}")

    return {
        "weekly_review_summary": {
            "schema_version": WEEKLY_SUMMARY_SCHEMA_VERSION,
            "week_start": str(week_start),
            "week_end": str(week_end),
            "generated_at": str(generated_at or _now_iso()),
            "journal_count": len(journal_payloads),
            "source_journal_paths": list(source_journal_paths or []),
            "morning_action_counts": dict(sorted(action_counts.items())),
            "manual_note_counts": dict(sorted(manual_note_counts.items())),
            "symbols_needing_followup": [
                {"code": code, "reasons": sorted(reasons)}
                for code, reasons in sorted(followups.items())
                if code
            ],
            "real_fills_inferred": False,
            "broker_connected": False,
        }
    }


def generate_weekly_review_summary_from_journals(
    *,
    journal_dir: str | Path,
    week_start: str,
    week_end: str,
    output_dir: Optional[str | Path] = None,
    generated_at: Optional[str] = None,
) -> Path:
    """Load local review journals for a date window and write a weekly summary."""
    start_date = _parse_date(week_start)
    end_date = _parse_date(week_end)
    if end_date < start_date:
        raise ValueError("week_end must be on or after week_start.")

    source_dir = Path(journal_dir)
    paths = [
        path
        for path in sorted(source_dir.glob("review_journal_*.json"))
        if _date_in_range(_journal_date_from_path(path), start_date=start_date, end_date=end_date)
    ]
    journals = [load_review_journal_file(path) for path in paths]
    weekly = build_weekly_review_summary(
        journals,
        week_start=week_start,
        week_end=week_end,
        source_journal_paths=[str(path) for path in paths],
        generated_at=generated_at,
    )
    target_dir = Path(output_dir) if output_dir is not None else source_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"review_weekly_summary_{_date_slug(week_start)}_{_date_slug(week_end)}.json"
    output_path.write_text(json.dumps(weekly, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def merge_review_journals(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge incoming journal data while preserving existing user-provided notes."""
    existing_payload = _journal_payload(existing)
    incoming_payload = _journal_payload(incoming)
    merged = _copy_journal_payload({"review_journal": incoming_payload})
    merged_payload = _journal_payload(merged)

    if existing_payload.get("created_at"):
        merged_payload["created_at"] = existing_payload["created_at"]
    for field in ("manual_execution_notes", "post_trade_notes"):
        merged_payload[field] = _append_unique(existing_payload.get(field) or [], incoming_payload.get(field) or [])
    merged_payload["updated_at"] = incoming_payload.get("updated_at") or existing_payload.get("updated_at") or _now_iso()
    return merged


def _read_json_object(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _journal_date_from_path(path: Path) -> Optional[date]:
    slug = "".join(ch for ch in path.stem if ch.isdigit())
    if len(slug) < 8:
        return None
    return _parse_date(f"{slug[:4]}-{slug[4:6]}-{slug[6:8]}")


def _date_in_range(value: Optional[date], *, start_date: date, end_date: date) -> bool:
    return value is not None and start_date <= value <= end_date


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(str(value)).date()


def _morning_actions_from_summary(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    actions.extend(_morning_actions_from_items(summary.get("actionable_items") or [], default_morning_action=None))
    actions.extend(_morning_actions_from_items(summary.get("watch_items") or [], default_morning_action="HOLD"))
    actions.extend(_morning_actions_from_items(summary.get("blocked_items") or [], default_morning_action="BLOCK"))
    return actions


def _morning_actions_from_items(items: Iterable[Mapping[str, Any]], *, default_morning_action: Optional[str]) -> List[Dict[str, Any]]:
    return [_morning_action_item(item, default_morning_action=default_morning_action) for item in items]


def _morning_action_item(item: Mapping[str, Any], *, default_morning_action: Optional[str]) -> Dict[str, Any]:
    default_validation_status = "BLOCK" if default_morning_action == "BLOCK" else "PASS"
    validation_status = str(item.get("validation_status") or default_validation_status).strip().upper()
    morning_action = default_morning_action or item.get("morning_action") or item.get("position_action") or "HOLD"
    return {
        "code": canonical_stock_code(item.get("code")),
        "morning_action": str(morning_action or "").strip().upper(),
        "final_decision": item.get("final_decision"),
        "position_action": item.get("position_action"),
        "target_weight": item.get("target_weight"),
        "delta_amount": item.get("delta_amount"),
        "validation_status": validation_status,
    }


def _journal_payload(journal: Mapping[str, Any]) -> Dict[str, Any]:
    payload = journal.get("review_journal")
    if not isinstance(payload, dict):
        raise ValueError("Expected review_journal payload.")
    return payload


def _copy_journal_payload(journal: Mapping[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(dict(journal))


def _append_unique(existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for item in list(existing) + list(incoming):
        copied = dict(item)
        if copied not in merged:
            merged.append(copied)
    return merged


def _manual_note_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    return normalized if normalized in MANUAL_NOTE_STATUSES else "unknown"


def _date_slug(value: Any) -> str:
    slug = "".join(ch for ch in str(value or "") if ch.isdigit())
    return slug or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
