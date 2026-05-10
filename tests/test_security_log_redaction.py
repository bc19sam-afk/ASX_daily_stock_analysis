# -*- coding: utf-8 -*-
"""Regression tests for security-sensitive log redaction."""

import logging
from unittest.mock import Mock, patch

from src.notification import NotificationService
from src.security_logging import (
    describe_database_url_for_log,
    log_sensitive_payload,
    summarize_http_response_for_log,
    summarize_sensitive_payload_for_log,
)
from src.storage import DatabaseManager


def test_prompt_and_ai_response_metadata_excludes_raw_payload_by_default(caplog, monkeypatch):
    monkeypatch.delenv("LOG_SENSITIVE_PAYLOADS", raising=False)
    raw_prompt = (
        "portfolio holdings: BHP.AX 1000 shares; prompt-secret-marker; "
        "LLM must see full user and portfolio context"
    )
    raw_response = (
        '{"analysis_summary":"response-secret-marker",'
        '"position_action":"BUY","target_quantity":999}'
    )

    caplog.set_level(logging.DEBUG, logger="security-redaction-test")
    logger = logging.getLogger("security-redaction-test")

    log_sensitive_payload(logger, logging.DEBUG, "LLM Prompt", raw_prompt)
    log_sensitive_payload(logger, logging.DEBUG, "LLM Response", raw_response)

    text = caplog.text
    assert "prompt-secret-marker" not in text
    assert "response-secret-marker" not in text
    assert "target_quantity" not in text
    assert "length=" in text
    assert "sha256=" in text
    assert "redacted" in text


def test_sensitive_payload_requires_explicit_env_to_log_full_content(monkeypatch):
    payload = "full-sensitive-debug-marker"

    monkeypatch.delenv("LOG_SENSITIVE_PAYLOADS", raising=False)
    default_summary = summarize_sensitive_payload_for_log("payload", payload)
    assert "full-sensitive-debug-marker" not in default_summary

    monkeypatch.setenv("LOG_SENSITIVE_PAYLOADS", "true")
    explicit_summary = summarize_sensitive_payload_for_log("payload", payload)
    assert "full-sensitive-debug-marker" in explicit_summary


def test_webhook_response_summary_hides_url_token_and_body_but_keeps_diagnostics():
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/token-secret-value"
    body = '{"msg":"failed token-secret-value", "debug":"provider-secret-marker"}'

    summary = summarize_http_response_for_log(
        "Feishu",
        status_code=400,
        body=body,
        message=f"bad webhook {webhook_url}",
    )

    assert "token-secret-value" not in summary
    assert "provider-secret-marker" not in summary
    assert webhook_url not in summary
    assert "status=400" in summary
    assert "body_length=" in summary
    assert "body_sha256=" in summary
    assert "[redacted-url]" in summary


def test_feishu_sender_logs_redacted_url_and_response_metadata(caplog):
    service = NotificationService.__new__(NotificationService)
    service._feishu_url = "https://open.feishu.cn/open-apis/bot/v2/hook/token-secret-value"
    service._webhook_verify_ssl = True
    response = Mock(
        status_code=400,
        text='{"msg":"failed token-secret-value","debug":"provider-secret-marker"}',
    )

    caplog.set_level(logging.DEBUG, logger="src.notification")
    with patch("src.notification.requests.post", return_value=response):
        assert service._send_feishu_message("hello") is False

    text = caplog.text
    assert service._feishu_url not in text
    assert "token-secret-value" not in text
    assert "provider-secret-marker" not in text
    assert "[redacted-url]" in text
    assert "status=400" in text
    assert "body_length=" in text
    assert "body_sha256=" in text


def test_database_url_log_description_hides_full_path_and_credentials():
    sqlite_url = "sqlite:///C:/Users/Steve/private/path/stock_analysis.db"
    postgres_url = "postgresql://dbuser:secret-password@db.internal.example:5432/portfolio"

    sqlite_summary = describe_database_url_for_log(sqlite_url)
    postgres_summary = describe_database_url_for_log(postgres_url)

    assert "C:/Users/Steve/private/path" not in sqlite_summary
    assert "stock_analysis.db" in sqlite_summary
    assert "secret-password" not in postgres_summary
    assert "db.internal.example" not in postgres_summary
    assert "postgresql" in postgres_summary


def test_database_manager_startup_log_hides_full_sqlite_path(tmp_path, caplog):
    DatabaseManager.reset_instance()
    db_dir = tmp_path / "private" / "path"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "stock_analysis.db"

    caplog.set_level(logging.INFO, logger="src.storage")
    manager = DatabaseManager(db_url=f"sqlite:///{db_path.as_posix()}")
    try:
        text = caplog.text
        assert db_dir.as_posix() not in text
        assert "stock_analysis.db" in text
        assert "database_type=sqlite" in text
    finally:
        manager._engine.dispose()
        DatabaseManager.reset_instance()
