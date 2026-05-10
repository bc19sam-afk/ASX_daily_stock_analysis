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


def test_frontend_analysis_types_include_validation_and_action_contract_fields():
    frontend_types = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "dsa-web"
        / "src"
        / "types"
        / "analysis.ts"
    ).read_text(encoding="utf-8")

    for field in (
        "analysisStatus",
        "validationStatus",
        "validationIssues",
        "finalDecision",
        "positionAction",
        "actionReason",
    ):
        assert field in frontend_types
