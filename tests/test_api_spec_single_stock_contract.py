# -*- coding: utf-8 -*-

import json
from pathlib import Path


def _load_api_spec() -> dict:
    spec_path = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "api_spec.json"
    return json.loads(spec_path.read_text(encoding="utf-8"))


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


def test_api_spec_analysis_report_declares_public_basis_fields_without_raw_debug_payload():
    spec = _load_api_spec()
    report = spec["components"]["schemas"]["AnalysisReport"]
    meta_props = report["properties"]["meta"]["properties"]
    details_props = report["properties"]["details"]["properties"]

    for field in (
        "report_date",
        "technical_basis_date",
        "price_policy",
        "execution_price_source",
    ):
        assert field in meta_props

    assert "最后已收盘交易日" in meta_props["technical_basis_date"]["description"]
    assert "raw_result" not in details_props
    assert "context_snapshot" not in details_props


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
