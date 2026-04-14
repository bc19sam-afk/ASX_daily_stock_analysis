from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


_TRANSIENT_STATUS_RE = re.compile(r"\b(429|500|502|503|504)\b")
_TRANSIENT_ERROR_TOKENS = (
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "temporarily unavailable",
    "service unavailable",
    "internal server error",
    "backend error",
    "deadline exceeded",
    "timed out",
    "timeout",
    "connection error",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection closed",
    "network error",
    "socket error",
)


def is_valid_gemini_api_key(key: Optional[str]) -> bool:
    return bool(key and not key.startswith("your_") and len(key) > 10)


def parse_gemini_api_keys(
    multi_value: Optional[str],
    single_value: Optional[str],
) -> list[str]:
    raw_values: list[str]
    if multi_value and multi_value.strip():
        raw_values = multi_value.split(",")
    elif single_value and single_value.strip():
        raw_values = [single_value]
    else:
        raw_values = []

    parsed: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        parsed.append(value)
    return parsed


def is_transient_gemini_error(error: Exception | str) -> bool:
    message = str(error or "").lower()
    if not message:
        return False
    if _TRANSIENT_STATUS_RE.search(message):
        return True
    return any(token in message for token in _TRANSIENT_ERROR_TOKENS)


@dataclass
class GeminiKeyManager:
    raw_keys: Iterable[str] = field(default_factory=list)
    _keys: list[str] = field(init=False, default_factory=list)
    _current_index: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for raw in self.raw_keys:
            key = str(raw or "").strip()
            if not is_valid_gemini_api_key(key) or key in seen:
                continue
            seen.add(key)
            self._keys.append(key)

    @classmethod
    def from_config(cls, config: object, override_key: Optional[str] = None) -> "GeminiKeyManager":
        if override_key is not None:
            return cls(raw_keys=[override_key])

        config_keys = list(getattr(config, "gemini_api_keys", []) or [])
        if config_keys:
            return cls(raw_keys=config_keys)

        legacy_key = getattr(config, "gemini_api_key", None)
        return cls(raw_keys=[legacy_key] if legacy_key else [])

    @property
    def current_key(self) -> Optional[str]:
        if not self._keys:
            return None
        return self._keys[self._current_index]

    @property
    def total_keys(self) -> int:
        return len(self._keys)

    def has_keys(self) -> bool:
        return bool(self._keys)

    def has_next_key(self) -> bool:
        return self._current_index + 1 < len(self._keys)

    def rotate_to_next_key(self) -> bool:
        if not self.has_next_key():
            return False
        self._current_index += 1
        return True

    def current_key_label(self) -> str:
        if not self.current_key:
            return "<none>"
        return f"{self.current_key[:8]}..."
