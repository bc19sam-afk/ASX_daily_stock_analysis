# -*- coding: utf-8 -*-
"""
===================================
历史查询服务层
===================================

职责：
1. 封装历史记录查询逻辑
2. 提供分页和筛选功能
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from src.core.validator import normalize_validation_status
from src.services.signal_history_stats_service import SignalHistoryStatsService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)


class HistoryService:
    """
    历史查询服务
    
    封装历史分析记录的查询逻辑
    """
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化历史查询服务
        
        Args:
            db_manager: 数据库管理器（可选，默认使用单例）
        """
        self.db = db_manager or DatabaseManager.get_instance()
    
    def get_history_list(
        self,
        stock_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        获取历史分析列表
        
        Args:
            stock_code: 股票代码筛选
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            page: 页码
            limit: 每页数量
            
        Returns:
            包含 total, items 的字典
        """
        try:
            # 解析日期参数
            start_dt = None
            end_dt = None
            
            if start_date:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning(f"无效的 start_date 格式: {start_date}")
            
            if end_date:
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning(f"无效的 end_date 格式: {end_date}")
            
            # 计算 offset
            offset = (page - 1) * limit
            
            # 使用新的分页查询方法
            records, total = self.db.get_analysis_history_paginated(
                code=stock_code,
                start_date=start_dt,
                end_date=end_dt,
                offset=offset,
                limit=limit
            )
            
            # 转换为响应格式
            items = []
            for record in records:
                items.append({
                    "query_id": record.query_id,
                    "stock_code": record.code,
                    "stock_name": record.name,
                    "report_type": record.report_type,
                    "sentiment_score": record.sentiment_score,
                    "operation_advice": record.operation_advice,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                })
            
            return {
                "total": total,
                "items": items,
            }
            
        except Exception as e:
            logger.error(f"查询历史列表失败: {e}", exc_info=True)
            return {"total": 0, "items": []}
    
    def get_history_detail(self, query_id: str) -> Optional[Dict[str, Any]]:
        """
        获取历史报告详情
        
        Args:
            query_id: 分析记录唯一标识
            
        Returns:
            完整的分析报告字典，不存在返回 None
        """
        try:
            # 查询数据库
            records = self.db.get_analysis_history(query_id=query_id, limit=1)
            
            if not records:
                return None
            
            record = records[0]
            
            # 解析 raw_result JSON
            raw_result = None
            if record.raw_result:
                try:
                    raw_result = json.loads(record.raw_result)
                except json.JSONDecodeError:
                    raw_result = record.raw_result
            validation_status = (
                normalize_validation_status(raw_result.get("validation_status"))
                if isinstance(raw_result, dict) and "validation_status" in raw_result
                else None
            )
            validation_issues = (
                list(raw_result.get("validation_issues") or [])
                if isinstance(raw_result, dict)
                else []
            )
            
            # 解析 context_snapshot JSON
            context_snapshot = None
            if record.context_snapshot:
                try:
                    context_snapshot = json.loads(record.context_snapshot)
                except json.JSONDecodeError:
                    context_snapshot = record.context_snapshot
            
            # 计算情绪标签
            sentiment_label = self._get_sentiment_label(
                record.sentiment_score if record.sentiment_score is not None else 50
            )
            similar_signal_performance = self._build_similar_signal_performance(record, raw_result)
            price_snapshot = self._extract_price_snapshot(context_snapshot)
            report_context = self._build_public_report_context(record, raw_result, context_snapshot)
            alert_context = self._build_public_alert_context(raw_result, context_snapshot)
            
            payload = {
                "query_id": record.query_id,
                "stock_code": record.code,
                "stock_name": record.name,
                "report_type": record.report_type,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "report_date": report_context.get("report_date"),
                "technical_basis_date": report_context.get("technical_basis_date"),
                "price_policy": report_context.get("price_policy"),
                "execution_price_source": report_context.get("execution_price_source"),
                "current_price": price_snapshot.get("current_price"),
                "change_pct": price_snapshot.get("change_pct"),
                "analysis_status": raw_result.get("analysis_status") if isinstance(raw_result, dict) else None,
                "validation_status": validation_status,
                "validation_issues": validation_issues,
                "analysis_summary": record.analysis_summary,
                "operation_advice": record.operation_advice,
                "trend_prediction": record.trend_prediction,
                "sentiment_score": record.sentiment_score,
                "sentiment_label": sentiment_label,
                "alpha_decision": record.alpha_decision,
                "final_decision": record.final_decision,
                "position_action": record.position_action,
                "target_weight": record.target_weight,
                "current_weight": record.current_weight,
                "delta_amount": record.delta_amount,
                "action_reason": record.action_reason,
                "watchlist_state": record.watchlist_state,
                "market_regime": record.market_regime,
                "news_sentiment": record.news_sentiment,
                "event_risk": record.event_risk,
                "sector_tone": record.sector_tone,
                "data_quality_flag": record.data_quality_flag,
                "similar_signal_performance": similar_signal_performance,
                "ideal_buy": str(record.ideal_buy) if record.ideal_buy else None,
                "secondary_buy": str(record.secondary_buy) if record.secondary_buy else None,
                "stop_loss": str(record.stop_loss) if record.stop_loss else None,
                "take_profit": str(record.take_profit) if record.take_profit else None,
                "news_content": record.news_content,
                "portfolio": self.db.get_portfolio_overview(),
            }
            payload.update(alert_context)
            return payload
            
        except Exception as e:
            logger.error(f"查询历史详情失败: {e}", exc_info=True)
            return None

    def _build_similar_signal_performance(self, record: Any, raw_result: Any) -> Dict[str, Any]:
        """Build display-only similar signal stats without affecting decisions."""
        try:
            return SignalHistoryStatsService(self.db).build_for_record(record, raw_result)
        except Exception as exc:
            logger.warning("构建类似信号历史表现失败，仅返回不可用状态: %s", exc)
            return {
                "contract_version": "similar_signal_history_v1",
                "display_only": True,
                "note": "仅供历史参考，不改变当前建议。",
                "status": "insufficient_data",
                "reason": "stats_unavailable",
                "sample_size": 0,
                "low_sample": True,
                "warning": "样本较少，参考价值有限",
                "windows": [],
            }

    def _build_public_report_context(
        self,
        record: Any,
        raw_result: Any,
        context_snapshot: Any,
    ) -> Dict[str, Optional[str]]:
        raw = raw_result if isinstance(raw_result, dict) else {}
        context = context_snapshot if isinstance(context_snapshot, dict) else {}
        created_at = getattr(record, "created_at", None)

        report_date = (
            self._first_string(
                raw,
                ("report_date",),
                ("summary", "report_date"),
                ("meta", "report_date"),
            )
            or self._date_part(created_at)
        )
        technical_basis_date = self._first_string(
            raw,
            ("technical_basis_date",),
            ("market_basis_date",),
            ("snapshot_basis_date",),
            ("summary", "technical_basis_date"),
            ("meta", "technical_basis_date"),
            ("market_snapshot", "date"),
            context,
            ("technical_basis_date",),
            ("market_basis_date",),
            ("snapshot_basis_date",),
            ("enhanced_context", "technical_basis_date"),
            ("enhanced_context", "market_basis_date"),
            ("enhanced_context", "snapshot_basis_date"),
            ("enhanced_context", "date"),
        )
        execution_price_source = self._first_string(
            raw,
            ("execution_price_source",),
            ("summary", "execution_price_source"),
            ("meta", "execution_price_source"),
            context,
            ("execution_price_source",),
            ("enhanced_context", "execution_price_source"),
        )
        price_policy = self._first_string(
            raw,
            ("price_policy",),
            ("summary", "price_policy"),
            ("meta", "price_policy"),
            context,
            ("price_policy",),
            ("enhanced_context", "price_policy"),
        ) or execution_price_source

        return {
            "report_date": report_date,
            "technical_basis_date": technical_basis_date,
            "price_policy": price_policy,
            "execution_price_source": execution_price_source,
        }

    def _build_public_alert_context(self, raw_result: Any, context_snapshot: Any) -> Dict[str, Any]:
        """Expose structured alert inputs without leaking raw_result/context_snapshot."""
        raw = raw_result if isinstance(raw_result, dict) else {}
        context = context_snapshot if isinstance(context_snapshot, dict) else {}
        enhanced = context.get("enhanced_context") if isinstance(context.get("enhanced_context"), dict) else {}
        daily_summary = raw.get("daily_decision_summary") if isinstance(raw.get("daily_decision_summary"), dict) else {}
        if not daily_summary:
            daily_summary = raw.get("summary_artifact") if isinstance(raw.get("summary_artifact"), dict) else {}

        payload: Dict[str, Any] = {}
        for key in (
            "evidence_matrix",
            "evidence_summary",
            "report_reliability",
            "watch_items",
            "blocked_items",
            "uncovered_holdings",
        ):
            value = daily_summary.get(key) if daily_summary else raw.get(key)
            if value is not None:
                payload[key] = value

        analysis_context_pack = raw.get("analysis_context_pack") or enhanced.get("analysis_context_pack")
        if isinstance(analysis_context_pack, dict):
            minimal_pack = self._minimal_analysis_context_pack(analysis_context_pack)
            if minimal_pack:
                payload["analysis_context_pack"] = minimal_pack

        if not payload.get("report_reliability") and isinstance(raw.get("report_reliability"), dict):
            payload["report_reliability"] = raw["report_reliability"]
        return payload

    @staticmethod
    def _minimal_analysis_context_pack(analysis_context_pack: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the AnalysisContextPack fields Alert Center needs."""
        payload: Dict[str, Any] = {}
        identity = analysis_context_pack.get("stock_identity")
        if isinstance(identity, dict) and identity.get("code"):
            payload["stock_identity"] = {"code": str(identity.get("code"))}
        risk_context = analysis_context_pack.get("risk_context")
        if isinstance(risk_context, dict):
            allowed = ("validation_status", "validation_issues", "actionability")
            payload["risk_context"] = {key: risk_context[key] for key in allowed if key in risk_context}
        return payload

    def _extract_price_snapshot(self, context_snapshot: Any) -> Dict[str, Optional[float]]:
        if not isinstance(context_snapshot, dict):
            return {"current_price": None, "change_pct": None}

        enhanced_context = context_snapshot.get("enhanced_context") or {}
        realtime = enhanced_context.get("realtime") or {}
        current_price = realtime.get("price")
        change_pct = realtime.get("change_pct") or realtime.get("change_60d")

        if current_price is None:
            realtime_quote_raw = context_snapshot.get("realtime_quote_raw") or {}
            current_price = realtime_quote_raw.get("price")
            change_pct = change_pct or realtime_quote_raw.get("change_pct") or realtime_quote_raw.get("pct_chg")

        return {
            "current_price": self._coerce_float(current_price),
            "change_pct": self._coerce_float(change_pct),
        }

    @classmethod
    def _first_string(cls, first_mapping: Any, *paths_and_mappings: Any) -> Optional[str]:
        current_mapping = first_mapping if isinstance(first_mapping, dict) else {}
        for item in paths_and_mappings:
            if isinstance(item, dict):
                current_mapping = item
                continue
            value = cls._nested_value(current_mapping, item)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _nested_value(mapping: Dict[str, Any], path: Any) -> Any:
        value: Any = mapping
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    @staticmethod
    def _date_part(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        text = str(value).strip()
        if not text:
            return None
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text[:10] if len(text) >= 10 else text

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_news_intel(self, query_id: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        获取指定 query_id 关联的新闻情报

        Args:
            query_id: 分析记录唯一标识
            limit: 返回数量限制

        Returns:
            新闻情报列表（包含 title、snippet、url）
        """
        try:
            records = self.db.get_news_intel_by_query_id(query_id=query_id, limit=limit)

            if not records:
                records = self._fallback_news_by_analysis_context(query_id=query_id, limit=limit)

            items: List[Dict[str, str]] = []
            for record in records:
                snippet = (record.snippet or "").strip()
                if len(snippet) > 200:
                    snippet = f"{snippet[:197]}..."
                items.append({
                    "title": record.title,
                    "snippet": snippet,
                    "url": record.url,
                })

            return items

        except Exception as e:
            logger.error(f"查询新闻情报失败: {e}", exc_info=True)
            return []

    def _fallback_news_by_analysis_context(self, query_id: str, limit: int) -> List[Any]:
        """
        Fallback by analysis context when direct query_id lookup returns no news.

        Typical scenarios:
        - URL-level dedup keeps one canonical news row across repeated analyses.
        - Legacy records may have different historical query_id strategies.
        """
        records = self.db.get_analysis_history(query_id=query_id, limit=1)
        if not records:
            return []

        analysis = records[0]
        if not analysis.code or not analysis.created_at:
            return []

        # Narrow down to same-stock recent news, then filter by analysis time window.
        days = max(1, (datetime.now() - analysis.created_at).days + 1)
        candidates = self.db.get_recent_news(code=analysis.code, days=days, limit=max(limit * 5, 50))

        start_time = analysis.created_at - timedelta(hours=6)
        end_time = analysis.created_at + timedelta(hours=6)
        matched = [
            item for item in candidates
            if item.fetched_at and start_time <= item.fetched_at <= end_time
        ]

        return matched[:limit]
    
    def _get_sentiment_label(self, score: int) -> str:
        """
        根据评分获取情绪标签
        
        Args:
            score: 情绪评分 (0-100)
            
        Returns:
            情绪标签
        """
        if score >= 80:
            return "极度乐观"
        elif score >= 60:
            return "乐观"
        elif score >= 40:
            return "中性"
        elif score >= 20:
            return "悲观"
        else:
            return "极度悲观"
