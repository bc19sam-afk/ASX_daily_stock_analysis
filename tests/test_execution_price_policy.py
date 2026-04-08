# -*- coding: utf-8 -*-

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.analyzer import AnalysisResult
from src.config import Config
from src.core.pipeline import StockAnalysisPipeline
from src.core.config_registry import get_field_definition


def test_config_execution_price_policy_defaults_to_realtime_if_available():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        os.environ.pop("EXECUTION_PRICE_POLICY", None)
        os.environ.pop("ENABLE_REALTIME_QUOTE", None)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.execution_price_policy == "realtime_if_available"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)


def test_config_execution_price_policy_uses_close_only_when_legacy_realtime_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("STOCK_LIST=BHP.AX\nENABLE_REALTIME_QUOTE=false\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        os.environ.pop("EXECUTION_PRICE_POLICY", None)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.execution_price_policy == "close_only"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)


def test_config_execution_price_policy_accepts_alias_and_normalizes():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("STOCK_LIST=BHP.AX\nEXECUTION_PRICE_POLICY=realtime\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.execution_price_policy == "realtime_if_available"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)


def test_config_execution_price_policy_invalid_explicit_falls_back_to_legacy_false():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "STOCK_LIST=BHP.AX\nEXECUTION_PRICE_POLICY=bad_value\nENABLE_REALTIME_QUOTE=false\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(env_path)
        os.environ["EXECUTION_PRICE_POLICY"] = "bad_value"
        os.environ["ENABLE_REALTIME_QUOTE"] = "false"
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.execution_price_policy == "close_only"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)
            os.environ.pop("EXECUTION_PRICE_POLICY", None)
            os.environ.pop("ENABLE_REALTIME_QUOTE", None)


def test_config_execution_price_policy_invalid_explicit_falls_back_to_legacy_true():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "STOCK_LIST=BHP.AX\nEXECUTION_PRICE_POLICY=bad_value\nENABLE_REALTIME_QUOTE=true\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(env_path)
        os.environ["EXECUTION_PRICE_POLICY"] = "bad_value"
        os.environ["ENABLE_REALTIME_QUOTE"] = "true"
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.execution_price_policy == "realtime_if_available"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)
            os.environ.pop("EXECUTION_PRICE_POLICY", None)
            os.environ.pop("ENABLE_REALTIME_QUOTE", None)


def test_config_registry_has_execution_price_policy_enum_validation():
    field = get_field_definition("EXECUTION_PRICE_POLICY")
    assert field["options"] == ["realtime_if_available", "close_only"]
    assert field["validation"].get("enum") == ["realtime_if_available", "close_only"]


def test_config_classify_reload_scope_separates_runtime_and_process_start_keys():
    runtime_refreshable, process_start = Config.classify_reload_scope(
        ["stock_list", "EXECUTION_PRICE_POLICY", "LOG_LEVEL", "ENABLE_CHIP_DISTRIBUTION"]
    )

    assert runtime_refreshable == [
        "ENABLE_CHIP_DISTRIBUTION",
        "EXECUTION_PRICE_POLICY",
        "STOCK_LIST",
    ]
    assert process_start == ["LOG_LEVEL"]


def test_runtime_execution_price_policy_close_only_ignores_realtime_price():
    enhanced_context = {
        "realtime": {"price": "101.5"},
        "today": {"close": "99.8"},
    }
    price = StockAnalysisPipeline._resolve_execution_price(
        enhanced_context=enhanced_context,
        execution_price_policy="close_only",
    )
    source = StockAnalysisPipeline._resolve_execution_price_source(
        enhanced_context=enhanced_context,
        execution_price_policy="close_only",
    )
    assert price == 99.8
    assert source == "close_only"


def test_runtime_execution_price_policy_realtime_if_available_prefers_realtime():
    enhanced_context = {
        "realtime": {"price": "101.5"},
        "today": {"close": "99.8"},
    }
    price = StockAnalysisPipeline._resolve_execution_price(
        enhanced_context=enhanced_context,
        execution_price_policy="realtime_if_available",
    )
    source = StockAnalysisPipeline._resolve_execution_price_source(
        enhanced_context=enhanced_context,
        execution_price_policy="realtime_if_available",
    )
    assert price == 101.5
    assert source == "realtime"


def test_runtime_signal_price_and_execution_price_are_separated():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(execution_price_policy="close_only")
    result = AnalysisResult(
        code="BHP.AX",
        name="BHP",
        sentiment_score=60,
        trend_prediction="震荡",
        operation_advice="持有",
    )
    enhanced_context = {
        "realtime": {"price": "120.2", "change_pct": "1.2"},
        "today": {"close": "118.4"},
    }
    pipeline._apply_runtime_price_fields(result=result, enhanced_context=enhanced_context)

    assert result.realtime_price == "120.2"
    assert result.current_price == 118.4
    assert result.execution_price_source == "close_only"
