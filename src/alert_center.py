# -*- coding: utf-8 -*-
"""Read-only Alert Center aggregation for daily ASX manual review."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from src.asx_announcements import ANNOUNCEMENT_RISK_FOUND, ANNOUNCEMENT_UNAVAILABLE
from src.core.validator import normalize_validation_status
from src.market_calendar import get_market_report_date, is_trading_day
from src.stock_code import canonical_stock_code


ALERT_SEVERITY_INFO = "info"
ALERT_SEVERITY_WARNING = "warning"
ALERT_SEVERITY_CRITICAL = "critical"

ASX_CALENDAR = "ASX"
ASX_TIMEZONE = "Australia/Sydney"
DISPLAY_LIMIT = 20


@dataclass(frozen=True)
class AlertItem:
    id: str
    category: str
    severity: str
    code: Optional[str]
    title: str
    message: str
    source: str
    as_of: str
    action_hint: str
    is_trade_instruction: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["is_trade_instruction"] = False
        return payload


def build_alert_center(
    *,
    latest_detail: Optional[Mapping[str, Any]] = None,
    summary_artifact: Optional[Mapping[str, Any]] = None,
    portfolio_import_result: Optional[Mapping[str, Any]] = None,
    as_of: Optional[datetime] = None,
    market_calendar: str = ASX_CALENDAR,
    market_timezone: str = ASX_TIMEZONE,
    item_limit: Optional[int] = DISPLAY_LIMIT,
) -> Dict[str, Any]:
    """Build display-only alerts from existing report, evidence, and portfolio data."""
    now = _market_now(as_of, market_timezone)
    detail = dict(latest_detail or {})
    artifact = dict(summary_artifact or {})
    technical_basis_date = get_market_report_date(
        now,
        calendar=market_calendar,
        market_timezone=market_timezone,
    )
    expected_report_date = _expected_report_date(now, market_calendar)
    data_report_date = _data_report_date(detail, artifact)
    items: List[AlertItem] = []

    items.extend(
        _report_freshness_alerts(
            detail,
            artifact,
            expected_report_date=expected_report_date,
            as_of=now,
        )
    )
    items.extend(_validation_alerts(detail, as_of=now))
    items.extend(_analysis_status_alerts(detail, as_of=now))
    items.extend(_analysis_context_alerts(_analysis_context_pack(detail, artifact), detail=detail, as_of=now))
    items.extend(_blocked_item_alerts(artifact.get("blocked_items") or [], as_of=now))
    items.extend(_report_reliability_alerts(artifact.get("report_reliability") or {}, as_of=now))
    items.extend(_evidence_matrix_alerts(artifact.get("evidence_matrix") or {}, as_of=now))
    items.extend(_portfolio_import_alerts(portfolio_import_result or {}, as_of=now))
    items.extend(_watchlist_and_holding_alerts(artifact, detail=detail, as_of=now))

    deduped_items = _dedupe_alerts(items)
    sorted_items = _sort_alerts(deduped_items, limit=item_limit)
    summary = _summary(deduped_items, item_limit=item_limit)
    summary["visible_count"] = len(sorted_items)
    summary["has_more"] = len(deduped_items) > len(sorted_items)
    data_basis = _data_basis(detail=detail, artifact=artifact)

    return {
        "summary": summary,
        "items": [item.to_dict() for item in sorted_items],
        "market_context": {
            "calendar": market_calendar,
            "timezone": market_timezone,
            "as_of": now.isoformat(),
            "report_date": expected_report_date.isoformat(),
            "technical_basis_date": technical_basis_date.isoformat(),
            "expected_report_date": expected_report_date.isoformat(),
            "data_report_date": data_report_date,
            "data_basis": data_basis,
            "note": _data_basis_note(data_basis),
        },
        "is_trade_instruction": False,
    }


def build_alert_center_from_workbench_inputs(
    *,
    latest_detail: Optional[Mapping[str, Any]],
    summary_artifact: Optional[Mapping[str, Any]] = None,
    portfolio_import_result: Optional[Mapping[str, Any]] = None,
    as_of: Optional[datetime] = None,
    item_limit: Optional[int] = DISPLAY_LIMIT,
) -> Dict[str, Any]:
    """Build alerts from the public latest-history detail used by the workbench."""
    detail = dict(latest_detail or {})
    artifact = _summary_artifact_from_detail(detail)
    if isinstance(summary_artifact, Mapping):
        artifact.update(dict(summary_artifact))
    return build_alert_center(
        latest_detail=detail,
        summary_artifact=artifact,
        portfolio_import_result=portfolio_import_result,
        as_of=as_of,
        item_limit=item_limit,
    )


def _report_freshness_alerts(
    detail: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    expected_report_date: date,
    as_of: datetime,
) -> List[AlertItem]:
    alerts: List[AlertItem] = []
    data_report_date = _data_report_date(detail, artifact)
    expected_text = expected_report_date.isoformat()
    if not data_report_date:
        alerts.append(
            AlertItem(
                id=f"report_freshness:missing:{expected_text}",
                category="report_freshness",
                severity=ALERT_SEVERITY_CRITICAL,
                code=None,
                title="今日日报未找到",
                message=f"未找到 {expected_text} 的日报数据，工作台提醒不能视为今日最新。",
                source="history.latest_report",
                as_of=_as_of_text(as_of),
                action_hint="先确认每日分析是否生成并推送，再使用工作台提醒。",
            )
        )
        return alerts

    if data_report_date != expected_text:
        alerts.append(
            AlertItem(
                id=f"report_freshness:stale:{data_report_date}:expected:{expected_text}",
                category="report_freshness",
                severity=ALERT_SEVERITY_CRITICAL,
                code=None,
                title="日报不是今日最新",
                message=f"当前提醒来自 {data_report_date} 日报；今日应查看 {expected_text} 日报。",
                source="history.latest_report.report_date",
                as_of=_as_of_text(as_of),
                action_hint="先检查今日日报生成/通知状态，避免用旧报告做今日复核。",
            )
        )

    artifact_status = str(artifact.get("artifact_status") or "").strip().lower()
    if artifact_status in {"missing", "invalid", "unavailable"}:
        alerts.append(
            AlertItem(
                id=f"report_freshness:summary_artifact:{artifact_status}:{data_report_date}",
                category="report_freshness",
                severity=ALERT_SEVERITY_WARNING,
                code=None,
                title="日报摘要文件不可用",
                message=f"{data_report_date} 的 daily_decision_summary 文件状态为 {artifact_status}。",
                source="reports.daily_decision_summary",
                as_of=_as_of_text(as_of),
                action_hint="打开日报文件或重新生成摘要后，再确认提醒完整性。",
            )
        )
    return alerts


def _validation_alerts(detail: Mapping[str, Any], *, as_of: datetime) -> List[AlertItem]:
    status = normalize_validation_status(detail.get("validation_status"))
    if status != "BLOCK":
        return []
    issues = _list_text(detail.get("validation_issues")) or ["验证阻断，需要人工复核。"]
    code = _code_from_detail(detail)
    return [
        AlertItem(
            id=f"validation:{code or 'latest'}:{index}",
            category="validation",
            severity=ALERT_SEVERITY_CRITICAL,
            code=code,
            title="验证阻断",
            message=issue,
            source="history.latest_report",
            as_of=_as_of_text(as_of),
            action_hint="先修复或确认阻断原因，再人工复核今日报告。",
        )
        for index, issue in enumerate(issues)
    ]


def _analysis_status_alerts(detail: Mapping[str, Any], *, as_of: datetime) -> List[AlertItem]:
    alerts: List[AlertItem] = []
    code = _code_from_detail(detail)
    status = str(detail.get("analysis_status") or "").strip().upper()
    if status in {"FAILED", "ERROR"}:
        alerts.append(
            AlertItem(
                id=f"analysis:{code or 'latest'}:failed",
                category="analysis",
                severity=ALERT_SEVERITY_CRITICAL,
                code=code,
                title="日报分析失败",
                message=_first_text(detail.get("error_message"), detail.get("analysis_summary"), "日报分析失败，需要重跑或人工检查。"),
                source="history.latest_report",
                as_of=_as_of_text(as_of),
                action_hint="先重跑失败标的，或在日报外人工补齐判断。",
            )
        )
    elif status == "DEGRADED":
        alerts.append(
            AlertItem(
                id=f"analysis:{code or 'latest'}:degraded",
                category="analysis",
                severity=ALERT_SEVERITY_WARNING,
                code=code,
                title="日报分析不完整",
                message=_first_text(detail.get("analysis_summary"), "日报处于 DEGRADED 状态。"),
                source="history.latest_report",
                as_of=_as_of_text(as_of),
                action_hint="打开最新报告，先确认缺失的数据或分析步骤。",
            )
        )

    if str(detail.get("data_quality_flag") or "").strip().upper() == "MISSING":
        alerts.append(
            AlertItem(
                id=f"data_quality:{code or 'latest'}:missing",
                category="data_quality",
                severity=ALERT_SEVERITY_WARNING,
                code=code,
                title="数据质量缺口",
                message="最新日报标记了数据缺口。",
                source="history.latest_report",
                as_of=_as_of_text(as_of),
                action_hint="先确认行情、新闻、估值或回测数据是否需要补齐。",
            )
        )
    return alerts


def _analysis_context_alerts(
    context_pack: Mapping[str, Any],
    *,
    detail: Mapping[str, Any],
    as_of: datetime,
) -> List[AlertItem]:
    risk_context = context_pack.get("risk_context") if isinstance(context_pack, Mapping) else {}
    if not isinstance(risk_context, Mapping):
        return []
    alerts: List[AlertItem] = []
    code = _code_from_detail(detail) or _context_code(context_pack)
    status = normalize_validation_status(risk_context.get("validation_status"))
    issues = _list_text(risk_context.get("validation_issues"))
    if status == "BLOCK" and issues:
        for index, issue in enumerate(issues):
            alerts.append(
                AlertItem(
                    id=f"risk_context:{code or 'latest'}:{index}",
                    category="risk_context",
                    severity=ALERT_SEVERITY_CRITICAL,
                    code=code or None,
                    title="上下文风险提示",
                    message=issue,
                    source="analysis_context_pack.risk_context",
                    as_of=_as_of_text(as_of),
                    action_hint="结合最新日报和上下文包人工复核。",
                )
            )
    actionability = str(risk_context.get("actionability") or "").strip().lower()
    if actionability == "observation_only" and not issues and status == "BLOCK":
        alerts.append(
            AlertItem(
                id=f"risk_context:{code or 'latest'}:observation_only",
                category="risk_context",
                severity=ALERT_SEVERITY_CRITICAL,
                code=code or None,
                title="仅观察上下文",
                message="AnalysisContextPack 标记为 observation_only。",
                source="analysis_context_pack.risk_context",
                as_of=_as_of_text(as_of),
                action_hint="把这条报告作为观察材料，不把它当成执行指令。",
            )
        )
    return alerts


def _report_reliability_alerts(reliability: Mapping[str, Any], *, as_of: datetime) -> List[AlertItem]:
    if not isinstance(reliability, Mapping):
        return []
    alerts: List[AlertItem] = []
    level = str(reliability.get("level") or "").strip()
    score = reliability.get("score")
    if level == "low_observe_only":
        alerts.append(
            AlertItem(
                id="report_reliability:low_observe_only",
                category="report_reliability",
                severity=ALERT_SEVERITY_WARNING,
                code=None,
                title="报告可信度偏低",
                message=f"报告可信度 {score if score is not None else 'N/A'}，仅适合作为观察和人工复核。",
                source="daily_decision_summary.report_reliability",
                as_of=_as_of_text(as_of),
                action_hint="先看主要扣分项，再决定是否需要重跑或补数据。",
            )
        )

    for flag in reliability.get("flags") or []:
        if not isinstance(flag, Mapping):
            continue
        code = str(flag.get("code") or "flag").strip() or "flag"
        message = str(flag.get("message") or "").strip()
        if not message:
            continue
        alerts.append(
            AlertItem(
                id=f"report_reliability:{code}",
                category="report_reliability",
                severity=_severity_from_source(flag.get("severity")),
                code=None,
                title=_title_for_reliability_flag(code),
                message=message,
                source="daily_decision_summary.report_reliability",
                as_of=_as_of_text(as_of),
                action_hint="按扣分项逐项人工确认。",
            )
        )
    return alerts


def _blocked_item_alerts(blocked_items: Any, *, as_of: datetime) -> List[AlertItem]:
    alerts: List[AlertItem] = []
    if not isinstance(blocked_items, Iterable) or isinstance(blocked_items, (str, bytes, Mapping)):
        return alerts
    for index, item in enumerate(blocked_items):
        if not isinstance(item, Mapping):
            continue
        code = canonical_stock_code(item.get("code"))
        reason = _first_text(item.get("reason"), item.get("validation_reason"), "验证阻断，需要人工复核。")
        alerts.append(
            AlertItem(
                id=f"blocked_item:{code or 'latest'}:{index}",
                category="validation",
                severity=ALERT_SEVERITY_CRITICAL,
                code=code or None,
                title="验证阻断",
                message=reason,
                source="daily_decision_summary.blocked_items",
                as_of=_as_of_text(as_of),
                action_hint="先确认阻断原因，不能把这条当作可执行动作。",
            )
        )
    return alerts


def _evidence_matrix_alerts(matrix: Mapping[str, Any], *, as_of: datetime) -> List[AlertItem]:
    if not isinstance(matrix, Mapping):
        return []
    alerts: List[AlertItem] = []
    for raw_code, entries in matrix.items():
        code = canonical_stock_code(raw_code)
        if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes, Mapping)):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            category = str(entry.get("category") or "evidence").strip() or "evidence"
            status = str(entry.get("status") or "").strip().lower()
            if category == "announcement" and status in {ANNOUNCEMENT_RISK_FOUND, ANNOUNCEMENT_UNAVAILABLE}:
                alerts.append(
                    AlertItem(
                        id=f"announcement:{code}:{status}",
                        category="announcement",
                        severity=ALERT_SEVERITY_CRITICAL if status == ANNOUNCEMENT_RISK_FOUND else ALERT_SEVERITY_WARNING,
                        code=code or None,
                        title="ASX 公告需要复核" if status == ANNOUNCEMENT_RISK_FOUND else "ASX 公告源不可用",
                        message=str(entry.get("details") or "ASX announcement 需要人工复核。"),
                        source=str(entry.get("source") or "evidence_matrix"),
                        as_of=_as_of_text(as_of, entry.get("as_of_date")),
                        action_hint="打开 ASX announcements 官方页面人工确认。",
                    )
                )
                continue
            if category in {"market_data", "technical", "valuation", "news", "backtest"} and status in {
                "missing",
                "stale",
                "not_checked",
                "unavailable",
                "partial",
            }:
                alerts.append(
                    AlertItem(
                        id=f"evidence:{code}:{category}:{status}",
                        category="evidence",
                        severity=ALERT_SEVERITY_WARNING,
                        code=code or None,
                        title=_title_for_evidence_gap(category, status),
                        message=str(entry.get("details") or f"{category} evidence is {status}."),
                        source=str(entry.get("source") or "daily_decision_summary.evidence_matrix"),
                        as_of=_as_of_text(as_of, entry.get("as_of_date")),
                        action_hint="先补齐或人工确认这项证据，再使用报告结论。",
                    )
                )
    return alerts


def _portfolio_import_alerts(result: Mapping[str, Any], *, as_of: datetime) -> List[AlertItem]:
    if not isinstance(result, Mapping):
        return []
    alerts: List[AlertItem] = []
    for index, message in enumerate(_list_text(result.get("errors"))):
        alerts.append(
            AlertItem(
                id=f"portfolio_import:error:{index}",
                category="portfolio_import",
                severity=ALERT_SEVERITY_CRITICAL,
                code=None,
                title="组合导入错误",
                message=message,
                source="portfolio_import",
                as_of=_as_of_text(as_of),
                action_hint="先修正 CSV 或导入结果，再应用到账本。",
            )
        )
    for index, message in enumerate(_list_text(result.get("warnings"))):
        alerts.append(
            AlertItem(
                id=f"portfolio_import:warning:{index}",
                category="portfolio_import",
                severity=ALERT_SEVERITY_WARNING,
                code=None,
                title="组合导入提醒",
                message=message,
                source="portfolio_import",
                as_of=_as_of_text(as_of),
                action_hint="应用前先确认导入预览。",
            )
        )

    integrity = result.get("integrity") if isinstance(result.get("integrity"), Mapping) else {}
    for index, message in enumerate(_list_text(integrity.get("errors"))):
        alerts.append(
            AlertItem(
                id=f"portfolio_integrity:error:{index}",
                category="portfolio_integrity",
                severity=ALERT_SEVERITY_CRITICAL,
                code=None,
                title="账本完整性错误",
                message=message,
                source="portfolio_import.integrity",
                as_of=_as_of_text(as_of),
                action_hint="先修复账本完整性，再继续人工复核。",
            )
        )
    for index, message in enumerate(_list_text(integrity.get("warnings"))):
        alerts.append(
            AlertItem(
                id=f"portfolio_integrity:warning:{index}",
                category="portfolio_integrity",
                severity=ALERT_SEVERITY_WARNING,
                code=None,
                title="账本完整性提醒",
                message=message,
                source="portfolio_import.integrity",
                as_of=_as_of_text(as_of),
                action_hint="确认账本快照和持仓权重是否一致。",
            )
        )
    return alerts


def _watchlist_and_holding_alerts(
    artifact: Mapping[str, Any],
    *,
    detail: Mapping[str, Any],
    as_of: datetime,
) -> List[AlertItem]:
    if not isinstance(artifact, Mapping):
        return []
    alerts: List[AlertItem] = []
    for index, item in enumerate(artifact.get("watch_items") or []):
        if not isinstance(item, Mapping):
            continue
        code = canonical_stock_code(item.get("code"))
        if not item.get("is_current_holding") and not _list_text(item.get("review_reasons")):
            continue
        alerts.append(
            AlertItem(
                id=f"watchlist:{code or index}:review",
                category="watchlist",
                severity=ALERT_SEVERITY_INFO,
                code=code or None,
                title="观察清单待复核",
                message=str(item.get("reason") or item.get("trigger") or f"{code or '观察项'} 需要人工复核。"),
                source="daily_decision_summary.watch_items",
                as_of=_as_of_text(as_of),
                action_hint="按观察清单触发条件人工复核。",
            )
        )

    for index, holding in enumerate(artifact.get("uncovered_holdings") or []):
        if not isinstance(holding, Mapping):
            continue
        holding_code = canonical_stock_code(holding.get("code"))
        alerts.append(
            AlertItem(
                id=f"holding:{holding_code or index}:uncovered",
                category="holding",
                severity=ALERT_SEVERITY_WARNING,
                code=holding_code or None,
                title="持仓未纳入今日分析",
                message=f"{holding_code or '某持仓'} 当前持仓未覆盖今日分析。",
                source="daily_decision_summary.uncovered_holdings",
                as_of=_as_of_text(as_of),
                action_hint="打开组合和历史报告，人工确认是否需要补跑。",
            )
        )
    return alerts


def _summary(items: List[AlertItem], *, item_limit: Optional[int] = DISPLAY_LIMIT) -> Dict[str, Any]:
    critical = sum(1 for item in items if item.severity == ALERT_SEVERITY_CRITICAL)
    warning = sum(1 for item in items if item.severity == ALERT_SEVERITY_WARNING)
    info = sum(1 for item in items if item.severity == ALERT_SEVERITY_INFO)
    severity = ALERT_SEVERITY_CRITICAL if critical else ALERT_SEVERITY_WARNING if warning else ALERT_SEVERITY_INFO
    if critical:
        message = f"有 {critical} 条必须优先处理的提醒。"
    elif warning:
        message = f"有 {warning} 条需要人工确认的提醒。"
    else:
        message = "今天没有必须优先处理的风险提醒。"
    return {
        "total": len(items),
        "critical_count": critical,
        "warning_count": warning,
        "info_count": info,
        "severity": severity,
        "message": message,
        "display_limit": item_limit,
    }


def _summary_artifact_from_detail(detail: Mapping[str, Any]) -> Dict[str, Any]:
    keys = {
        "evidence_matrix",
        "evidence_summary",
        "report_reliability",
        "watch_items",
        "blocked_items",
        "uncovered_holdings",
        "price_policy",
        "generated_at",
        "report_date",
    }
    artifact = {key: detail.get(key) for key in keys if key in detail}
    if "report_date" not in artifact and detail.get("report_date"):
        artifact["report_date"] = detail.get("report_date")
    return artifact


def _expected_report_date(now: datetime, calendar: str) -> date:
    candidate = now.date()
    if is_trading_day(candidate, calendar):
        return candidate
    candidate -= timedelta(days=1)
    while not is_trading_day(candidate, calendar):
        candidate -= timedelta(days=1)
    return candidate


def _data_report_date(detail: Mapping[str, Any], artifact: Mapping[str, Any]) -> Optional[str]:
    for source in (artifact, detail):
        report_date = _date_text(source.get("report_date")) if isinstance(source, Mapping) else None
        if report_date:
            return report_date
    return None


def _date_text(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _analysis_context_pack(detail: Mapping[str, Any], artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    for source in (detail, artifact):
        pack = source.get("analysis_context_pack") if isinstance(source, Mapping) else None
        if isinstance(pack, Mapping):
            return pack
    return {}


def _context_code(context_pack: Mapping[str, Any]) -> Optional[str]:
    identity = context_pack.get("stock_identity") if isinstance(context_pack, Mapping) else {}
    if not isinstance(identity, Mapping):
        return None
    return canonical_stock_code(identity.get("code")) or None


def _data_basis(*, detail: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    basis_values = [
        normalized
        for normalized in (
            _basis_value(detail.get("price_policy")),
            _basis_value(detail.get("execution_price_source")),
            _basis_value(artifact.get("price_policy")),
        )
        if normalized
    ]
    if not basis_values:
        return "unavailable"
    if all(value == "close_only" for value in basis_values):
        return "close_only"
    unavailable_values = {"unavailable", "unknown", "not_available", "n/a", "none"}
    if any(value not in unavailable_values for value in basis_values):
        return "delayed"
    return "unavailable"


def _basis_value(value: Any) -> str:
    return str(value or "").strip().lower()


def _data_basis_note(data_basis: str) -> str:
    if data_basis == "close_only":
        return "使用最后已收盘交易日数据。"
    if data_basis == "delayed":
        return "数据不是纯 close_only 口径，按延迟/混合口径提示人工确认。"
    return "数据口径不可用，不能推断为已确认。"


def _market_now(value: Optional[datetime], timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if value is None:
        return datetime.now(tz)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(tz)


def _as_of_text(default: datetime, override: Any = None) -> str:
    text = str(override or "").strip()
    return text or default.isoformat()


def _severity_from_source(value: Any) -> str:
    severity = str(value or "").strip().lower()
    if severity in {"block", "critical", "error"}:
        return ALERT_SEVERITY_CRITICAL
    if severity in {"warning", "warn"}:
        return ALERT_SEVERITY_WARNING
    return ALERT_SEVERITY_INFO


def _sort_alerts(items: List[AlertItem], *, limit: Optional[int] = DISPLAY_LIMIT) -> List[AlertItem]:
    severity_rank = {
        ALERT_SEVERITY_CRITICAL: 0,
        ALERT_SEVERITY_WARNING: 1,
        ALERT_SEVERITY_INFO: 2,
    }
    sorted_items = sorted(items, key=lambda item: (severity_rank.get(item.severity, 9), item.category, item.id))
    return sorted_items if limit is None else sorted_items[:limit]


def _dedupe_alerts(items: List[AlertItem]) -> List[AlertItem]:
    seen = set()
    result = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _list_text(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _code_from_detail(detail: Mapping[str, Any]) -> Optional[str]:
    code = canonical_stock_code(detail.get("stock_code") or detail.get("code"))
    return code or None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _title_for_reliability_flag(code: str) -> str:
    labels = {
        "evidence_missing": "证据缺口",
        "backtest_not_checked": "回测证据未检查",
        "market_data_missing": "行情数据缺口",
        "price_basis_mismatch": "价格口径需确认",
        "validation_block": "验证阻断",
        "asx_announcement_unavailable": "ASX 公告源不可用",
        "asx_announcement_risk_found": "ASX 公告风险",
    }
    return labels.get(code, "报告可信度提醒")


def _title_for_evidence_gap(category: str, status: str) -> str:
    labels = {
        "market_data": "行情数据缺口",
        "technical": "技术证据缺口",
        "valuation": "估值证据缺口",
        "news": "新闻证据缺口",
        "backtest": "回测证据未检查",
    }
    suffix = "不可用" if status == "unavailable" else "需复核"
    return f"{labels.get(category, '证据缺口')}（{suffix}）"
