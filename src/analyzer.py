# -*- coding: utf-8 -*-
"""
===================================
澳股自选股智能分析系统 - AI分析层
===================================

职责：
1. 封装 Gemini API 调用逻辑
2. 利用 Google Search Grounding 获取实时新闻
3. 结合技术面和消息面生成分析报告
"""

import json
import math
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from json_repair import repair_json
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.config import get_config

logger = logging.getLogger(__name__)


class CoreConclusionSchema(BaseModel):
    """dashboard.core_conclusion 最小结构约束。"""

    model_config = ConfigDict(extra="allow")
    one_sentence: str = Field(min_length=1)


class DashboardSchema(BaseModel):
    """dashboard 最小结构约束。"""

    model_config = ConfigDict(extra="allow")
    core_conclusion: CoreConclusionSchema
    data_perspective: Dict[str, Any]
    intelligence: Dict[str, Any]
    battle_plan: Dict[str, Any]

    @field_validator("data_perspective", "intelligence", "battle_plan")
    @classmethod
    def _validate_non_empty_obj(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("must be a non-empty object")
        return value


class AnalysisOutputSchema(BaseModel):
    """进入 AnalysisResult 前的结构化 schema gate。"""

    model_config = ConfigDict(extra="allow")
    stock_name: str = Field(min_length=1)
    sentiment_score: int = Field(ge=0, le=100)
    trend_prediction: str = Field(min_length=1)
    operation_advice: str = Field(min_length=1)
    confidence_level: str
    analysis_summary: str = Field(min_length=1)
    risk_warning: str = Field(min_length=1)
    dashboard: Optional[DashboardSchema] = None

    @field_validator("confidence_level")
    @classmethod
    def _validate_confidence_level(cls, value: str) -> str:
        if value not in {"高", "中", "低"}:
            raise ValueError("confidence_level must be one of: 高/中/低")
        return value


# 股票名称映射（常见股票）
STOCK_NAME_MAP = {
    # === 澳股 (ASX) ===
    'BHP.AX': '必和必拓',
    'CBA.AX': '澳洲联邦银行',
    'CSL.AX': 'CSL血浆',
    'FMG.AX': '福德斯克',
    'MQG.AX': '麦格理集团',
    'WBC.AX': '西太平洋银行',
    'ANZ.AX': '澳新银行',
    'NAB.AX': '国民银行',
    'WES.AX': '西农集团',
    'TLS.AX': '澳洲电讯',

    # === 美股 ===
    'AAPL': '苹果',
    'TSLA': '特斯拉',
    'MSFT': '微软',
    'GOOGL': '谷歌A',
    'GOOG': '谷歌C',
    'AMZN': '亚马逊',
    'NVDA': '英伟达',
    'META': 'Meta',
    'AMD': 'AMD',
    'INTC': '英特尔',
    'BABA': '阿里巴巴',
    'PDD': '拼多多',
    'JD': '京东',
    'BIDU': '百度',
    'NIO': '蔚来',
    'XPEV': '小鹏汽车',
    'LI': '理想汽车',
    'COIN': 'Coinbase',
    'MSTR': 'MicroStrategy',
}


def get_stock_name_multi_source(
    stock_code: str,
    context: Optional[Dict] = None,
    data_manager = None
) -> str:
    """
    多来源获取股票中文名称

    获取策略（按优先级）：
    1. 从传入的 context 中获取（realtime 数据）
    2. 从静态映射表 STOCK_NAME_MAP 获取
    3. 从 DataFetcherManager 获取（各数据源）
    4. 返回默认名称（股票+代码）

    Args:
        stock_code: 股票代码
        context: 分析上下文（可选）
        data_manager: DataFetcherManager 实例（可选）

    Returns:
        股票中文名称
    """
    # 1. 从上下文获取（实时行情数据）
    if context:
        # 优先从 stock_name 字段获取
        if context.get('stock_name'):
            name = context['stock_name']
            if name and not name.startswith('股票'):
                return name

        # 其次从 realtime 数据获取
        if 'realtime' in context and context['realtime'].get('name'):
            return context['realtime']['name']

    # 2. 从静态映射表获取
    if stock_code in STOCK_NAME_MAP:
        return STOCK_NAME_MAP[stock_code]

    # 3. 从数据源获取
    if data_manager is None:
        try:
            from data_provider.base import DataFetcherManager
            data_manager = DataFetcherManager()
        except Exception as e:
            logger.debug(f"无法初始化 DataFetcherManager: {e}")

    if data_manager:
        try:
            name = data_manager.get_stock_name(stock_code)
            if name:
                # 更新缓存
                STOCK_NAME_MAP[stock_code] = name
                return name
        except Exception as e:
            logger.debug(f"从数据源获取股票名称失败: {e}")

    # 4. 返回默认名称
    return f'股票{stock_code}'


@dataclass
class AnalysisResult:
    """
    AI 分析结果数据类 - 决策仪表盘版

    封装 Gemini 返回的分析结果，包含决策仪表盘和详细分析
    """
    code: str
    name: str

    # ========== 核心指标 ==========
    sentiment_score: int  # 综合评分 0-100 (>70强烈看多, >60看多, 40-60震荡, <40看空)
    trend_prediction: str  # 趋势预测：强烈看多/看多/震荡/看空/强烈看空
    operation_advice: str  # 操作建议：买入/加仓/持有/减仓/卖出/观望
    decision_type: str = "hold"  # 决策类型：buy/hold/sell（用于统计）
    confidence_level: str = "中"  # 置信度：高/中/低

    # ========== 决策结构（确定性主链）==========
    alpha_decision: str = "HOLD"       # BUY/HOLD/SELL（规则层）
    final_decision: str = "HOLD"       # BUY/HOLD/SELL（合成后）
    watchlist_state: str = "ACTIVE"    # OBSERVE/ACTIVE/DROP（独立于交易动作）
    market_regime: str = "NEUTRAL"     # RISK_ON/NEUTRAL/RISK_OFF（overlay）
    news_sentiment: str = "NEU"        # POS/NEU/NEG（overlay，稳定值）
    event_risk: str = "MEDIUM"         # LOW/MEDIUM/HIGH（overlay，稳定值）
    sector_tone: str = "NEU"           # POS/NEU/NEG（overlay，稳定值）
    data_quality_flag: str = "OK"      # OK/MISSING（gate）
    position_action: str = "HOLD"      # OPEN/ADD/HOLD/REDUCE/CLOSE
    target_weight: float = 0.0         # 目标仓位(0-1)
    current_weight: float = 0.0        # 当前仓位(0-1)
    delta_amount: float = 0.0          # 本次建议调仓金额(货币)
    action_reason: str = ""            # 持仓决策理由
    # 原始提取状态（允许 UNKNOWN；排错与复盘使用）
    news_sentiment_raw: str = "UNKNOWN"
    event_risk_raw: str = "UNKNOWN"
    sector_tone_raw: str = "UNKNOWN"

    # ========== 决策仪表盘 (新增) ==========
    dashboard: Optional[Dict[str, Any]] = None  # 完整的决策仪表盘数据

    # ========== 走势分析 ==========
    trend_analysis: str = ""  # 走势形态分析（支撑位、压力位、趋势线等）
    short_term_outlook: str = ""  # 短期展望（1-3日）
    medium_term_outlook: str = ""  # 中期展望（1-2周）

    # ========== 技术面分析 ==========
    technical_analysis: str = ""  # 技术指标综合分析
    ma_analysis: str = ""  # 均线分析（多头/空头排列，金叉/死叉等）
    volume_analysis: str = ""  # 量能分析（放量/缩量，主力动向等）
    pattern_analysis: str = ""  # K线形态分析

    # ========== 基本面分析 ==========
    fundamental_analysis: str = ""  # 基本面综合分析
    sector_position: str = ""  # 板块地位和行业趋势
    company_highlights: str = ""  # 公司亮点/风险点

    # ========== 情绪面/消息面分析 ==========
    news_summary: str = ""  # 近期重要新闻/公告摘要
    market_sentiment: str = ""  # 市场情绪分析
    hot_topics: str = ""  # 相关热点话题

    # ========== 综合分析 ==========
    analysis_summary: str = ""  # 综合分析摘要
    key_points: str = ""  # 核心看点（3-5个要点）
    risk_warning: str = ""  # 风险提示
    buy_reason: str = ""  # 买入/卖出理由

    # ========== 元数据 ==========
    market_snapshot: Optional[Dict[str, Any]] = None  # 当日行情快照（展示用）
    raw_response: Optional[str] = None  # 原始响应（调试用）
    search_performed: bool = False  # 是否执行了联网搜索
    data_sources: str = ""  # 数据来源说明
    success: bool = True
    analysis_status: str = "OK"  # OK/DEGRADED/FAILED
    error_message: Optional[str] = None

    # ========== 价格数据（分析时快照）==========
    current_price: Optional[float] = None  # 分析时的股价
    change_pct: Optional[float] = None     # 分析时的涨跌幅(%)
    realtime_price: Optional[float] = None  # 真实实时价格（若不可用则为 None）
    execution_price_source: str = "close_only"  # realtime | latest_close | close_only

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典以便最终推送"""
        return {
            'code': self.code,
            'name': self.name,
            'sentiment_score': self.sentiment_score,
            'trend_prediction': self.trend_prediction,
            'operation_advice': self.operation_advice,
            'decision_type': self.decision_type,
            'confidence_level': self.confidence_level,
            'alpha_decision': self.alpha_decision,
            'final_decision': self.final_decision,
            'watchlist_state': self.watchlist_state,
            'market_regime': self.market_regime,
            'news_sentiment': self.news_sentiment,
            'event_risk': self.event_risk,
            'sector_tone': self.sector_tone,
            'data_quality_flag': self.data_quality_flag,
            'position_action': self.position_action,
            'target_weight': self.target_weight,
            'current_weight': self.current_weight,
            'delta_amount': self.delta_amount,
            'action_reason': self.action_reason,
            'news_sentiment_raw': self.news_sentiment_raw,
            'event_risk_raw': self.event_risk_raw,
            'sector_tone_raw': self.sector_tone_raw,
            'dashboard': self.dashboard,
            'trend_analysis': self.trend_analysis,
            'short_term_outlook': self.short_term_outlook,
            'medium_term_outlook': self.medium_term_outlook,
            'technical_analysis': self.technical_analysis,
            'ma_analysis': self.ma_analysis,
            'volume_analysis': self.volume_analysis,
            'pattern_analysis': self.pattern_analysis,
            'fundamental_analysis': self.fundamental_analysis,
            'sector_position': self.sector_position,
            'company_highlights': self.company_highlights,
            'news_summary': self.news_summary,
            'market_sentiment': self.market_sentiment,
            'hot_topics': self.hot_topics,
            'analysis_summary': self.analysis_summary,
            'key_points': self.key_points,
            'risk_warning': self.risk_warning,
            'buy_reason': self.buy_reason,
            'market_snapshot': self.market_snapshot,
            'search_performed': self.search_performed,
            'success': self.success,
            'analysis_status': self.analysis_status,
            'error_message': self.error_message,
        }

    def get_core_conclusion(self) -> str:
        """获取核心结论（一句话）"""
        if self.dashboard and 'core_conclusion' in self.dashboard:
            return self.dashboard['core_conclusion'].get('one_sentence', self.analysis_summary)
        return self.analysis_summary

    def get_position_advice(self, has_position: bool = False) -> str:
        """获取持仓建议"""
        if self.dashboard and 'core_conclusion' in self.dashboard:
            pos_advice = self.dashboard['core_conclusion'].get('position_advice', {})
            if has_position:
                return pos_advice.get('has_position', self.operation_advice)
            return pos_advice.get('no_position', self.operation_advice)
        return self.operation_advice

    def get_sniper_points(self) -> Dict[str, str]:
        """获取狙击点位"""
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('sniper_points', {})
        return {}

    def get_checklist(self) -> List[str]:
        """获取检查清单"""
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('action_checklist', [])
        return []

    def get_risk_alerts(self) -> List[str]:
        """获取风险警报"""
        if self.dashboard and 'intelligence' in self.dashboard:
            return self.dashboard['intelligence'].get('risk_alerts', [])
        return []

    def get_emoji(self) -> str:
        """根据操作建议返回对应 emoji"""
        emoji_map = {
            '买入': '🟢',
            '加仓': '🟢',
            '强烈买入': '💚',
            '持有': '🟡',
            '观望': '⚪',
            '减仓': '🟠',
            '卖出': '🔴',
            '强烈卖出': '❌',
        }
        advice = self.operation_advice or ''
        # Direct match first
        if advice in emoji_map:
            return emoji_map[advice]
        # Handle compound advice like "卖出/观望" — use the first part
        for part in advice.replace('/', '|').split('|'):
            part = part.strip()
            if part in emoji_map:
                return emoji_map[part]
        # Score-based fallback
        score = self.sentiment_score
        if score >= 80:
            return '💚'
        elif score >= 65:
            return '🟢'
        elif score >= 55:
            return '🟡'
        elif score >= 45:
            return '⚪'
        elif score >= 35:
            return '🟠'
        else:
            return '🔴'

    def get_confidence_stars(self) -> str:
        """返回置信度星级"""
        star_map = {'高': '⭐⭐⭐', '中': '⭐⭐', '低': '⭐'}
        return star_map.get(self.confidence_level, '⭐⭐')


class GeminiAnalyzer:
    """
    Gemini AI 分析器

    职责：
    1. 调用 Google Gemini API 进行股票分析
    2. 结合预先搜索的新闻和技术面数据生成分析报告
    3. 解析 AI 返回的 JSON 格式结果

    使用方式：
        analyzer = GeminiAnalyzer()
        result = analyzer.analyze(context, news_context)
    """

    # ========================================
    # 系统提示词 - 决策仪表盘 v2.0
    # ========================================
    # 输出格式升级：从简单信号升级为决策仪表盘
    # 核心模块：核心结论 + 数据透视 + 舆情情报 + 作战计划
    # ========================================

    SYSTEM_PROMPT = """你是一位专注于趋势交易的全球市场（尤其是澳洲 ASX 股市）投资分析师，负责生成专业的【决策仪表盘】分析报告。注意：澳股无涨跌幅限制且实行 T+0 交易，请勿使用 A 股的涨跌停逻辑。
    
## 核心交易理念（ASX 适配版）

### 1. 估值与分红优先 (Dividend & Value)
- **核心指标**：必须评估股息率（Dividend Yield）及红利抵免（Franking Credits）的价值。
- 对于银行股和矿业蓝筹，派息的稳定性和安全性是第一考量。

### 2. 宏观与周期驱动 (Macro & Commodity)
- 资源股必须结合相关大宗商品（如铁矿石、铜、锂、黄金）的全球价格趋势进行评估。
- 关注澳洲央行（RBA）的利率决议及通胀数据对大盘（特别是金融与地产板块）的影响。

### 3. 趋势与波动率 (Trend & Volatility)
- 澳股蓝筹波动率较低，MA5 > MA10 > MA20 多头排列依然是有效的趋势确认指标。
- 适当放宽乖离率要求：乖离率 < 8% 即可视为安全区间，不僵化死守 5%。

### 4. 风险排查重点 (ASX 专属)
- **绝对红线**：ASX 官方发布的价格敏感公告（Price Sensitive Announcements）若存在重大利空。
- 目前正处于 2026 年 2 月的财报季（Reporting Season），需高度警惕业绩不及预期（Earnings Miss）导致的跳空暴跌。
- 异常升高的做空比例（Short Interest）或被做空机构狙击。

### 5. 买点偏好（回踩支撑）
- 最佳买点：股价回踩 MA10 获得支撑，且当前股息率处于历史较高百分位。
- 观望情况：跌破 MA20 且宏观大宗商品价格处于明确下行周期。

## 输出格式：决策仪表盘 JSON

请严格按照以下 JSON 格式输出，这是一个完整的【决策仪表盘】：
并且必须只输出合法 JSON，不要输出任何 JSON 之外的解释文字，关键字段不得缺失。

```json
{
    "stock_name": "股票中文名称",
    "sentiment_score": 0-100整数,
    "trend_prediction": "强烈看多/看多/震荡/看空/强烈看空",
    "operation_advice": "买入/加仓/持有/减仓/卖出/观望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",

    "dashboard": {
        "core_conclusion": {
            "one_sentence": "一句话核心结论（30字以内，直接告诉用户做什么）",
            "signal_type": "🟢买入信号/🟡持有观望/🔴卖出信号/⚠️风险警告",
            "time_sensitivity": "立即行动/今日内/本周内/不急",
            "position_advice": {
                "no_position": "空仓者建议：具体操作指引",
                "has_position": "持仓者建议：具体操作指引"
            }
        },

        "data_perspective": {
            "trend_status": {
                "ma_alignment": "均线排列状态描述",
                "is_bullish": true/false,
                "trend_score": 0-100
            },
            "price_position": {
                "current_price": 当前价格数值,
                "ma5": MA5数值,
                "ma10": MA10数值,
                "ma20": MA20数值,
                "bias_ma5": 乖离率百分比数值,
                "bias_status": "安全/警戒/危险",
                "support_level": 支撑位价格,
                "resistance_level": 压力位价格
            },
            "volume_analysis": {
                "volume_ratio": 量比数值,
                "volume_status": "放量/缩量/平量",
                "turnover_rate": 换手率百分比,
                "volume_meaning": "量能含义解读（如：缩量回调表示抛压减轻）"
            },
            "chip_structure": {
                "profit_ratio": 获利比例,
                "avg_cost": 平均成本,
                "concentration": 筹码集中度,
                "chip_health": "健康/一般/警惕"
            }
        },

        "intelligence": {
            "latest_news": "【最新消息】近期重要新闻摘要",
            "risk_alerts": ["风险点1：具体描述", "风险点2：具体描述"],
            "positive_catalysts": ["利好1：具体描述", "利好2：具体描述"],
            "earnings_outlook": "业绩预期分析（基于年报预告、业绩快报等）",
            "sentiment_summary": "舆情情绪一句话总结"
        },

        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想买入点：XX元（在MA5附近）",
                "secondary_buy": "次优买入点：XX元（在MA10附近）",
                "stop_loss": "止损位：XX元（跌破MA20或X%）",
                "take_profit": "目标位：XX元（前高/整数关口）"
            },
            "position_strategy": {
                "suggested_position": "建议仓位：X成",
                "entry_plan": "分批建仓策略描述",
                "risk_control": "风控策略描述"
            },
            "action_checklist": [
                "✅/⚠️/❌ 检查项1：多头排列",
                "✅/⚠️/❌ 检查项2：乖离率合理（强势趋势可放宽）",
                "✅/⚠️/❌ 检查项3：量能配合",
                "✅/⚠️/❌ 检查项4：无重大利空",
                "✅/⚠️/❌ 检查项5：筹码健康",
                "✅/⚠️/❌ 检查项6：PE估值合理",
                "✅/⚠️/❌ 检查项7：当前宏观大盘（美股/ASX）及大宗商品环境是否支持操作",
                "✅/⚠️/❌ 检查项8：资金面健康 (内部人/机构动向)"
            ]
        }
    },

    "analysis_summary": "100字综合分析摘要",
    "key_points": "3-5个核心看点，逗号分隔",
    "risk_warning": "风险提示",
    "buy_reason": "操作理由，引用交易理念",

    "trend_analysis": "走势形态分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技术面综合分析",
    "ma_analysis": "均线系统分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K线形态分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板块行业分析",
    "company_highlights": "公司亮点/风险",
    "news_summary": "新闻摘要",
    "market_sentiment": "市场情绪",
    "hot_topics": "相关热点",

    "search_performed": true/false,
    "data_sources": "数据来源说明"
}
```

## 评分标准

### 强烈买入（80-100分）：
- ✅ 多头排列：MA5 > MA10 > MA20
- ✅ 低乖离率：<2%，最佳买点
- ✅ 缩量回调或放量突破
- ✅ 筹码集中健康
- ✅ 消息面有利好催化

### 买入（60-79分）：
- ✅ 多头排列或弱势多头
- ✅ 乖离率 <5%
- ✅ 量能正常
- ⚪ 允许一项次要条件不满足

### 观望（40-59分）：
- ⚠️ 乖离率 >5%（追高风险）
- ⚠️ 均线缠绕趋势不明
- ⚠️ 有风险事件

### 卖出/减仓（0-39分）：
- ❌ 空头排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 决策仪表盘核心原则

1. **核心结论先行**：一句话说清该买该卖
2. **分持仓建议**：空仓者和持仓者给不同建议
3. **精确狙击点**：必须给出具体价格，不说模糊的话
4. **检查清单可视化**：用 ✅⚠️❌ 明确显示每项检查结果
5. **风险优先级**：舆情中的风险点要醒目标出"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化 AI 分析器

        优先级：Gemini > Anthropic > OpenAI

        Args:
            api_key: Gemini API Key（可选，默认从配置读取）
        """
        config = get_config()
        self._api_key = api_key or config.gemini_api_key
        self._model = None
        self._current_model_name = None  # 当前使用的模型名称
        self._using_fallback = False  # 是否正在使用备选模型
        self._use_openai = False  # 是否使用 OpenAI 兼容 API
        self._use_anthropic = False  # 是否使用 Anthropic Claude API
        self._openai_client = None  # OpenAI 客户端
        self._anthropic_client = None  # Anthropic 客户端

        # 检查 Gemini API Key 是否有效（过滤占位符）
        gemini_key_valid = self._api_key and not self._api_key.startswith('your_') and len(self._api_key) > 10

        # 优先级：Gemini > Anthropic > OpenAI
        if gemini_key_valid:
            try:
                self._init_model()
            except Exception as e:
                logger.warning(f"Gemini init failed: {e}, trying Anthropic then OpenAI")
                self._try_anthropic_then_openai()
        else:
            logger.info("Gemini API Key not configured, trying Anthropic then OpenAI")
            self._try_anthropic_then_openai()

        if not self._model and not self._anthropic_client and not self._openai_client:
            logger.warning("No AI API Key configured, AI analysis will be unavailable")

    def _try_anthropic_then_openai(self) -> None:
        """优先尝试 Anthropic，其次 OpenAI 作为备选。两者均初始化以供运行时互为故障转移（如 Anthropic 429 时切 OpenAI）。"""
        self._init_anthropic_fallback()
        self._init_openai_fallback()

    def _init_anthropic_fallback(self) -> None:
        """
        初始化 Anthropic Claude API 作为备选。

        使用 Anthropic Messages API：https://docs.anthropic.com/en/api/messages
        """
        config = get_config()
        anthropic_key_valid = (
            config.anthropic_api_key
            and not config.anthropic_api_key.startswith('your_')
            and len(config.anthropic_api_key) > 10
        )
        if not anthropic_key_valid:
            logger.debug("Anthropic API Key not configured or invalid")
            return
        try:
            from anthropic import Anthropic

            self._anthropic_client = Anthropic(api_key=config.anthropic_api_key)
            self._current_model_name = config.anthropic_model
            self._use_anthropic = True
            logger.info(
                f"Anthropic Claude API init OK (model: {config.anthropic_model})"
            )
        except ImportError:
            logger.error("anthropic package not installed, run: pip install anthropic")
        except Exception as e:
            logger.error(f"Anthropic API init failed: {e}")

    def _init_openai_fallback(self) -> None:
        """
        初始化 OpenAI 兼容 API 作为备选

        支持所有 OpenAI 格式的 API，包括：
        - OpenAI 官方
        - DeepSeek
        - 通义千问
        - Moonshot 等
        """
        config = get_config()

        # 检查 OpenAI API Key 是否有效（过滤占位符）
        openai_key_valid = (
            config.openai_api_key and
            not config.openai_api_key.startswith('your_') and
            len(config.openai_api_key) > 10
        )

        if not openai_key_valid:
            logger.debug("OpenAI 兼容 API 未配置或配置无效")
            return

        # 分离 import 和客户端创建，以便提供更准确的错误信息
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("未安装 openai 库，请运行: pip install openai")
            return

        try:
            # base_url 可选，不填则使用 OpenAI 官方默认地址
            client_kwargs = {"api_key": config.openai_api_key}
            if config.openai_base_url and config.openai_base_url.startswith('http'):
                client_kwargs["base_url"] = config.openai_base_url

            self._openai_client = OpenAI(**client_kwargs)
            self._current_model_name = config.openai_model
            self._use_openai = True
            logger.info(f"OpenAI 兼容 API 初始化成功 (base_url: {config.openai_base_url}, model: {config.openai_model})")
        except ImportError as e:
            # 依赖缺失（如 socksio）
            if 'socksio' in str(e).lower() or 'socks' in str(e).lower():
                logger.error(f"OpenAI 客户端需要 SOCKS 代理支持，请运行: pip install httpx[socks] 或 pip install socksio")
            else:
                logger.error(f"OpenAI 依赖缺失: {e}")
        except Exception as e:
            error_msg = str(e).lower()
            if 'socks' in error_msg or 'socksio' in error_msg or 'proxy' in error_msg:
                logger.error(f"OpenAI 代理配置错误: {e}，如使用 SOCKS 代理请运行: pip install httpx[socks]")
            else:
                logger.error(f"OpenAI 兼容 API 初始化失败: {e}")

    def _init_model(self) -> None:
        """
        初始化 Gemini 模型（使用新版 google-genai SDK）
        """
        try:
            from google import genai

            config = get_config()
            model_name = config.gemini_model
            fallback_model = config.gemini_model_fallback

            # 新版 SDK 使用 Client
            self._model = genai.Client(api_key=self._api_key)
            self._current_model_name = model_name
            self._using_fallback = False
            logger.info(f"Gemini 模型初始化成功 (模型: {model_name})")

        except Exception as e:
            logger.error(f"Gemini 模型初始化失败: {e}")
            self._model = None

    def _switch_to_fallback_model(self) -> bool:
        """
        切换到备选模型

        Returns:
            是否成功切换
        """
        try:
            config = get_config()
            fallback_model = config.gemini_model_fallback
            logger.warning(f"[LLM] 切换到备选模型: {fallback_model}")
            self._current_model_name = fallback_model
            self._using_fallback = True
            logger.info(f"[LLM] 备选模型 {fallback_model} 初始化成功")
            return True
        except Exception as e:
            logger.error(f"[LLM] 切换备选模型失败: {e}")
            return False

    def is_available(self) -> bool:
        """检查分析器是否可用。"""
        return (
            self._model is not None
            or self._anthropic_client is not None
            or self._openai_client is not None
        )

    def _call_anthropic_api(self, prompt: str, generation_config: dict) -> str:
        """
        调用 Anthropic Claude Messages API。

        Args:
            prompt: 用户提示词
            generation_config: 生成配置（temperature, max_output_tokens）

        Returns:
            响应文本
        """
        config = get_config()
        max_retries = config.gemini_max_retries
        base_delay = config.gemini_retry_delay
        temperature = generation_config.get(
            'temperature', config.anthropic_temperature
        )
        max_tokens = generation_config.get('max_output_tokens', config.anthropic_max_tokens)

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    delay = min(delay, 60)
                    logger.info(
                        f"[Anthropic] Retry {attempt + 1}/{max_retries}, "
                        f"waiting {delay:.1f}s..."
                    )
                    time.sleep(delay)

                message = self._anthropic_client.messages.create(
                    model=self._current_model_name,
                    max_tokens=max_tokens,
                    system=self.SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                )
                if (
                    message.content
                    and len(message.content) > 0
                    and hasattr(message.content[0], 'text')
                ):
                    return message.content[0].text
                raise ValueError("Anthropic API returned empty response")
            except Exception as e:
                error_str = str(e)
                is_rate_limit = (
                    '429' in error_str
                    or 'rate' in error_str.lower()
                    or 'quota' in error_str.lower()
                )
                if is_rate_limit:
                    logger.warning(
                        f"[Anthropic] Rate limit, attempt {attempt + 1}/"
                        f"{max_retries}: {error_str[:100]}"
                    )
                else:
                    logger.warning(
                        f"[Anthropic] API failed, attempt {attempt + 1}/"
                        f"{max_retries}: {error_str[:100]}"
                    )
                if attempt == max_retries - 1:
                    raise
        raise Exception("Anthropic API failed after max retries")

    def _call_openai_api(self, prompt: str, generation_config: dict) -> str:
        """
        调用 OpenAI 兼容 API

        Args:
            prompt: 提示词
            generation_config: 生成配置

        Returns:
            响应文本
        """
        config = get_config()
        max_retries = config.gemini_max_retries
        base_delay = config.gemini_retry_delay

        def _build_base_request_kwargs() -> dict:
            kwargs = {
                "model": self._current_model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": generation_config.get('temperature', config.openai_temperature),
            }
            return kwargs

        def _is_unsupported_param_error(error_message: str, param_name: str) -> bool:
            lower_msg = error_message.lower()
            return ('400' in lower_msg or "unsupported parameter" in lower_msg or "unsupported param" in lower_msg) and param_name in lower_msg

        if not hasattr(self, "_token_param_mode"):
            self._token_param_mode = {}

        max_output_tokens = generation_config.get('max_output_tokens', 8192)
        model_name = self._current_model_name
        mode = self._token_param_mode.get(model_name, "max_tokens")

        def _kwargs_with_mode(mode_value):
            kwargs = _build_base_request_kwargs()
            if mode_value is not None:
                kwargs[mode_value] = max_output_tokens
            return kwargs

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    delay = min(delay, 60)
                    logger.info(f"[OpenAI] 第 {attempt + 1} 次重试，等待 {delay:.1f} 秒...")
                    time.sleep(delay)

                try:
                    response = self._openai_client.chat.completions.create(**_kwargs_with_mode(mode))
                except Exception as e:
                    error_str = str(e)
                    if mode == "max_tokens" and _is_unsupported_param_error(error_str, "max_tokens"):
                        mode = "max_completion_tokens"
                        self._token_param_mode[model_name] = mode
                        response = self._openai_client.chat.completions.create(**_kwargs_with_mode(mode))
                    elif mode == "max_completion_tokens" and _is_unsupported_param_error(error_str, "max_completion_tokens"):
                        mode = None
                        self._token_param_mode[model_name] = mode
                        response = self._openai_client.chat.completions.create(**_kwargs_with_mode(mode))
                    else:
                        raise

                if response and response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content
                else:
                    raise ValueError("OpenAI API 返回空响应")
                    
            except Exception as e:
                error_str = str(e)
                is_rate_limit = '429' in error_str or 'rate' in error_str.lower() or 'quota' in error_str.lower()
                
                if is_rate_limit:
                    logger.warning(f"[OpenAI] API 限流，第 {attempt + 1}/{max_retries} 次尝试: {error_str[:100]}")
                else:
                    logger.warning(f"[OpenAI] API 调用失败，第 {attempt + 1}/{max_retries} 次尝试: {error_str[:100]}")
                
                if attempt == max_retries - 1:
                    raise
        
        raise Exception("OpenAI API 调用失败，已达最大重试次数")
    
    def _call_api_with_retry(self, prompt: str, generation_config: dict) -> str:
        """
        调用 AI API，带有重试和模型切换机制
        
        优先级：Gemini > Gemini 备选模型 > OpenAI 兼容 API
        
        处理 429 限流错误：
        1. 先指数退避重试
        2. 多次失败后切换到备选模型
        3. Gemini 完全失败后尝试 OpenAI
        
        Args:
            prompt: 提示词
            generation_config: 生成配置
            
        Returns:
            响应文本
        """
        # 若使用 Anthropic，调用 Anthropic（失败时回退到 OpenAI）
        if self._use_anthropic:
            try:
                return self._call_anthropic_api(prompt, generation_config)
            except Exception as anthropic_error:
                if self._openai_client:
                    logger.warning(
                        "[Anthropic] All retries failed, falling back to OpenAI"
                    )
                    return self._call_openai_api(prompt, generation_config)
                raise anthropic_error

        # 若使用 OpenAI（仅当无 Anthropic 时为主选）
        if self._use_openai:
            return self._call_openai_api(prompt, generation_config)

        config = get_config()
        max_retries = config.gemini_max_retries
        base_delay = config.gemini_retry_delay
        
        last_error = None
        tried_fallback = getattr(self, '_using_fallback', False)
        
        for attempt in range(max_retries):
            try:
                # 请求前增加延时（防止请求过快触发限流）
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))  # 指数退避: 5, 10, 20, 40...
                    delay = min(delay, 60)  # 最大60秒
                    logger.info(f"[Gemini] 第 {attempt + 1} 次重试，等待 {delay:.1f} 秒...")
                    time.sleep(delay)
                
                from google.genai import types as genai_types
                response = self._model.models.generate_content(
                    model=self._current_model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_PROMPT,
                        temperature=generation_config.get("temperature", 0.7),
                        max_output_tokens=generation_config.get("max_output_tokens", 8192),
                    )
                )

                if response and response.text:
                    return response.text
                else:
                    raise ValueError("Gemini 返回空响应")
                    
            except Exception as e:
                last_error = e
                error_str = str(e)
                
                # 检查是否是 429 限流 或 503 过载错误
                is_rate_limit = '429' in error_str or 'quota' in error_str.lower() or 'rate' in error_str.lower()
                is_overload = '503' in error_str or 'unavailable' in error_str.lower() or 'connection' in error_str.lower()
                
                if is_rate_limit or is_overload:
                    err_type = "限流 (429)" if is_rate_limit else "过载/连接失败 (503)"
                    logger.warning(f"[Gemini] API {err_type}，第 {attempt + 1}/{max_retries} 次尝试: {error_str[:100]}")
                    
                    # 503/连接失败时重建Client，避免持久连接状态损坏
                    if is_overload and hasattr(self, '_model') and self._model is not None:
                        try:
                            from google import genai as _genai
                            self._model = _genai.Client(api_key=self._api_key)
                            logger.info("[Gemini] 已重建Client连接")
                        except Exception:
                            pass
                    
                    # 如果已经重试了一半次数且还没切换过备选模型，尝试切换
                    if attempt >= max_retries // 2 and not tried_fallback:
                        if self._switch_to_fallback_model():
                            tried_fallback = True
                            logger.info("[Gemini] 已切换到备选模型，继续重试")
                        else:
                            logger.warning("[Gemini] 切换备选模型失败，继续使用当前模型重试")
                else:
                    # 其他错误，记录并继续重试
                    logger.warning(f"[Gemini] API 调用失败，第 {attempt + 1}/{max_retries} 次尝试: {error_str[:100]}")
        
        # Gemini 重试耗尽，尝试 Anthropic 再 OpenAI
        if self._anthropic_client:
            logger.warning("[Gemini] All retries failed, switching to Anthropic")
            try:
                return self._call_anthropic_api(prompt, generation_config)
            except Exception as anthropic_error:
                logger.warning(
                    f"[Anthropic] Fallback failed: {anthropic_error}"
                )
                if self._openai_client:
                    logger.warning("[Gemini] Trying OpenAI as final fallback")
                    try:
                        return self._call_openai_api(prompt, generation_config)
                    except Exception as openai_error:
                        logger.error(
                            f"[OpenAI] Final fallback also failed: {openai_error}"
                        )
                        raise last_error or anthropic_error or openai_error
                raise last_error or anthropic_error

        if self._openai_client:
            logger.warning("[Gemini] All retries failed, switching to OpenAI")
            try:
                return self._call_openai_api(prompt, generation_config)
            except Exception as openai_error:
                logger.error(f"[OpenAI] Fallback also failed: {openai_error}")
                raise last_error or openai_error
        # 懒加载 Anthropic，再尝试 OpenAI
        if config.anthropic_api_key and not self._anthropic_client:
            logger.warning("[Gemini] Trying lazy-init Anthropic API")
            self._init_anthropic_fallback()
            if self._anthropic_client:
                try:
                    return self._call_anthropic_api(prompt, generation_config)
                except Exception as ae:
                    logger.warning(f"[Anthropic] Lazy fallback failed: {ae}")
                    if self._openai_client:
                        try:
                            return self._call_openai_api(prompt, generation_config)
                        except Exception as oe:
                            raise last_error or ae or oe
                    raise last_error or ae
        if config.openai_api_key and not self._openai_client:
            logger.warning("[Gemini] Trying lazy-init OpenAI API")
            self._init_openai_fallback()
            if self._openai_client:
                try:
                    return self._call_openai_api(prompt, generation_config)
                except Exception as openai_error:
                    logger.error(f"[OpenAI] Lazy fallback also failed: {openai_error}")
                    raise last_error or openai_error

        # 所有备选均耗尽
        raise last_error or Exception("所有 AI API 调用失败，已达最大重试次数")
    
    def analyze(
        self, 
        context: Dict[str, Any],
        news_context: Optional[str] = None
    ) -> AnalysisResult:
        """
        分析单只股票
        
        流程：
        1. 格式化输入数据（技术面 + 新闻）
        2. 调用 Gemini API（带重试和模型切换）
        3. 解析 JSON 响应
        4. 返回结构化结果
        
        Args:
            context: 从 storage.get_analysis_context() 获取的上下文数据
            news_context: 预先搜索的新闻内容（可选）
            
        Returns:
            AnalysisResult 对象
        """
        code = context.get('code', 'Unknown')
        config = get_config()
        
        # 请求前增加延时（防止连续请求触发限流）
        request_delay = config.gemini_request_delay
        if request_delay > 0:
            logger.debug(f"[LLM] 请求前等待 {request_delay:.1f} 秒...")
            time.sleep(request_delay)
        
        # 优先从上下文获取股票名称（由 main.py 传入）
        name = context.get('stock_name')
        if not name or name.startswith('股票'):
            # 备选：从 realtime 中获取
            if 'realtime' in context and context['realtime'].get('name'):
                name = context['realtime']['name']
            else:
                # 最后从映射表获取
                name = STOCK_NAME_MAP.get(code, f'股票{code}')
        
        # 如果模型不可用，返回默认结果
        if not self.is_available():
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='震荡',
                operation_advice='持有',
                confidence_level='低',
                analysis_summary='AI 分析功能未启用（未配置 API Key）',
                risk_warning='请配置 Gemini API Key 后重试',
                success=False,
                analysis_status='FAILED',
                error_message='Gemini API Key 未配置',
            )
        
        try:
            # 格式化输入（包含技术面数据和新闻）
            prompt = self._format_prompt(context, name, news_context)
            
            # 获取模型名称
            model_name = getattr(self, '_current_model_name', None)
            if not model_name:
                model_name = getattr(self._model, '_model_name', 'unknown')
                if hasattr(self._model, 'model_name'):
                    model_name = self._current_model_name
            
            logger.info(f"========== AI 分析 {name}({code}) ==========")
            time.sleep(30)
            logger.info(f"[LLM配置] 模型: {model_name}")
            logger.info(f"[LLM配置] Prompt 长度: {len(prompt)} 字符")
            logger.info(f"[LLM配置] 是否包含新闻: {'是' if news_context else '否'}")
            
            # 记录完整 prompt 到日志（INFO级别记录摘要，DEBUG记录完整）
            prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
            logger.info(f"[LLM Prompt 预览]\n{prompt_preview}")
            logger.debug(f"=== 完整 Prompt ({len(prompt)}字符) ===\n{prompt}\n=== End Prompt ===")

            # 设置生成配置（从配置文件读取温度参数）
            config = get_config()
            generation_config = {
                "temperature": config.gemini_temperature,
                "max_output_tokens": 8192,
            }

            # 记录实际使用的 API 提供方
            api_provider = (
                "OpenAI" if self._use_openai
                else "Anthropic" if self._use_anthropic
                else "Gemini"
            )
            logger.info(f"[LLM调用] 开始调用 {api_provider} API...")
            
            # 使用带重试的 API 调用
            start_time = time.time()
            response_text = self._call_api_with_retry(prompt, generation_config)
            elapsed = time.time() - start_time

            # 记录响应信息
            logger.info(f"[LLM返回] {api_provider} API 响应成功, 耗时 {elapsed:.2f}s, 响应长度 {len(response_text)} 字符")
            
            # 记录响应预览（INFO级别）和完整响应（DEBUG级别）
            response_preview = response_text[:300] + "..." if len(response_text) > 300 else response_text
            logger.info(f"[LLM返回 预览]\n{response_preview}")
            logger.debug(f"=== {api_provider} 完整响应 ({len(response_text)}字符) ===\n{response_text}\n=== End Response ===")
            
            # 解析响应
            result = self._parse_response(response_text, code, name)
            result = self._apply_fundamental_sanitization_guard(result, context)
            result.raw_response = response_text
            result.search_performed = bool(news_context)
            result.market_snapshot = self._build_market_snapshot(context)

            logger.info(f"[LLM解析] {name}({code}) 分析完成: {result.trend_prediction}, 评分 {result.sentiment_score}")
            
            return result
            
        except Exception as e:
            logger.error(f"AI 分析 {name}({code}) 失败: {e}")
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='震荡',
                operation_advice='持有',
                confidence_level='低',
                analysis_summary=f'分析过程出错: {str(e)[:100]}',
                risk_warning='分析失败，请稍后重试或手动分析',
                success=False,
                analysis_status='FAILED',
                error_message=str(e),
            )
    

# =======================================================
    # [新增方法] 自动生成历史 K 线表格 (已修复缩进)
    # =======================================================
    def _generate_history_table(self, history_data: List[Dict[str, Any]]) -> str:
        """补充历史数据表格"""
        if not history_data:
            return "暂无历史数据"

        lines = []
        # 取最近 30 天的数据
        recent = history_data[-30:]
        recent.reverse() 

        for r in recent:
            # 1. 日期
            dt = str(r.get('date', '')).split(' ')[0]
            
            # 2. 收盘价
            try:
                cl = f"{float(r.get('close', 0)):.2f}"
            except:
                cl = "N/A"

            # 3. 涨跌幅
            try:
                pct = r.get('pct_chg') or r.get('change_pct') or 0
                pc = f"{float(pct):.2f}%"
            except:
                pc = "N/A"
            
            # 4. 成交量 (修复了这里的缩进问题)
            try:
                val = float(r.get('volume', 0))
                if val > 1000000:
                    vo = f"{val/1000000:.2f}M"
                elif val > 1000:
                    vo = f"{val/1000:.1f}K"
                else:
                    vo = str(int(val))
            except:
                vo = "N/A"
            
            lines.append(f"| {dt} | {cl} | {pc} | {vo} |")
            
        return "\n".join(lines)

    # =======================================================
    # [修改方法] 格式化 Prompt
    # =======================================================
    def _format_prompt(
        self, 
        context: Dict[str, Any], 
        name: str,
        news_context: Optional[str] = None
    ) -> str:
        """
        格式化分析提示词（决策仪表盘 v2.0）
        """
        code = context.get('code', 'Unknown')

        # 尝试从 history_data DataFrame 中提取资金面数据注入 context
        # （兼容 yfinance_fetcher 将数据写在 DataFrame 列里的做法）
        raw_data = context.get('history_data') or context.get('kline') or context.get('history')
        if raw_data is not None and hasattr(raw_data, 'columns'):
            if 'Insider_Desc' in raw_data.columns and 'Insider_Desc' not in context:
                context['Insider_Desc'] = raw_data['Insider_Desc'].iloc[-1]
            if 'Inst_Desc' in raw_data.columns and 'Inst_Desc' not in context:
                context['Inst_Desc'] = raw_data['Inst_Desc'].iloc[-1]

        # 优先使用上下文中的股票名称
        stock_name = context.get('stock_name', name)
        if not stock_name or stock_name == f'股票{code}':
            stock_name = STOCK_NAME_MAP.get(code, f'股票{code}')
            
        today = context.get('today', {})

        # >>>>>> [修改：暴力查找数据] >>>>>>
        price_table = context.get('price_history_table')
        
        # 如果没有现成表格，尝试从原始数据生成
        if not price_table or price_table == 'N/A':
            # 尝试所有可能的字段名 (history_data, kline, history)
            raw_data = context.get('history_data') or context.get('kline') or context.get('history')
            
            if raw_data:
                price_table = self._generate_history_table(raw_data)
            else:
                # 打印一下有哪些 key，方便调试
                keys_str = ",".join(list(context.keys()))
                price_table = f'N/A (无数据, 可用字段: {keys_str})'
        # <<<<<< [修改结束] <<<<<<
        
        # 基本面硬校验：异常值在进入 Prompt 前统一降级为 N/A
        raw_fundamentals = context.get('fundamentals', {})
        fundamentals, sanitized_fields = self._sanitize_fundamentals(raw_fundamentals)
        context['fundamentals'] = fundamentals
        context['_fundamentals_sanitized_fields'] = sanitized_fields

        if fundamentals:
            fund_lines = ["| 指标 | 数值 |", "|------|------|"]
            for k, v in fundamentals.items():
                fund_lines.append(f"| {k} | {v} |")
            if sanitized_fields:
                fund_lines.append("| 说明 | 检测到异常基本面值，已统一降级为 N/A，禁止据此做确定性结论 |")
            fundamentals_table = "\n".join(fund_lines)
        else:
            fundamentals_table = "暂无基本面数据"

        # 生成历史回测胜率摘要
        bt = context.get('backtest_summary')
        if bt:
            backtest_block = f"""### ⏳ 历史回测实测数据（真实，非估计）
| 指标 | 数值 |
|------|------|
| 样本数 | {bt.get('total', 0)} 次 |
| 方向准确率 | {bt.get('direction_accuracy') or 'N/A'}% |
| 胜率（含中性） | {bt.get('win_rate') or 'N/A'}% |
| 平均收益 | {bt.get('avg_return') or 'N/A'}% |
| 止损触发率 | {bt.get('stop_loss_rate') or 'N/A'}% |"""
        else:
            backtest_block = """### ⏳ 历史回测数据
⚠️ **数据不足，暂无历史回测结果。请勿编造胜率数字，直接注明"样本不足，无法统计"。**"""

        # 生成大盘宏观表格
        market_overview = context.get('market_overview', {})
        if market_overview:
            mkt_lines = ["| 指标 | 收盘 | 涨跌幅 |", "|------|------|--------|"]
            for name, d in market_overview.items():
                close = d.get('close', 'N/A')
                pct = f"{d.get('pct_chg', 'N/A')}%" if d.get('pct_chg') is not None else 'N/A'
                trend = d.get('trend', '')
                mkt_lines.append(f"| {name} | {close} | {trend} {pct} |")
            market_table = "\n".join(mkt_lines)
        else:
            market_table = "暂无大盘数据"

        # 止损追踪警告block
        stop_loss_alert = context.get('stop_loss_alert')
        if stop_loss_alert and stop_loss_alert.get('warning'):
            sl_block = f"""
### ⚠️ 止损追踪警告
{stop_loss_alert['warning']}
- 上次止损位（{stop_loss_alert.get('prev_date', '')} {stop_loss_alert.get('prev_operation', '')}信号）：{stop_loss_alert['prev_stop_loss']:.3f} AUD
- 当前价格：{stop_loss_alert['current_price']:.3f} AUD
- 距止损位：{stop_loss_alert['diff_pct']:.1f}%

**请在分析结论中重点说明是否需要执行止损操作。**
"""
        elif stop_loss_alert and stop_loss_alert.get('prev_stop_loss'):
            sl_block = (
                "### 📍 历史止损参考\n"
                f"上次止损位（{stop_loss_alert.get('prev_date', '')}）：{stop_loss_alert['prev_stop_loss']:.3f} AUD，"
                f"当前距止损 {stop_loss_alert['diff_pct']:.1f}%\n"
            )
        else:
            sl_block = ""

        # 信号连续性block
        streak = context.get('signal_streak')
        if streak and streak.get('streak', 0) >= 2:
            streak_block = "### 📅 信号连续性\n" + streak['summary'] + "，请在分析中说明趋势是否仍然有效。\n"
        else:
            streak_block = ""

        # ========== 构建决策仪表盘格式的输入 ==========
        prompt = f"""# 决策仪表盘分析请求

## 📊 股票基础信息
| 项目 | 数据 |
|------|------|
| 股票代码 | **{code}** |
| 股票名称 | **{stock_name}** |
| 分析日期 | {context.get('date', '未知')} |

---

## 📈 技术面数据

### 今日行情
| 指标 | 数值 |
|------|------|
| 收盘价 | {today.get('close', 'N/A')} AUD |
| 开盘价 | {today.get('open', 'N/A')} AUD |
| 最高价 | {today.get('high', 'N/A')} AUD |
| 最低价 | {today.get('low', 'N/A')} AUD |
| 涨跌幅 | {today.get('pct_chg', 'N/A')}% |
| 成交量 | {self._format_volume(today.get('volume'))} |
| 成交额 | {self._format_amount(today.get('amount'))} |

{backtest_block}

{sl_block}
{streak_block}
### 🌏 今日大盘环境
{market_table}

### 📊 基本面数据
{fundamentals_table}

### 📈 近期价格走势 (最近 30 个交易日数据)
| 日期 | 收盘价 | 涨跌幅 | 成交量 |
|------|--------|--------|--------|
{price_table}

### 均线系统（关键判断指标）
| 均线 | 数值 | 说明 |
|------|------|------|
| MA5 | {today.get('ma5', 'N/A')} | 短期趋势线 |
| MA10 | {today.get('ma10', 'N/A')} | 中短期趋势线 |
| MA20 | {today.get('ma20', 'N/A')} | 中期趋势线 |
| 均线形态 | {context.get('ma_status', '未知')} | 多头/空头/缠绕 |
"""
        # ... (后续代码保持不变，注意不要删掉后面的部分) ...
        
        # 记得把 prompt 后面追加的内容接上 (实时行情、筹码分布等)
        # 只要确保上面这段覆盖了对应的部分即可。
        
        # 添加昨日对比数据
        if 'yesterday' in context:
            volume_change = context.get('volume_change_ratio', 'N/A')
            prompt += f"""
### 量价变化
- 成交量较昨日变化：{volume_change}倍
- 价格较昨日变化：{context.get('price_change_ratio', 'N/A')}%
"""
        
        # 添加新闻搜索结果（量化进阶版：1-2-3-4 专业排序）
        # 1. 注入量化思维核心指令
        prompt += f"""
---

## 🌍 第一阶段：板块轮动与共振 (Sector Check)
**量化要求**：判定所属板块（Mining, Banking, Healthcare等），结合今日大宗商品（铁矿石/金/铜/原油）走势。若板块利空，即使个股技术面好，也必须提示“板块共振向下”并调低评分。这是第一道宏观过滤器。

## ⏳ 第二阶段：历史回测复盘 (Backtesting)
**量化要求**：上方已提供本股的真实系统回测数据，请直接引用。若显示“样本不足”则注明“历史样本不足，暂无统计”，**严禁自行编造或估算任何胜率数字**。
【30天历史价格表（辅助参考）】：
{context.get('price_history_table', '暂无历史数据')}

## 📅 第三阶段：财报季避雷针 (Earnings)
**量化要求**：检查当前是否处于澳洲 2 月或 8 月财报披露月。若未来 7 天内有业绩发布，必须强制标记为【高波动风险】，并建议仓位减半，防止技术面失效。

## 💰 第四阶段：风险仓位控制 (Risk Control)
**量化要求**：
1. **本金基数**：当前账户总本金为 {get_config().total_assets} AUD。
2. **风险红线**：单笔交易最大允许亏损为总本金的 1%（即 {get_config().total_assets * 0.01} AUD）。
3. **仓位计算**：计算 1.5 倍 ATR 的止损空间。(当前14日真实 ATR: **{round(context.get('atr', 0), 4)} AUD**，止损空间 = ATR × 1.5 = **{round(context.get('atr', 0) * 1.5, 4)} AUD**)
4. **具体指令**：请根据上述数据，给出精确的【建议买入股数】（公式：{get_config().total_assets * 0.01} / {round(context.get('atr', 0) * 1.5, 4)} = 精确股数）。

这是最后执行的红线，必须给出具体数字。
"""

        # 2. 注入动态新闻
        if news_context:
            prompt += f"""
---
## 📰 舆情情报摘要
以下是该股最新的市场情报，请结合上述板块和财报逻辑进行总结：
{news_context}
"""
        else:
            prompt += "\n目前未搜索到近期相关新闻，请主要依据技术面和板块趋势进行分析。\n"

        # 注入资金面数据（Insider + Institutional）
        insider_desc = context.get('Insider_Desc', '无数据')
        inst_desc = context.get('Inst_Desc', '无数据')

        if insider_desc != '无数据' or inst_desc != '无数据':
            prompt += f"""
---
## 💰 资金面深度扫描 (Yahoo Finance 实时数据)

| 项目 | 数据 |
|------|------|
| 内部人交易 (Insider) | {insider_desc} |
| 机构持仓 (Institutional) | {inst_desc} |

**量化解读**：
- 若内部人净买入 > 0，通常视为强烈利好信号（高管最懂公司）。
- 若机构持股比例高 (>30%) 且持续增持，说明"聪明钱"看好。
- 警惕"背离"：股价涨但内部人在卖出，或机构大幅减持。
"""
        else:
            prompt += "\n⚠️ 资金面数据缺失，无法分析内部人及机构动向。\n"

        # 3. 注入数据缺失警告
        if context.get('data_missing'):
            prompt += """
---
⚠️ **数据缺失警告**：行情数据不完整，请重点分析舆情，严禁编造数据。
"""

        # 4. 最终任务指令
        prompt += f"""
---
## ✅ 最终分析任务与强制输出规范
请**严格按照**【板块共振】->【历史回测】->【财报预警】->【风险控制】的专业顺序进行综合研判，为 **{stock_name}({code})** 生成报告。

🚨 **强制填表要求（极其重要）**：
1. 你必须将算出的【精确买入股数】和【ATR止损价】，强制写在输出 JSON 的 `仓位建议` 或 `操作建议` 字段中！
2. 你必须将【30天历史回测胜率】结论，强制写在 `建仓策略` 或 `分析摘要` 字段中！
绝不允许用“轻仓/重仓”等模糊词汇敷衍，必须给出具体数字！
"""
        if sanitized_fields:
            prompt += (
                "\n### 基本面数据质量约束\n"
                "- 以下指标值被判定为异常并降级为 N/A："
                + ", ".join(sanitized_fields)
                + "。\n"
                "- 对 N/A 指标必须明确说明“数据异常/不可用”，"
                "不得输出确定性基本面结论，不得给出高置信度表述。\n"
            )
        
        return prompt

    def _sanitize_fundamentals(self, fundamentals: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
        """基本面硬校验：异常值一律降级为 N/A。"""
        if not isinstance(fundamentals, dict) or not fundamentals:
            return {}, []

        sanitized: Dict[str, Any] = {}
        sanitized_fields: List[str] = []
        for key, value in fundamentals.items():
            if self._is_abnormal_fundamental_value(key, value):
                sanitized[key] = "N/A"
                sanitized_fields.append(key)
            else:
                sanitized[key] = value
        return sanitized, sanitized_fields

    def _parse_fundamental_number(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            parsed = float(value)
        elif isinstance(value, str):
            cleaned = (
                value.strip()
                .replace('%', '')
                .replace(',', '')
                .replace('亿AUD', '')
                .replace('AUD', '')
            )
            if not cleaned:
                return None
            try:
                parsed = float(cleaned)
            except ValueError:
                return None
        else:
            return None

        if not math.isfinite(parsed):
            return None
        return parsed

    def _is_abnormal_fundamental_value(self, key: str, value: Any) -> bool:
        k = (key or "").strip().lower()
        if not self._is_guarded_numeric_fundamental_key(k):
            return False

        numeric = self._parse_fundamental_number(value)
        if numeric is None:
            return True

        if k in {"pe", "市盈率"}:
            return numeric <= 0 or numeric > 200
        if k in {"pb", "市净率"}:
            return numeric <= 0 or numeric > 50
        if "股息率" in k or "dividend" in k or "yield" in k:
            return numeric < 0 or numeric > 100
        if "增速" in k or "growth" in k:
            return numeric < -100 or numeric > 500
        if "payout" in k or "派息率" in k or "分红率" in k:
            return numeric < 0 or numeric > 100
        if "roe" in k or "净资产收益率" in k:
            return numeric < -100 or numeric > 100
        if "负债权益比" in k or "debt" in k:
            return numeric < 0 or numeric > 1000

        return False

    def _is_guarded_numeric_fundamental_key(self, key: str) -> bool:
        if key in {"pe", "市盈率", "pb", "市净率"}:
            return True
        if "股息率" in key or "dividend" in key or "yield" in key:
            return True
        if "增速" in key or "growth" in key:
            return True
        if "payout" in key or "派息率" in key or "分红率" in key:
            return True
        if "roe" in key or "净资产收益率" in key:
            return True
        if "负债权益比" in key or "debt" in key:
            return True
        return False

    def _apply_fundamental_sanitization_guard(
        self,
        result: AnalysisResult,
        context: Dict[str, Any],
    ) -> AnalysisResult:
        sanitized_fields = context.get('_fundamentals_sanitized_fields') or []
        if not sanitized_fields:
            return result

        result.fundamental_analysis = "N/A（关键基本面指标存在异常值，已禁用基本面自动解读）"
        if result.confidence_level == "高":
            result.confidence_level = "中"
        result.data_quality_flag = "MISSING"
        warning = f"基本面关键指标异常（{', '.join(sanitized_fields)}）"
        result.risk_warning = f"{result.risk_warning}；{warning}" if result.risk_warning else warning
        return result
    
    def _format_volume(self, volume: Optional[float]) -> str:
        """格式化成交量显示 (ASX适配)"""
        if volume is None:
            return 'N/A'
        if volume >= 1e9:
            return f"{volume / 1e9:.2f} B"
        elif volume >= 1e6:
            return f"{volume / 1e6:.2f} M"
        else:
            return f"{volume:.0f}"
    
    def _format_amount(self, amount: Optional[float]) -> str:
        """格式化成交额显示 (ASX适配)"""
        if amount is None:
            return 'N/A'
        if amount >= 1e9:
            return f"{amount / 1e9:.2f} B AUD"
        elif amount >= 1e6:
            return f"{amount / 1e6:.2f} M AUD"
        else:
            return f"{amount:.0f} AUD"

    def _format_percent(self, value: Optional[float]) -> str:
        """格式化百分比显示"""
        if value is None:
            return 'N/A'
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_price(self, value: Optional[float]) -> str:
        """格式化价格显示"""
        if value is None:
            return 'N/A'
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _build_market_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """构建当日行情快照（展示用）"""
        today = context.get('today', {}) or {}
        realtime = context.get('realtime', {}) or {}
        yesterday = context.get('yesterday', {}) or {}

        prev_close = yesterday.get('close')
        close = today.get('close')
        high = today.get('high')
        low = today.get('low')

        amplitude = None
        change_amount = None
        if prev_close not in (None, 0) and high is not None and low is not None:
            try:
                amplitude = (float(high) - float(low)) / float(prev_close) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                amplitude = None
        if prev_close is not None and close is not None:
            try:
                change_amount = float(close) - float(prev_close)
            except (TypeError, ValueError):
                change_amount = None

        snapshot = {
            "date": context.get('date', '未知'),
            "close": self._format_price(close),
            "open": self._format_price(today.get('open')),
            "high": self._format_price(high),
            "low": self._format_price(low),
            "prev_close": self._format_price(prev_close),
            "pct_chg": self._format_percent(today.get('pct_chg')),
            "change_amount": self._format_price(change_amount),
            "amplitude": self._format_percent(amplitude),
            "volume": self._format_volume(today.get('volume')),
            "amount": self._format_amount(today.get('amount')),
        }

        if realtime:
            snapshot.update({
                "price": self._format_price(realtime.get('price')),
                "volume_ratio": realtime.get('volume_ratio', 'N/A'),
                "turnover_rate": self._format_percent(realtime.get('turnover_rate')),
                "source": getattr(realtime.get('source'), 'value', realtime.get('source', 'N/A')),
            })

        return snapshot

    def _validate_analysis_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """schema gate：仅允许通过校验的数据进入 AnalysisResult 映射。"""
        validated = AnalysisOutputSchema.model_validate(data)
        return validated.model_dump()

    def _extract_json_data(self, response_text: str) -> Dict[str, Any]:
        """从响应中提取并修复 JSON，再转为 dict。"""
        cleaned_text = response_text
        if '```json' in cleaned_text:
            cleaned_text = cleaned_text.replace('```json', '').replace('```', '')
        elif '```' in cleaned_text:
            cleaned_text = cleaned_text.replace('```', '')

        json_start = cleaned_text.find('{')
        json_end = cleaned_text.rfind('}') + 1
        if json_start < 0 or json_end <= json_start:
            raise ValueError("json block not found")

        json_str = cleaned_text[json_start:json_end]
        json_str = self._fix_json_string(json_str)
        return json.loads(json_str)

    def _call_single_attempt_repair(self, prompt: str, generation_config: dict) -> str:
        """补救路径专用：只发起单次请求，不走全量重试/多 provider fallback。"""
        if self._use_anthropic and self._anthropic_client:
            message = self._anthropic_client.messages.create(
                model=self._current_model_name,
                max_tokens=generation_config.get("max_output_tokens", 2048),
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=generation_config.get("temperature", 0.1),
            )
            if message.content and len(message.content) > 0 and hasattr(message.content[0], "text"):
                return message.content[0].text
            raise ValueError("Anthropic repair returned empty response")

        if self._use_openai and self._openai_client:
            response = self._openai_client.chat.completions.create(
                model=self._current_model_name,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=generation_config.get("temperature", 0.1),
                max_tokens=generation_config.get("max_output_tokens", 2048),
            )
            if response and response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
            raise ValueError("OpenAI repair returned empty response")

        if self._model is not None:
            from google.genai import types as genai_types

            response = self._model.models.generate_content(
                model=self._current_model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    temperature=generation_config.get("temperature", 0.1),
                    max_output_tokens=generation_config.get("max_output_tokens", 2048),
                ),
            )
            if response and response.text:
                return response.text
            raise ValueError("Gemini repair returned empty response")

        raise ValueError("No available model for one-shot repair")

    def _repair_and_revalidate(self, response_text: str) -> Optional[Dict[str, Any]]:
        """仅一次定向补救：要求模型修复为合法 JSON 并补齐关键字段。"""
        repair_prompt = f"""请修复下面内容，仅输出一个合法 JSON 对象，不要输出任何额外文字。
必须包含字段：stock_name, sentiment_score(0-100), trend_prediction, operation_advice, confidence_level(高/中/低), analysis_summary, risk_warning。
dashboard 可以省略；如果输出了 dashboard，必须包含 dashboard.core_conclusion.one_sentence, dashboard.data_perspective, dashboard.intelligence, dashboard.battle_plan。

原始内容如下：
{response_text}
"""
        repair_generation_config = {
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 20,
            "max_output_tokens": 2048,
        }
        try:
            repaired_response = self._call_single_attempt_repair(repair_prompt, repair_generation_config)
            repaired_data = self._extract_json_data(repaired_response)
            return self._validate_analysis_output(repaired_data)
        except Exception as e:
            logger.warning(f"schema 补救重试失败: {e}")
            return None

    def _build_schema_fallback_result(
        self,
        response_text: str,
        code: str,
        name: str,
        reason: str,
        parsed_data: Optional[Dict[str, Any]] = None,
    ) -> AnalysisResult:
        """schema gate 失败后的安全降级结果。"""
        safe_data = parsed_data or {}

        def _safe_int_0_100(value: Any) -> Optional[int]:
            try:
                score = int(value)
                return score if 0 <= score <= 100 else None
            except (TypeError, ValueError):
                return None

        def _safe_text(value: Any) -> Optional[str]:
            text = str(value).strip() if value is not None else ""
            return text if text else None

        stock_name = _safe_text(safe_data.get("stock_name")) or name
        sentiment_score = _safe_int_0_100(safe_data.get("sentiment_score"))
        trend_prediction = _safe_text(safe_data.get("trend_prediction"))
        operation_advice = _safe_text(safe_data.get("operation_advice"))
        analysis_summary = _safe_text(safe_data.get("analysis_summary"))
        risk_warning = _safe_text(safe_data.get("risk_warning"))

        return AnalysisResult(
            code=code,
            name=stock_name,
            sentiment_score=sentiment_score if sentiment_score is not None else 50,
            trend_prediction=trend_prediction if trend_prediction is not None else "震荡",
            operation_advice=operation_advice if operation_advice is not None else "观望",
            decision_type="hold",
            confidence_level="低",
            analysis_summary=analysis_summary if analysis_summary is not None else "结构化输出校验失败，已降级为保守结果。",
            risk_warning=risk_warning if risk_warning is not None else "结构化输出未通过校验，请谨慎参考。",
            key_points="schema gate 失败，触发保守降级",
            raw_response=response_text,
            success=True,
            analysis_status='DEGRADED',
            error_message=reason,
        )

    def _parse_response(
        self, 
        response_text: str, 
        code: str, 
        name: str
    ) -> AnalysisResult:
        """
        解析 Gemini 响应（决策仪表盘版）
        
        尝试从响应中提取 JSON 格式的分析结果，包含 dashboard 字段
        如果解析失败，尝试智能提取或返回默认结果
        """
        try:
            data = self._extract_json_data(response_text)
            try:
                data = self._validate_analysis_output(data)
            except ValidationError as schema_error:
                logger.warning(f"schema 校验失败，尝试一次定向补救: {schema_error}")
                repaired_data = self._repair_and_revalidate(response_text)
                if repaired_data is None:
                    return self._build_schema_fallback_result(
                        response_text=response_text,
                        code=code,
                        name=name,
                        reason=f"schema 校验失败: {schema_error}",
                        parsed_data=data,
                    )
                data = repaired_data

            # 提取 dashboard 数据
            dashboard = data.get('dashboard', None)

            # 优先使用 AI 返回的股票名称（如果原名称无效或包含代码）
            ai_stock_name = data.get('stock_name')
            if ai_stock_name and (name.startswith('股票') or name == code or 'Unknown' in name):
                name = ai_stock_name

            # 解析所有字段，使用默认值防止缺失
            # 解析 decision_type，如果没有则根据 operation_advice 推断
            decision_type = data.get('decision_type', '')
            if not decision_type:
                op = data.get('operation_advice', '持有')
                if op in ['买入', '加仓', '强烈买入']:
                    decision_type = 'buy'
                elif op in ['卖出', '减仓', '强烈卖出']:
                    decision_type = 'sell'
                else:
                    decision_type = 'hold'

            # Overlay 因子（原始提取状态允许 UNKNOWN）
            news_sentiment_raw = self._normalize_enum(
                data.get('news_sentiment'),
                {"POS", "NEU", "NEG"},
                default="UNKNOWN",
            )
            event_risk_raw = self._normalize_enum(
                data.get('event_risk'),
                {"LOW", "MEDIUM", "HIGH"},
                default="UNKNOWN",
            )
            sector_tone_raw = self._normalize_enum(
                data.get('sector_tone'),
                {"POS", "NEU", "NEG"},
                default="UNKNOWN",
            )

            return AnalysisResult(
                code=code,
                name=name,
                # 核心指标
                sentiment_score=int(data.get('sentiment_score', 50)),
                trend_prediction=data.get('trend_prediction', '震荡'),
                operation_advice=data.get('operation_advice', '持有'),
                decision_type=decision_type,
                confidence_level=data.get('confidence_level', '中'),
                news_sentiment=self._fold_unknown(news_sentiment_raw, fallback="NEU"),
                event_risk=self._fold_unknown(event_risk_raw, fallback="MEDIUM"),
                sector_tone=self._fold_unknown(sector_tone_raw, fallback="NEU"),
                news_sentiment_raw=news_sentiment_raw,
                event_risk_raw=event_risk_raw,
                sector_tone_raw=sector_tone_raw,
                # 决策仪表盘
                dashboard=dashboard,
                # 走势分析
                trend_analysis=data.get('trend_analysis', ''),
                short_term_outlook=data.get('short_term_outlook', ''),
                medium_term_outlook=data.get('medium_term_outlook', ''),
                # 技术面
                technical_analysis=data.get('technical_analysis', ''),
                ma_analysis=data.get('ma_analysis', ''),
                volume_analysis=data.get('volume_analysis', ''),
                pattern_analysis=data.get('pattern_analysis', ''),
                # 基本面
                fundamental_analysis=data.get('fundamental_analysis', ''),
                sector_position=data.get('sector_position', ''),
                company_highlights=data.get('company_highlights', ''),
                # 情绪面/消息面
                news_summary=data.get('news_summary', ''),
                market_sentiment=data.get('market_sentiment', ''),
                hot_topics=data.get('hot_topics', ''),
                # 综合
                analysis_summary=data.get('analysis_summary', '分析完成'),
                key_points=data.get('key_points', ''),
                risk_warning=data.get('risk_warning', ''),
                buy_reason=data.get('buy_reason', ''),
                # 元数据
                search_performed=data.get('search_performed', False),
                data_sources=data.get('data_sources', '技术面数据'),
                success=True,
                analysis_status='OK',
            )
        
        except ValueError as e:
            logger.warning(f"无法从响应中提取 JSON: {e}，使用原始文本分析")
            return self._parse_text_response(response_text, code, name)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}，尝试从文本提取")
            return self._parse_text_response(response_text, code, name)
    
    def _fix_json_string(self, json_str: str) -> str:
        """修复常见的 JSON 格式问题"""
        import re
        
        # 移除注释
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
        
        # 修复尾随逗号
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # 确保布尔值是小写
        json_str = json_str.replace('True', 'true').replace('False', 'false')
        
        # fix by json-repair
        json_str = repair_json(json_str)
        
        return json_str
    
    def _parse_text_response(
        self, 
        response_text: str, 
        code: str, 
        name: str
    ) -> AnalysisResult:
        """从纯文本响应中尽可能提取分析信息"""
        # 尝试识别关键词来判断情绪
        sentiment_score = 50
        trend = '震荡'
        advice = '持有'
        
        text_lower = response_text.lower()
        
        # 简单的情绪识别
        positive_keywords = ['看多', '买入', '上涨', '突破', '强势', '利好', '加仓', 'bullish', 'buy']
        negative_keywords = ['看空', '卖出', '下跌', '跌破', '弱势', '利空', '减仓', 'bearish', 'sell']
        
        positive_count = sum(1 for kw in positive_keywords if kw in text_lower)
        negative_count = sum(1 for kw in negative_keywords if kw in text_lower)
        
        if positive_count > negative_count + 1:
            sentiment_score = 65
            trend = '看多'
            advice = '买入'
            decision_type = 'buy'
        elif negative_count > positive_count + 1:
            sentiment_score = 35
            trend = '看空'
            advice = '卖出'
            decision_type = 'sell'
        else:
            decision_type = 'hold'
        
        # 截取前500字符作为摘要
        summary = response_text[:500] if response_text else '无分析结果'
        
        return AnalysisResult(
            code=code,
            name=name,
            sentiment_score=sentiment_score,
            trend_prediction=trend,
            operation_advice=advice,
            decision_type=decision_type,
            confidence_level='低',
            news_sentiment="NEU",
            event_risk="MEDIUM",
            sector_tone="NEU",
            news_sentiment_raw="UNKNOWN",
            event_risk_raw="UNKNOWN",
            sector_tone_raw="UNKNOWN",
            analysis_summary=summary,
            key_points='JSON解析失败，仅供参考',
            risk_warning='分析结果可能不准确，建议结合其他信息判断',
            raw_response=response_text,
            success=True,
            analysis_status='DEGRADED',
        )

    @staticmethod
    def _normalize_enum(value: Any, allowed: set[str], default: str) -> str:
        text = str(value or "").strip().upper()
        return text if text in allowed else default

    @staticmethod
    def _fold_unknown(value: str, fallback: str) -> str:
        return fallback if str(value).upper() == "UNKNOWN" else value
    
    def batch_analyze(
        self, 
        contexts: List[Dict[str, Any]],
        delay_between: float = 2.0
    ) -> List[AnalysisResult]:
        """
        批量分析多只股票
        
        注意：为避免 API 速率限制，每次分析之间会有延迟
        
        Args:
            contexts: 上下文数据列表
            delay_between: 每次分析之间的延迟（秒）
            
        Returns:
            AnalysisResult 列表
        """
        results = []
        
        for i, context in enumerate(contexts):
            if i > 0:
                logger.debug(f"等待 {delay_between} 秒后继续...")
                time.sleep(delay_between)
            
            result = self.analyze(context)
            results.append(result)
        
        return results


    def generate_portfolio_summary(self, results: list) -> str:
        """
        基于确定性动作字段生成组合层面的摘要。
        输入：AnalysisResult 列表
        输出：纯文本的组合决策摘要（Markdown格式）
        """
        if not results:
            return ""

        ordered_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        final_counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
        action_counts = {"OPEN": 0, "ADD": 0, "HOLD": 0, "REDUCE": 0, "CLOSE": 0}
        total_delta = 0.0
        total_turnover = 0.0
        target_weight_sum = 0.0

        for r in ordered_results:
            final_decision = str(getattr(r, "final_decision", "") or "").upper()
            if final_decision not in final_counts:
                final_decision = "HOLD"
            final_counts[final_decision] += 1

            position_action = str(getattr(r, "position_action", "") or "").upper()
            if position_action not in action_counts:
                position_action = "HOLD"
            action_counts[position_action] += 1

            target_weight = float(getattr(r, "target_weight", 0.0) or 0.0)
            delta_amount = float(getattr(r, "delta_amount", 0.0) or 0.0)
            target_weight_sum += target_weight
            total_delta += delta_amount
            total_turnover += abs(delta_amount)

        avg_target_weight = target_weight_sum / len(ordered_results) if ordered_results else 0.0
        execution_action_count = (
            action_counts["OPEN"] + action_counts["ADD"] + action_counts["REDUCE"] + action_counts["CLOSE"]
        )
        has_execution_actions = execution_action_count > 0
        has_meaningful_turnover = total_turnover > 0.0
        if total_delta > 0:
            net_delta_label = "整体偏加仓"
        elif total_delta < 0:
            net_delta_label = "整体偏减仓"
        elif has_execution_actions or has_meaningful_turnover:
            net_delta_label = "有换仓/再平衡动作，整体仓位中性"
        else:
            net_delta_label = "以观察为主"
        caution_label = "组合整体偏谨慎" if action_counts["HOLD"] >= max(action_counts["OPEN"] + action_counts["ADD"], action_counts["REDUCE"] + action_counts["CLOSE"]) else "组合存在明确调仓方向"

        return "\n".join([
            "### 组合动作总览（今日建议）",
            f"- 建议新开仓：{action_counts['OPEN']} | 加仓：{action_counts['ADD']} | 持有观察：{action_counts['HOLD']} | 减仓：{action_counts['REDUCE']} | 清仓：{action_counts['CLOSE']}",
            "",
            "### 组合仓位与调仓强度（计划口径）",
            f"- 平均目标仓位（逐标的平均）：{avg_target_weight:.2%}",
            f"- 计划调仓净额：{total_delta:,.2f}（{net_delta_label}）",
            f"- 计划调仓总额（绝对值）：{total_turnover:,.2f}",
            f"- 一句话解读：{caution_label}。",
        ])

# 便捷函数
def get_analyzer() -> GeminiAnalyzer:
    """获取 LLM 分析器实例"""
    return GeminiAnalyzer()


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    # 模拟上下文数据
    test_context = {
        'code': '600519',
        'date': '2026-01-09',
        'today': {
            'open': 1800.0,
            'high': 1850.0,
            'low': 1780.0,
            'close': 1820.0,
            'volume': 10000000,
            'amount': 18200000000,
            'pct_chg': 1.5,
            'ma5': 1810.0,
            'ma10': 1800.0,
            'ma20': 1790.0,
            'volume_ratio': 1.2,
        },
        'ma_status': '多头排列 📈',
        'volume_change_ratio': 1.3,
        'price_change_ratio': 1.5,
    }
    
    analyzer = GeminiAnalyzer()
    
    if analyzer.is_available():
        print("=== AI 分析测试 ===")
        result = analyzer.analyze(test_context)
        print(f"分析结果: {result.to_dict()}")
    else:
        print("Gemini API 未配置，跳过测试")
