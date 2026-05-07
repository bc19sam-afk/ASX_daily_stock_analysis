# -*- coding: utf-8 -*-
"""Daily review journal artifact tests."""

import ast
import copy
import json
from pathlib import Path

from src.review_journal import (
    append_manual_execution_note,
    attach_intraday_review,
    bootstrap_review_journal_from_artifacts,
    build_weekly_review_summary,
    generate_weekly_review_summary_from_journals,
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


def test_bootstrap_from_artifacts_merges_intraday_and_preserves_manual_notes(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    summary_path = reports_dir / "daily_decision_summary_20260506.json"
    intraday_path = reports_dir / "intraday_review_20260506.json"
    summary_path.write_text(json.dumps(_summary_payload(), ensure_ascii=False), encoding="utf-8")
    intraday_path.write_text(json.dumps(_intraday_payload(), ensure_ascii=False), encoding="utf-8")

    result = bootstrap_review_journal_from_artifacts(
        summary_path=summary_path,
        output_dir=reports_dir,
        created_at="2026-05-06T16:00:00+10:00",
        updated_at="2026-05-06T16:30:00+10:00",
    )
    journal_path = Path(result["journal_path"])
    with_note = append_manual_execution_note(
        load_review_journal_file(journal_path),
        code="BHP.AX",
        note="Manual note survives bootstrap rerun.",
        status="skipped",
        timestamp="2026-05-06T17:00:00+10:00",
    )
    write_review_journal_file(with_note, output_dir=reports_dir)

    rerun = bootstrap_review_journal_from_artifacts(
        summary_path=summary_path,
        output_dir=reports_dir,
        created_at="2026-05-06T18:00:00+10:00",
        updated_at="2026-05-06T18:30:00+10:00",
    )
    loaded = load_review_journal_file(rerun["journal_path"])
    payload = loaded["review_journal"]

    assert result["attached_intraday_review"] is True
    assert result["source_intraday_review_path"] == str(intraday_path)
    assert result["infers_real_fills"] is False
    assert payload["created_at"] == "2026-05-06T16:00:00+10:00"
    assert payload["manual_execution_notes"] == with_note["review_journal"]["manual_execution_notes"]
    assert len(payload["intraday_reviews"]) == 2


def test_weekly_review_summary_counts_local_journals_without_inferring_fills(tmp_path: Path):
    first = build_review_journal_from_summary(
        _summary_payload(),
        source_summary_path="reports/daily_decision_summary_20260506.json",
        created_at="2026-05-06T16:00:00+10:00",
    )
    first = attach_intraday_review(
        first,
        _intraday_payload(),
        source_review_path="reports/intraday_review_20260506.json",
        updated_at="2026-05-06T16:30:00+10:00",
    )
    first = append_manual_execution_note(
        first,
        code="BHP.AX",
        note="Skipped after manual news check.",
        status="skipped",
        timestamp="2026-05-06T17:00:00+10:00",
    )
    second_summary = copy.deepcopy(_summary_payload())
    second_summary["report_date"] = "2026-05-07"
    second_summary["actionable_items"][0]["code"] = "CSL.AX"
    second = build_review_journal_from_summary(
        second_summary,
        source_summary_path="reports/daily_decision_summary_20260507.json",
        created_at="2026-05-07T16:00:00+10:00",
    )

    weekly = build_weekly_review_summary(
        [first, second],
        week_start="2026-05-04",
        week_end="2026-05-10",
        source_journal_paths=["reports/review_journal_20260506.json", "reports/review_journal_20260507.json"],
        generated_at="2026-05-10T18:00:00+10:00",
    )["weekly_review_summary"]

    assert weekly["schema_version"] == "review_weekly_summary.v1"
    assert weekly["journal_count"] == 2
    assert weekly["morning_action_counts"]["OPEN"] == 2
    assert weekly["morning_action_counts"]["HOLD"] == 2
    assert weekly["morning_action_counts"]["BLOCK"] == 2
    assert weekly["intraday_review_counts"]["still_valid"] == 1
    assert weekly["intraday_review_counts"]["observe_only"] == 1
    assert weekly["manual_note_counts"]["skipped"] == 1
    assert weekly["real_fills_inferred"] is False
    assert weekly["broker_connected"] is False
    assert {"code": "BHP.AX", "reasons": ["manual_skipped"]} in weekly["symbols_needing_followup"]


def test_generate_weekly_review_summary_from_journal_files(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    old_dir = tmp_path / "old"
    reports_dir.mkdir()
    old_dir.mkdir()
    write_review_journal_file(
        build_review_journal_from_summary(
            _summary_payload(),
            source_summary_path="reports/daily_decision_summary_20260506.json",
            created_at="2026-05-06T16:00:00+10:00",
        ),
        output_dir=reports_dir,
    )
    old_summary = copy.deepcopy(_summary_payload())
    old_summary["report_date"] = "2026-04-29"
    write_review_journal_file(
        build_review_journal_from_summary(
            old_summary,
            source_summary_path="reports/daily_decision_summary_20260429.json",
            created_at="2026-04-29T16:00:00+10:00",
        ),
        output_dir=reports_dir,
    )

    output_path = generate_weekly_review_summary_from_journals(
        journal_dir=reports_dir,
        week_start="2026-05-04",
        week_end="2026-05-10",
        output_dir=old_dir,
        generated_at="2026-05-10T18:00:00+10:00",
    )
    weekly = json.loads(output_path.read_text(encoding="utf-8"))["weekly_review_summary"]

    assert output_path.name == "review_weekly_summary_20260504_20260510.json"
    assert weekly["journal_count"] == 1
    assert weekly["source_journal_paths"] == [str(reports_dir / "review_journal_20260506.json")]
    assert weekly["morning_action_counts"]["OPEN"] == 1


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
