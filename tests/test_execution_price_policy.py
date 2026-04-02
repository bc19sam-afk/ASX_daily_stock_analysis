# -*- coding: utf-8 -*-

import os
import tempfile
from pathlib import Path

from src.config import Config
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
