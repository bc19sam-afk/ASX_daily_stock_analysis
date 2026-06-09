# -*- coding: utf-8 -*-
"""Regression tests for ASX-first default runtime surfaces."""

from pathlib import Path

from src.config import Config
from src.core.config_registry import get_field_definition


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_default_config_stock_list_is_asx_first(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("STOCK_LIST", raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()
        assert config.stock_list == ["BHP.AX", "CBA.AX", "CSL.AX"]
    finally:
        Config.reset_instance()


def test_refresh_stock_list_empty_env_preserves_asx_first_default(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("STOCK_LIST", raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()
        config.stock_list = ["SHOULD.BE.REPLACED"]

        config.refresh_stock_list()

        assert config.stock_list == ["BHP.AX", "CBA.AX", "CSL.AX"]
    finally:
        Config.reset_instance()


def test_config_stock_list_canonicalizes_common_asx_suffix_alias(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=NHF.ASX,NHF.AX,BHP.AX\n", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("STOCK_LIST", raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()

        assert config.stock_list == ["NHF.AX", "BHP.AX"]

        env_path.write_text("STOCK_LIST=SHL.ASX,GMG.AX\n", encoding="utf-8")
        config.refresh_stock_list()

        assert config.stock_list == ["SHL.AX", "GMG.AX"]
    finally:
        Config.reset_instance()


def test_config_registry_stock_list_default_is_asx_first():
    stock_list = get_field_definition("STOCK_LIST")

    assert stock_list is not None
    assert stock_list["default_value"] == Config.default_stock_list_csv()


def test_daily_workflow_gemini_defaults_match_runtime_config():
    daily_workflow = _read(".github/workflows/daily_analysis.yml")

    assert "GEMINI_MODEL: ${{ vars.GEMINI_MODEL || secrets.GEMINI_MODEL || 'gemini-3.5-flash' }}" in daily_workflow
    assert (
        "GEMINI_MODEL_FALLBACK: "
        "${{ vars.GEMINI_MODEL_FALLBACK || secrets.GEMINI_MODEL_FALLBACK || 'gemini-3-flash-preview' }}"
    ) in daily_workflow
    assert "GEMINI_MODEL: ${{ vars.GEMINI_MODEL || secrets.GEMINI_MODEL || 'gemini-3-flash-preview' }}" not in daily_workflow
    assert "GEMINI_MODEL_FALLBACK: ${{ vars.GEMINI_MODEL_FALLBACK || secrets.GEMINI_MODEL_FALLBACK || 'gemini-2.5-flash' }}" not in daily_workflow


def test_daily_workflow_exposes_gemini_grounding_search_defaults():
    daily_workflow = _read(".github/workflows/daily_analysis.yml")

    assert "GEMINI_GROUNDING_SEARCH_ENABLED: ${{ vars.GEMINI_GROUNDING_SEARCH_ENABLED || 'true' }}" in daily_workflow
    assert (
        "GEMINI_GROUNDING_MODEL: "
        "${{ vars.GEMINI_GROUNDING_MODEL || secrets.GEMINI_GROUNDING_MODEL || vars.GEMINI_MODEL || secrets.GEMINI_MODEL || 'gemini-3.5-flash' }}"
    ) in daily_workflow
    assert "GEMINI_GROUNDING_MAX_RESULTS: ${{ vars.GEMINI_GROUNDING_MAX_RESULTS || '3' }}" in daily_workflow


def test_daily_workflow_keeps_serpapi_market_review_fallback_default_off():
    daily_workflow = _read(".github/workflows/daily_analysis.yml")

    assert (
        "SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED: "
        "${{ vars.SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED || 'false' }}"
    ) in daily_workflow


def test_daily_workflow_exposes_asx_announcement_defaults_without_secrets():
    daily_workflow = _read(".github/workflows/daily_analysis.yml")

    assert "ASX_ANNOUNCEMENTS_ENABLED: ${{ vars.ASX_ANNOUNCEMENTS_ENABLED || 'true' }}" in daily_workflow
    assert "ASX_ANNOUNCEMENTS_LOOKBACK_DAYS: ${{ vars.ASX_ANNOUNCEMENTS_LOOKBACK_DAYS || '1' }}" in daily_workflow
    assert "ASX_ANNOUNCEMENTS_MAX_ITEMS: ${{ vars.ASX_ANNOUNCEMENTS_MAX_ITEMS || '5' }}" in daily_workflow
    assert "ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS: ${{ vars.ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS || '10' }}" in daily_workflow
    assert "secrets.ASX_ANNOUNCEMENTS" not in daily_workflow


def test_config_registry_exposes_asx_announcement_defaults():
    enabled = get_field_definition("ASX_ANNOUNCEMENTS_ENABLED")
    lookback = get_field_definition("ASX_ANNOUNCEMENTS_LOOKBACK_DAYS")
    max_items = get_field_definition("ASX_ANNOUNCEMENTS_MAX_ITEMS")
    timeout = get_field_definition("ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS")

    assert enabled["default_value"] == "true"
    assert lookback["default_value"] == "1"
    assert max_items["default_value"] == "5"
    assert timeout["default_value"] == "10"
    assert enabled["is_sensitive"] is False
    assert timeout["validation"]["max"] == 10


def test_config_registry_exposes_news_intel_cache_defaults():
    enabled = get_field_definition("NEWS_INTEL_CACHE_ENABLED")
    days = get_field_definition("NEWS_INTEL_CACHE_DAYS")
    min_results = get_field_definition("NEWS_INTEL_CACHE_MIN_RESULTS")

    assert enabled["category"] == "data_source"
    assert enabled["default_value"] == "true"
    assert days["default_value"] == "1"
    assert days["validation"]["min"] == 1
    assert min_results["default_value"] == "1"
    assert min_results["validation"]["min"] == 1


def test_config_registry_exposes_serpapi_market_review_fallback_default_off():
    enabled = get_field_definition("SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED")

    assert enabled["category"] == "data_source"
    assert enabled["default_value"] == "false"
    assert enabled["data_type"] == "boolean"
    assert enabled["is_sensitive"] is False


def test_config_registry_exposes_single_buy_cash_cap_defaults():
    fraction = get_field_definition("MAX_SINGLE_BUY_CASH_FRACTION")
    amount = get_field_definition("MAX_SINGLE_BUY_CASH_AMOUNT")

    assert fraction["category"] == "system"
    assert fraction["default_value"] == "0.34"
    assert fraction["validation"] == {"min": 0.0, "max": 1.0}
    assert fraction["is_sensitive"] is False
    assert amount["category"] == "system"
    assert amount["default_value"] is None
    assert amount["validation"] == {"min": 0.0}
    assert amount["is_sensitive"] is False


def test_runtime_config_exposes_news_intel_cache_defaults(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    for key in (
        "NEWS_INTEL_CACHE_ENABLED",
        "NEWS_INTEL_CACHE_DAYS",
        "NEWS_INTEL_CACHE_MIN_RESULTS",
    ):
        monkeypatch.delenv(key, raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()

        assert config.news_intel_cache_enabled is True
        assert config.news_intel_cache_days == 1
        assert config.news_intel_cache_min_results == 1
    finally:
        Config.reset_instance()


def test_runtime_config_keeps_serpapi_market_review_fallback_default_off(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED", raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()
        assert config.serpapi_market_review_fallback_enabled is False
    finally:
        Config.reset_instance()

    monkeypatch.setenv("SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED", "true")
    Config.reset_instance()
    try:
        config = Config.get_instance()
        assert config.serpapi_market_review_fallback_enabled is True
    finally:
        Config.reset_instance()


def test_runtime_config_exposes_asx_announcement_defaults(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    for key in (
        "ASX_ANNOUNCEMENTS_ENABLED",
        "ASX_ANNOUNCEMENTS_LOOKBACK_DAYS",
        "ASX_ANNOUNCEMENTS_MAX_ITEMS",
        "ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()

        assert config.asx_announcements_enabled is True
        assert config.asx_announcements_lookback_days == 1
        assert config.asx_announcements_max_items == 5
        assert config.asx_announcements_timeout_seconds == 10
    finally:
        Config.reset_instance()


def test_analyzer_llm_pre_call_wait_is_conservative_twenty_seconds():
    analyzer_py = _read("src/analyzer.py")

    assert "time.sleep(20)" in analyzer_py
    assert "time.sleep(30)" not in analyzer_py


def test_workflow_and_docker_defaults_are_asx_sydney():
    daily_workflow = _read(".github/workflows/daily_analysis.yml")
    ci_workflow = _read(".github/workflows/ci.yml")
    dockerfile = _read("docker/Dockerfile")
    compose = _read("docker/docker-compose.yml")

    assert "BHP.AX,CBA.AX,CSL.AX" in daily_workflow
    assert "|| '600519'" not in daily_workflow
    assert "pull_request:" in ci_workflow
    assert "push:" in ci_workflow
    assert "branches: [main]" in ci_workflow
    assert "ENV TZ=Australia/Sydney" in dockerfile
    assert "ENV TZ=Asia/Shanghai" not in dockerfile
    assert "- TZ=Australia/Sydney" in compose
    assert "- TZ=Asia/Shanghai" not in compose


def test_cn_legacy_exposure_is_removed_from_active_examples_and_docs():
    env_example = _read(".env.example")
    daily_workflow = _read(".github/workflows/daily_analysis.yml")
    full_guide_en = _read("docs/full-guide_EN.md")

    assert "REALTIME_SOURCE_PRIORITY=yfinance" in env_example
    assert "REALTIME_SOURCE_PRIORITY: ${{ vars.REALTIME_SOURCE_PRIORITY || 'yfinance' }}" in daily_workflow
    assert "A-shares" not in full_guide_en


def test_data_provider_default_package_exports_only_asx_path():
    import data_provider

    assert data_provider.__all__ == [
        "BaseFetcher",
        "DataFetcherManager",
        "YfinanceFetcher",
    ]

    for legacy_file in ROOT.glob("data_provider/*_fetcher.py"):
        assert legacy_file.name == "yfinance_fetcher.py"



def test_public_contract_docs_are_asx_first_with_compatibility_examples():
    api_spec = _read("docs/architecture/api_spec.json")
    deploy_zh = _read("docs/DEPLOY.md")
    deploy_en = _read("docs/DEPLOY_EN.md")
    full_guide_zh = _read("docs/full-guide.md")
    full_guide_en = _read("docs/full-guide_EN.md")

    assert "ASX-first 自选股分析系统 API" in api_spec
    assert "Australia/Sydney 08:00" in deploy_zh
    assert "18:00 Beijing Time" not in deploy_en
    assert "08:00 Australia/Sydney" in full_guide_en
    assert "BHP.AX,hk00700,hk01810" in full_guide_zh
    assert "BHP.AX,hk00700,hk01810" in full_guide_en


def test_cli_and_api_examples_are_asx_first():
    main_py = _read("main.py")
    from api.v1.schemas.analysis import AnalyzeRequest
    from api.v1.schemas.stocks import StockHistoryResponse, StockQuote

    assert "python main.py --stocks BHP.AX,CBA.AX,AAPL" in main_py
    assert "python main.py --stocks 600519" not in main_py

    analyze_example = AnalyzeRequest.model_config["json_schema_extra"]["example"]
    quote_example = StockQuote.model_config["json_schema_extra"]["example"]
    history_example = StockHistoryResponse.model_config["json_schema_extra"]["example"]
    assert analyze_example["stock_code"] == "BHP.AX"
    assert analyze_example["stock_codes"] == ["BHP.AX"]
    assert quote_example["stock_code"] == "BHP.AX"
    assert history_example["stock_code"] == "BHP.AX"
