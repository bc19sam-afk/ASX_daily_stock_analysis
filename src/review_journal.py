# -*- coding: utf-8 -*-
"""Daily review journal artifact helpers.

The journal records morning plans, intraday review artifacts, and user-provided
notes. It does not connect to brokers, infer real fills, update portfolios, or
mutate daily decision summaries.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA_VERSION = "review_journal.v1"
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
            "intraday_reviews": [],
            "manual_execution_notes": [],
            "post_trade_notes": [],
        }
    }


def attach_intraday_review(
    journal: Mapping[str, Any],
    intraday_review: Mapping[str, Any],
    *,
    source_review_path: str,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Append intraday review items without changing recorded morning actions."""
    updated = _copy_journal_payload(journal)
    payload = _journal_payload(updated)
    payload["updated_at"] = str(updated_at or _now_iso())
    payload.setdefault("intraday_reviews", []).extend(
        _intraday_review_items(intraday_review, source_review_path=source_review_path)
    )
    return updated


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
            "code": _normalize_code(code),
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


def load_review_journal_file(path: str | Path) -> Dict[str, Any]:
    """Load a review journal artifact from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("review_journal"), dict):
        raise ValueError("Review journal file must contain a review_journal object.")
    return payload


def merge_review_journals(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge incoming journal data while preserving existing user-provided notes."""
    existing_payload = _journal_payload(existing)
    incoming_payload = _journal_payload(incoming)
    merged = _copy_journal_payload({"review_journal": incoming_payload})
    merged_payload = _journal_payload(merged)

    if existing_payload.get("created_at"):
        merged_payload["created_at"] = existing_payload["created_at"]
    for field in ("manual_execution_notes", "post_trade_notes", "intraday_reviews"):
        merged_payload[field] = _append_unique(existing_payload.get(field) or [], incoming_payload.get(field) or [])
    merged_payload["updated_at"] = incoming_payload.get("updated_at") or existing_payload.get("updated_at") or _now_iso()
    return merged


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
        "code": _normalize_code(item.get("code")),
        "morning_action": str(morning_action or "").strip().upper(),
        "final_decision": item.get("final_decision"),
        "position_action": item.get("position_action"),
        "target_weight": item.get("target_weight"),
        "delta_amount": item.get("delta_amount"),
        "validation_status": validation_status,
    }


def _intraday_review_items(intraday_review: Mapping[str, Any], *, source_review_path: str) -> List[Dict[str, Any]]:
    items = []
    for item in intraday_review.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        items.append(
            {
                "code": _normalize_code(item.get("code")),
                "morning_action": str(item.get("morning_action") or "").strip().upper(),
                "review_status": str(item.get("review_status") or ""),
                "reason": str(item.get("reason") or ""),
                "source_review_path": str(source_review_path or ""),
            }
        )
    return items


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


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
