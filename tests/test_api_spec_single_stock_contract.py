# -*- coding: utf-8 -*-

import json
from pathlib import Path


def _load_api_spec() -> dict:
    spec_path = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "api_spec.json"
    return json.loads(spec_path.read_text(encoding="utf-8"))


def _read_frontend_types() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "dsa-web"
        / "src"
        / "types"
        / "analysis.ts"
    ).read_text(encoding="utf-8")


def _read_report_overview() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "dsa-web"
        / "src"
        / "components"
        / "report"
        / "ReportOverview.tsx"
    ).read_text(encoding="utf-8")


def _interface_block(source: str, name: str) -> str:
    start = source.index(f"export interface {name}")
    next_interface = source.find("export interface ", start + 1)
    return source[start:] if next_interface == -1 else source[start:next_interface]


def test_api_spec_analyze_description_declares_single_stock_limit():
    spec = _load_api_spec()
    description = spec["paths"]["/api/v1/analysis/analyze"]["post"]["description"]

    assert "单次请求只支持一只股票" in description
    assert "400 validation_error" in description
    assert "批量分析" not in description


def test_api_spec_analyze_request_no_longer_implies_multi_stock_support():
    spec = _load_api_spec()
    analyze_request = spec["components"]["schemas"]["AnalyzeRequest"]
    stock_codes = analyze_request["properties"]["stock_codes"]
    report_type = analyze_request["properties"]["report_type"]

    assert "仅支持单元素列表" in stock_codes["description"]
    assert stock_codes["example"] == ["BHP.AX"]

    assert report_type["default"] == "full"
    assert report_type["enum"] == ["simple", "full", "detailed"]


def test_api_spec_analysis_report_declares_validation_and_action_contract():
    spec = _load_api_spec()
    report = spec["components"]["schemas"]["AnalysisReport"]
    meta_props = report["properties"]["meta"]["properties"]
    summary_props = report["properties"]["summary"]["properties"]

    assert "analysis_status" in meta_props
    assert "validation_status" in meta_props
    for field in (
        "analysis_status",
        "validation_status",
        "validation_issues",
        "final_decision",
        "position_action",
        "action_reason",
    ):
        assert field in summary_props


def test_api_spec_analysis_report_declares_display_only_similar_signal_stats():
    spec = _load_api_spec()
    summary_props = spec["components"]["schemas"]["AnalysisReport"]["properties"]["summary"]["properties"]

    assert "similar_signal_performance" in summary_props
    assert "仅供历史参考" in summary_props["similar_signal_performance"]["description"]
    for forbidden in (
        "manual_actionable",
        "execution_ready",
        "order_quantity",
        "target_quantity",
        "risk_plan",
        "manual_checklist",
    ):
        assert forbidden not in summary_props


def test_frontend_analysis_types_include_validation_and_action_contract_fields():
    frontend_types = _read_frontend_types()

    for field in (
        "analysisStatus",
        "validationStatus",
        "validationIssues",
        "finalDecision",
        "positionAction",
        "actionReason",
    ):
        assert field in frontend_types


def test_frontend_analysis_types_include_display_only_similar_signal_stats():
    frontend_types = _read_frontend_types()
    similar_stats_types = (
        _interface_block(frontend_types, "SimilarSignalWindowStats")
        + _interface_block(frontend_types, "SimilarSignalPerformance")
    )

    assert "similarSignalPerformance" in frontend_types
    assert "displayOnly: true" in frontend_types
    for forbidden in (
        "manualActionable",
        "executionReady",
        "orderQuantity",
        "targetQuantity",
        "riskPlan",
        "manualChecklist",
        "finalDecision",
        "positionAction",
        "entryReference",
        "entryPrice",
        "entrySource",
    ):
        assert forbidden not in similar_stats_types


def test_frontend_similar_signal_card_uses_display_only_copy():
    report_overview = _read_report_overview()
    marker = "类似信号历史表现"
    card_start = report_overview.index(marker)
    card_block = report_overview[card_start:]

    assert "仅供历史参考，不改变当前建议" in card_block
    for forbidden in (
        "建议执行",
        "可执行",
        "下单",
        "execution",
        "Entry",
        "entry",
        "orderQuantity",
        "target quantity",
        "manual_actionable",
        "execution_ready",
    ):
        assert forbidden not in card_block
