# -*- coding: utf-8 -*-
"""ASX official announcement check contract.

This module defines status metadata only. It does not fetch ASX data, call AI,
or feed announcement status back into deterministic portfolio actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.stock_code import canonical_stock_code


ANNOUNCEMENT_CLEAR = "clear"
ANNOUNCEMENT_RISK_FOUND = "risk_found"
ANNOUNCEMENT_UNAVAILABLE = "unavailable"
ANNOUNCEMENT_NOT_CHECKED = "not_checked"

VALID_ANNOUNCEMENT_STATUSES = {
    ANNOUNCEMENT_CLEAR,
    ANNOUNCEMENT_RISK_FOUND,
    ANNOUNCEMENT_UNAVAILABLE,
    ANNOUNCEMENT_NOT_CHECKED,
}


@dataclass(frozen=True)
class ASXAnnouncementCheck:
    """Conservative ASX announcement check status for reporting/evidence only."""

    code: str
    checked: bool = False
    source: str = "not_configured"
    checked_at: Optional[str] = None
    has_price_sensitive_item: Optional[bool] = None
    latest_items: List[Dict[str, Any]] = field(default_factory=list)
    status: str = ANNOUNCEMENT_NOT_CHECKED
    reason: str = ""

    def __post_init__(self) -> None:
        code = canonical_stock_code(self.code)
        status = normalize_announcement_status(self.status)
        if self.has_price_sensitive_item is True and status in {ANNOUNCEMENT_CLEAR, ANNOUNCEMENT_NOT_CHECKED}:
            status = ANNOUNCEMENT_RISK_FOUND
        checked = bool(self.checked or status in {ANNOUNCEMENT_CLEAR, ANNOUNCEMENT_RISK_FOUND})
        source = str(self.source or "").strip() or ("not_configured" if status == ANNOUNCEMENT_NOT_CHECKED else "asx_announcements")
        reason = str(self.reason or "").strip() or default_announcement_reason(status)
        latest_items = [_item_dict(item) for item in (self.latest_items or [])]

        object.__setattr__(self, "code", code)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "checked", checked)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "latest_items", latest_items)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], *, code: Optional[str] = None) -> "ASXAnnouncementCheck":
        """Build a check object from serialized metadata."""
        data = dict(payload or {})
        if code and not data.get("code"):
            data["code"] = code
        return cls(
            code=data.get("code") or "",
            checked=bool(data.get("checked")),
            source=str(data.get("source") or "not_configured"),
            checked_at=data.get("checked_at"),
            has_price_sensitive_item=data.get("has_price_sensitive_item"),
            latest_items=list(data.get("latest_items") or []),
            status=str(data.get("status") or ANNOUNCEMENT_NOT_CHECKED),
            reason=str(data.get("reason") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize contract metadata for summary/report artifacts."""
        return {
            "code": self.code,
            "checked": self.checked,
            "source": self.source,
            "checked_at": self.checked_at,
            "has_price_sensitive_item": self.has_price_sensitive_item,
            "latest_items": list(self.latest_items or []),
            "status": self.status,
            "reason": self.reason,
        }


def build_asx_announcement_check(code: str, **overrides: Any) -> ASXAnnouncementCheck:
    """Return a conservative announcement check, defaulting to not_checked."""
    return ASXAnnouncementCheck(code=code, **overrides)


def coerce_asx_announcement_check(code: str, value: Any) -> ASXAnnouncementCheck:
    """Normalize optional check metadata without inventing a clear status."""
    if isinstance(value, ASXAnnouncementCheck):
        if value.code == canonical_stock_code(code):
            return value
        data = value.to_dict()
        data["code"] = code
        return ASXAnnouncementCheck.from_dict(data)
    if isinstance(value, dict):
        return ASXAnnouncementCheck.from_dict(value, code=code)
    return build_asx_announcement_check(code)


def normalize_announcement_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in VALID_ANNOUNCEMENT_STATUSES:
        return status
    return ANNOUNCEMENT_NOT_CHECKED


def default_announcement_reason(status: str) -> str:
    if status == ANNOUNCEMENT_CLEAR:
        return "ASX 官方公告已检查；未发现已标记的 price-sensitive 风险。"
    if status == ANNOUNCEMENT_RISK_FOUND:
        return "检测到 price-sensitive 公告风险；执行前必须人工复核 ASX 公告。"
    if status == ANNOUNCEMENT_UNAVAILABLE:
        return "ASX 官方公告源不可用；执行前需人工检查公告。"
    return "ASX 官方公告未检查；执行前需人工检查 ASX announcements。"


def _item_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"title": str(value or "").strip()}
