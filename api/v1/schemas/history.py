# -*- coding: utf-8 -*-
"""
===================================
历史记录相关模型
===================================

职责：
1. 定义历史记录列表和详情模型
2. 定义分析报告完整模型
"""

from typing import Optional, List, Any

from pydantic import BaseModel, Field


class HistoryItem(BaseModel):
    """历史记录摘要（列表展示用）"""

    query_id: str = Field(..., description="分析记录唯一标识")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    sentiment_score: Optional[int] = Field(
        None,
        description="情绪评分 (0-100)",
        ge=0,
        le=100,
    )
    operation_advice: Optional[str] = Field(None, description="操作建议")
    created_at: Optional[str] = Field(None, description="创建时间")

    class Config:
        json_schema_extra = {
            "example": {
                "query_id": "abc123",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "sentiment_score": 75,
                "operation_advice": "持有",
                "created_at": "2024-01-01T12:00:00",
            }
        }


class HistoryListResponse(BaseModel):
    """历史记录列表响应"""

    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    limit: int = Field(..., description="每页数量")
    items: List[HistoryItem] = Field(default_factory=list, description="记录列表")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 100,
                "page": 1,
                "limit": 20,
                "items": [],
            }
        }


class NewsIntelItem(BaseModel):
    """新闻情报条目"""

    title: str = Field(..., description="新闻标题")
    snippet: str = Field("", description="新闻摘要（最多200字）")
    url: str = Field(..., description="新闻链接")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "公司发布业绩快报，营收同比增长20%",
                "snippet": "公司公告显示，季度营收同比增长20%...",
                "url": "https://example.com/news/123",
            }
        }


class NewsIntelResponse(BaseModel):
    """新闻情报响应"""

    total: int = Field(..., description="新闻条数")
    items: List[NewsIntelItem] = Field(default_factory=list, description="新闻列表")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 2,
                "items": [],
            }
        }


class ReportMeta(BaseModel):
    """报告元信息"""

    query_id: str = Field(..., description="分析记录唯一标识")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    created_at: Optional[str] = Field(None, description="创建时间")
    current_price: Optional[float] = Field(None, description="分析时股价")
    change_pct: Optional[float] = Field(None, description="分析时涨跌幅(%)")
    analysis_status: Optional[str] = Field(None, description="外层分析状态(OK/DEGRADED/FAILED)")
    validation_status: Optional[str] = Field(None, description="决策验证状态(PASS/WARN/BLOCK)")


class ReportSummary(BaseModel):
    """报告概览区"""

    analysis_summary: Optional[str] = Field(None, description="关键结论")
    operation_advice: Optional[str] = Field(None, description="操作建议")
    analysis_status: Optional[str] = Field(None, description="外层分析状态(OK/DEGRADED/FAILED)")
    validation_status: Optional[str] = Field(None, description="决策验证状态(PASS/WARN/BLOCK)")
    validation_issues: Optional[List[str]] = Field(None, description="决策验证问题列表")
    trend_prediction: Optional[str] = Field(None, description="趋势预测")
    sentiment_score: Optional[int] = Field(
        None,
        description="情绪评分 (0-100)",
        ge=0,
        le=100,
    )
    sentiment_label: Optional[str] = Field(None, description="情绪标签")
    alpha_decision: Optional[str] = Field(None, description="规则层决策(BUY/HOLD/SELL)")
    final_decision: Optional[str] = Field(None, description="最终决策(BUY/HOLD/SELL)")
    position_action: Optional[str] = Field(None, description="仓位动作(OPEN/ADD/HOLD/REDUCE/CLOSE)")
    target_weight: Optional[float] = Field(None, description="目标仓位(0-1)")
    current_weight: Optional[float] = Field(None, description="当前仓位(0-1)")
    delta_amount: Optional[float] = Field(None, description="建议调仓金额")
    action_reason: Optional[str] = Field(None, description="仓位决策原因")
    watchlist_state: Optional[str] = Field(None, description="观察池状态(OBSERVE/ACTIVE/DROP)")
    market_regime: Optional[str] = Field(None, description="市场状态(RISK_ON/NEUTRAL/RISK_OFF)")
    news_sentiment: Optional[str] = Field(None, description="新闻情绪(POS/NEU/NEG)")
    event_risk: Optional[str] = Field(None, description="事件风险(LOW/MEDIUM/HIGH)")
    sector_tone: Optional[str] = Field(None, description="板块语气(POS/NEU/NEG)")
    data_quality_flag: Optional[str] = Field(None, description="数据质量闸门(OK/MISSING)")


class ReportStrategy(BaseModel):
    """策略点位区"""

    ideal_buy: Optional[str] = Field(None, description="理想买入价")
    secondary_buy: Optional[str] = Field(None, description="第二买入价")
    stop_loss: Optional[str] = Field(None, description="止损价")
    take_profit: Optional[str] = Field(None, description="止盈价")


class ReportDetails(BaseModel):
    """报告详情区"""

    news_content: Optional[str] = Field(None, description="新闻摘要")
    raw_result: Optional[Any] = Field(None, description="原始分析结果(JSON)")
    context_snapshot: Optional[Any] = Field(None, description="分析时上下文快照(JSON)")


class AnalysisReport(BaseModel):
    """完整分析报告"""

    meta: ReportMeta = Field(..., description="元信息")
    summary: ReportSummary = Field(..., description="概览区")
    strategy: Optional[ReportStrategy] = Field(None, description="策略点位区")
    details: Optional[ReportDetails] = Field(None, description="详情区")
    portfolio: Optional[Any] = Field(None, description="组合快照与持仓明细")

    class Config:
        json_schema_extra = {
            "example": {
                "meta": {
                    "query_id": "abc123",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "report_type": "detailed",
                    "created_at": "2024-01-01T12:00:00",
                    "validation_status": "PASS",
                },
                "summary": {
                    "analysis_summary": "技术面向好，建议持有",
                    "operation_advice": "持有",
                    "trend_prediction": "看多",
                    "sentiment_score": 75,
                    "sentiment_label": "乐观",
                    "validation_status": "PASS",
                    "validation_issues": [],
                },
                "strategy": {
                    "ideal_buy": "1800.00",
                    "secondary_buy": "1750.00",
                    "stop_loss": "1700.00",
                    "take_profit": "2000.00",
                },
                "details": None,
            }
        }
