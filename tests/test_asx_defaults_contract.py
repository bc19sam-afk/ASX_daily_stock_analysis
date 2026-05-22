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
