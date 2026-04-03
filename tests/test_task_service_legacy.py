import logging
import os

from src.enums import ReportType
from src.services import task_service


def test_get_task_service_emits_legacy_warning_once(caplog):
    # isolate singleton and one-time warning state for this test
    task_service.TaskService._instance = None
    task_service._LEGACY_WARNING_EMITTED = False

    caplog.set_level(logging.WARNING)

    task_service.get_task_service()
    task_service.get_task_service()

    legacy_records = [
        r for r in caplog.records
        if "Legacy compatibility layer only" in r.getMessage()
    ]
    assert len(legacy_records) == 1


def test_task_service_run_analysis_applies_proxy_env_without_main(monkeypatch):
    task_service.TaskService._instance = None

    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("USE_PROXY", "true")
    monkeypatch.setenv("PROXY_HOST", "10.8.0.1")
    monkeypatch.setenv("PROXY_PORT", "18080")
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)

    class DummyPipeline:
        def __init__(self, **kwargs):
            assert kwargs["query_id"] == "task_proxy"
            assert kwargs["query_source"] == "bot"
            assert kwargs["save_context_snapshot"] is None
            assert kwargs["max_workers"] == 1
            assert kwargs["source_message"] is None
            assert kwargs["config"] is not None
            assert os.environ["http_proxy"] == "http://10.8.0.1:18080"
            assert os.environ["https_proxy"] == "http://10.8.0.1:18080"

        def process_single_stock(self, **kwargs):
            return None

    monkeypatch.setattr("src.config.get_config", lambda: object())
    monkeypatch.setattr("src.core.pipeline.StockAnalysisPipeline", DummyPipeline)

    svc = task_service.TaskService()
    result = svc._run_analysis("BHP.AX", "task_proxy", ReportType.SIMPLE)
    assert result["success"] is False
