# -*- coding: utf-8 -*-
"""Daily review journal artifact tests."""

import ast
import copy
import json
from pathlib import Path

from src.review_journal import (
    append_manual_execution_note,
    attach_intraday_review,
    build_review_journal_from_summary,
    load_review_journal_file,
    write_review_journal_file,
)


def _summary_payload():
    return {
        "report_date": "2026-05-06",
        "actionable_items": [
            {
                "code": "BHP.AX",
                "morning_action": "OPEN",
                "final_decision": "BUY",
                "position_action": "OPEN",
                "target_weight": 0.10,
                "delta_amount": 10000.0,
                "validation_status": "PASS",
            }
        ],
        "watch_items": [
            {
                "code": "WES.AX",
                "final_decision": "HOLD",
                "position_action": "HOLD",
                "target_weight": 0.0,
                "delta_amount": 0.0,
                "validation_status": "PASS",
            }
        ],
        "blocked_items": [
            {
                "code": "NAB.AX",
                "final_decision": "BUY",
                "position_action": "ADD",
                "target_weight": 0.12,
                "delta_amount": 12000.0,
                "validation_status": "BLOCK",
            }
        ],
        "action_counts": {
            "buy": 1,
            "add": 0,
            "reduce": 0,
            "close": 0,
            "hold_watch": 1,
            "blocked": 1,
        },
    }


def _intraday_payload():
    return {
        "report_date": "2026-05-06",
        "items": [
            {
                "code": "BHP.AX",
                "morning_action": "OPEN",
                "review_status": "still_valid",
                "reason": "Price deviation inside threshold; manual review only.",
            },
            {
                "code": "NAB.AX",
                "morning_action": "BLOCK",
                "review_status": "observe_only",
                "reason": "Morning BLOCK remains observe-only.",
            },
        ],
    }


def test_journal_initializes_from_daily_summary_without_mutating_it():
    summary = _summary_payload()
    original = copy.deepcopy(summary)

    journal = build_review_journal_from_summary(
        summary,
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )

    payload = journal["review_journal"]
    assert summary == original
    assert payload["schema_version"] == "review_journal.v1"
    assert payload["report_date"] == "2026-05-06"
    assert payload["source_summary_path"] == "reports/daily_decision_summary_20260506.json"
    assert payload["created_at"] == "2026-05-06T16:00:00+10:00"
    assert payload["updated_at"] == "2026-05-06T16:00:00+10:00"
    assert payload["intraday_reviews"] == []
    assert payload["manual_execution_notes"] == []
    assert payload["post_trade_notes"] == []

    by_code = {item["code"]: item for item in payload["morning_actions"]}
    assert by_code["BHP.AX"]["final_decision"] == "BUY"
    assert by_code["BHP.AX"]["position_action"] == "OPEN"
    assert by_code["BHP.AX"]["target_weight"] == 0.10
    assert by_code["BHP.AX"]["delta_amount"] == 10000.0
    assert by_code["NAB.AX"]["validation_status"] == "BLOCK"
    assert by_code["NAB.AX"]["morning_action"] == "BLOCK"


def test_journal_attaches_intraday_review_without_changing_morning_actions():
    journal = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )
    before_actions = copy.deepcopy(journal["review_journal"]["morning_actions"])

    updated = attach_intraday_review(
        journal,
        _intraday_payload(),
        source_review_path="reports/intraday_review_20260506.json",
        updated_at="2026-05-06T16:30:00+10:00",
    )

    payload = updated["review_journal"]
    assert payload["morning_actions"] == before_actions
    assert payload["updated_at"] == "2026-05-06T16:30:00+10:00"
    assert payload["intraday_reviews"] == [
        {
            "code": "BHP.AX",
            "morning_action": "OPEN",
            "review_status": "still_valid",
            "reason": "Price deviation inside threshold; manual review only.",
            "source_review_path": "reports/intraday_review_20260506.json",
        },
        {
            "code": "NAB.AX",
            "morning_action": "BLOCK",
            "review_status": "observe_only",
            "reason": "Morning BLOCK remains observe-only.",
            "source_review_path": "reports/intraday_review_20260506.json",
        },
    ]


def test_manual_execution_note_is_user_provided_and_append_only():
    journal = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )

    first = append_manual_execution_note(
        journal,
        code="BHP.AX",
        note="User skipped execution after checking announcement.",
        status="skipped",
        timestamp="2026-05-06T17:00:00+10:00",
    )
    second = append_manual_execution_note(
        first,
        code="WES.AX",
        note="No action taken.",
        status="unknown",
        timestamp="2026-05-06T17:10:00+10:00",
    )

    notes = second["review_journal"]["manual_execution_notes"]
    assert len(notes) == 2
    assert notes[0]["user_provided"] is True
    assert notes[0]["status"] == "skipped"
    assert notes[1]["code"] == "WES.AX"
    assert first["review_journal"]["manual_execution_notes"][0] == notes[0]


def test_writing_existing_journal_preserves_manual_notes(tmp_path: Path):
    output_dir = tmp_path / "reports"
    initial = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )
    with_note = append_manual_execution_note(
        initial,
        code="BHP.AX",
        note="Existing note must survive.",
        status="executed",
        timestamp="2026-05-06T17:00:00+10:00",
    )
    path = write_review_journal_file(with_note, output_dir=output_dir)

    fresh = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T18:00:00+10:00",
    )
    same_path = write_review_journal_file(fresh, output_dir=output_dir)
    loaded = load_review_journal_file(same_path)

    assert path == same_path
    assert loaded["review_journal"]["manual_execution_notes"] == with_note["review_journal"]["manual_execution_notes"]
    assert loaded["review_journal"]["created_at"] == "2026-05-06T16:00:00+10:00"


def test_journal_file_is_serializable_and_uses_expected_name(tmp_path: Path):
    journal = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )

    path = write_review_journal_file(journal, output_dir=tmp_path)
    loaded = load_review_journal_file(path)

    assert path.name == "review_journal_20260506.json"
    assert json.loads(path.read_text(encoding="utf-8")) == loaded
    assert loaded["review_journal"]["report_date"] == "2026-05-06"


def test_review_journal_module_does_not_import_broker_storage_or_data_provider():
    source = Path("src/review_journal.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden = ["broker", "data_provider", "storage", "portfolio_manager", "openai", "anthropic", "yfinance"]
    assert all(marker not in imported for imported in imports for marker in forbidden)
