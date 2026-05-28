# -*- coding: utf-8 -*-
"""ASX official market announcement checks for reporting evidence.

This module fetches only ASX public market-announcement listing metadata. It
does not download PDFs, call AI, connect to brokers, or feed announcement
status back into deterministic portfolio actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from src.stock_code import canonical_stock_code, canonical_stock_codes


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

ASX_MARKET_ANNOUNCEMENTS_SOURCE = "asx_market_announcements"
ASX_TODAY_ANNOUNCEMENTS_URL = "https://www.asx.com.au/asx/v2/statistics/todayAnns.do"
ASX_PREVIOUS_TRADING_DAY_ANNOUNCEMENTS_URL = "https://www.asx.com.au/asx/v2/statistics/prevBusDayAnns.do"
ASX_ANNOUNCEMENTS_USER_AGENT = (
    "ASX-daily-stock-analysis/1.0 "
    "(read-only announcement metadata; https://github.com/ZhuLinsen/daily_stock_analysis)"
)
ASX_TIMEZONE = ZoneInfo("Australia/Sydney")
MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS = 10.0

RISK_HEADLINE_RE = re.compile(
    r"\b("
    r"trading\s+halt|"
    r"suspension|"
    r"capital\s+raising|"
    r"material|"
    r"earnings\s+guidance|"
    r"profit\s+guidance|"
    r"takeover|"
    r"scheme\s+of\s+arrangement|"
    r"placement|"
    r"entitlement\s+offer|"
    r"rights\s+issue|"
    r"merger|"
    r"acquisition"
    r")\b",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


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
        source = str(self.source or "").strip() or (
            "not_configured" if status == ANNOUNCEMENT_NOT_CHECKED else ASX_MARKET_ANNOUNCEMENTS_SOURCE
        )
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


@dataclass(frozen=True)
class ASXAnnouncementsFetchResult:
    """Best-effort batch fetch result for ASX listing pages."""

    status: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    reason: str = ""


class ASXAnnouncementParseError(ValueError):
    """Raised when the ASX listing page no longer exposes expected columns."""


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
        return "ASX 公告源不可用，执行前人工检查。"
    return "ASX 官方公告未检查；执行前需人工检查 ASX announcements。"


def is_asx_ticker(value: Any) -> bool:
    """Return True for canonical ASX tickers handled by this source."""
    return canonical_stock_code(value).endswith(".AX")


def fetch_asx_market_announcements(
    *,
    session: Any = None,
    lookback_days: int = 1,
    timeout_seconds: float = MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS,
) -> ASXAnnouncementsFetchResult:
    """Fetch ASX listing pages once per page and parse announcement metadata."""
    http = session or requests.Session()
    timeout = _bounded_timeout(timeout_seconds)
    urls = [ASX_TODAY_ANNOUNCEMENTS_URL]
    if _safe_int(lookback_days, default=1) > 0:
        urls.append(ASX_PREVIOUS_TRADING_DAY_ANNOUNCEMENTS_URL)

    items: List[Dict[str, Any]] = []
    fetched_urls: List[str] = []
    for url in urls[:2]:
        fetched_urls.append(url)
        try:
            response = http.get(
                url,
                headers={"User-Agent": ASX_ANNOUNCEMENTS_USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            items.extend(parse_asx_market_announcements_html(response.text, base_url=url))
        except (ASXAnnouncementParseError, requests.RequestException, TimeoutError, OSError, ValueError) as exc:
            reason = f"ASX announcement source unavailable: {type(exc).__name__}: {exc}"
            logger.warning("%s", reason)
            return ASXAnnouncementsFetchResult(
                status=ANNOUNCEMENT_UNAVAILABLE,
                items=[],
                source_urls=fetched_urls,
                reason=reason,
            )
        except Exception as exc:  # pragma: no cover - defensive daily-job guard
            reason = f"ASX announcement source unavailable: {type(exc).__name__}: {exc}"
            logger.warning("%s", reason)
            return ASXAnnouncementsFetchResult(
                status=ANNOUNCEMENT_UNAVAILABLE,
                items=[],
                source_urls=fetched_urls,
                reason=reason,
            )

    return ASXAnnouncementsFetchResult(
        status="available",
        items=items,
        source_urls=fetched_urls,
        reason="",
    )


def build_asx_announcement_checks(
    codes: List[Any],
    *,
    enabled: bool = True,
    session: Any = None,
    lookback_days: int = 1,
    max_items: int = 5,
    timeout_seconds: float = MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS,
    now_iso: Optional[str] = None,
) -> Dict[str, ASXAnnouncementCheck]:
    """Build per-ASX-code checks from one batched official announcement fetch."""
    if not enabled:
        return {}

    asx_codes = [code for code in canonical_stock_codes(codes) if is_asx_ticker(code)]
    if not asx_codes:
        return {}

    checked_at = now_iso or _checked_at_iso()
    fetch_result = fetch_asx_market_announcements(
        session=session,
        lookback_days=lookback_days,
        timeout_seconds=timeout_seconds,
    )
    if fetch_result.status != "available":
        return {
            code: ASXAnnouncementCheck(
                code=code,
                checked=False,
                source=ASX_MARKET_ANNOUNCEMENTS_SOURCE,
                checked_at=checked_at,
                has_price_sensitive_item=None,
                latest_items=[],
                status=ANNOUNCEMENT_UNAVAILABLE,
                reason=default_announcement_reason(ANNOUNCEMENT_UNAVAILABLE),
            )
            for code in asx_codes
        }

    grouped = _items_by_code(fetch_result.items)
    limit = max(0, _safe_int(max_items, default=5))
    checks: Dict[str, ASXAnnouncementCheck] = {}
    for code in asx_codes:
        items = grouped.get(code, [])
        risk_items = [item for item in items if _item_is_risky(item)]
        latest_items = (risk_items + [item for item in items if item not in risk_items])[:limit]
        if risk_items:
            checks[code] = ASXAnnouncementCheck(
                code=code,
                checked=True,
                source=ASX_MARKET_ANNOUNCEMENTS_SOURCE,
                checked_at=checked_at,
                has_price_sensitive_item=True,
                latest_items=latest_items,
                status=ANNOUNCEMENT_RISK_FOUND,
                reason="ASX 官方公告发现 price-sensitive 标记或风险标题；执行前人工复核。",
            )
        else:
            checks[code] = ASXAnnouncementCheck(
                code=code,
                checked=True,
                source=ASX_MARKET_ANNOUNCEMENTS_SOURCE,
                checked_at=checked_at,
                has_price_sensitive_item=False,
                latest_items=items[:limit],
                status=ANNOUNCEMENT_CLEAR,
                reason=default_announcement_reason(ANNOUNCEMENT_CLEAR),
            )
    return checks


def parse_asx_market_announcements_html(html_text: str, *, base_url: str = ASX_TODAY_ANNOUNCEMENTS_URL) -> List[Dict[str, Any]]:
    """Parse the ASX listing table metadata without downloading announcement PDFs."""
    parser = _ASXAnnouncementHTMLParser()
    parser.feed(str(html_text or ""))
    rows = parser.rows
    header_index, header_map = _find_header_row(rows)
    if header_index is None:
        raise ASXAnnouncementParseError("expected ASX announcements table headers were not found")

    items: List[Dict[str, Any]] = []
    required_indexes = [header_map["code"], header_map["date"], header_map["price_sensitive"], header_map["headline"]]
    for row in rows[header_index + 1 :]:
        if not row or all(not _normal_text(cell.get("text")) for cell in row):
            continue
        if any(index >= len(row) for index in required_indexes):
            raise ASXAnnouncementParseError("announcement row has fewer cells than expected")

        code_cell = row[header_map["code"]]
        date_cell = row[header_map["date"]]
        price_cell = row[header_map["price_sensitive"]]
        headline_cell = row[header_map["headline"]]

        code = _canonical_asx_row_code(code_cell.get("text"))
        headline = _headline_from_cell(headline_cell.get("text"))
        if not code or not headline:
            raise ASXAnnouncementParseError("announcement row is missing code or headline")

        published_at, date_text = _parse_asx_datetime(date_cell.get("text"))
        text = _normal_text(headline_cell.get("text")) or ""
        item = {
            "code": code,
            "date": date_text,
            "published_at": published_at,
            "headline": headline,
            "url": urljoin(base_url, str(headline_cell.get("href") or "")),
            "price_sensitive": bool(price_cell.get("price_sensitive")) or _truthy_price_sensitive_text(price_cell.get("text")),
        }
        pages = _extract_pages(text)
        size = _extract_size(text)
        if pages is not None:
            item["pages"] = pages
        if size:
            item["size"] = size
        items.append(item)

    return items


def _item_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"title": str(value or "").strip()}


class _ASXAnnouncementHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[Dict[str, Any]]] = []
        self._in_row = False
        self._row: List[Dict[str, Any]] = []
        self._cell: Optional[Dict[str, Any]] = None
        self._cell_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row = []
            return
        if self._in_row and tag in {"th", "td"}:
            self._cell = {
                "tag": tag,
                "href": None,
                "price_sensitive": _attrs_indicate_price_sensitive(attrs_dict),
            }
            self._cell_text = []
            return
        if self._cell is None:
            return
        if tag == "br":
            self._cell_text.append("\n")
        elif tag == "a" and attrs_dict.get("href") and not self._cell.get("href"):
            self._cell["href"] = attrs_dict.get("href")
        elif tag == "img" and _attrs_indicate_price_sensitive(attrs_dict):
            self._cell["price_sensitive"] = True

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None:
            cell = dict(self._cell)
            cell["text"] = _clean_cell_text("".join(self._cell_text))
            self._row.append(cell)
            self._cell = None
            self._cell_text = []
            return
        if tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []


def _find_header_row(rows: List[List[Dict[str, Any]]]) -> tuple[Optional[int], Dict[str, int]]:
    for index, row in enumerate(rows):
        header_map: Dict[str, int] = {}
        for cell_index, cell in enumerate(row):
            header = _header_key(cell.get("text"))
            if header:
                header_map[header] = cell_index
        if {"code", "date", "price_sensitive", "headline"} <= set(header_map):
            return index, header_map
    return None, {}


def _header_key(value: Any) -> str:
    text = re.sub(r"[^a-z ]+", "", str(value or "").strip().lower())
    text = re.sub(r"\s+", " ", text)
    if text.startswith("asx code"):
        return "code"
    if text == "date":
        return "date"
    if text.startswith("price sens"):
        return "price_sensitive"
    if text.startswith("headline"):
        return "headline"
    return ""


def _attrs_indicate_price_sensitive(attrs: Dict[str, str]) -> bool:
    haystack = " ".join(str(value or "").lower() for value in attrs.values())
    return "pricesens" in haystack or "price sensitive" in haystack


def _clean_cell_text(value: str) -> str:
    text = str(value or "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _headline_from_cell(value: Any) -> str:
    for line in str(value or "").splitlines():
        text = _normal_text(line)
        if not text:
            continue
        if re.fullmatch(r"\d+\s+pages?", text, re.IGNORECASE):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:kb|mb)", text, re.IGNORECASE):
            continue
        if text.upper() == "PDF":
            continue
        return text
    return ""


def _canonical_asx_row_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return canonical_stock_code(text if "." in text else f"{text}.AX")


def _parse_asx_datetime(value: Any) -> tuple[Optional[str], Optional[str]]:
    lines = [_normal_text(line) for line in str(value or "").splitlines()]
    parts = [line for line in lines if line]
    if not parts:
        return None, None
    date_text = parts[0]
    time_text = parts[1] if len(parts) > 1 else ""
    if time_text:
        try:
            parsed = datetime.strptime(f"{date_text} {time_text}", "%d/%m/%Y %I:%M %p").replace(tzinfo=ASX_TIMEZONE)
            return parsed.isoformat(), parsed.date().isoformat()
        except ValueError:
            return None, date_text
    try:
        parsed_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        return None, parsed_date.isoformat()
    except ValueError:
        return None, date_text


def _truthy_price_sensitive_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"*", "yes", "y", "price sensitive", "pricesens"}


def _extract_pages(value: str) -> Optional[int]:
    match = re.search(r"\b(\d+)\s+pages?\b", value, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _extract_size(value: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(KB|MB)\b", value, re.IGNORECASE)
    if not match:
        return ""
    return f"{match.group(1)}{match.group(2).upper()}"


def _items_by_code(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items or []:
        code = canonical_stock_code(item.get("code"))
        if not code:
            continue
        grouped.setdefault(code, []).append(dict(item))
    return grouped


def _item_is_risky(item: Dict[str, Any]) -> bool:
    if bool(item.get("price_sensitive")):
        return True
    return bool(RISK_HEADLINE_RE.search(str(item.get("headline") or "")))


def _checked_at_iso() -> str:
    return datetime.now(ASX_TIMEZONE).isoformat(timespec="seconds")


def _bounded_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS
    if timeout <= 0:
        timeout = MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS
    return min(timeout, MAX_ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normal_text(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if raw.lower() in {"", "none", "null", "n/a", "unknown", "未知", "nan"}:
        return None
    return raw
