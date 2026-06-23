# -*- coding: utf-8 -*-

from src.analyzer import AnalysisResult
from src.services.analysis_service import AnalysisService
from src.enums import ReportType


def test_analysis_service_exposes_outer_status_in_meta_and_summary():
    service = AnalysisService()
    result = AnalysisResult(
        code="CBA.AX",
        name="Commonwealth Bank",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="观望",
        analysis_status="DEGRADED",
        success=True,
    )

    payload = service._build_analysis_response(result=result, query_id="q1", report_type=ReportType.FULL)

    assert payload["report"]["meta"]["analysis_status"] == "DEGRADED"
    assert payload["report"]["summary"]["analysis_status"] == "DEGRADED"


def test_analysis_service_exposes_status_reason_without_degrading_recovered_result():
    service = AnalysisService()
    result = AnalysisResult(
        code="CBA.AX",
        name="Commonwealth Bank",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="观望",
        analysis_status="OK",
        analysis_status_reason="schema_bridge_recovered",
        schema_recovered_fields=["analysis_summary", "risk_warning"],
        success=True,
    )

    payload = service._build_analysis_response(result=result, query_id="q1", report_type=ReportType.FULL)

    assert payload["report"]["meta"]["analysis_status"] == "OK"
    assert payload["report"]["summary"]["analysis_status"] == "OK"
    assert payload["report"]["meta"]["analysis_status_reason"] == "schema_bridge_recovered"
    assert payload["report"]["summary"]["analysis_status_reason"] == "schema_bridge_recovered"
