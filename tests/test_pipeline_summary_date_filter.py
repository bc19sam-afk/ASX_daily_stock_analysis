import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.notification import NotificationChannel


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

    def _build_pipeline_for_email_split(self, *, stock_email_groups=None):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(
            market_calendar="ASX",
            market_timezone="Australia/Sydney",
            stock_email_groups=stock_email_groups or [],
        )
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.generate_portfolio_summary.return_value = ""
        pipeline.notifier = MagicMock()
        pipeline.notifier.get_last_daily_decision_summary.return_value = {"report_date": "2026-05-18"}
        pipeline.notifier.save_report_to_file.return_value = "/tmp/report.md"
        pipeline.notifier.save_report_archive_html.return_value = "/tmp/report.html"
        pipeline.notifier.save_daily_decision_summary_to_file.return_value = "/tmp/summary.json"
        pipeline.notifier.is_available.return_value = True
        pipeline.notifier.get_available_channels.return_value = [NotificationChannel.EMAIL]
        pipeline.notifier.send_to_context.return_value = False
        pipeline.notifier.send_to_email.return_value = True
        return pipeline

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

    def test_email_channel_uses_concise_body_while_archive_keeps_full_report(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        archive_report = "# report\n\n## 开盘前决策驾驶舱\n\nmain\n\n## 详情 / 审计附录\n\nmatrix"
        email_report = "# report\n\n## 开盘前决策驾驶舱\n\nmain\n\n## 完整归档"
        pipeline.notifier.generate_dashboard_report.return_value = archive_report
        pipeline.notifier.build_email_report_body.return_value = email_report

        pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        pipeline.notifier.save_report_to_file.assert_called_once_with(
            archive_report,
            report_date="2026-05-18",
        )
        pipeline.notifier.save_report_archive_html.assert_called_once()
        self.assertEqual(pipeline.notifier.save_report_archive_html.call_args.args[0], archive_report)
        pipeline.notifier.send_to_context.assert_called_once_with(archive_report)
        pipeline.notifier.build_email_report_body.assert_called_once_with(archive_report)
        pipeline.notifier.send_to_email.assert_called_once_with(email_report)

    def test_stock_email_groups_use_concise_group_body(self) -> None:
        pipeline = self._build_pipeline_for_email_split(
            stock_email_groups=[
                (["AAA"], ["aaa@example.com"]),
                (["BBB"], ["bbb@example.com"]),
            ],
        )
        results = [
            self._build_result("2026-05-15"),
            AnalysisResult(
                code="BBB",
                name="样例二",
                sentiment_score=55,
                trend_prediction="震荡",
                operation_advice="观察",
                market_snapshot={"date": "2026-05-15"},
            ),
        ]

        def render_report(group_results, **_kwargs):
            codes = "-".join(r.code for r in group_results)
            return f"# {codes}\n\n## 开盘前决策驾驶舱\n\nmain\n\n## 详情 / 审计附录\n\nmatrix-{codes}"

        pipeline.notifier.generate_dashboard_report.side_effect = render_report
        pipeline.notifier.build_email_report_body.side_effect = lambda body: body.split("\n## 详情 / 审计附录", 1)[0]

        pipeline._send_notifications(results, skip_push=False)

        sent_calls = pipeline.notifier.send_to_email.call_args_list
        self.assertEqual(len(sent_calls), 2)
        sent_bodies = [call.args[0] for call in sent_calls]
        self.assertTrue(any(body.startswith("# AAA") for body in sent_bodies))
        self.assertTrue(any(body.startswith("# BBB") for body in sent_bodies))
        self.assertTrue(all("详情 / 审计附录" not in body for body in sent_bodies))
        self.assertTrue(all("matrix-" not in body for body in sent_bodies))
        sent_receivers = [call.kwargs["receivers"] for call in sent_calls]
        self.assertIn(["aaa@example.com"], sent_receivers)
        self.assertIn(["bbb@example.com"], sent_receivers)


if __name__ == "__main__":
    unittest.main()
