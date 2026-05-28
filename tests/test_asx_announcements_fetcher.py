# -*- coding: utf-8 -*-
"""Mocked ASX official market announcements fetcher tests."""

import requests

from src.asx_announcements import (
    ASX_TODAY_ANNOUNCEMENTS_URL,
    ASX_PREVIOUS_TRADING_DAY_ANNOUNCEMENTS_URL,
    build_asx_announcement_checks,
    fetch_asx_market_announcements,
    is_asx_ticker,
)


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.url = "https://www.asx.com.au/asx/v2/statistics/todayAnns.do"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls = []

    def get(self, url, *, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
        if self.exc:
            raise self.exc
        if self.responses:
            return self.responses.pop(0)
        return _Response(_announcement_html([]))


def _announcement_html(rows):
    row_html = "\n".join(rows)
    return f"""
    <html>
      <body>
        <announcement_data>
          <table>
            <caption>Today's Announcements</caption>
            <tr>
              <th>ASX Code</th>
              <th>Date</th>
              <th>Price sens.</th>
              <th><span>Headline</span></th>
            </tr>
            {row_html}
          </table>
        </announcement_data>
      </body>
    </html>
    """


def _row(code, headline, *, price_sensitive=False, pages="2", size="1.2MB"):
    price_cell = (
        '<td class="pricesens"><img alt="asterix" title="price sensitive" '
        'src="/asx/v2/markets/image/icon-price-sensitive.svg"></td>'
        if price_sensitive
        else "<td></td>"
    )
    return f"""
    <tr>
      <td>{code}</td>
      <td>28/05/2026<br><span class="dates-time">9:13 am</span></td>
      {price_cell}
      <td>
        <a target="_blank" href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=123">
          {headline}<br>
          <img src="/asx/v2/markets/image/pdf_icon.png">
          <span class="page">{pages} pages</span>
          <span class="filesize">{size}</span>
        </a>
      </td>
    </tr>
    """


def test_fetcher_uses_batched_asx_pages_user_agent_and_timeout():
    session = _Session(
        [
            _Response(_announcement_html([_row("BHP", "Quarterly activities report")])),
            _Response(_announcement_html([_row("CBA", "Appendix 3Y")])),
        ]
    )

    result = fetch_asx_market_announcements(
        session=session,
        lookback_days=1,
        timeout_seconds=7,
    )

    assert result.status == "available"
    assert [call["url"] for call in session.calls] == [
        ASX_TODAY_ANNOUNCEMENTS_URL,
        ASX_PREVIOUS_TRADING_DAY_ANNOUNCEMENTS_URL,
    ]
    assert all("ASX-daily-stock-analysis" in call["headers"]["User-Agent"] for call in session.calls)
    assert all(call["timeout"] == 7 for call in session.calls)
    assert [item["code"] for item in result.items] == ["BHP.AX", "CBA.AX"]
    assert result.items[0]["headline"] == "Quarterly activities report"
    assert result.items[0]["published_at"] == "2026-05-28T09:13:00+10:00"
    assert result.items[0]["pages"] == 2
    assert result.items[0]["size"] == "1.2MB"


def test_clear_check_when_recent_announcements_have_no_risk_terms_or_price_sensitive_marker():
    session = _Session([_Response(_announcement_html([_row("BHP", "Quarterly activities report")]))])

    checks = build_asx_announcement_checks(
        ["BHP.AX"],
        session=session,
        lookback_days=0,
        now_iso="2026-05-28T08:00:00+10:00",
    )

    check = checks["BHP.AX"]
    assert check.status == "clear"
    assert check.checked is True
    assert check.source == "asx_market_announcements"
    assert check.checked_at == "2026-05-28T08:00:00+10:00"
    assert check.has_price_sensitive_item is False
    assert check.latest_items[0]["headline"] == "Quarterly activities report"


def test_price_sensitive_marker_sets_risk_found():
    session = _Session([_Response(_announcement_html([_row("BHP", "Investor update", price_sensitive=True)]))])

    checks = build_asx_announcement_checks(["BHP.AX"], session=session, lookback_days=0)

    check = checks["BHP.AX"]
    assert check.status == "risk_found"
    assert check.has_price_sensitive_item is True
    assert check.latest_items[0]["price_sensitive"] is True


def test_trading_halt_and_suspension_headlines_set_risk_found_without_marker():
    session = _Session(
        [
            _Response(
                _announcement_html(
                    [
                        _row("BHP", "Trading halt request"),
                        _row("CBA", "Suspension from quotation"),
                    ]
                )
            )
        ]
    )

    checks = build_asx_announcement_checks(["BHP.AX", "CBA.AX"], session=session, lookback_days=0)

    assert checks["BHP.AX"].status == "risk_found"
    assert checks["BHP.AX"].has_price_sensitive_item is True
    assert checks["CBA.AX"].status == "risk_found"
    assert checks["CBA.AX"].has_price_sensitive_item is True


def test_asx_code_canonicalization_and_non_asx_skip():
    session = _Session([_Response(_announcement_html([_row("BHP", "Quarterly activities report")]))])

    checks = build_asx_announcement_checks(["bhp.asx", "AAPL", "MSFT"], session=session, lookback_days=0)

    assert list(checks) == ["BHP.AX"]
    assert checks["BHP.AX"].status == "clear"
    assert is_asx_ticker("BHP.AX") is True
    assert is_asx_ticker("BHP.ASX") is True
    assert is_asx_ticker("AAPL") is False


def test_page_structure_change_returns_unavailable_not_clear():
    session = _Session([_Response("<html><body><table><tr><td>changed</td></tr></table></body></html>")])

    checks = build_asx_announcement_checks(["BHP.AX"], session=session, lookback_days=0)

    assert checks["BHP.AX"].status == "unavailable"
    assert checks["BHP.AX"].checked is False
    assert checks["BHP.AX"].has_price_sensitive_item is None
    assert "不可用" in checks["BHP.AX"].reason


def test_timeout_or_network_error_does_not_raise_to_daily_flow():
    session = _Session(exc=requests.Timeout("timed out"))

    checks = build_asx_announcement_checks(["BHP.AX"], session=session, lookback_days=0)

    assert checks["BHP.AX"].status == "unavailable"
    assert checks["BHP.AX"].checked is False


def test_disabled_fetcher_keeps_current_behavior_without_announcement_evidence():
    checks = build_asx_announcement_checks(["BHP.AX"], enabled=False)

    assert checks == {}
