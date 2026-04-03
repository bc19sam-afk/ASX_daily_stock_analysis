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
    assert stock_codes["example"] == ["600519"]

    assert report_type["default"] == "full"
    assert report_type["enum"] == ["simple", "full", "detailed"]
