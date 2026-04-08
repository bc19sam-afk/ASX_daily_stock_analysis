# -*- coding: utf-8 -*-
"""Helpers for pipeline-triggered notification dispatch."""

from __future__ import annotations

from logging import Logger

from src.analyzer import AnalysisResult
from src.enums import ReportType


def send_single_stock_notification(
    *,
    notifier,
    result: AnalysisResult,
    report_type: ReportType,
    code: str,
    logger: Logger,
) -> bool:
    """Build and send a single-stock notification without changing behavior."""
    if report_type == ReportType.FULL:
        report_content = notifier.generate_dashboard_report([result])
        logger.info(f"[{code}] 使用完整报告格式")
    else:
        report_content = notifier.generate_single_stock_report(result)
        logger.info(f"[{code}] 使用精简报告格式")

    return bool(notifier.send(report_content, email_stock_codes=[code]))
