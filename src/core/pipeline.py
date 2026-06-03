# -*- coding: utf-8 -*-
"""
===================================
ASX-first 自选股智能分析系统 - 核心分析流水线
===================================

职责：
1. 管理整个分析流程
2. 协调数据获取、存储、搜索、分析、通知等模块
3. 实现并发控制和异常处理
4. 提供股票分析的核心功能
"""

import logging
import math
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo

from src.config import get_config, Config
from src.storage import get_db
from data_provider import DataFetcherManager
from src.analysis_context import build_analysis_context_pack
from src.analyzer import GeminiAnalyzer, AnalysisResult, STOCK_NAME_MAP
from src.notification import NotificationService, NotificationChannel
from src.search_service import SearchService
from src.enums import ReportType
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult
from src.core.position_manager import PositionManager
from src.core.pipeline_notifications import send_single_stock_notification
from src.core.pipeline_validation import apply_validation_gate as apply_pipeline_validation_gate
from src.market_calendar import get_market_report_date, is_pre_market_open
from src.security_logging import log_sensitive_payload
from src.stock_code import canonical_stock_code, canonical_stock_codes
from bot.models import BotMessage


logger = logging.getLogger(__name__)

DEFAULT_MARKET_TIMEZONE = "Australia/Sydney"


def _resolve_timezone_name_safe(timezone_name: Optional[str]) -> str:
    """Return a valid market timezone name, falling back to Sydney fail-safe."""
    candidate = (timezone_name or DEFAULT_MARKET_TIMEZONE).strip()
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception as exc:
        logger.warning(
            "无效市场时区 %s，已回退到 %s: %s",
            timezone_name,
            DEFAULT_MARKET_TIMEZONE,
            exc,
        )
        return DEFAULT_MARKET_TIMEZONE


def _now_in_timezone_safe(timezone_name: Optional[str]) -> datetime:
    """Return timezone-aware now with fail-safe fallback to Sydney."""
    safe_timezone = _resolve_timezone_name_safe(timezone_name)
    return datetime.now(ZoneInfo(safe_timezone))


def _market_report_date_safe(config: Config) -> date:
    """Return the last closed market session used for cache and close-only data."""
    market_timezone = _resolve_timezone_name_safe(getattr(config, "market_timezone", DEFAULT_MARKET_TIMEZONE))
    market_now = _now_in_timezone_safe(market_timezone)
    try:
        return get_market_report_date(
            market_now,
            calendar=getattr(config, "market_calendar", "ASX"),
            market_timezone=market_timezone,
        )
    except Exception as exc:
        logger.error("无法解析市场报告日期，停止使用缓存日期: %s", exc)
        raise ValueError("无法解析市场报告日期，请检查 market_calendar / market_timezone 配置") from exc


def _report_run_date_safe(config: Config) -> date:
    """Return the market-local report generation date used for labels."""
    market_timezone = _resolve_timezone_name_safe(getattr(config, "market_timezone", DEFAULT_MARKET_TIMEZONE))
    return _now_in_timezone_safe(market_timezone).date()


