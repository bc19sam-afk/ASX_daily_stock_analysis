# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.config import Config
from src.core.pipeline import StockAnalysisPipeline


def test_pipeline_run_refreshes_stock_list_on_reused_config(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=BHP.AX,CBA.AX\n", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    Config.reset_instance()

    monkeypatch.setattr(
        "src.core.pipeline.get_db",
        lambda: SimpleNamespace(
            has_today_data=lambda code: False,
        ),
    )
    monkeypatch.setattr(
        "src.core.pipeline.DataFetcherManager",
        lambda config=None: SimpleNamespace(prefetch_realtime_quotes=lambda codes: 0),
    )
    monkeypatch.setattr("src.core.pipeline.StockTrendAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.GeminiAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "src.core.pipeline.NotificationService",
        lambda source_message=None: SimpleNamespace(is_available=lambda: False),
    )
    monkeypatch.setattr("src.core.pipeline.PositionManager", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.SearchService", lambda **kwargs: SimpleNamespace(is_available=False))

    config = Config.get_instance()
    pipeline = StockAnalysisPipeline(config=config, max_workers=1)

    observed_codes: list[str] = []

    def fake_process_single_stock(code, **kwargs):
        observed_codes.append(code)
        return None

    monkeypatch.setattr(pipeline, "_fetch_market_overview", lambda: {})
    monkeypatch.setattr(pipeline, "process_single_stock", fake_process_single_stock)

    env_path.write_text("STOCK_LIST=CSL.AX,GMG.AX\n", encoding="utf-8")

    pipeline.run(stock_codes=None, dry_run=True, send_notification=False)

    assert observed_codes == ["CSL.AX", "GMG.AX"]
