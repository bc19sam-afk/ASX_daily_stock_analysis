# -*- coding: utf-8 -*-
"""Score bucket calibration contract tests."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary, render_preopen_decision_dashboard


def _result(**overrides) -> AnalysisResult:
    base = dict(
        code="CBA.AX",
        name="CBA",
        sentiment_score=76,
        trend_prediction="震荡上行",
        operation_advice="按确定性动作观察",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.10,
        delta_amount=5000.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-04", "close": "100.00", "source": "yfinance"},
        technical_analysis="MA20 仍在价格下方",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        action_reason="deterministic action",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _model(result: AnalysisResult) -> dict:
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results, *, score_bucket_calibration=None):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-05-05",
        generated_at=datetime(2026, 5, 5, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
        get_primary_action_model=_model,
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
        score_bucket_calibration=score_bucket_calibration,
    )


def _rows_for_bucket(score: int, *, count: int, wins: int, return_pct: float):
    return [
        SimpleNamespace(
            eval_status="completed",
            sentiment_score=score,
            outcome="win" if index < wins else "loss",
            simulated_return_pct=return_pct,
        )
        for index in range(count)
    ]


def test_score_bucket_calibration_groups_completed_rows_by_score_bucket():
    from src.backtest_confidence import build_score_bucket_calibration

    rows = [
        SimpleNamespace(eval_status="completed", sentiment_score=65, outcome="win", simulated_return_pct=2.0),
        SimpleNamespace(eval_status="completed", sentiment_score=69, outcome="loss", simulated_return_pct=-1.0),
        SimpleNamespace(eval_status="completed", sentiment_score=75, outcome="win", simulated_return_pct=3.0),
        SimpleNamespace(eval_status="completed", sentiment_score=85, outcome="win", simulated_return_pct=4.0),
        SimpleNamespace(eval_status="pending", sentiment_score=85, outcome="win", simulated_return_pct=99.0),
        SimpleNamespace(eval_status="completed", sentiment_score=59, outcome="win", simulated_return_pct=99.0),
    ]

    calibration = build_score_bucket_calibration(score_results=rows, window_days=10)

    assert calibration["60_70"]["sample_size"] == 2
    assert calibration["60_70"]["win_rate_pct"] == 50.0
    assert calibration["60_70"]["avg_simulated_return_pct"] == 0.5
    assert calibration["60_70"]["window_days"] == 10
    assert calibration["70_80"]["sample_size"] == 1
    assert calibration["80_100"]["sample_size"] == 1


def test_score_bucket_calibration_low_sample_rendering_avoids_confidence_boost():
    from src.backtest_confidence import build_score_bucket_calibration, render_score_bucket_calibration_lines

    calibration = build_score_bucket_calibration(
        score_results=_rows_for_bucket(85, count=3, wins=3, return_pct=5.0),
        window_days=10,
        current_results=[_result(sentiment_score=86)],
        format_stock_display_name=lambda name, code: f"{name} ({code})",
    )

    rendered = "\n".join(render_score_bucket_calibration_lines(calibration))

    assert "评分校准" in rendered
    assert "CBA (CBA.AX) 评分 86 -> 80_100" in rendered
    assert "10 日窗口" in rendered
    assert "样本不足，不作为置信增强" in rendered
    assert "高置信" not in rendered


def test_dashboard_renders_current_score_bucket_metrics_when_sample_available():
    from src.backtest_confidence import build_score_bucket_calibration

    rows = _rows_for_bucket(76, count=20, wins=12, return_pct=1.25)
    summary = _summary(
        [_result(sentiment_score=76)],
        score_bucket_calibration=build_score_bucket_calibration(score_results=rows, window_days=10),
    )
    report = "\n".join(render_preopen_decision_dashboard(summary))

    assert "评分校准" in report
    assert "CBA (CBA.AX) 评分 76 -> 70_80" in report
    assert "10 日窗口" in report
    assert "样本 20 次" in report
    assert "胜率 60.00%" in report
    assert "平均模拟收益 +1.25%" in report
    assert "不是交易保证" in report
    assert "保证收益" not in report


def test_missing_sentiment_score_skips_current_bucket_mapping():
    from src.backtest_confidence import build_score_bucket_calibration

    result = _result()
    result.sentiment_score = None
    summary = _summary(
        [result],
        score_bucket_calibration=build_score_bucket_calibration(score_results=[], window_days=10),
    )
    report = "\n".join(render_preopen_decision_dashboard(summary))

    assert summary["score_bucket_calibration"]["current_items"] == []
    assert "当前结果缺少可映射评分，跳过评分校准" in report


def test_score_bucket_calibration_does_not_change_actions_or_counts():
    from src.backtest_confidence import build_score_bucket_calibration

    result = _result(position_action="OPEN", final_decision="BUY", target_weight=0.1, delta_amount=5000.0)
    calibration = build_score_bucket_calibration(
        score_results=_rows_for_bucket(76, count=20, wins=12, return_pct=1.25),
        window_days=10,
    )

    baseline = _summary([result])
    with_calibration = _summary([result], score_bucket_calibration=calibration)

    assert with_calibration["action_counts"] == baseline["action_counts"]
    assert with_calibration["actionable_items"][0]["position_action"] == baseline["actionable_items"][0]["position_action"]
    assert with_calibration["actionable_items"][0]["final_action_display"] == baseline["actionable_items"][0]["final_action_display"]


def test_blocked_item_is_not_score_bucket_enhanced_into_actionable():
    from src.backtest_confidence import build_score_bucket_calibration

    blocked = _result(
        validation_status="BLOCK",
        validation_issues=["收盘价缺失，无法确认昨收计划。"],
        sentiment_score=86,
    )
    summary = _summary(
        [blocked],
        score_bucket_calibration=build_score_bucket_calibration(
            score_results=_rows_for_bucket(86, count=20, wins=18, return_pct=5.0),
            window_days=10,
        ),
    )
    report = "\n".join(render_preopen_decision_dashboard(summary))

    assert summary["action_counts"]["blocked"] == 1
    assert summary["action_counts"]["total_actions"] == 0
    assert summary["score_bucket_calibration"]["current_items"] == []
    assert "CBA (CBA.AX) 评分 86" not in report
