# -*- coding: utf-8 -*-
"""Helpers for logging metadata about security-sensitive payloads."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.engine import make_url


_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_WORD_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization)"
    r"[:=]?[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]*"
)


def sensitive_payload_logging_enabled() -> bool:
    """Return whether full sensitive payload logging was explicitly enabled."""
    value = os.getenv("LOG_SENSITIVE_PAYLOADS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _sha256_12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def redact_log_text(text: Any, *, max_chars: int = 200) -> str:
    """Redact common URL/token shapes while preserving short diagnostic context."""
    value = _coerce_text(text)
    value = _URL_RE.sub("[redacted-url]", value)
    value = _SECRET_WORD_RE.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    if len(value) > max_chars:
        value = f"{value[:max_chars]}..."
    return value


def summarize_sensitive_payload_for_log(
    label: str,
    payload: Any,
    *,
    allow_full: Optional[bool] = None,
) -> str:
    """Summarize prompt/response/report payloads without logging the raw body."""
    text = _coerce_text(payload)
    if allow_full is None:
        allow_full = sensitive_payload_logging_enabled()

    metadata = f"{label} redacted length={len(text)} sha256={_sha256_12(text)}"
    if not allow_full:
        return metadata
    return f"{metadata} full_payload_enabled=true\n{text}"


def log_sensitive_payload(
    logger: logging.Logger,
    level: int,
    label: str,
    payload: Any,
    *,
    allow_full: Optional[bool] = None,
) -> None:
    """Log a sensitive payload summary, optionally full only via explicit config."""
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        summarize_sensitive_payload_for_log(label, payload, allow_full=allow_full),
    )


def summarize_http_response_for_log(
    provider: str,
    *,
    status_code: int,
    body: Any,
    message: Any = None,
) -> str:
    """Summarize provider responses without logging webhook URLs or raw bodies."""
    text = _coerce_text(body)
    parts = [
        f"{provider} response",
        f"status={status_code}",
        f"body_length={len(text)}",
        f"body_sha256={_sha256_12(text)}",
    ]
    if message:
        parts.append(f"message={redact_log_text(message)}")
    return " ".join(parts)


def describe_database_url_for_log(db_url: str) -> str:
    """Describe a database URL without leaking local paths or credentials."""
    try:
        url = make_url(db_url)
    except Exception:
        text = _coerce_text(db_url)
        return f"database_type=unknown url_sha256={_sha256_12(text)}"

    driver = url.drivername or "unknown"
    backend = driver.split("+", 1)[0]
    if backend == "sqlite":
        database = url.database or ""
        if database in {"", ":memory:"}:
            db_name = database or "[memory]"
        else:
            db_name = Path(database).name or "[redacted]"
        return f"database_type={driver} database={db_name}"
    return f"database_type={driver} database=[redacted]"
