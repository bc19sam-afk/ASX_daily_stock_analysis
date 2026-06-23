import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.notification import NotificationChannel, NotificationService


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

        health = pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        pipeline.notifier.save_report_to_file.assert_called_once_with(
            archive_report,
            report_date="2026-05-18",
        )
        pipeline.notifier.save_report_archive_html.assert_called_once()
        self.assertEqual(pipeline.notifier.save_report_archive_html.call_args.args[0], archive_report)
        pipeline.notifier.send_to_context.assert_called_once_with(archive_report)
        pipeline.notifier.build_email_report_body.assert_called_once_with(archive_report)
        pipeline.notifier.send_to_email.assert_called_once_with(email_report)
        self.assertTrue(health["report_saved"])
        self.assertTrue(health["html_saved"])
        self.assertTrue(health["json_saved"])
        self.assertTrue(health["notification_attempted"])
        self.assertFalse(health["notification_failed"])
        self.assertEqual(health["report_path"], "/tmp/report.md")
        self.assertEqual(health["html_path"], "/tmp/report.html")
        self.assertEqual(health["summary_path"], "/tmp/summary.json")

    def test_delivery_health_marks_partial_notification_failure(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        self.assertIsNone(pipeline.get_last_delivery_health())
        pipeline.notifier.get_available_channels.return_value = [
            NotificationChannel.EMAIL,
            NotificationChannel.SERVERCHAN3,
        ]
        pipeline.notifier.generate_dashboard_report.return_value = "# report"
        pipeline.notifier.build_email_report_body.return_value = "# email"
        pipeline.notifier.send_to_email.return_value = True
        pipeline.notifier.send_to_serverchan3.return_value = False

        health = pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        self.assertTrue(health["notification_attempted"])
        self.assertFalse(health["notification_failed"])
        self.assertTrue(health["notification_partial_failed"])
        self.assertEqual(health["notification_failed_channels"], ["serverchan3"])
        self.assertEqual(
            health["notification_channel_results"],
            {"email": True, "serverchan3": False},
        )
        self.assertEqual(pipeline.get_last_delivery_health(), health)

        returned_health = pipeline.get_last_delivery_health()
        returned_health["notification_failed_channels"].append("mutated")
        self.assertEqual(pipeline.get_last_delivery_health()["notification_failed_channels"], ["serverchan3"])

    def test_delivery_health_keeps_channel_failures_visible_when_context_succeeds(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        pipeline.notifier.get_available_channels.return_value = [
            NotificationChannel.EMAIL,
            NotificationChannel.SERVERCHAN3,
        ]
        pipeline.notifier.send_to_context.return_value = True
        pipeline.notifier.last_context_channel_attempted = True
        pipeline.notifier.generate_dashboard_report.return_value = "# report"
        pipeline.notifier.build_email_report_body.return_value = "# email"
        pipeline.notifier.send_to_email.return_value = False
        pipeline.notifier.send_to_serverchan3.return_value = False

        health = pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        self.assertTrue(health["notification_context_success"])
        self.assertFalse(health["notification_failed"])
        self.assertTrue(health["notification_partial_failed"])
        self.assertEqual(health["notification_failed_channels"], ["email", "serverchan3"])
        self.assertEqual(
            health["notification_channel_results"],
            {"context": True, "email": False, "serverchan3": False},
        )

    def test_delivery_health_keeps_context_failure_visible_when_channel_succeeds(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        pipeline.notifier.get_available_channels.return_value = [NotificationChannel.EMAIL]
        pipeline.notifier.send_to_context.return_value = False
        pipeline.notifier.last_context_channel_attempted = True
        pipeline.notifier.generate_dashboard_report.return_value = "# report"
        pipeline.notifier.build_email_report_body.return_value = "# email"
        pipeline.notifier.send_to_email.return_value = True

        health = pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        self.assertTrue(health["notification_context_attempted"])
        self.assertFalse(health["notification_context_success"])
        self.assertFalse(health["notification_failed"])
        self.assertTrue(health["notification_partial_failed"])
        self.assertEqual(health["notification_failed_channels"], ["context"])
        self.assertEqual(
            health["notification_channel_results"],
            {"context": False, "email": True},
        )

    def test_delivery_health_marks_email_render_failure_after_artifacts_saved(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        pipeline.notifier.generate_dashboard_report.return_value = "# report"
        pipeline.notifier.build_email_report_body.side_effect = RuntimeError("email body render failed")

        with patch("src.core.pipeline.logger.error") as mock_error:
            health = pipeline._send_notifications([self._build_result("2026-05-15")], skip_push=False)

        self.assertTrue(health["report_saved"])
        self.assertTrue(health["html_saved"])
        self.assertTrue(health["json_saved"])
        self.assertTrue(health["notification_attempted"])
        self.assertTrue(health["notification_failed"])
        self.assertEqual(health["notification_failure_stage"], "email")
        self.assertIn("email body render failed", health["notification_failure_message"])
        self.assertTrue(
            any(
                "日报交付健康检查失败" in call.args[0]
                and call.kwargs.get("exc_info")
                for call in mock_error.call_args_list
            )
        )

    @patch("src.notification.get_db")
    def test_malformed_dashboard_data_still_saves_all_daily_artifacts(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 10000.0,
            "equity_value": 0.0,
            "total_value": 10000.0,
            "holdings": [],
        }
        mock_get_db.return_value.get_paper_portfolio_overview.return_value = {"initialized": False}
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(market_timezone="Australia/Sydney")
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.generate_portfolio_summary.return_value = ""
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = False
        service._report_timezone = "Australia/Sydney"
        service._last_daily_decision_summary = None
        service._now_in_report_tz = lambda: datetime(2026, 6, 3, 8, 30, tzinfo=ZoneInfo("Australia/Sydney"))
        pipeline.notifier = service
        result = AnalysisResult(
            code="GMG.AX",
            name="GOOD GROUP",
            sentiment_score=70,
            trend_prediction="震荡",
            operation_advice="观察",
            final_decision="HOLD",
            position_action="HOLD",
            market_snapshot={"date": "2026-06-02", "close": "10.00", "source": "yfinance"},
            dashboard={"core_conclusion": "string-shaped core block"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_reports_dir = Path(tmpdir)

            def save_report(content, filename=None, reports_dir=None, *, report_date=None):
                return NotificationService.save_report_to_file(
                    service,
                    content,
                    filename=filename,
                    reports_dir=tmp_reports_dir,
                    report_date=report_date,
                )

            def save_html(content, filename=None, *, markdown_filepath=None, reports_dir=None, report_date=None):
                return NotificationService.save_report_archive_html(
                    service,
                    content,
                    filename=filename,
                    markdown_filepath=markdown_filepath,
                    reports_dir=tmp_reports_dir,
                    report_date=report_date,
                )

            def save_summary(summary, filename=None, *, reports_dir=None):
                return NotificationService.save_daily_decision_summary_to_file(
                    service,
                    summary,
                    filename=filename,
                    reports_dir=tmp_reports_dir,
                )

            service.save_report_to_file = save_report
            service.save_report_archive_html = save_html
            service.save_daily_decision_summary_to_file = save_summary
            health = pipeline._send_notifications([result], skip_push=True)

        self.assertTrue(health["report_saved"])
        self.assertTrue(health["html_saved"])
        self.assertTrue(health["json_saved"])
        self.assertFalse(health["notification_attempted"])
        self.assertIn("report_20260603.md", health["report_path"])
        self.assertIn("report_20260603.html", health["html_path"])
        self.assertIn("daily_decision_summary_20260603.json", health["summary_path"])

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

    def test_stock_email_group_partial_failure_is_visible_in_delivery_health(self) -> None:
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
        pipeline.notifier.generate_dashboard_report.side_effect = lambda group_results, **_kwargs: (
            "# " + "-".join(r.code for r in group_results)
        )
        pipeline.notifier.build_email_report_body.side_effect = lambda body: body
        pipeline.notifier.send_to_email.side_effect = [True, False]

        health = pipeline._send_notifications(results, skip_push=False)

        self.assertFalse(health["notification_failed"])
        self.assertTrue(health["notification_partial_failed"])
        self.assertEqual(health["notification_failed_channels"], ["email"])
        self.assertEqual(health["notification_channel_results"], {"email": False})
        self.assertEqual(
            health["notification_email_batch_results"],
            [
                {"receivers": ["aaa@example.com"], "success": True},
                {"receivers": ["bbb@example.com"], "success": False},
            ],
        )

    def test_notification_failure_logs_traceback_context(self) -> None:
        pipeline = self._build_pipeline_for_email_split()
        pipeline.notifier.generate_dashboard_report.side_effect = RuntimeError("string-shaped data")

        with patch("src.core.pipeline.logger.error") as mock_error:
            pipeline._send_notifications([self._build_result("2026-06-02")], skip_push=True)

        mock_error.assert_called_once()
        self.assertTrue(mock_error.call_args.kwargs.get("exc_info"))
        self.assertIn("发送通知失败", mock_error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
