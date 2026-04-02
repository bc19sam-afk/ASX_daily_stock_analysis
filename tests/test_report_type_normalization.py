# -*- coding: utf-8 -*-

import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.v1.schemas.analysis import AnalyzeRequest
from src.config import Config
from src.enums import ReportType


def test_report_type_normalize_supports_legacy_detailed_alias():
    assert ReportType.normalize("detailed") == ReportType.FULL
    assert ReportType.normalize("full") == ReportType.FULL
    assert ReportType.normalize("simple") == ReportType.SIMPLE


def test_report_type_normalize_rejects_invalid_value():
    with pytest.raises(ValueError):
        ReportType.normalize("verbose")


def test_config_report_type_parses_legacy_alias_to_full():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("REPORT_TYPE=detailed\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        os.environ.pop("REPORT_TYPE", None)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.report_type == "full"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)


def test_config_report_type_invalid_falls_back_to_full():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("REPORT_TYPE=invalid_type\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        os.environ.pop("REPORT_TYPE", None)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.report_type == "full"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)


def test_api_request_normalizes_detailed_to_full():
    request = AnalyzeRequest(stock_code="BHP.AX", report_type="detailed")
    assert request.report_type == "full"


def test_api_request_rejects_invalid_report_type():
    with pytest.raises(ValidationError):
        AnalyzeRequest(stock_code="BHP.AX", report_type="invalid_type")


def test_config_report_type_missing_uses_full_default():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")

        os.environ["ENV_FILE"] = str(env_path)
        os.environ.pop("REPORT_TYPE", None)
        Config.reset_instance()
        try:
            config = Config.get_instance()
            assert config.report_type == "full"
        finally:
            Config.reset_instance()
            os.environ.pop("ENV_FILE", None)