class StockAnalysisPipeline:
    """
    股票分析主流程调度器
    
    职责：
    1. 管理整个分析流程
    2. 协调数据获取、存储、搜索、分析、通知等模块
    3. 实现并发控制和异常处理
    """
    def __init__(
        self,
        config: Optional[Config] = None,
        max_workers: Optional[int] = None,
        source_message: Optional[BotMessage] = None,
        query_id: Optional[str] = None,
        query_source: Optional[str] = None,
        save_context_snapshot: Optional[bool] = None
        
    ):
        """
        初始化调度器
        
        Args:
            config: 配置对象（可选，默认使用全局配置）
            max_workers: 最大并发线程数（可选，默认从配置读取）
        """
        self.config = config or get_config()
        self.max_workers = max_workers or self.config.max_workers
        self.source_message = source_message
        self.query_id = query_id
        self.query_source = self._resolve_query_source(query_source)
        self.save_context_snapshot = (
            self.config.save_context_snapshot if save_context_snapshot is None else save_context_snapshot
        )
        
        # 初始化各模块
        self.db = get_db()
        self.fetcher_manager = DataFetcherManager(config=self.config)
        # 统一使用 fetcher_manager 获取增强数据
        self.trend_analyzer = StockTrendAnalyzer()  # 趋势分析器
        self.analyzer = GeminiAnalyzer()
        self.notifier = NotificationService(source_message=source_message)
        self.position_manager = PositionManager()
        
        # 初始化搜索服务
        self.search_service = SearchService(
            tavily_keys=self.config.tavily_api_keys,
            serpapi_keys=self.config.serpapi_keys,
            gemini_keys=self.config.gemini_api_keys,
            gemini_grounding_enabled=self.config.gemini_grounding_search_enabled,
            gemini_grounding_model=self.config.gemini_grounding_model,
            gemini_grounding_max_results=self.config.gemini_grounding_max_results,
            news_max_age_days=self.config.news_max_age_days,
            market_timezone=self.config.market_timezone,
        )
        
        logger.info(f"调度器初始化完成，最大并发数: {self.max_workers}")
        logger.info("已启用趋势分析器 (MA5>MA10>MA20 多头判断)")
        # 打印实时行情配置状态
        if self.config.enable_realtime_quote:
            logger.info(f"实时行情已启用 (优先级: {self.config.realtime_source_priority})")
        else:
            logger.info("实时行情已禁用，将使用历史收盘价")
        if self.search_service.is_available:
            logger.info("搜索服务已启用 (Tavily/Gemini Grounding/SerpAPI)")
        else:
            logger.warning("搜索服务未启用（未配置 API Key）")
    
    def fetch_and_save_stock_data(
        self, 
        code: str,
        force_refresh: bool = False
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        获取并保存单只股票数据
        
        断点续传逻辑：
        1. 检查数据库是否已有今日数据
        2. 如果有且不强制刷新，则跳过网络请求
        3. 否则从数据源获取并保存
        
        Args:
            code: 股票代码
            force_refresh: 是否强制刷新（忽略本地缓存）
            
        Returns:
            Tuple[是否成功, 错误信息, 数据属性]
        """
        code = canonical_stock_code(code)
        try:
            today = _market_report_date_safe(self.config)
            
            # 断点续传检查：如果今日数据已存在，跳过
            if not force_refresh and self.db.has_today_data(code, today):
                logger.info(f"[{code}] 今日数据已存在，跳过获取（断点续传）")
                return True, None, {}
            
            # 从数据源获取数据
            logger.info(f"[{code}] 开始从数据源获取数据...")
            df, source_name = self.fetcher_manager.get_daily_data(code, days=30)
            
            if df is None or df.empty:
                return False, "获取数据为空", {}
            
            # 缓存 df.attrs（含股票名称和资金面摘要）
            df_attrs = dict(df.attrs) if hasattr(df, 'attrs') else {}

            # 保存到数据库
            saved_count = self.db.save_daily_data(df, code, source_name)
            logger.info(f"[{code}] 数据保存成功（来源: {source_name}，新增 {saved_count} 条）")
            
            return True, None, df_attrs
            
        except Exception as e:
            error_msg = f"获取/保存数据失败: {str(e)}"
            logger.error(f"[{code}] {error_msg}")
            return False, error_msg, {}
    
    def analyze_stock(
        self,
        code: str,
        report_type: ReportType,
        query_id: str,
        df_attrs: Optional[dict] = None,
        market_overview: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> Optional[AnalysisResult]:
        """
        分析单只股票（增强版：含量比、换手率、多维度情报）
        
        流程：
        1. 获取实时行情（量比、换手率）- 通过 DataFetcherManager 自动故障切换
        2. 进行趋势分析（基于交易理念）
        3. 多维度情报搜索（最新消息+风险排查+业绩预期）
        4. 从数据库获取分析上下文
        5. 调用 AI 进行综合分析
        
        Args:
            query_id: 查询链路关联 id
            code: 股票代码
            report_type: 报告类型
            
        Returns:
            AnalysisResult 或 None（如果分析失败）
        """
        code = canonical_stock_code(code)
        try:
            # 获取股票名称（优先从实时行情获取真实名称）
            stock_name = STOCK_NAME_MAP.get(code, '')
            
            # Step 1: 获取实时行情（量比、换手率等）- 使用统一入口，自动故障切换
            realtime_quote = None
            try:
                realtime_quote = self.fetcher_manager.get_realtime_quote(code)
                if realtime_quote:
                    # 使用实时行情返回的真实股票名称
                    if realtime_quote.name:
                        stock_name = realtime_quote.name
                    # 兼容不同数据源的字段（有些数据源可能没有 volume_ratio）
                    volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
                    turnover_rate = getattr(realtime_quote, 'turnover_rate', None)
                    logger.info(f"[{code}] {stock_name} 实时行情: 价格={realtime_quote.price}, "
                              f"量比={volume_ratio}, 换手率={turnover_rate}% "
                              f"(来源: {realtime_quote.source.value if hasattr(realtime_quote, 'source') else 'unknown'})")
                else:
                    logger.info(f"[{code}] 实时行情获取失败或已禁用，将使用历史数据进行分析")
            except Exception as e:
                logger.warning(f"[{code}] 获取实时行情失败: {e}")
            
            # 如果还是没有名称，使用代码作为名称
            # 从 yfinance df.attrs 补充股票名称（解决"股票ARB.AX"问题）
            if not stock_name and df_attrs.get('stock_name'):
                stock_name = df_attrs['stock_name']
            if not stock_name:
                stock_name = f'股票{code}'
            
            # Step 3: 趋势分析（基于交易理念）
            trend_result: Optional[TrendAnalysisResult] = None
            try:
                # 获取历史数据进行趋势分析
                context = self.db.get_analysis_context(code)
                if context and 'raw_data' in context:
                    import pandas as pd
                    raw_data = context['raw_data']
                    if isinstance(raw_data, list) and len(raw_data) > 0:
                        df = pd.DataFrame(raw_data)
                        trend_result = self.trend_analyzer.analyze(df, code)
                        logger.info(f"[{code}] 趋势分析: {trend_result.trend_status.value}, "
                                  f"买入信号={trend_result.buy_signal.value}, 评分={trend_result.signal_score}")
            except Exception as e:
                logger.warning(f"[{code}] 趋势分析失败: {e}")
            
            # Step 4: 多维度情报搜索（最新消息+风险排查+业绩预期）
            news_context = None
            news_intel_cache_enabled = bool(getattr(self.config, "news_intel_cache_enabled", False))
            if self.search_service.is_available or news_intel_cache_enabled:
                logger.info(f"[{code}] 开始多维度情报搜索...")
                
                # 使用多维度搜索（最多5次搜索）
                intel_results = self._search_comprehensive_intel_with_news_cache(
                    code=code,
                    stock_name=stock_name,
                    max_searches=5,
                    force_refresh=force_refresh,
                )
                
                # 格式化情报报告
                if intel_results:
                    news_context = self.search_service.format_intel_report(intel_results, stock_name)
                    total_results = sum(
                        len(r.results) for r in intel_results.values() if r.success
                    )
                    logger.info(f"[{code}] 情报搜索完成: 共 {total_results} 条结果")
                    log_sensitive_payload(logger, logging.DEBUG, f"[{code}] 情报搜索结果", news_context)

                    # 保存新闻情报到数据库（用于后续复盘与查询）
                    try:
                        query_context = self._build_query_context(query_id=query_id)
                        for dim_name, response in intel_results.items():
                            if response and response.success and response.results:
                                if response.provider == SearchService.NEWS_INTEL_CACHE_PROVIDER:
                                    continue
                                self.db.save_news_intel(
                                    code=code,
                                    name=stock_name,
                                    dimension=dim_name,
                                    query=response.query,
                                    response=response,
                                    query_context=query_context
                                )
                    except Exception as e:
                        logger.warning(f"[{code}] 保存新闻情报失败: {e}")
            else:
                logger.info(f"[{code}] 搜索服务不可用，跳过情报搜索")
            
            # Step 5: 获取分析上下文（技术面数据）
            context = self.db.get_analysis_context(code)
            
            if context is None:
                logger.warning(f"[{code}] 无法获取历史行情数据，将仅基于新闻和实时行情分析")
                from datetime import date
                context = {
                    'code': code,
                    'stock_name': stock_name,
                    'date': date.today().isoformat(),
                    'data_missing': True,
                    'today': {},
                    'yesterday': {}
                }
            
            # Step 5.5: 注入资金面数据（直接从df_attrs读取，无需重复调用yfinance）
            try:
                if context.get('allows_current_only_data', True):
                    insider_desc = df_attrs.get('insider_desc', '')
                    inst_desc = df_attrs.get('inst_desc', '')
                    if insider_desc or inst_desc:
                        context['Insider_Desc'] = insider_desc
                        context['Inst_Desc'] = inst_desc
                        logger.info(f"[{code}] 资金面数据已注入 context")
                    else:
                        logger.debug(f"[{code}] df_attrs 无资金面数据，跳过注入")

                    # 注入基本面数据
                    fundamentals = df_attrs.get('fundamentals', {})
                    if fundamentals:
                        context['fundamentals'] = fundamentals
                        logger.info(f"[{code}] 基本面数据已注入 context: {list(fundamentals.keys())}")
                else:
                    logger.info(f"[{code}] 历史上下文禁用 current-only 基本面/持仓数据注入")
            except Exception as e:
                logger.warning(f"[{code}] 资金面数据注入失败（已跳过）：{e}")

            # Step 5.6: 注入大盘宏观数据
            if market_overview:
                context['market_overview'] = market_overview
                logger.info(f"[{code}] 大盘数据已注入 context")

            # Step 5.7: 注入历史回测胜率（真实数据，防止 AI 编造）
            try:
                from src.services.backtest_service import BacktestService
                bt_service = BacktestService()
                summary = bt_service.get_summary(scope='stock', code=code)
                if summary and summary.get('completed_count', 0) >= 3:
                    context['backtest_summary'] = {
                        'total': summary.get('completed_count', 0),
                        'win_rate': summary.get('win_rate_pct'),
                        'direction_accuracy': summary.get('direction_accuracy_pct'),
                        'avg_return': summary.get('avg_stock_return_pct'),
                        'stop_loss_rate': summary.get('stop_loss_trigger_rate'),
                    }
                    logger.info(f"[{code}] 历史胜率已注入: 胜率={summary.get('win_rate_pct')}% 样本={summary.get('completed_count')}")
                else:
                    context['backtest_summary'] = None
            except Exception as e:
                logger.debug(f"[{code}] 回测胜率查询失败（已跳过）: {e}")
                context['backtest_summary'] = None

            # Step 5.8: 注入止损追踪数据（对比昨日止损位和今日价格）
            try:
                prev = self.db.get_previous_signals(code=code, days=7)
                if prev and prev.get('stop_loss'):
                    current_price = None
                    if context.get('today') and isinstance(context['today'], dict):
                        current_price = context['today'].get('close')
                    if current_price and prev['stop_loss'] > 0:
                        sl = prev['stop_loss']
                        diff_pct = (current_price - sl) / sl * 100
                        warning = None
                        if current_price <= sl:
                            warning = f"🚨 止损已触发！当前价 {current_price:.3f} 已跌破止损位 {sl:.3f}"
                        elif diff_pct <= 5:
                            warning = f"⚠️ 止损临近！当前价 {current_price:.3f} 距止损位 {sl:.3f} 仅剩 {diff_pct:.1f}%"
                        context['stop_loss_alert'] = {
                            'prev_stop_loss': sl,
                            'prev_operation': prev.get('operation_advice', ''),
                            'prev_date': prev.get('created_at', ''),
                            'current_price': current_price,
                            'diff_pct': round(diff_pct, 1),
                            'warning': warning,
                        }
                        if warning:
                            logger.warning(f"[{code}] {warning}")
                    else:
                        context['stop_loss_alert'] = None
                else:
                    context['stop_loss_alert'] = None
            except Exception as e:
                logger.debug(f"[{code}] 止损追踪查询失败（已跳过）: {e}")
                context['stop_loss_alert'] = None

            # Step 5.9: 注入信号连续性数据
            try:
                streak_data = self.db.get_signal_streak(code=code, days=10)
                context['signal_streak'] = streak_data
                if streak_data.get('streak', 0) >= 2:
                    logger.info(f"[{code}] 信号连续性: {streak_data.get('summary', '')}")
            except Exception as e:
                logger.debug(f"[{code}] 信号连续性查询失败（已跳过）: {e}")
                context['signal_streak'] = None

            # Step 6: 增强上下文数据（添加实时行情、趋势分析结果、股票名称）
            enhanced_context = self._enhance_context(
                context, 
                realtime_quote, 
                trend_result,
                stock_name  # 传入股票名称
            )
            enhanced_context["analysis_context_pack"] = build_analysis_context_pack(
                enhanced_context,
                stock_name=stock_name,
                news_context=news_context,
                report_date=_report_run_date_safe(self.config).isoformat(),
            ).to_dict()
            
            # Step 7: 调用 AI 分析（传入增强的上下文和新闻）
            result = self.analyzer.analyze(enhanced_context, news_context=news_context)

            # Step 7.5: 填充分析时的价格信息到 result
            if result:
                self._apply_decision_structure(
                    result=result,
                    enhanced_context=enhanced_context,
                    trend_result=trend_result,
                )
                self._apply_backtest_guard(
                    result=result,
                    enhanced_context=enhanced_context,
                )
                self._apply_runtime_price_fields(
                    result=result,
                    enhanced_context=enhanced_context,
                )
                self._apply_validation_gate(
                    result=result,
                    enhanced_context=enhanced_context,
                )
                enhanced_context["analysis_context_pack"] = build_analysis_context_pack(
                    enhanced_context,
                    stock_name=result.name,
                    news_context=news_context,
                    report_date=_report_run_date_safe(self.config).isoformat(),
                    validation_status=result.validation_status,
                    validation_issues=result.validation_issues,
                ).to_dict()
                if result.validation_status != "BLOCK":
                    self._apply_position_management(
                        result=result,
                        query_id=query_id,
                        current_price=result.current_price,
                        persist=not getattr(self.config, "analysis_read_only", True),
                    )

            # Step 8: 保存分析历史记录
            if result:
                try:
                    context_snapshot = self._build_context_snapshot(
                        enhanced_context=enhanced_context,
                        news_content=news_context,
                        realtime_quote=realtime_quote
                    )
                    self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=news_context,
                        context_snapshot=context_snapshot,
                        save_snapshot=self.save_context_snapshot
                    )
                except Exception as e:
                    logger.warning(f"[{code}] 保存分析历史失败: {e}")

            return result
            
        except Exception as e:
            logger.error(f"[{code}] 分析失败: {e}")
            logger.exception(f"[{code}] 详细错误信息:")
            return None

    def _search_comprehensive_intel_with_news_cache(
        self,
        *,
        code: str,
        stock_name: str,
        max_searches: int,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Reuse recent persisted news_intel rows before falling back to external search.
        """
        cache_enabled = bool(getattr(self.config, "news_intel_cache_enabled", False))
        if force_refresh or not cache_enabled:
            return self.search_service.search_comprehensive_intel(
                stock_code=code,
                stock_name=stock_name,
                max_searches=max_searches,
            )

        try:
            search_limit = max(0, int(max_searches))
        except (TypeError, ValueError):
            search_limit = 5

        dimensions = self.search_service.build_comprehensive_intel_dimensions(code, stock_name)[:search_limit]
        min_results = max(1, int(getattr(self.config, "news_intel_cache_min_results", 1) or 1))
        cache_days = max(1, int(getattr(self.config, "news_intel_cache_days", 1) or 1))
        cached_intel: Dict[str, Any] = {}

        for dim in dimensions:
            try:
                records = self.db.get_recent_news_intel(
                    code=code,
                    dimension=dim["name"],
                    days=cache_days,
                    limit=max(3, min_results),
                )
                cached_response = self.search_service.build_news_intel_cache_response(
                    stock_code=code,
                    stock_name=stock_name,
                    dimension=dim["name"],
                    query=dim["query"],
                    records=records,
                    min_results=min_results,
                )
                if cached_response is not None:
                    cached_intel[dim["name"]] = cached_response
            except Exception as exc:
                logger.debug(
                    "[%s] 读取 news_intel 缓存失败，维度 %s 将走搜索 provider: %s",
                    code,
                    dim["name"],
                    exc,
                )

        missing_dimensions = [dim for dim in dimensions if dim["name"] not in cached_intel]
        results = dict(cached_intel)
        if missing_dimensions:
            if self.search_service.is_available:
                fresh_results = self.search_service.search_comprehensive_intel(
                    stock_code=code,
                    stock_name=stock_name,
                    max_searches=len(missing_dimensions),
                    dimensions=missing_dimensions,
                )
                results.update(fresh_results)
            elif not results:
                return {}

        return {
            dim["name"]: results[dim["name"]]
            for dim in dimensions
            if dim["name"] in results
        }

    @staticmethod
    def _map_alpha_decision(buy_signal: Optional[str]) -> str:
        signal = str(buy_signal or "").strip()
        if signal in ("强烈买入", "买入"):
            return "BUY"
        if signal in ("卖出", "强烈卖出"):
            return "SELL"
        return "HOLD"

    @staticmethod
    def _infer_market_regime(market_overview: Optional[dict]) -> str:
        if not market_overview or not isinstance(market_overview, dict):
            return "NEUTRAL"
        pct_values = []
        for item in market_overview.values():
            if not isinstance(item, dict):
                continue
            pct = item.get("pct_chg")
            try:
                pct_values.append(float(pct))
            except (TypeError, ValueError):
                continue
        if not pct_values:
            return "NEUTRAL"
        avg = sum(pct_values) / len(pct_values)
        if avg >= 0.5:
            return "RISK_ON"
        if avg <= -0.5:
            return "RISK_OFF"
        return "NEUTRAL"

    @staticmethod
    def _synthesize_final_decision(
        *,
        alpha_decision: str,
        market_regime: str,
        news_sentiment: str,
        event_risk: str,
        sector_tone: str,
        data_quality_flag: str,
    ) -> str:
        # 确定性规则：
        # - BUY 可降级到 HOLD
        # - HOLD 不直接降到 SELL
        # - SELL 维持 SELL
        # LLM overlay 中 news_sentiment/sector_tone 只用于解释展示。
        # event_risk=HIGH 是保守风控硬约束：不得与 BUY/OPEN/ADD 共存。
        if event_risk == "HIGH":
            return "HOLD"
        if alpha_decision == "SELL":
            return "SELL"
        if alpha_decision == "HOLD":
            return "HOLD"

        blocked = False
        if data_quality_flag == "MISSING":
            blocked = True
        if market_regime == "RISK_OFF":
            blocked = True

        return "HOLD" if blocked else "BUY"

    def _apply_decision_structure(
        self,
        *,
        result: AnalysisResult,
        enhanced_context: Dict[str, Any],
        trend_result: Optional[TrendAnalysisResult],
    ) -> None:
        buy_signal = getattr(trend_result, "buy_signal", None)
        buy_signal_text = getattr(buy_signal, "value", buy_signal)
        alpha_decision = self._map_alpha_decision(buy_signal_text)

        market_regime = self._infer_market_regime(enhanced_context.get("market_overview"))
        data_quality_flag = "MISSING" if enhanced_context.get("data_missing") else "OK"

        # Overlay 稳定值（对外不暴露 UNKNOWN）
        news_sentiment = getattr(result, "news_sentiment", "NEU")
        if news_sentiment not in ("POS", "NEU", "NEG"):
            news_sentiment = "NEU"

        event_risk = getattr(result, "event_risk", "MEDIUM")
        if event_risk not in ("LOW", "MEDIUM", "HIGH"):
            event_risk = "MEDIUM"

        sector_tone = getattr(result, "sector_tone", "NEU")
        if sector_tone not in ("POS", "NEU", "NEG"):
            sector_tone = "NEU"

        final_decision = self._synthesize_final_decision(
            alpha_decision=alpha_decision,
            market_regime=market_regime,
            news_sentiment=news_sentiment,
            event_risk=event_risk,
            sector_tone=sector_tone,
            data_quality_flag=data_quality_flag,
        )

        result.alpha_decision = alpha_decision
        result.market_regime = market_regime
        result.news_sentiment = news_sentiment
        result.event_risk = event_risk
        result.sector_tone = sector_tone
        result.data_quality_flag = data_quality_flag
        result.final_decision = final_decision
        result.watchlist_state = "ACTIVE"
        if event_risk == "HIGH" and alpha_decision in ("BUY", "SELL"):
            note = "高事件风险，可执行动作已降级为仅观察"
            if note not in (result.risk_warning or ""):
                result.risk_warning = f"{result.risk_warning}；{note}" if result.risk_warning else note

    @staticmethod
    def _classify_backtest_quality(backtest_summary: Optional[Dict[str, Any]]) -> str:
        """Classify backtest quality for deterministic risk guard."""
        if not isinstance(backtest_summary, dict):
            return "INSUFFICIENT"

        completed_count = backtest_summary.get("completed_count", backtest_summary.get("total"))
        try:
            completed_count = int(completed_count)
        except (TypeError, ValueError):
            completed_count = 0
        if completed_count < 5:
            return "INSUFFICIENT"

        def _to_float(value: Any) -> Optional[float]:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        direction_accuracy = _to_float(backtest_summary.get("direction_accuracy"))
        win_rate = _to_float(backtest_summary.get("win_rate"))
        stop_loss_rate = _to_float(backtest_summary.get("stop_loss_rate"))

        if direction_accuracy is not None and direction_accuracy < 50:
            return "WEAK"
        if win_rate is not None and win_rate < 45:
            return "WEAK"
        if stop_loss_rate is not None and stop_loss_rate > 50:
            return "WEAK"
        return "NEUTRAL"

    @staticmethod
    def _downgrade_confidence_level(level: str) -> str:
        if level == "高":
            return "中"
        if level == "中":
            return "低"
        return "低"

    def _apply_backtest_guard(
        self,
        *,
        result: AnalysisResult,
        enhanced_context: Dict[str, Any],
    ) -> None:
        backtest_summary = enhanced_context.get("backtest_summary") if isinstance(enhanced_context, dict) else None
        backtest_quality = self._classify_backtest_quality(backtest_summary)
        if backtest_quality != "WEAK":
            return

        result.confidence_level = self._downgrade_confidence_level(result.confidence_level)
        if result.final_decision == "BUY":
            result.final_decision = "HOLD"
        result.watchlist_state = "ACTIVE"

        downgrade_note = "历史回测表现偏弱，已触发保守降级"
        if downgrade_note not in (result.risk_warning or ""):
            result.risk_warning = (
                f"{result.risk_warning}；{downgrade_note}" if result.risk_warning else downgrade_note
            )

    def _apply_runtime_price_fields(
        self,
        *,
        result: AnalysisResult,
        enhanced_context: Dict[str, Any],
    ) -> None:
        """Apply runtime signal/execution price fields to analysis result."""
        realtime_data = enhanced_context.get("realtime", {}) if isinstance(enhanced_context, dict) else {}
        result.realtime_price = realtime_data.get("price") if isinstance(realtime_data, dict) else None
        result.change_pct = realtime_data.get("change_pct") if isinstance(realtime_data, dict) else None

        execution_price_policy = str(
            getattr(self.config, "execution_price_policy", "realtime_if_available")
        ).strip().lower()
        execution_price_policy = self._resolve_runtime_execution_price_policy(
            execution_price_policy=execution_price_policy,
        )
        result.current_price = self._resolve_execution_price(
            enhanced_context=enhanced_context,
            execution_price_policy=execution_price_policy,
        )
        result.execution_price_source = self._resolve_execution_price_source(
            enhanced_context=enhanced_context,
            execution_price_policy=execution_price_policy,
        )

    def _resolve_runtime_execution_price_policy(
        self,
        *,
        execution_price_policy: str,
    ) -> str:
        """Apply market-window overrides to the configured execution price policy."""
        policy = str(execution_price_policy or "").strip().lower()
        if policy != "realtime_if_available":
            return policy

        if is_pre_market_open(
            getattr(self, "_now_for_testing", None),
            calendar=getattr(self.config, "market_calendar", "ASX"),
            market_timezone=getattr(self.config, "market_timezone", "Australia/Sydney"),
        ):
            return "close_only"
        return policy

    def _apply_validation_gate(
        self,
        *,
        result: AnalysisResult,
        enhanced_context: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> None:
        apply_pipeline_validation_gate(
            logger=logger,
            result=result,
            enhanced_context=enhanced_context,
            market_timezone=getattr(self.config, "market_timezone", "Australia/Sydney"),
            market_calendar=getattr(self.config, "market_calendar", "ASX"),
            query_id=getattr(self, "query_id", None),
            now=now,
            load_portfolio_state=self._load_existing_portfolio_state,
        )

    def _load_existing_portfolio_state(
        self,
        *,
        result: AnalysisResult,
    ) -> Optional[Dict[str, float]]:
        db = getattr(self, "db", None)
        if db is None:
            return None
        try:
            latest_snapshot = db.get_latest_account_snapshot()
            code = canonical_stock_code(result.code)
            existing = db.get_portfolio_position_by_alias(code)
            open_positions = db.get_portfolio_positions(only_open=True)
            return self._build_live_portfolio_state(
                code=code,
                existing=existing,
                open_positions=open_positions,
                latest_snapshot=latest_snapshot,
                current_price=getattr(result, "current_price", None),
            )
        except Exception:
            logger.exception("[%s] failed to load existing portfolio state for blocked validation", result.code)
            return None

    @staticmethod
    def _resolve_execution_price(
        *,
        enhanced_context: Dict[str, Any],
        execution_price_policy: str = "realtime_if_available",
    ) -> Optional[float]:
        """Resolve executable price for position sizing.

        Priority:
        1) realtime quote price
        2) today's close from context
        """
        policy = str(execution_price_policy or "").strip().lower()
        candidates: List[Any] = []
        realtime = enhanced_context.get("realtime") if isinstance(enhanced_context, dict) else None
        if policy != "close_only" and isinstance(realtime, dict):
            candidates.append(realtime.get("price"))
        today = enhanced_context.get("today") if isinstance(enhanced_context, dict) else None
        if isinstance(today, dict):
            candidates.append(today.get("close"))

        for value in candidates:
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
        return None

    @staticmethod
    def _resolve_execution_price_source(
        *,
        enhanced_context: Dict[str, Any],
        execution_price_policy: str = "realtime_if_available",
    ) -> str:
        """Resolve execution price basis: realtime / latest_close / close_only."""
        policy = str(execution_price_policy or "").strip().lower()
        if policy == "close_only":
            return "close_only"

        realtime = enhanced_context.get("realtime") if isinstance(enhanced_context, dict) else None
        if isinstance(realtime, dict):
            try:
                if float(realtime.get("price")) > 0:
                    return "realtime"
            except (TypeError, ValueError):
                pass

        today = enhanced_context.get("today") if isinstance(enhanced_context, dict) else None
        if isinstance(today, dict):
            try:
                if float(today.get("close")) > 0:
                    return "latest_close"
            except (TypeError, ValueError):
                pass

        return "close_only"

    def _apply_position_management(
        self,
        *,
        result: AnalysisResult,
        query_id: str,
        current_price: Optional[float],
        persist: bool = True,
    ) -> None:
        result.code = canonical_stock_code(result.code)
        if str(getattr(result, "event_risk", "") or "").upper() == "HIGH" and str(
            getattr(result, "final_decision", "") or ""
        ).upper() in {"BUY", "SELL"}:
            result.final_decision = "HOLD"
            note = "高事件风险，可执行动作已降级为仅观察"
            if note not in (result.risk_warning or ""):
                result.risk_warning = f"{result.risk_warning}；{note}" if result.risk_warning else note
        if persist:
            with self.db.get_portfolio_write_lock():
                self._apply_position_management_unlocked(
                    result=result,
                    query_id=query_id,
                    current_price=current_price,
                    persist=persist,
                )
            return

        self._apply_position_management_unlocked(
            result=result,
            query_id=query_id,
            current_price=current_price,
            persist=persist,
        )

    def _apply_position_management_unlocked(
        self,
        *,
        result: AnalysisResult,
        query_id: str,
        current_price: Optional[float],
        persist: bool = True,
    ) -> None:
        result.code = canonical_stock_code(result.code)
        if not persist:
            latest_snapshot = self.db.get_latest_account_snapshot()
            existing = self.db.get_portfolio_position_by_alias(result.code)
            open_positions = self.db.get_portfolio_positions(only_open=True)
            portfolio_state = self._build_live_portfolio_state(
                code=result.code,
                existing=existing,
                open_positions=open_positions,
                latest_snapshot=latest_snapshot,
                current_price=current_price,
            )
            decision = self.position_manager.decide(
                current_weight=portfolio_state["current_weight"],
                avg_cost=portfolio_state["avg_cost"],
                available_cash=portfolio_state["cash"],
                total_value=portfolio_state["total_value"],
                final_decision=result.final_decision,
                market_regime=result.market_regime,
                event_risk=result.event_risk,
                data_quality_flag=result.data_quality_flag,
            )
            calc = self._calculate_position_transition(
                existing=existing,
                quantity=portfolio_state["quantity"],
                current_weight=portfolio_state["current_weight"],
                decision=decision,
                cash=portfolio_state["cash"],
                total_value=portfolio_state["total_value"],
                current_price=current_price,
                current_value=portfolio_state["current_position_value"],
                min_delta_amount=self._get_min_position_delta_amount(),
                min_order_notional=self._get_min_order_notional(),
            )
            if calc is None:
                result.position_action = "HOLD"
                result.current_weight = round(portfolio_state["current_weight"], 4)
                result.target_weight = round(portfolio_state["current_weight"], 4)
                result.delta_amount = 0.0
                result.action_reason = f"{decision.reason}, execution_blocked=price_unavailable"
                logger.warning("[%s] 仓位管理跳过：缺少可执行价格，保持账户状态不变", result.code)
                return
            result.position_action = calc["action"]
            result.target_quantity = calc["target_quantity"]
            result.current_weight = round(portfolio_state["current_weight"], 4)
            result.target_weight = (
                round(calc["target_value"] / portfolio_state["total_value"], 4)
                if portfolio_state["total_value"] > 0
                else 0.0
            )
            result.delta_amount = calc["delta_amount"]
            result.action_reason = (
                f"{decision.reason}, execution_blocked={calc['suppressed_by']}"
                if calc.get("suppressed_by")
                else decision.reason
            )
            logger.info("[%s] 分析只读模式：仅计算仓位建议，不写入账户状态", result.code)
            return

        session = None
        try:
            # 复合写入在单一事务内完成，并通过 SQLite BEGIN IMMEDIATE 先拿写锁，
            # 防止并发写路径基于同一旧快照计算后覆盖，造成 cash/equity/total 漂移。
            with self.db.get_session() as session:
                self.db.begin_portfolio_write_transaction(session)
                latest_snapshot = self.db.get_latest_account_snapshot_in_session(session)
                existing = self.db.get_portfolio_position_by_alias_in_session(session, result.code)
                open_positions = self.db.get_open_portfolio_positions_in_session(session)
                portfolio_state = self._build_live_portfolio_state(
                    code=result.code,
                    existing=existing,
                    open_positions=open_positions,
                    latest_snapshot=latest_snapshot,
                    current_price=current_price,
                )
                decision = self.position_manager.decide(
                    current_weight=portfolio_state["current_weight"],
                    avg_cost=portfolio_state["avg_cost"],
                    available_cash=portfolio_state["cash"],
                    total_value=portfolio_state["total_value"],
                    final_decision=result.final_decision,
                    market_regime=result.market_regime,
                    event_risk=result.event_risk,
                    data_quality_flag=result.data_quality_flag,
                )
                calc = self._calculate_position_transition(
                    existing=existing,
                    quantity=portfolio_state["quantity"],
                    current_weight=portfolio_state["current_weight"],
                    decision=decision,
                    cash=portfolio_state["cash"],
                    total_value=portfolio_state["total_value"],
                    current_price=current_price,
                    current_value=portfolio_state["current_position_value"],
                    min_delta_amount=self._get_min_position_delta_amount(),
                    min_order_notional=self._get_min_order_notional(),
                )
                if calc is None:
                    result.position_action = "HOLD"
                    result.current_weight = round(portfolio_state["current_weight"], 4)
                    result.target_weight = round(portfolio_state["current_weight"], 4)
                    result.delta_amount = 0.0
                    result.action_reason = f"{decision.reason}, execution_blocked=price_unavailable"
                    logger.warning("[%s] 仓位管理跳过：缺少可执行价格，保持账户状态不变", result.code)
                    return
                result.position_action = calc["action"]
                result.target_quantity = calc["target_quantity"]
                result.current_weight = round(portfolio_state["current_weight"], 4)
                result.target_weight = (
                    round(calc["target_value"] / portfolio_state["total_value"], 4)
                    if portfolio_state["total_value"] > 0
                    else 0.0
                )
                result.delta_amount = calc["delta_amount"]
                result.action_reason = (
                    f"{decision.reason}, execution_blocked={calc['suppressed_by']}"
                    if calc.get("suppressed_by")
                    else decision.reason
                )

                self.db.upsert_portfolio_position_in_session(
                    session=session,
                    code=result.code,
                    name=result.name,
                    quantity=calc["target_quantity"],
                    avg_cost=(
                        portfolio_state["avg_cost"]
                        if portfolio_state["quantity"] > 0
                        else (calc["price"] if calc["target_quantity"] > 0 else 0.0)
                    ),
                    current_price=calc["price"] or None,
                    weight=result.target_weight,
                    market_value=calc["target_value"],
                )
                self.db.save_trade_journal_in_session(
                    session=session,
                    query_id=query_id,
                    code=result.code,
                    action_date=date.today(),
                    action=calc["action"],
                    final_decision=result.final_decision,
                    market_regime=result.market_regime,
                    event_risk=result.event_risk,
                    data_quality_flag=result.data_quality_flag,
                    current_weight=portfolio_state["current_weight"],
                    target_weight=result.target_weight,
                    delta_amount=calc["delta_amount"],
                    current_quantity=portfolio_state["quantity"],
                    target_quantity=calc["target_quantity"],
                    current_price=calc["price"] or None,
                    available_cash_before=portfolio_state["cash"],
                    available_cash_after=calc["cash_after"],
                    reason=result.action_reason,
                )
                session.flush()
                open_positions = self.db.get_open_portfolio_positions_in_session(session)
                equity_value = round(sum(float(p.market_value or 0.0) for p in open_positions), 2)
                total_value_after = round(calc["cash_after"] + equity_value, 2)
                self.db.save_account_snapshot_in_session(
                    session=session,
                    snapshot_date=date.today(),
                    cash=calc["cash_after"],
                    equity_value=max(equity_value, 0.0),
                    total_value=max(total_value_after, 0.0),
                    note="updated_by_position_manager",
                )
                session.commit()
        except Exception:
            if session is not None:
                session.rollback()
            logger.exception("[%s] 仓位管理事务提交失败，已回滚", result.code)
            raise

    @staticmethod
    def _calculate_position_transition(
        *,
        existing,
        quantity: float,
        current_weight: float,
        decision,
        cash: float,
        total_value: float,
        current_price: Optional[float],
        current_value: Optional[float] = None,
        min_delta_amount: float = 0.0,
        min_order_notional: float = 0.0,
    ) -> Optional[Dict[str, float | str]]:
        # Deterministic precedence order for executable sizing:
        # 1) normalize executable sizing to whole shares
        # 2) compute delta/notional from normalized values
        # 3) apply affordability safeguard (floor, never round-up)
        # 4) apply MIN_POSITION_DELTA_AMOUNT
        # 5) apply MIN_ORDER_NOTIONAL
        # 6) if blocked, suppress to HOLD/no-action with consistent accounting fields
        price = float(current_price) if current_price and current_price > 0 else 0.0
        if price <= 0 and existing and existing.current_price and existing.current_price > 0:
            price = float(existing.current_price)
        if price <= 0:
            return None

        current_value = float(current_value or 0.0)
        target_value = decision.target_weight * total_value
        target_quantity = int(round(target_value / price, 0))
        delta_amount = round(target_quantity * price - current_value, 2)
        cash_after = round(cash - delta_amount, 2)
        if cash_after < 0:
            affordable_target_value = current_value + cash
            target_quantity = int(math.floor(max(affordable_target_value, 0.0) / price))
            target_value = round(target_quantity * price, 2)
            delta_amount = round(target_value - current_value, 2)
            cash_after = round(cash - delta_amount, 2)
            if cash_after < 0:
                max_affordable_delta_shares = int(math.floor(max(cash, 0.0) / price))
                current_quantity = float(quantity or 0.0)
                affordable_quantity = min(target_quantity, int(math.floor(current_quantity + max_affordable_delta_shares)))
                target_quantity = max(affordable_quantity, 0)
                target_value = round(target_quantity * price, 2)
                delta_amount = round(target_value - current_value, 2)
                cash_after = round(cash - delta_amount, 2)
                if cash_after < 0:
                    cash_after = 0.0
        else:
            target_value = round(target_quantity * price, 2)

        if target_quantity < 0:
            target_quantity = 0
            target_value = 0.0
            delta_amount = round(-current_value, 2)
            cash_after = round(cash - delta_amount, 2)

        if quantity <= 0 and target_quantity > 0:
            action = "OPEN"
        elif quantity > 0 and target_quantity <= 0:
            action = "CLOSE"
        elif target_quantity > quantity:
            action = "ADD"
        elif target_quantity < quantity:
            action = "REDUCE"
        else:
            action = "HOLD"

        suppressed_by = None
        order_notional = round(abs(target_quantity - quantity) * price, 2)
        if action != "HOLD" and abs(delta_amount) < max(min_delta_amount, 0.0):
            suppressed_by = "min_delta_amount"
        if (
            action != "HOLD"
            and suppressed_by is None
            and order_notional < max(min_order_notional, 0.0)
        ):
            suppressed_by = "min_order_notional"
        if suppressed_by:
            logger.info(
                "仓位调整被抑制: constraint=%s, action=%s, abs_delta_amount=%.2f, order_notional=%.2f",
                suppressed_by,
                action,
                abs(delta_amount),
                order_notional,
            )
            target_quantity = float(quantity or 0.0)
            target_value = round(current_value, 2)
            delta_amount = 0.0
            cash_after = round(cash, 2)
            action = "HOLD"

        return {
            "price": price,
            "current_value": current_value,
            "target_value": target_value,
            "target_quantity": target_quantity,
            "delta_amount": delta_amount,
            "cash_after": cash_after,
            "action": action,
            "current_weight": current_weight,
            "suppressed_by": suppressed_by,
        }

    def _get_min_position_delta_amount(self) -> float:
        config = getattr(self, "config", None)
        if config is None:
            return 0.0
        return max(float(getattr(config, "min_position_delta_amount", 0.0) or 0.0), 0.0)

    def _get_min_order_notional(self) -> float:
        config = getattr(self, "config", None)
        if config is None:
            return 0.0
        return max(float(getattr(config, "min_order_notional", 0.0) or 0.0), 0.0)

    @staticmethod
    def _build_live_portfolio_state(
        *,
        code: str,
        existing,
        open_positions: List[Any],
        latest_snapshot,
        current_price: Optional[float],
    ) -> Dict[str, float]:
        cash = float(latest_snapshot.cash) if latest_snapshot else 10000.0
        cash = max(cash, 0.0)
        quantity = float(existing.quantity) if existing else 0.0
        avg_cost = float(existing.avg_cost) if existing else 0.0
        current_symbol_price = float(current_price) if current_price and current_price > 0 else 0.0
        if current_symbol_price <= 0 and existing and existing.current_price and existing.current_price > 0:
            current_symbol_price = float(existing.current_price)

        current_position_value = quantity * current_symbol_price if quantity > 0 and current_symbol_price > 0 else 0.0
        if current_position_value <= 0 and existing and quantity > 0:
            fallback_market_value = float(existing.market_value or 0.0)
            if fallback_market_value > 0:
                current_position_value = fallback_market_value

        current_equity_value = 0.0
        for position in open_positions or []:
            position_quantity = float(position.quantity or 0.0)
            if position_quantity <= 0:
                continue
            position_price = 0.0
            if position.code == code and current_symbol_price > 0:
                position_price = current_symbol_price
            elif position.current_price and float(position.current_price) > 0:
                position_price = float(position.current_price)
            position_value = position_quantity * position_price if position_price > 0 else float(position.market_value or 0.0)
            current_equity_value += max(position_value, 0.0)

        snapshot_equity = float(latest_snapshot.equity_value) if latest_snapshot else 0.0
        snapshot_total = float(latest_snapshot.total_value) if latest_snapshot else 0.0
        if current_equity_value <= 0 and snapshot_equity > 0:
            current_equity_value = snapshot_equity

        current_total_value = cash + current_equity_value
        if current_total_value <= 0 and snapshot_total > 0:
            current_total_value = snapshot_total
        if current_total_value <= 0:
            current_total_value = max(cash, 10000.0)
        current_weight = current_position_value / current_total_value if current_total_value > 0 else 0.0

        return {
            "cash": cash,
            "quantity": quantity,
            "avg_cost": avg_cost,
            "current_position_value": round(current_position_value, 2),
            "current_equity_value": round(current_equity_value, 2),
            "total_value": round(current_total_value, 2),
            "current_weight": round(current_weight, 6),
        }
    
    def _enhance_context(
        self,
        context: Dict[str, Any],
        realtime_quote,
        trend_result: Optional[TrendAnalysisResult],
        stock_name: str = ""
    ) -> Dict[str, Any]:
        """
        增强分析上下文
        
        将实时行情、趋势分析结果、股票名称添加到上下文中
        
        Args:
            context: 原始上下文
            realtime_quote: 实时行情数据（UnifiedRealtimeQuote 或 None）
            trend_result: 趋势分析结果
            stock_name: 股票名称
            
        Returns:
            增强后的上下文
        """
        enhanced = context.copy()

        execution_price_policy = str(
            getattr(self.config, "execution_price_policy", "close_only")
        ).strip().lower()
        enhanced["execution_price_policy"] = self._resolve_runtime_execution_price_policy(
            execution_price_policy=execution_price_policy,
        )
        
        # 添加股票名称
        if stock_name:
            enhanced['stock_name'] = stock_name
        elif realtime_quote and getattr(realtime_quote, 'name', None):
            enhanced['stock_name'] = realtime_quote.name
        
        # 添加实时行情（兼容不同数据源的字段差异）
        if realtime_quote:
            # 使用 getattr 安全获取字段，缺失字段返回 None 或默认值
            volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
            enhanced['realtime'] = {
                'name': getattr(realtime_quote, 'name', ''),
                'price': getattr(realtime_quote, 'price', None),
                'change_pct': getattr(realtime_quote, 'change_pct', None),
                'volume_ratio': volume_ratio,
                'volume_ratio_desc': self._describe_volume_ratio(volume_ratio) if volume_ratio else '无数据',
                'turnover_rate': getattr(realtime_quote, 'turnover_rate', None),
                'pe_ratio': getattr(realtime_quote, 'pe_ratio', None),
                'pb_ratio': getattr(realtime_quote, 'pb_ratio', None),
                'total_mv': getattr(realtime_quote, 'total_mv', None),
                'circ_mv': getattr(realtime_quote, 'circ_mv', None),
                'change_60d': getattr(realtime_quote, 'change_60d', None),
                'source': getattr(realtime_quote, 'source', None),
            }
            # 移除 None 值以减少上下文大小
            enhanced['realtime'] = {k: v for k, v in enhanced['realtime'].items() if v is not None}
        
        # 添加趋势分析结果
        if trend_result:
            enhanced['trend_analysis'] = {
                'trend_status': trend_result.trend_status.value,
                'ma_alignment': trend_result.ma_alignment,
                'trend_strength': trend_result.trend_strength,
                'ma5': trend_result.ma5,
                'ma10': trend_result.ma10,
                'ma20': trend_result.ma20,
                'atr': getattr(trend_result, 'atr', None),
                'bias_ma5': trend_result.bias_ma5,
                'bias_ma10': trend_result.bias_ma10,
                'volume_status': trend_result.volume_status.value,
                'volume_trend': trend_result.volume_trend,
                'buy_signal': trend_result.buy_signal.value,
                'signal_score': trend_result.signal_score,
                'signal_reasons': trend_result.signal_reasons,
                'risk_factors': trend_result.risk_factors,
            }

        enhanced["analysis_context_pack"] = build_analysis_context_pack(
            enhanced,
            stock_name=enhanced.get("stock_name"),
            report_date=enhanced.get("report_date") or enhanced.get("date"),
        ).to_dict()
        
        return enhanced
    
    def _describe_volume_ratio(self, volume_ratio: float) -> str:
        """
        量比描述
        
        量比 = 当前成交量 / 过去5日平均成交量
        """
        if volume_ratio < 0.5:
            return "极度萎缩"
        elif volume_ratio < 0.8:
            return "明显萎缩"
        elif volume_ratio < 1.2:
            return "正常"
        elif volume_ratio < 2.0:
            return "温和放量"
        elif volume_ratio < 3.0:
            return "明显放量"
        else:
            return "巨量"

    def _build_context_snapshot(
        self,
        enhanced_context: Dict[str, Any],
        news_content: Optional[str],
        realtime_quote: Any
    ) -> Dict[str, Any]:
        """
        构建分析上下文快照
        """
        return {
            "enhanced_context": enhanced_context,
            "news_content": news_content,
            "realtime_quote_raw": self._safe_to_dict(realtime_quote),
        }

    @staticmethod
    def _safe_to_dict(value: Any) -> Optional[Dict[str, Any]]:
        """
        安全转换为字典
        """
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return None
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                return None
        return None

    def _resolve_query_source(self, query_source: Optional[str]) -> str:
        """
        解析请求来源。

        优先级（从高到低）：
        1. 显式传入的 query_source：调用方明确指定时优先使用，便于覆盖推断结果或兼容未来 source_message 来自非 bot 的场景
        2. 存在 source_message 时推断为 "bot"：当前约定为机器人会话上下文
        3. 存在 query_id 时推断为 "web"：Web 触发的请求会带上 query_id
        4. 默认 "system"：定时任务或 CLI 等无上述上下文时

        Args:
            query_source: 调用方显式指定的来源，如 "bot" / "web" / "cli" / "system"

        Returns:
            归一化后的来源标识字符串，如 "bot" / "web" / "cli" / "system"
        """
        if query_source:
            return query_source
        if self.source_message:
            return "bot"
        if self.query_id:
            return "web"
        return "system"

    def _build_query_context(self, query_id: Optional[str] = None) -> Dict[str, str]:
        """
        生成用户查询关联信息
        """
        effective_query_id = query_id or self.query_id or ""

        context: Dict[str, str] = {
            "query_id": effective_query_id,
            "query_source": self.query_source or "",
        }

        if self.source_message:
            context.update({
                "requester_platform": self.source_message.platform or "",
                "requester_user_id": self.source_message.user_id or "",
                "requester_user_name": self.source_message.user_name or "",
                "requester_chat_id": self.source_message.chat_id or "",
                "requester_message_id": self.source_message.message_id or "",
                "requester_query": self.source_message.content or "",
            })

        return context
    
    def process_single_stock(
        self,
        code: str,
        skip_analysis: bool = False,
        single_stock_notify: bool = False,
        report_type: ReportType = ReportType.SIMPLE,
        analysis_query_id: Optional[str] = None,
        market_overview: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> Optional[AnalysisResult]:
        """
        处理单只股票的完整流程

        包括：
        1. 获取数据
        2. 保存数据
        3. AI 分析
        4. 单股推送（可选，#55）

        此方法会被线程池调用，需要处理好异常

        Args:
            analysis_query_id: 查询链路关联 id
            code: 股票代码
            skip_analysis: 是否跳过 AI 分析
            single_stock_notify: 是否启用单股推送模式（每分析完一只立即推送）
            report_type: 报告类型枚举（从配置读取，Issue #119）
            force_refresh: 是否强制刷新行情缓存

        Returns:
            AnalysisResult 或 None
        """
        code = canonical_stock_code(code)
        logger.info(f"========== 开始处理 {code} ==========")
        
        try:
            # Step 1: 获取并保存数据
            success, error, df_attrs = self.fetch_and_save_stock_data(code, force_refresh=force_refresh)
            
            if not success:
                logger.warning(f"[{code}] 数据获取失败: {error}")
                # 即使获取失败，也尝试用已有数据分析
            
            # Step 2: AI 分析
            if skip_analysis:
                logger.info(f"[{code}] 跳过 AI 分析（dry-run 模式）")
                return None
            
            effective_query_id = analysis_query_id or self.query_id or uuid.uuid4().hex
            result = self.analyze_stock(
                code,
                report_type,
                query_id=effective_query_id,
                df_attrs=df_attrs,
                market_overview=market_overview,
                force_refresh=force_refresh,
            )
            
            if result:
                logger.info(
                    f"[{code}] 分析完成: {result.operation_advice}, "
                    f"评分 {result.sentiment_score}"
                )
                
                # 单股推送模式（#55）：每分析完一只股票立即推送
                if single_stock_notify and self.notifier.is_available():
                    try:
                        if send_single_stock_notification(
                            notifier=self.notifier,
                            result=result,
                            report_type=report_type,
                            code=code,
                            logger=logger,
                        ):
                            logger.info(f"[{code}] 单股推送成功")
                        else:
                            logger.warning(f"[{code}] 单股推送失败")
                    except Exception as e:
                        logger.error(f"[{code}] 单股推送异常: {e}")
            
            return result
            
        except Exception as e:
            # 捕获所有异常，确保单股失败不影响整体
            logger.exception(f"[{code}] 处理过程发生未知异常: {e}")
            return None
    
    def _fetch_market_overview(self) -> dict:
        """
        复用 MarketAnalyzer._get_main_indices() 拉取大盘数据，
        转换为 {名称: {close, pct_chg, trend}} 格式注入个股 context。
        """
        try:
            from src.market_analyzer import MarketAnalyzer
            ma = MarketAnalyzer()
            indices = ma._get_main_indices()
            overview = {}
            for idx in indices:
                pct = round(idx.change_pct, 2) if idx.change_pct is not None else None
                overview[idx.name] = {
                    'close': round(idx.current, 2),
                    'pct_chg': pct,
                    'trend': '📈' if (pct or 0) > 0 else ('📉' if (pct or 0) < 0 else '➡️'),
                    'data_date': getattr(idx, 'data_date', ''),
                    'source_basis': getattr(idx, 'source_basis', ''),
                }
            if overview:
                logger.info(f"[大盘] 已获取 {len(overview)} 个指标（复用 MarketAnalyzer）")
            return overview
        except Exception as e:
            logger.warning(f"[大盘] 大盘数据获取失败（已跳过）: {e}")
            return {}

    def run(
        self,
        stock_codes: Optional[List[str]] = None,
        dry_run: bool = False,
        send_notification: bool = True,
        merge_notification: bool = False
    ) -> List[AnalysisResult]:
        """
        运行完整的分析流程

        流程：
        1. 获取待分析的股票列表
        2. 使用线程池并发处理
        3. 收集分析结果
        4. 发送通知

        Args:
            stock_codes: 股票代码列表（可选，默认使用配置中的自选股）
            dry_run: 是否仅获取数据不分析
            send_notification: 是否发送推送通知
            merge_notification: 是否合并推送（跳过本次推送，由 main 层合并个股+大盘后统一发送，Issue #190）

        Returns:
            分析结果列表
        """
        start_time = time.time()
        
        # 使用配置中的股票列表
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        stock_codes = canonical_stock_codes(stock_codes)
        
        if not stock_codes:
            logger.error("未配置自选股列表，请在 .env 文件中设置 STOCK_LIST")
            return []
        
        logger.info(f"===== 开始分析 {len(stock_codes)} 只股票 =====")
        logger.info(f"股票列表: {', '.join(stock_codes)}")
        logger.info(f"并发数: {self.max_workers}, 模式: {'仅获取数据' if dry_run else '完整分析'}")
        
        # === 抓取大盘宏观数据（一次性，共享给所有股票）===
        market_overview = self._fetch_market_overview()
        if market_overview:
            # 找 ASX200 数据（key 可能是 "ASX 200 (看点位)" 或 "ASX200"）
            asx_data = market_overview.get('ASX200') or market_overview.get('ASX 200 (看点位)') or {}
            logger.info(f"[大盘] ASX200: {asx_data.get('close', 'N/A')} ({asx_data.get('pct_chg', 'N/A')}%)")

        # === 批量预取实时行情（优化：避免每只股票都触发全量拉取）===
        # 只有股票数量 >= 5 时才进行预取，少量股票直接逐个查询更高效
        if len(stock_codes) >= 5:
            prefetch_count = self.fetcher_manager.prefetch_realtime_quotes(stock_codes)
            if prefetch_count > 0:
                logger.info(f"已启用批量预取架构：一次拉取全市场数据，{len(stock_codes)} 只股票共享缓存")
        
        # 单股推送模式（#55）：从配置读取
        single_stock_notify = getattr(self.config, 'single_stock_notify', False)
        # Issue #119: 从配置读取报告类型
        report_type_str = getattr(self.config, 'report_type', ReportType.SIMPLE.value)
        report_type = ReportType.normalize(report_type_str)
        # Issue #128: 从配置读取分析间隔
        analysis_delay = getattr(self.config, 'analysis_delay', 0)

        if single_stock_notify:
            logger.info(f"已启用单股推送模式：每分析完一只股票立即推送（报告类型: {report_type_str}）")
        
        results: List[AnalysisResult] = []
        
        # 使用线程池并发处理
        # 注意：max_workers 设置较低（默认3）以避免触发反爬
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交任务
            future_to_code = {
                executor.submit(
                    self.process_single_stock,
                    code,
                    skip_analysis=dry_run,
                    single_stock_notify=single_stock_notify and send_notification,
                    report_type=report_type,  # Issue #119: 传递报告类型
                    analysis_query_id=uuid.uuid4().hex,
                    market_overview=market_overview,
                ): code
                for code in stock_codes
            }
            
            # 收集结果
            for idx, future in enumerate(as_completed(future_to_code)):
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)

                    # Issue #128: 分析间隔 - 在个股分析和大盘分析之间添加延迟
                    if idx < len(stock_codes) - 1 and analysis_delay > 0:
                        logger.debug(f"等待 {analysis_delay} 秒后继续下一只股票...")
                        time.sleep(analysis_delay)

                except Exception as e:
                    logger.error(f"[{code}] 任务执行失败: {e}")
        
        # 统计
        elapsed_time = time.time() - start_time
        
        # dry-run 模式下，数据获取成功即视为成功
        if dry_run:
            # 检查哪些股票的数据今天已存在
            cache_date = _market_report_date_safe(self.config)
            success_count = sum(1 for code in stock_codes if self.db.has_today_data(code, cache_date))
            fail_count = len(stock_codes) - success_count
        else:
            success_count = len(results)
            fail_count = len(stock_codes) - success_count
        
        logger.info("===== 分析完成 =====")
        logger.info(f"成功: {success_count}, 失败: {fail_count}, 耗时: {elapsed_time:.2f} 秒")

        if results and not dry_run:
            self._apply_paper_portfolio_simulation(results)
        
        # 发送通知（单股推送模式下跳过汇总推送，避免重复）
        if results and send_notification and not dry_run:
            if single_stock_notify:
                # 单股推送模式：只保存汇总报告，不再重复推送
                logger.info("单股推送模式：跳过汇总推送，仅保存报告到本地")
                self._send_notifications(results, skip_push=True)
            elif merge_notification:
                # 合并模式（Issue #190）：仅保存，不推送，由 main 层合并个股+大盘后统一发送
                logger.info("合并推送模式：跳过本次推送，将在个股+大盘复盘后统一发送")
                self._send_notifications(results, skip_push=True)
            else:
                self._send_notifications(results)
        
        return results

    def _apply_paper_portfolio_simulation(
        self,
        results: List[AnalysisResult],
        *,
        simulation_time: Optional[datetime] = None,
    ) -> bool:
        """Persist today's recommendations into the independent paper ledger before reporting."""
        if not getattr(self.config, "paper_portfolio_auto_apply", True):
            logger.info("模拟盘自动执行已关闭，跳过写入 paper_portfolio 账本")
            return False
        if not results:
            return False

        sim_time = simulation_time
        if sim_time is None:
            sim_time = _now_in_timezone_safe(getattr(self.config, "market_timezone", DEFAULT_MARKET_TIMEZONE))

        try:
            overview = self.db.get_paper_portfolio_overview()
        except Exception as exc:
            logger.warning("读取模拟盘状态失败，跳过模拟执行: %s", exc)
            return False

        if not bool(overview.get("initialized")):
            logger.warning("模拟盘尚未初始化，跳过模拟执行")
            return False

        last_simulation_time = overview.get("last_simulation_time")
        if last_simulation_time:
            try:
                last_dt = datetime.fromisoformat(str(last_simulation_time).replace("Z", "+00:00"))
                if last_dt.date() == sim_time.date():
                    logger.info("模拟盘今日已执行过（%s），跳过重复写入", last_simulation_time)
                    return False
            except Exception:
                logger.debug("无法解析模拟盘 last_simulation_time=%s，继续执行本次模拟", last_simulation_time)

        try:
            from src.services.paper_portfolio_service import PaperPortfolioService

            PaperPortfolioService(self.db).apply_analysis_results(results, simulation_time=sim_time)
            logger.info("模拟盘已按本次分析结果写入账本（%s 条结果）", len(results))
            return True
        except Exception as exc:
            logger.warning("模拟盘写入失败，报告将继续生成但不更新模拟账本: %s", exc)
            return False
    
    def _send_notifications(self, results: List[AnalysisResult], skip_push: bool = False) -> Dict[str, Any]:
        """
        发送分析结果通知
        
        生成决策仪表盘格式的报告
        
        Args:
            results: 分析结果列表
            skip_push: 是否跳过推送（仅保存到本地，用于单股推送模式）
        """
        delivery_health: Dict[str, Any] = {
            "report_saved": False,
            "html_saved": False,
            "json_saved": False,
            "notification_attempted": False,
            "notification_failed": False,
            "notification_failure_stage": None,
            "notification_failure_message": None,
            "report_path": None,
            "html_path": None,
            "summary_path": None,
            "notification_channels": [],
        }
        notification_stage: Optional[str] = None
        try:
            logger.info("生成决策仪表盘日报...")

            # 生成组合层面 AI 总结（在个股报告前面）
            portfolio_summary_section = ""
            try:
                logger.info("生成组合决策总结...")
                portfolio_summary = self.analyzer.generate_portfolio_summary(results)
                if portfolio_summary:
                    report_day = _report_run_date_safe(self.config).isoformat()
                    invalid_snapshot_tokens = {"", "none", "null", "n/a", "unknown"}

                    def _normalize_snapshot_date(value: Any) -> Optional[str]:
                        raw = str(value or "").strip()
                        if raw.lower() in invalid_snapshot_tokens:
                            return None
                        try:
                            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
                        except Exception:
                            return None

                    snapshot_dates = sorted(
                        {
                            normalized_date
                            for r in results
                            for normalized_date in [
                                _normalize_snapshot_date((getattr(r, "market_snapshot", None) or {}).get("date"))
                            ]
                            if normalized_date
                        }
                    )
                    if len(snapshot_dates) == 1:
                        date_label = f"技术基准日 {snapshot_dates[0]}｜报告日 {report_day}"
                    elif snapshot_dates:
                        date_label = f"技术基准日 {snapshot_dates[0]}~{snapshot_dates[-1]}｜报告日 {report_day}"
                    else:
                        date_label = f"报告日 {report_day}"
                    portfolio_summary_section = "## 🎯 组合决策总结（" + date_label + "）\n\n" + portfolio_summary
                    logger.info("组合决策总结生成成功")
            except Exception as e:
                logger.warning(f"组合决策总结生成失败（已跳过）: {e}")

            # 生成决策仪表盘格式的详细日报
            report = self.notifier.generate_dashboard_report(
                results,
                portfolio_summary_section=portfolio_summary_section,
            )
            daily_summary = self.notifier.get_last_daily_decision_summary()
            report_date = str((daily_summary or {}).get("report_date") or "")
            
            # 保存到本地
            filepath = self.notifier.save_report_to_file(report, report_date=report_date or None)
            delivery_health["report_saved"] = True
            delivery_health["report_path"] = filepath
            logger.info(f"决策仪表盘日报已保存: {filepath}")
            try:
                html_path = self.notifier.save_report_archive_html(
                    report,
                    markdown_filepath=filepath,
                    report_date=report_date or None,
                )
                delivery_health["html_saved"] = True
                delivery_health["html_path"] = html_path
                logger.info(f"HTML归档日报已保存: {html_path}")
            except Exception as e:
                delivery_health["html_failed"] = True
                delivery_health["html_failure_message"] = str(e)
                logger.warning("日报HTML归档输出生成失败（Markdown 已保存）: %s", e, exc_info=True)

            if daily_summary:
                try:
                    summary_path = self.notifier.save_daily_decision_summary_to_file(daily_summary)
                    delivery_health["json_saved"] = True
                    delivery_health["summary_path"] = summary_path
                    logger.info(f"daily_decision_summary 已保存: {summary_path}")
                except Exception as e:
                    delivery_health["json_failed"] = True
                    delivery_health["json_failure_message"] = str(e)
                    logger.warning("daily_decision_summary 输出生成失败（Markdown 已保存）: %s", e, exc_info=True)
            else:
                delivery_health["json_failure_message"] = "daily_decision_summary unavailable"
            
            # 跳过推送（单股推送模式）
            if skip_push:
                return delivery_health
            
            # 推送通知
            if self.notifier.is_available():
                channels = self.notifier.get_available_channels()
                delivery_health["notification_attempted"] = True
                delivery_health["notification_channels"] = [
                    getattr(channel, "value", str(channel)) for channel in channels
                ]
                notification_stage = "context"
                context_success = self.notifier.send_to_context(report)

                # 企业微信：只发精简版（平台限制）
                wechat_success = False
                if NotificationChannel.WECHAT in channels:
                    notification_stage = "wechat"
                    dashboard_content = self.notifier.generate_wechat_dashboard(
                        results,
                        report_date=report_date or None,
                    )
                    logger.info(f"企业微信仪表盘长度: {len(dashboard_content)} 字符")
                    log_sensitive_payload(logger, logging.DEBUG, "企业微信推送内容", dashboard_content)
                    wechat_success = self.notifier.send_to_wechat(dashboard_content)

                # 其他渠道按各自口径发送；Email 使用精简正文，非 Email 保留完整报告。
                non_wechat_success = False
                stock_email_groups = getattr(self.config, 'stock_email_groups', []) or []
                for channel in channels:
                    if channel == NotificationChannel.WECHAT:
                        continue
                    if channel == NotificationChannel.FEISHU:
                        notification_stage = "feishu"
                        non_wechat_success = self.notifier.send_to_feishu(report) or non_wechat_success
                    elif channel == NotificationChannel.TELEGRAM:
                        notification_stage = "telegram"
                        non_wechat_success = self.notifier.send_to_telegram(report) or non_wechat_success
                    elif channel == NotificationChannel.EMAIL:
                        notification_stage = "email"
                        if stock_email_groups:
                            code_to_emails: Dict[str, Optional[List[str]]] = {}
                            for r in results:
                                if r.code not in code_to_emails:
                                    emails = []
                                    for stocks, emails_list in stock_email_groups:
                                        if r.code in stocks:
                                            emails.extend(emails_list)
                                    code_to_emails[r.code] = list(dict.fromkeys(emails)) if emails else None
                            emails_to_results: Dict[Optional[Tuple], List] = defaultdict(list)
                            for r in results:
                                recs = code_to_emails.get(r.code)
                                key = tuple(recs) if recs else None
                                emails_to_results[key].append(r)
                            for key, group_results in emails_to_results.items():
                                grp_report = self.notifier.generate_dashboard_report(
                                    group_results,
                                    report_date=report_date or None,
                                )
                                grp_email_report = self.notifier.build_email_report_body(grp_report)
                                if key is None:
                                    non_wechat_success = (
                                        self.notifier.send_to_email(grp_email_report) or non_wechat_success
                                    )
                                else:
                                    non_wechat_success = (
                                        self.notifier.send_to_email(grp_email_report, receivers=list(key))
                                        or non_wechat_success
                                    )
                        else:
                            email_report = self.notifier.build_email_report_body(report)
                            non_wechat_success = self.notifier.send_to_email(email_report) or non_wechat_success
                    elif channel == NotificationChannel.CUSTOM:
                        notification_stage = "custom"
                        non_wechat_success = self.notifier.send_to_custom(report) or non_wechat_success
                    elif channel == NotificationChannel.PUSHPLUS:
                        notification_stage = "pushplus"
                        non_wechat_success = self.notifier.send_to_pushplus(report) or non_wechat_success
                    elif channel == NotificationChannel.SERVERCHAN3:
                        notification_stage = "serverchan3"
                        non_wechat_success = self.notifier.send_to_serverchan3(report) or non_wechat_success
                    elif channel == NotificationChannel.DISCORD:
                        notification_stage = "discord"
                        non_wechat_success = self.notifier.send_to_discord(report) or non_wechat_success
                    elif channel == NotificationChannel.PUSHOVER:
                        notification_stage = "pushover"
                        non_wechat_success = self.notifier.send_to_pushover(report) or non_wechat_success
                    elif channel == NotificationChannel.ASTRBOT:
                        notification_stage = "astrbot"
                        non_wechat_success = self.notifier.send_to_astrbot(report) or non_wechat_success
                    else:
                        logger.warning(f"未知通知渠道: {channel}")

                success = wechat_success or non_wechat_success or context_success
                if success:
                    logger.info("决策仪表盘推送成功")
                else:
                    delivery_health["notification_failed"] = True
                    delivery_health["notification_failure_stage"] = notification_stage or "notification"
                    delivery_health[
                        "notification_failure_message"
                    ] = "all configured notification channels returned false"
                    logger.warning("决策仪表盘推送失败")
            else:
                logger.info("通知渠道未配置，跳过推送")
                
        except Exception as e:
            if delivery_health.get("notification_attempted"):
                delivery_health["notification_failed"] = True
                delivery_health["notification_failure_stage"] = notification_stage or "notification"
                delivery_health["notification_failure_message"] = str(e)
            else:
                delivery_health["report_generation_failed"] = True
                delivery_health["report_generation_failure_message"] = str(e)
            logger.error(
                "发送通知失败；日报交付健康检查失败: stage=%s health=%s",
                notification_stage or "report_generation",
                delivery_health,
                exc_info=True,
            )
        finally:
            logger.info(
                "日报交付健康检查: report_saved=%s html_saved=%s json_saved=%s "
                "notification_attempted=%s notification_failed=%s report_path=%s html_path=%s "
                "summary_path=%s failure_stage=%s",
                delivery_health.get("report_saved"),
                delivery_health.get("html_saved"),
                delivery_health.get("json_saved"),
                delivery_health.get("notification_attempted"),
                delivery_health.get("notification_failed"),
                delivery_health.get("report_path"),
                delivery_health.get("html_path"),
                delivery_health.get("summary_path"),
                delivery_health.get("notification_failure_stage"),
            )
        return delivery_health
