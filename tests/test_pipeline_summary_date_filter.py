import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline


class PipelineSummaryDateFilterTestCase(unittest.TestCase):
    def _build_result(self, snapshot_date):
        return AnalysisResult(
            code="AAA",
            name="样例",
            sentiment_score=60,
            trend_prediction="震荡",
            operation_advice="观察",
            market_snapshot={"date": snapshot_date},
        )

    @patch("src.core.pipeline._now_in_timezone_safe")
    def test_summary_prefix_falls_back_to_report_day_when_snapshot_dates_invalid(self, mock_now) -> None:
        mock_now.return_value = datetime(2026, 4, 7, 9, 0, 0)
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(market_timezone="Australia/Sydney")
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.generate_portfolio_summary.return_value = "summary-body"
        pipeline.notifier = MagicMock()
        pipeline.notifier.generate_dashboard_report.return_value = "dashboard-body"
        pipeline.notifier.save_report_to_file.return_value = "/tmp/report.md"
        pipeline.notifier.get_last_daily_decision_summary.return_value = None

        results = [
            self._build_result(None),
            self._build_result("None"),
            self._build_result("unknown"),
            self._build_result("N/A"),
            self._build_result(""),
        ]

        pipeline._send_notifications(results, skip_push=True)

        portfolio_section = pipeline.notifier.generate_dashboard_report.call_args.kwargs["portfolio_summary_section"]
        self.assertIn("## 🎯 组合决策总结（报告日 2026-04-07）", portfolio_section)
        self.assertNotIn("技术基准日 None", portfolio_section)

    @patch("src.core.pipeline._now_in_timezone_safe")
    def test_summary_prefix_keeps_valid_snapshot_date(self, mock_now) -> None:
        mock_now.return_value = datetime(2026, 4, 7, 9, 0, 0)
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(market_timezone="Australia/Sydney")
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.generate_portfolio_summary.return_value = "summary-body"
        pipeline.notifier = MagicMock()
        pipeline.notifier.generate_dashboard_report.return_value = "dashboard-body"
        pipeline.notifier.save_report_to_file.return_value = "/tmp/report.md"
        pipeline.notifier.get_last_daily_decision_summary.return_value = None

        pipeline._send_notifications([self._build_result("2026-04-06")], skip_push=True)

        portfolio_section = pipeline.notifier.generate_dashboard_report.call_args.kwargs["portfolio_summary_section"]
        self.assertIn("## 🎯 组合决策总结（技术基准日 2026-04-06｜报告日 2026-04-07）", portfolio_section)

    @patch("src.core.pipeline._now_in_timezone_safe")
    def test_summary_prefix_uses_report_run_date_before_market_open(self, mock_now) -> None:
        mock_now.return_value = datetime(2026, 3, 30, 8, 30, 0, tzinfo=ZoneInfo("Australia/Sydney"))
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(market_calendar="ASX", market_timezone="Australia/Sydney")
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.generate_portfolio_summary.return_value = "summary-body"
        pipeline.notifier = MagicMock()
        pipeline.notifier.generate_dashboard_report.return_value = "dashboard-body"
        pipeline.notifier.save_report_to_file.return_value = "/tmp/report.md"
        pipeline.notifier.get_last_daily_decision_summary.return_value = None

        pipeline._send_notifications([self._build_result("2026-03-27")], skip_push=True)

        portfolio_section = pipeline.notifier.generate_dashboard_report.call_args.kwargs["portfolio_summary_section"]
        self.assertIn("## 🎯 组合决策总结（技术基准日 2026-03-27｜报告日 2026-03-30）", portfolio_section)


if __name__ == "__main__":
    unittest.main()
