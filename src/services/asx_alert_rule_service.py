# -*- coding: utf-8 -*-
"""Read-only ASX alert-rule dry-run evaluation service."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from src.alert_center import build_alert_center_from_workbench_inputs
from src.asx_announcements import ANNOUNCEMENT_RISK_FOUND, ANNOUNCEMENT_UNAVAILABLE
from src.core.validator import normalize_validation_status
from src.services.portfolio_event_service import PortfolioEventFilters, PortfolioEventService
from src.stock_code import canonical_stock_code
from src.storage import DatabaseManager


MAX_TARGETS = 100

STATUS_TRIGGERED = "triggered"
STATUS_NOT_TRIGGERED = "not_triggered"
STATUS_DEGRADED = "degraded"
STATUS_SKIPPED = "skipped"
STATUS_EVALUATION_ERROR = "evaluation_error"


class AlertRuleDryRunService:
    """Evaluate one temporary alert rule without persisting actions or state."""

    def __init__(self, db_manager: DatabaseManager, config_service: Any = None):
        self.db = db_manager
        self.config_service = config_service

    def batch_dry_run(
        self,
        *,
        rules: Iterable[Mapping[str, Any]],
        context: Mapping[str, Any],
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate temporary alert rules as one read-only diagnostic batch."""
        results: List[Dict[str, Any]] = []
        for index, rule in enumerate(rules, start=1):
            result = self.dry_run(rule, context=context)
            result.update(
                {
                    "rule_index": index,
                    "target_scope": _clean_text(rule.get("target_scope")),
                    "alert_type": _clean_text(rule.get("alert_type")),
                    "severity": _clean_text(rule.get("severity")) or "warning",
                }
            )
            results.append(result)

        summary = {
            "evaluated_target_count": sum(int(item.get("evaluated_count") or 0) for item in results),
            "triggered_count": sum(int(item.get("triggered_count") or 0) for item in results),
            "degraded_count": sum(int(item.get("degraded_count") or 0) for item in results),
            "skipped_count": sum(int(item.get("skipped_count") or 0) for item in results),
            "evaluation_error_count": sum(
                1
                for item in results
                for target_result in item.get("target_results") or []
                if isinstance(target_result, Mapping)
                and target_result.get("status") == STATUS_EVALUATION_ERROR
            ),
        }
        if summary["evaluation_error_count"]:
            status = STATUS_EVALUATION_ERROR
        elif summary["triggered_count"]:
            status = STATUS_TRIGGERED
        elif summary["degraded_count"]:
            status = STATUS_DEGRADED
        elif summary["skipped_count"]:
            status = STATUS_SKIPPED
        else:
            status = STATUS_NOT_TRIGGERED

        return {
            "mode": "alert_rule_batch_dry_run_diagnostics",
            "name": _clean_text(name) or None,
            "status": status,
            "is_dry_run": True,
            "will_write": False,
            "is_trade_instruction": False,
            "manual_review_required": True,
            "side_effects": [],
            "forbidden_side_effects": [
                "db_write",
                "background_worker",
                "notification",
                "broker_execution",
                "paper_simulation",
                "persisted_execution_state",
            ],
            "rule_count": len(results),
            "evaluated_rule_count": len(results),
            "summary": summary,
            "results": results,
        }

    def dry_run(self, rule: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        alert_center = build_alert_center_from_workbench_inputs(
            latest_detail=context.get("latest_detail"),
            summary_artifact=context.get("summary_artifact"),
            portfolio_import_result=context.get("portfolio_alert_context"),
            item_limit=None,
        )
        targets, capped_skipped = self._expand_targets(rule)
        scope = _clean_text(rule.get("target_scope"))

        results: List[Dict[str, Any]] = []
        if not targets and scope == "watchlist":
            results.append(
                _target_result(
                    target="watchlist",
                    status=STATUS_SKIPPED,
                    observed_value="empty",
                    threshold="configured STOCK_LIST",
                    message="未配置自选股 STOCK_LIST，跳过 watchlist dry-run。",
                    source="system_config.STOCK_LIST",
                    as_of=_market_as_of(alert_center),
                    action_hint="先配置自选股列表或改用单标的 dry-run 后人工复核。",
                )
            )
        elif not targets:
            targets = ["portfolio_account" if rule.get("target_scope") == "portfolio_account" else str(rule.get("target") or "all")]

        for target in targets:
            try:
                results.append(self._evaluate_target(rule, target, context, alert_center))
            except Exception as exc:
                results.append(
                    _target_result(
                        target=target,
                        status=STATUS_EVALUATION_ERROR,
                        observed_value="evaluation_error",
                        threshold=None,
                        message=f"规则 dry-run 评估失败：{exc}",
                        source="alert_rules.dry_run",
                        as_of=_market_as_of(alert_center),
                        action_hint="保留为人工复核，不生成任何执行动作。",
                    )
                )

        triggered_count = sum(1 for item in results if item["status"] == STATUS_TRIGGERED)
        degraded_count = sum(1 for item in results if item["status"] == STATUS_DEGRADED)
        skipped_count = capped_skipped + sum(1 for item in results if item["status"] == STATUS_SKIPPED)
        evaluation_error_count = sum(1 for item in results if item["status"] == STATUS_EVALUATION_ERROR)

        if evaluation_error_count:
            status = STATUS_EVALUATION_ERROR
        elif triggered_count:
            status = STATUS_TRIGGERED
        elif degraded_count:
            status = STATUS_DEGRADED
        else:
            status = STATUS_NOT_TRIGGERED

        return {
            "name": _clean_text(rule.get("name")) or None,
            "status": status,
            "triggered": triggered_count > 0,
            "evaluated_count": len(results),
            "triggered_count": triggered_count,
            "degraded_count": degraded_count,
            "skipped_count": skipped_count,
            "target_results": results,
            "market_context": alert_center.get("market_context") or {},
            "is_trade_instruction": False,
        }

    def _expand_targets(self, rule: Mapping[str, Any]) -> Tuple[List[str], int]:
        scope = _clean_text(rule.get("target_scope"))
        target = _clean_text(rule.get("target")) or "all"
        max_targets = _max_targets(rule.get("parameters"))

        if scope == "single_symbol":
            code = canonical_stock_code(target)
            return ([code] if code else [target]), 0
        if scope == "watchlist":
            targets = self._watchlist_targets()
            return _cap_targets(targets, max_targets)
        if scope == "portfolio_holdings":
            targets = self._portfolio_holding_targets()
            if target.lower() != "all":
                wanted = canonical_stock_code(target)
                targets = [code for code in targets if code == wanted]
            return _cap_targets(targets, max_targets)
        if scope == "portfolio_account":
            return ["portfolio_account"], 0
        return [target], 0

    def _watchlist_targets(self) -> List[str]:
        payload: Mapping[str, Any] = {}
        if self.config_service is not None:
            try:
                payload = self.config_service.get_config(include_schema=False) or {}
            except Exception:
                payload = {}
        items = list(payload.get("items") or []) if isinstance(payload, Mapping) else []
        stock_list = ""
        for item in items:
            if str(item.get("key") or "").upper() == "STOCK_LIST":
                stock_list = str(item.get("value") or "")
                break
        return _symbol_list(stock_list)

    def _portfolio_holding_targets(self) -> List[str]:
        try:
            overview = self.db.get_portfolio_overview() or {}
        except Exception:
            return []
        holdings = overview.get("holdings") if isinstance(overview, Mapping) else []
        result = []
        for holding in holdings or []:
            if not isinstance(holding, Mapping):
                continue
            code = canonical_stock_code(holding.get("code"))
            if code:
                result.append(code)
        return list(dict.fromkeys(result))

    def _evaluate_target(
        self,
        rule: Mapping[str, Any],
        target: str,
        context: Mapping[str, Any],
        alert_center: Mapping[str, Any],
    ) -> Dict[str, Any]:
        alert_type = _clean_text(rule.get("alert_type"))
        if alert_type == "validation_block":
            return self._evaluate_validation_block(target, context, alert_center)
        if alert_type == "data_gap":
            return self._evaluate_data_gap(target, context, alert_center)
        if alert_type == "announcement_risk":
            return self._evaluate_announcement_risk(target, context, alert_center)
        if alert_type == "stale_price":
            return self._evaluate_stale_price(target, alert_center)
        if alert_type == "portfolio_concentration":
            return self._evaluate_portfolio_concentration(target, rule)
        if alert_type == "portfolio_drawdown":
            if _clean_text(rule.get("target_scope")) != "portfolio_account":
                return _target_result(
                    target=target,
                    status=STATUS_EVALUATION_ERROR,
                    observed_value="invalid_scope",
                    threshold="portfolio_account",
                    message="portfolio_drawdown 是账户级规则，target_scope 必须为 portfolio_account。",
                    source="alert_rules.dry_run",
                    as_of=_market_as_of(alert_center),
                    action_hint="把规则改为 portfolio_account 后再 dry-run。",
                )
            return self._evaluate_portfolio_drawdown(target, rule)
        if alert_type == "portfolio_price_stale":
            return self._evaluate_portfolio_price_stale(target)
        return _target_result(
            target=target,
            status=STATUS_EVALUATION_ERROR,
            observed_value=alert_type or "missing",
            threshold=None,
            message="未知 alert_type，无法执行 dry-run。",
            source="alert_rules.dry_run",
            as_of=_market_as_of(alert_center),
            action_hint="修正规则类型后再人工复核。",
        )

    def _evaluate_validation_block(
        self,
        target: str,
        context: Mapping[str, Any],
        alert_center: Mapping[str, Any],
    ) -> Dict[str, Any]:
        detail = context.get("latest_detail") if isinstance(context.get("latest_detail"), Mapping) else {}
        status = normalize_validation_status(detail.get("validation_status"))
        code = canonical_stock_code(detail.get("stock_code") or detail.get("code"))
        issues = _list_text(detail.get("validation_issues")) or ["验证阻断，需要人工复核。"]
        if code == target and status == "BLOCK":
            return _target_result(
                target=target,
                status=STATUS_TRIGGERED,
                observed_value="BLOCK",
                threshold="PASS",
                message=issues[0],
                source="history.latest_report.validation_status",
                as_of=_market_as_of(alert_center),
                action_hint="先确认验证阻断原因，再做人工复核。",
            )
        for item in _alert_items(alert_center, target):
            if item.get("category") in {"validation", "risk_context"}:
                return _target_result(
                    target=target,
                    status=STATUS_TRIGGERED,
                    observed_value=item.get("severity") or "alert",
                    threshold="no critical validation alert",
                    message=str(item.get("message") or "验证阻断，需要人工复核。"),
                    source=str(item.get("source") or "alert_center"),
                    as_of=str(item.get("as_of") or _market_as_of(alert_center)),
                    action_hint=str(item.get("action_hint") or "先人工复核。"),
                )
        return _target_result(
            target=target,
            status=STATUS_NOT_TRIGGERED,
            observed_value=status or "PASS",
            threshold="BLOCK",
            message="未发现该标的的验证阻断提醒。",
            source="alert_center",
            as_of=_market_as_of(alert_center),
            action_hint="保留为人工复核输入，不生成执行动作。",
        )

    def _evaluate_data_gap(
        self,
        target: str,
        context: Mapping[str, Any],
        alert_center: Mapping[str, Any],
    ) -> Dict[str, Any]:
        detail = context.get("latest_detail") if isinstance(context.get("latest_detail"), Mapping) else {}
        code = canonical_stock_code(detail.get("stock_code") or detail.get("code"))
        quality = _clean_text(detail.get("data_quality_flag")).upper()
        if code == target and quality == "MISSING":
            return _target_result(
                target=target,
                status=STATUS_TRIGGERED,
                observed_value="MISSING",
                threshold="OK",
                message="最新日报标记了数据缺口。",
                source="history.latest_report.data_quality_flag",
                as_of=_market_as_of(alert_center),
                action_hint="先补齐或确认缺失数据，再人工复核。",
            )
        for item in _alert_items(alert_center, target):
            if item.get("category") in {"data_quality", "evidence", "report_freshness"}:
                return _target_result(
                    target=target,
                    status=STATUS_TRIGGERED,
                    observed_value=item.get("category") or "data_gap",
                    threshold="no data gap alert",
                    message=str(item.get("message") or "证据或行情数据需要人工确认。"),
                    source=str(item.get("source") or "alert_center"),
                    as_of=str(item.get("as_of") or _market_as_of(alert_center)),
                    action_hint=str(item.get("action_hint") or "先人工复核。"),
                )
        return _target_result(
            target=target,
            status=STATUS_NOT_TRIGGERED,
            observed_value=quality or "OK",
            threshold="MISSING",
            message="未发现该标的的数据缺口提醒。",
            source="alert_center",
            as_of=_market_as_of(alert_center),
            action_hint="保留为人工复核输入，不生成执行动作。",
        )

    def _evaluate_announcement_risk(
        self,
        target: str,
        context: Mapping[str, Any],
        alert_center: Mapping[str, Any],
    ) -> Dict[str, Any]:
        entry = _announcement_entry(context.get("summary_artifact"), target)
        if entry:
            status = _clean_text(entry.get("status")).lower()
            if status == ANNOUNCEMENT_RISK_FOUND:
                return _target_result(
                    target=target,
                    status=STATUS_TRIGGERED,
                    observed_value=ANNOUNCEMENT_RISK_FOUND,
                    threshold="no price-sensitive announcement risk",
                    message=str(entry.get("details") or "ASX 公告发现风险，需要人工复核。"),
                    source=str(entry.get("source") or "daily_decision_summary.evidence_matrix"),
                    as_of=str(entry.get("as_of_date") or _market_as_of(alert_center)),
                    action_hint="打开 ASX 官方公告页面人工确认。",
                )
            if status == ANNOUNCEMENT_UNAVAILABLE:
                return _target_result(
                    target=target,
                    status=STATUS_DEGRADED,
                    observed_value=ANNOUNCEMENT_UNAVAILABLE,
                    threshold="announcement source available",
                    message="ASX 公告源不可用，不能推断为 clear，需要人工复核。",
                    source=str(entry.get("source") or "daily_decision_summary.evidence_matrix"),
                    as_of=str(entry.get("as_of_date") or _market_as_of(alert_center)),
                    action_hint="先手动打开 ASX announcements 官方页面。",
                )
        for item in _alert_items(alert_center, target):
            if item.get("category") == "announcement":
                observed = ANNOUNCEMENT_RISK_FOUND if item.get("severity") == "critical" else ANNOUNCEMENT_UNAVAILABLE
                return _target_result(
                    target=target,
                    status=STATUS_TRIGGERED if observed == ANNOUNCEMENT_RISK_FOUND else STATUS_DEGRADED,
                    observed_value=observed,
                    threshold="announcement source available",
                    message=str(item.get("message") or "ASX 公告需要人工复核。"),
                    source=str(item.get("source") or "alert_center"),
                    as_of=str(item.get("as_of") or _market_as_of(alert_center)),
                    action_hint=str(item.get("action_hint") or "先人工复核。"),
                )
        return _target_result(
            target=target,
            status=STATUS_NOT_TRIGGERED,
            observed_value="not_found",
            threshold=ANNOUNCEMENT_RISK_FOUND,
            message="未发现该标的的 ASX 公告风险提醒。",
            source="daily_decision_summary.evidence_matrix",
            as_of=_market_as_of(alert_center),
            action_hint="保留为人工复核输入，不生成执行动作。",
        )

    def _evaluate_stale_price(self, target: str, alert_center: Mapping[str, Any]) -> Dict[str, Any]:
        market_context = alert_center.get("market_context") if isinstance(alert_center.get("market_context"), Mapping) else {}
        basis = _clean_text(market_context.get("data_basis")) or "unavailable"
        if basis in {"close_only", "delayed", "unavailable"}:
            return _target_result(
                target=target,
                status=STATUS_DEGRADED,
                observed_value=basis,
                threshold="fresh intraday data",
                message=f"当前价格口径为 {basis}，不能推断为 clear，需要人工复核。",
                source="alert_center.market_context.data_basis",
                as_of=str(market_context.get("as_of") or ""),
                action_hint="先确认行情时间基准和最新收盘/延迟口径。",
            )
        return _target_result(
            target=target,
            status=STATUS_NOT_TRIGGERED,
            observed_value=basis,
            threshold="fresh intraday data",
            message="价格口径未触发 stale/delayed 降级提醒。",
            source="alert_center.market_context.data_basis",
            as_of=str(market_context.get("as_of") or ""),
            action_hint="保留为人工复核输入，不生成执行动作。",
        )

    def _evaluate_portfolio_concentration(self, target: str, rule: Mapping[str, Any]) -> Dict[str, Any]:
        max_weight = _float_parameter(rule.get("parameters"), "max_weight", 0.25)
        holding = self._holding_for_target(target)
        if holding is None:
            return _target_result(
                target=target,
                status=STATUS_SKIPPED,
                observed_value=None,
                threshold=max_weight,
                message="组合中未找到该持仓，跳过评估。",
                source="portfolio_overview.holdings",
                as_of="",
                action_hint="确认持仓代码后再人工复核。",
            )
        weight = round(float(holding.get("weight") or 0.0), 6)
        triggered = weight > max_weight
        return _target_result(
            target=target,
            status=STATUS_TRIGGERED if triggered else STATUS_NOT_TRIGGERED,
            observed_value=weight,
            threshold=max_weight,
            message=(
                f"{target} 当前组合权重 {weight:.2%} 高于 dry-run 阈值 {max_weight:.2%}。"
                if triggered
                else f"{target} 当前组合权重 {weight:.2%} 未超过 dry-run 阈值。"
            ),
            source="portfolio_overview.holdings",
            as_of=str(self._portfolio_overview().get("snapshot_date") or ""),
            action_hint="作为人工复核提醒，不生成调仓或交易动作。",
        )

    def _evaluate_portfolio_drawdown(self, target: str, rule: Mapping[str, Any]) -> Dict[str, Any]:
        threshold_pct = _float_parameter(rule.get("parameters"), "drawdown_pct", 5.0)
        event = self._latest_account_snapshot_event()
        if event is None:
            return _target_result(
                target=target,
                status=STATUS_DEGRADED,
                observed_value="unavailable",
                threshold=threshold_pct,
                message="未找到组合账户快照，不能推断为 clear，需要人工复核。",
                source="portfolio_events.account_snapshot",
                as_of="",
                action_hint="先确认账户快照或手工组合记录。",
            )
        daily_pnl = _optional_float((event.get("metadata") or {}).get("daily_pnl"))
        total_value = _optional_float(event.get("total_value"))
        if daily_pnl is None or not total_value:
            return _target_result(
                target=target,
                status=STATUS_DEGRADED,
                observed_value="unavailable",
                threshold=threshold_pct,
                message="账户快照缺少 daily_pnl 或 total_value，不能推断为 clear，需要人工复核。",
                source="portfolio_events.account_snapshot",
                as_of=str(event.get("created_at") or event.get("event_date") or ""),
                action_hint="先补齐账户快照字段或人工计算。",
            )
        observed_pct = round((daily_pnl / total_value) * 100, 4)
        triggered = observed_pct <= -abs(threshold_pct)
        return _target_result(
            target=target,
            status=STATUS_TRIGGERED if triggered else STATUS_NOT_TRIGGERED,
            observed_value=observed_pct,
            threshold=-abs(threshold_pct),
            message=(
                f"账户日内/日级 PnL 为 {observed_pct:.2f}%，触发 dry-run 回撤提醒。"
                if triggered
                else f"账户日内/日级 PnL 为 {observed_pct:.2f}%，未触发 dry-run 回撤阈值。"
            ),
            source="portfolio_events.account_snapshot",
            as_of=str(event.get("created_at") or event.get("event_date") or ""),
            action_hint="作为人工复核提醒，不生成调仓或交易动作。",
        )

    def _evaluate_portfolio_price_stale(self, target: str) -> Dict[str, Any]:
        holding = self._holding_for_target(target)
        if holding is None:
            return _target_result(
                target=target,
                status=STATUS_SKIPPED,
                observed_value=None,
                threshold="current_price available",
                message="组合中未找到该持仓，跳过评估。",
                source="portfolio_overview.holdings",
                as_of="",
                action_hint="确认持仓代码后再人工复核。",
            )
        current_price = holding.get("current_price")
        if current_price is None:
            return _target_result(
                target=target,
                status=STATUS_DEGRADED,
                observed_value="missing_current_price",
                threshold="current_price available",
                message="持仓缺少 current_price，不能推断为 clear，需要人工复核。",
                source="portfolio_overview.holdings.current_price",
                as_of=str(self._portfolio_overview().get("snapshot_date") or ""),
                action_hint="先确认组合价格更新时间和数据来源。",
            )
        return _target_result(
            target=target,
            status=STATUS_DEGRADED,
            observed_value=current_price,
            threshold="price timestamp available",
            message="组合持仓只有 current_price，没有价格时间戳，不能推断为 clear，需要人工复核。",
            source="portfolio_overview.holdings.current_price",
            as_of=str(self._portfolio_overview().get("snapshot_date") or ""),
            action_hint="先确认组合价格更新时间和数据来源。",
        )

    def _portfolio_overview(self) -> Mapping[str, Any]:
        try:
            overview = self.db.get_portfolio_overview() or {}
        except Exception:
            overview = {}
        return overview if isinstance(overview, Mapping) else {}

    def _holding_for_target(self, target: str) -> Optional[Mapping[str, Any]]:
        for holding in self._portfolio_overview().get("holdings") or []:
            if isinstance(holding, Mapping) and canonical_stock_code(holding.get("code")) == target:
                return holding
        return None

    def _latest_account_snapshot_event(self) -> Optional[Mapping[str, Any]]:
        events = PortfolioEventService(self.db).list_events(
            PortfolioEventFilters(event_type="account_snapshot", page=1, page_size=50)
        )
        rows = events.get("events") if isinstance(events, Mapping) else []
        for event in rows or []:
            if not isinstance(event, Mapping):
                continue
            metadata = event.get("metadata") if isinstance(event.get("metadata"), Mapping) else {}
            if metadata.get("daily_pnl") is not None and event.get("total_value") is not None:
                return event
        for event in rows or []:
            if isinstance(event, Mapping):
                return event
        return None


def _target_result(
    *,
    target: str,
    status: str,
    observed_value: Any,
    threshold: Any,
    message: str,
    source: str,
    as_of: str,
    action_hint: str,
) -> Dict[str, Any]:
    return {
        "target": target,
        "status": status,
        "triggered": status == STATUS_TRIGGERED,
        "observed_value": observed_value,
        "threshold": threshold,
        "message": message,
        "source": source,
        "as_of": as_of,
        "action_hint": action_hint,
        "is_trade_instruction": False,
    }


def _alert_items(alert_center: Mapping[str, Any], target: str) -> List[Mapping[str, Any]]:
    items = alert_center.get("items") if isinstance(alert_center, Mapping) else []
    result = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        code = canonical_stock_code(item.get("code"))
        if code == target or item.get("code") in {None, ""}:
            result.append(item)
    return result


def _announcement_entry(summary_artifact: Any, target: str) -> Optional[Mapping[str, Any]]:
    if not isinstance(summary_artifact, Mapping):
        return None
    matrix = summary_artifact.get("evidence_matrix")
    if not isinstance(matrix, Mapping):
        return None
    entries = matrix.get(target) or matrix.get(target.replace(".AX", "")) or []
    if isinstance(entries, Mapping) or isinstance(entries, (str, bytes)):
        return None
    for entry in entries:
        if isinstance(entry, Mapping) and _clean_text(entry.get("category")) == "announcement":
            return entry
    return None


def _symbol_list(value: str) -> List[str]:
    result = []
    for part in str(value or "").replace(";", ",").split(","):
        code = canonical_stock_code(part)
        if code:
            result.append(code)
    return list(dict.fromkeys(result))


def _cap_targets(targets: List[str], max_targets: int) -> Tuple[List[str], int]:
    unique = list(dict.fromkeys(targets))
    return unique[:max_targets], max(len(unique) - max_targets, 0)


def _max_targets(parameters: Any) -> int:
    if not isinstance(parameters, Mapping):
        return MAX_TARGETS
    raw = parameters.get("max_targets", MAX_TARGETS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = MAX_TARGETS
    return min(max(value, 1), MAX_TARGETS)


def _float_parameter(parameters: Any, key: str, default: float) -> float:
    if not isinstance(parameters, Mapping) or key not in parameters:
        return default
    value = float(parameters[key])
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_as_of(alert_center: Mapping[str, Any]) -> str:
    market_context = alert_center.get("market_context") if isinstance(alert_center, Mapping) else {}
    return str((market_context or {}).get("as_of") or "")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


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
