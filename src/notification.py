# -*- coding: utf-8 -*-
"""
===================================
ASX-first 自选股智能分析系统 - 通知层
===================================

职责：
1. 汇总分析结果生成日报
2. 支持 Markdown 格式输出
3. 多渠道推送（自动识别）：
   - 企业微信 Webhook
   - 飞书 Webhook
   - Telegram Bot
   - 邮件 SMTP
   - Pushover（手机/桌面推送）
"""
import base64
import hashlib
import hmac
import logging
import json
import math
import smtplib
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.header import Header
from email.utils import formataddr
from enum import Enum

import requests
try:
    import discord
    discord_available = True
except ImportError:
    discord_available = False

from src.config import get_config
from src.analyzer import AnalysisResult
from src.asx_announcements import ASXAnnouncementCheck, build_asx_announcement_checks, is_asx_ticker
from src.core.utils import is_failed_analysis
from src.core.validator import normalize_validation_status
from src.security_logging import redact_log_text, summarize_http_response_for_log
from src.daily_decision_summary import (
    DEFAULT_ACTIONABLE_DELTA_AMOUNT,
    build_daily_decision_summary,
    render_preopen_decision_appendix,
    render_preopen_decision_dashboard,
)
from src.conditional_plan import (
    build_conditional_plan_points,
    format_conditional_plan_points_inline,
    render_conditional_plan_points_markdown,
)
from src.final_action_display import build_final_action_display
from src.core.risk_sizing import risk_sizing_settings_from_config
from src.formatters import (
    format_feishu_markdown,
    markdown_to_archive_html_document,
    markdown_to_html_document,
)
from src.stock_code import canonical_stock_code
from src import notification_formatting
from src.notification_recommended_action_builders import (
    build_recommended_actions_table,
)
from src.notification_portfolio_builders import (
    build_holdings_audit_table,
    build_report_time_portfolio_overview,
    build_section_c_reconciliation_lines,
    build_simulated_target_allocation_table,
)
from src.notification_dashboard_observation_builders import (
    build_dashboard_observation_appendix_lines,
)
from src.storage import get_db
from bot.models import BotMessage

logger = logging.getLogger(__name__)


# WeChat Work image msgtype limit ~2MB (base64 payload)
WECHAT_IMAGE_MAX_BYTES = 2 * 1024 * 1024


def _get_effective_decision(result: Any) -> str:
    """获取用于统计的主决策（优先 final_decision，兼容 decision_type）。"""
    final_decision = str(getattr(result, 'final_decision', '') or '').upper()
    if final_decision in ('BUY', 'HOLD', 'SELL'):
        return final_decision
    decision_type = str(getattr(result, 'decision_type', '') or '').lower()
    if decision_type == 'buy':
        return 'BUY'
    if decision_type == 'sell':
        return 'SELL'
    return 'HOLD'


def _normalize_position_action(result: Any) -> str:
    """Return normalized position action."""
    action = str(getattr(result, 'position_action', '') or '').upper()
    if action in ('OPEN', 'ADD', 'HOLD', 'REDUCE', 'CLOSE'):
        return action
    return ''


def _decision_from_position_action(position_action: str) -> Optional[str]:
    """Map position_action to BUY/HOLD/SELL decision bucket."""
    mapping = {
        'OPEN': 'BUY',
        'ADD': 'BUY',
        'HOLD': 'HOLD',
        'REDUCE': 'SELL',
        'CLOSE': 'SELL',
    }
    return mapping.get(position_action)


def _decision_to_canonical_advice(decision: str) -> str:
    """Map BUY/HOLD/SELL to canonical user-facing advice wording."""
    return {
        'BUY': '买入/加仓',
        'HOLD': '持有/观望',
        'SELL': '减仓/卖出',
    }.get(str(decision or '').upper(), '持有/观望')


def _decision_to_signal_emoji(decision: str) -> str:
    """Map BUY/HOLD/SELL to deterministic signal emoji."""
    return {
        'BUY': '🟢',
        'HOLD': '⚪',
        'SELL': '🔴',
    }.get(str(decision or '').upper(), '⚪')


def _normalize_analysis_status(result: Any) -> str:
    """Normalize outer analysis status to OK/DEGRADED/FAILED."""
    if not bool(getattr(result, 'success', True)):
        return 'FAILED'
    status = str(getattr(result, 'analysis_status', '') or '').strip().upper()
    if status in ('OK', 'DEGRADED', 'FAILED'):
        return status
    return 'OK'


def _normalize_validation_status(result: Any) -> str:
    """Normalize validation status to the current PASS/BLOCK contract."""
    return normalize_validation_status(getattr(result, 'validation_status', None))


def _is_validation_blocked(result: Any) -> bool:
    return _normalize_validation_status(result) == 'BLOCK'


def _get_validation_issues(result: Any) -> List[str]:
    issues = getattr(result, 'validation_issues', None)
    if not isinstance(issues, list):
        return []
    return [str(item).strip() for item in issues if str(item).strip()]


class NotificationChannel(Enum):
    """通知渠道类型"""
    WECHAT = "wechat"      # 企业微信
    FEISHU = "feishu"      # 飞书
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # 邮件
    PUSHOVER = "pushover"  # Pushover（手机/桌面推送）
    PUSHPLUS = "pushplus"  # PushPlus（国内推送服务）
    SERVERCHAN3 = "serverchan3"  # Server酱3（手机APP推送服务）
    CUSTOM = "custom"      # 自定义 Webhook
    DISCORD = "discord"    # Discord 机器人 (Bot)
    ASTRBOT = "astrbot"
    UNKNOWN = "unknown"    # 未知


# SMTP 服务器配置（自动识别）
SMTP_CONFIGS = {
    # QQ邮箱
    "qq.com": {"server": "smtp.qq.com", "port": 465, "ssl": True},
    "foxmail.com": {"server": "smtp.qq.com", "port": 465, "ssl": True},
    # 网易邮箱
    "163.com": {"server": "smtp.163.com", "port": 465, "ssl": True},
    "126.com": {"server": "smtp.126.com", "port": 465, "ssl": True},
    # Gmail
    "gmail.com": {"server": "smtp.gmail.com", "port": 587, "ssl": False},
    # Outlook
    "outlook.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "hotmail.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "live.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    # 新浪
    "sina.com": {"server": "smtp.sina.com", "port": 465, "ssl": True},
    # 搜狐
    "sohu.com": {"server": "smtp.sohu.com", "port": 465, "ssl": True},
    # 阿里云
    "aliyun.com": {"server": "smtp.aliyun.com", "port": 465, "ssl": True},
    # 139邮箱
    "139.com": {"server": "smtp.139.com", "port": 465, "ssl": True},
}


class ChannelDetector:
    """
    渠道检测器 - 简化版
    
    根据配置直接判断渠道类型（不再需要 URL 解析）
    """
    
    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """获取渠道中文名称"""
        names = {
            NotificationChannel.WECHAT: "企业微信",
            NotificationChannel.FEISHU: "飞书",
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "邮件",
            NotificationChannel.PUSHOVER: "Pushover",
            NotificationChannel.PUSHPLUS: "PushPlus",
            NotificationChannel.SERVERCHAN3: "Server酱3",
            NotificationChannel.CUSTOM: "自定义Webhook",
            NotificationChannel.DISCORD: "Discord机器人",
            NotificationChannel.ASTRBOT: "ASTRBOT机器人",
            NotificationChannel.UNKNOWN: "未知渠道",
        }
        return names.get(channel, "未知渠道")


class NotificationService:
    """
    通知服务
    
    职责：
    1. 生成 Markdown 格式的分析日报
    2. 向所有已配置的渠道推送消息（多渠道并发）
    3. 支持本地保存日报
    
    支持的渠道：
    - 企业微信 Webhook
    - 飞书 Webhook
    - Telegram Bot
    - 邮件 SMTP
    - Pushover（手机/桌面推送）
    
    注意：所有已配置的渠道都会收到推送
    """

    AI_POSITION_REFERENCE_DOWNGRADE = "AI仓位测算已降级为非执行参考；执行数量以主动作目标仓位/模拟调仓为准"
    AI_NUMERIC_QUANTITY_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    AUDIT_APPENDIX_HEADING = "## 详情 / 审计附录"
    
    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        初始化通知服务
        
        检测所有已配置的渠道，推送时会向所有渠道发送
        """
        config = get_config()
        self._report_timezone = getattr(config, "market_timezone", "Australia/Sydney")
        self._source_message = source_message
        self._context_channels: List[str] = []
        self._last_daily_decision_summary: Optional[Dict[str, Any]] = None
        self._last_report_date: Optional[str] = None
        
        # 各渠道的 Webhook URL
        self._wechat_url = config.wechat_webhook_url
        self._feishu_url = getattr(config, 'feishu_webhook_url', None)

        # 微信消息类型配置
        self._wechat_msg_type = getattr(config, 'wechat_msg_type', 'markdown')
        # Telegram 配置
        self._telegram_config = {
            'bot_token': getattr(config, 'telegram_bot_token', None),
            'chat_id': getattr(config, 'telegram_chat_id', None),
            'message_thread_id': getattr(config, 'telegram_message_thread_id', None),
        }
        
        # 邮件配置
        self._email_config = {
            'sender': config.email_sender,
            'sender_name': getattr(config, 'email_sender_name', 'daily_stock_analysis股票分析助手'),
            'password': config.email_password,
            'receivers': config.email_receivers or ([config.email_sender] if config.email_sender else []),
        }
        # Stock-to-email group routing (Issue #268)
        self._stock_email_groups = getattr(config, 'stock_email_groups', None) or []

        # Pushover 配置
        self._pushover_config = {
            'user_key': getattr(config, 'pushover_user_key', None),
            'api_token': getattr(config, 'pushover_api_token', None),
        }

        # PushPlus 配置
        self._pushplus_token = getattr(config, 'pushplus_token', None)
       
        # Server酱3 配置
        self._serverchan3_sendkey = getattr(config, 'serverchan3_sendkey', None)
        self._serverchan3_sendkey_2 = getattr(config, 'serverchan3_sendkey_2', None)

        # 自定义 Webhook 配置
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        self._custom_webhook_bearer_token = getattr(config, 'custom_webhook_bearer_token', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)

        # Discord 配置
        self._discord_config = {
            'bot_token': getattr(config, 'discord_bot_token', None),
            'channel_id': getattr(config, 'discord_main_channel_id', None),
            'webhook_url': getattr(config, 'discord_webhook_url', None),
        }

        self._astrbot_config = {
            'astrbot_url': getattr(config, 'astrbot_url', None),
            'astrbot_token': getattr(config, 'astrbot_token', None),
        }
        
        # 消息长度限制（字节）
        self._feishu_max_bytes = getattr(config, 'feishu_max_bytes', 20000)
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)

        # Markdown 转图片（Issue #289）
        self._markdown_to_image_channels = set(
            getattr(config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            config, 'markdown_to_image_max_chars', 15000
        )

        # 仅分析结果摘要（Issue #262）：true 时只推送汇总，不含个股详情
        self._report_summary_only = getattr(config, 'report_summary_only', False)

        # 检测所有已配置的渠道
        self._available_channels = self._detect_all_channels()
        if self._has_context_channel():
            self._context_channels.append("钉钉会话")
        
        if not self._available_channels and not self._context_channels:
            logger.warning("未配置有效的通知渠道，将不发送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"已配置 {len(channel_names)} 个通知渠道：{', '.join(channel_names)}")

    def _now_in_report_tz(self) -> datetime:
        """Return timezone-aware now using configured report/market timezone."""
        try:
            return datetime.now(ZoneInfo(self._report_timezone))
        except Exception:
            return datetime.now()

    def _default_report_date(self, now: Optional[datetime] = None) -> str:
        """Return the report generation/display date in the configured report timezone."""
        report_now = now or self._now_in_report_tz()
        return report_now.strftime("%Y-%m-%d")

    def _remember_report_date(self, report_date: str) -> None:
        self._last_report_date = report_date
    
    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        检测所有已配置的渠道
        
        Returns:
            已配置的渠道列表
        """
        channels = []
        
        # 企业微信
        if self._wechat_url:
            channels.append(NotificationChannel.WECHAT)
        
        # 飞书
        if self._feishu_url:
            channels.append(NotificationChannel.FEISHU)
        
        # Telegram
        if self._is_telegram_configured():
            channels.append(NotificationChannel.TELEGRAM)
        
        # 邮件
        if self._is_email_configured():
            channels.append(NotificationChannel.EMAIL)
        
        # Pushover
        if self._is_pushover_configured():
            channels.append(NotificationChannel.PUSHOVER)

        # PushPlus
        if self._pushplus_token:
            channels.append(NotificationChannel.PUSHPLUS)

       # Server酱3
        if self._serverchan3_sendkey:
            channels.append(NotificationChannel.SERVERCHAN3)
       
        # 自定义 Webhook
        if self._custom_webhook_urls:
            channels.append(NotificationChannel.CUSTOM)
        
        # Discord
        if self._is_discord_configured():
            channels.append(NotificationChannel.DISCORD)
        # AstrBot
        if self._is_astrbot_configured():
            channels.append(NotificationChannel.ASTRBOT)
        return channels
    
    def _is_telegram_configured(self) -> bool:
        """检查 Telegram 配置是否完整"""
        return bool(self._telegram_config['bot_token'] and self._telegram_config['chat_id'])
    
    def _is_discord_configured(self) -> bool:
        """检查 Discord 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 Webhook 或完整的 Bot Token+Channel，即视为可用
        bot_ok = bool(self._discord_config['bot_token'] and self._discord_config['channel_id'])
        webhook_ok = bool(self._discord_config['webhook_url'])
        return bot_ok or webhook_ok

    def _is_astrbot_configured(self) -> bool:
        """检查 AstrBot 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 URL，即视为可用
        url_ok = bool(self._astrbot_config['astrbot_url'])
        return url_ok

    def _is_email_configured(self) -> bool:
        """检查邮件配置是否完整（只需邮箱和授权码）"""
        return bool(self._email_config['sender'] and self._email_config['password'])

    def get_receivers_for_stocks(self, stock_codes: List[str]) -> List[str]:
        """
        Look up email receivers for given stock codes based on stock_email_groups.
        Returns union of receivers for all matching groups; falls back to default if none match.
        """
        if not stock_codes or not self._stock_email_groups:
            return self._email_config['receivers']
        seen: set = set()
        result: List[str] = []
        for stocks, emails in self._stock_email_groups:
            for code in stock_codes:
                if code in stocks:
                    for e in emails:
                        if e not in seen:
                            seen.add(e)
                            result.append(e)
                    break
        return result if result else self._email_config['receivers']

    def get_all_email_receivers(self) -> List[str]:
        """
        Return union of all configured email receivers (all groups + default).
        Used for market review which should go to everyone.
        """
        seen: set = set()
        result: List[str] = []
        for _, emails in self._stock_email_groups:
            for e in emails:
                if e not in seen:
                    seen.add(e)
                    result.append(e)
        for e in self._email_config['receivers']:
            if e not in seen:
                seen.add(e)
                result.append(e)
        return result
    
    def _is_pushover_configured(self) -> bool:
        """检查 Pushover 配置是否完整"""
        return bool(self._pushover_config['user_key'] and self._pushover_config['api_token'])
    
    def is_available(self) -> bool:
        """检查通知服务是否可用（至少有一个渠道或上下文渠道）"""
        return len(self._available_channels) > 0 or self._has_context_channel()
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """获取所有已配置的渠道"""
        return self._available_channels
    
    def get_channel_names(self) -> str:
        """获取所有已配置渠道的名称"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        if self._has_context_channel():
            names.append("钉钉会话")
        return ', '.join(names)

    def _has_context_channel(self) -> bool:
        """判断是否存在基于消息上下文的临时渠道（如钉钉会话、飞书会话）"""
        return (
            self._extract_dingtalk_session_webhook() is not None
            or self._extract_feishu_reply_info() is not None
        )

    def _extract_dingtalk_session_webhook(self) -> Optional[str]:
        """从来源消息中提取钉钉会话 Webhook（用于 Stream 模式回复）"""
        if not isinstance(self._source_message, BotMessage):
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        if not isinstance(raw_data, dict):
            return None
        session_webhook = (
            raw_data.get("_session_webhook")
            or raw_data.get("sessionWebhook")
            or raw_data.get("session_webhook")
            or raw_data.get("session_webhook_url")
        )
        if not session_webhook and isinstance(raw_data.get("headers"), dict):
            session_webhook = raw_data["headers"].get("sessionWebhook")
        return session_webhook

    def _extract_feishu_reply_info(self) -> Optional[Dict[str, str]]:
        """
        从来源消息中提取飞书回复信息（用于 Stream 模式回复）
        
        Returns:
            包含 chat_id 的字典，或 None
        """
        if not isinstance(self._source_message, BotMessage):
            return None
        if getattr(self._source_message, "platform", "") != "feishu":
            return None
        chat_id = getattr(self._source_message, "chat_id", "")
        if not chat_id:
            return None
        return {"chat_id": chat_id}

    def send_to_context(self, content: str) -> bool:
        """
        向基于消息上下文的渠道发送消息（例如钉钉 Stream 会话）
        
        Args:
            content: Markdown 格式内容
        """
        return self._send_via_source_context(content)

    @staticmethod
    def _has_valid_price(value: Any) -> bool:
        if value in (None, "", "N/A", "-"):
            return False
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _is_realtime_price_available(result: AnalysisResult) -> bool:
        snapshot = getattr(result, "market_snapshot", None) or {}
        return NotificationService._has_valid_price(snapshot.get("price")) or NotificationService._has_valid_price(
            getattr(result, "current_price", None)
        )

    @staticmethod
    def _classify_price_basis(result: AnalysisResult) -> str:
        """Classify price basis into: realtime / latest_close / close_only."""
        explicit_source = str(getattr(result, "execution_price_source", "") or "").strip().lower()
        if explicit_source == "legacy_report_time":
            return "close_only"
        if explicit_source in {"realtime", "latest_close", "close_only"}:
            return explicit_source

        if NotificationService._is_realtime_price_available(result):
            return "realtime"
        close_value = (getattr(result, "market_snapshot", None) or {}).get("close")
        if NotificationService._has_valid_price(close_value):
            return "latest_close"
        return "close_only"

    @staticmethod
    def _format_validation_issue_text(result: AnalysisResult) -> str:
        issues = _get_validation_issues(result)
        if not issues:
            return "验证未通过，但未提供具体原因。"
        readable: List[str] = []
        for issue in issues:
            text = NotificationService._human_validation_issue_text(issue)
            if text and text not in readable:
                readable.append(text)
        return "；".join(readable) if readable else "验证未通过，需人工复核。"

    @staticmethod
    def _human_validation_issue_text(issue: Any) -> str:
        text = str(issue or "").strip()
        if not text:
            return ""
        compact = re.sub(r"\s+", "", text.lower())
        if "analysis_status=failed" in compact or "analysisstatus=failed" in compact:
            return "分析失败，建议重跑后再判断。"
        if "analysis_status=degraded" in compact or "analysisstatus=degraded" in compact:
            return "分析结果不完整，需补数据后复核。"
        if "validation_status=block" in compact or "validationstatus=block" in compact or "validationblock" in compact:
            return "验证未通过，已暂停动作，仅观察。"
        if any(token in compact for token in ("text_fallback", "schema", "json")):
            return "AI 输出格式异常，需补数据后复核。"
        return text

    def _build_data_baseline_lines(
        self,
        results: List[AnalysisResult],
        generated_at: datetime,
        *,
        title: str = "## 🕒 数据时间基准",
    ) -> List[str]:
        """构建用户可读的时间基准说明（仅展示口径，不改变数据流）。"""
        daily_anchor = "最新可用日线（通常为昨日收盘）"
        snapshot_dates = sorted(
            {
                str((getattr(r, "market_snapshot", None) or {}).get("date")).strip()
                for r in results
                if str((getattr(r, "market_snapshot", None) or {}).get("date", "")).strip()
                and str((getattr(r, "market_snapshot", None) or {}).get("date")).strip() != "未知"
            }
        )
        has_mixed_dates = len(snapshot_dates) > 1
        if len(snapshot_dates) == 1:
            daily_anchor = f"{snapshot_dates[0]} 日线（收盘口径）"
        elif has_mixed_dates:
            daily_anchor = "多只股票日线日期不一致（混合日期）"

        news_cutoff = generated_at.strftime("%Y-%m-%d %H:%M")
        normal_results = [r for r in results if not is_failed_analysis(r)]
        failed_results = [r for r in results if is_failed_analysis(r)]
        blocked_results = [r for r in normal_results if _is_validation_blocked(r)]
        total_count = len(normal_results)
        basis_counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
        for result in normal_results:
            basis_counts[self._classify_price_basis(result)] += 1
        realtime_count = basis_counts["realtime"]
        latest_close_count = basis_counts["latest_close"]
        close_only_count = basis_counts["close_only"]
        has_realtime = realtime_count > 0

        lines = [
            title,
            "",
            f"- 报告生成时间：**{generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}**。",
            f"- 技术基准日说明：本次技术判断基于 **{daily_anchor}**。",
            f"- 新闻信息更新至：**{news_cutoff}**。",
            (
                f"- 价格口径披露：**{realtime_count}/{total_count}** 只使用实时价格，"
                f"**{latest_close_count}/{total_count}** 只使用最新收盘，"
                f"**{close_only_count}/{total_count}** 只按收盘口径。"
            ),
        ]
        if has_mixed_dates:
            lines.append(f"- 日期说明：本次技术面涉及多个日线日期（{', '.join(snapshot_dates)}）。")
        if has_realtime:
            lines.append(
                f"- 说明：当前报告存在“旧日线信号 + 新实时价格”混用（实时 {realtime_count} 只，非实时 {latest_close_count + close_only_count} 只），已在此披露。"
            )
        elif total_count > 0 and close_only_count == total_count:
            lines.append(
                "- 开盘前阅读提示：本报告按上一交易日收盘后的计划口径生成；开盘后执行前请二次确认最新价格。"
            )
        lines.append("")
        return lines

    def _get_price_basis_label(self, result: AnalysisResult) -> str:
        """返回单只股票的价格口径标签（仅用于展示层披露）。"""
        return notification_formatting.format_price_basis_label(self._classify_price_basis(result))

    def _get_price_metric_label(self, result: AnalysisResult) -> str:
        """返回价格字段在当前口径下的用户可读标签。"""
        basis = self._classify_price_basis(result)
        if basis == "realtime":
            return "实时参考价"
        if basis == "latest_close":
            return "最新收盘价"
        return "收盘基准价"
    
    def generate_daily_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成 Markdown 格式的日报（详细版）

        Args:
            results: 分析结果列表
            report_date: 报告日期（默认今天）

        Returns:
            Markdown 格式的日报内容
        """
        if report_date is None:
            report_date = self._default_report_date()
        self._remember_report_date(report_date)
        generated_at = self._now_in_report_tz()

        # 标题
        report_lines = [
            f"# 📅 {report_date} 股票智能分析报告",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 报告生成时间：{generated_at.strftime('%H:%M:%S')}",
            "",
            "---",
            "",
        ]
        report_lines.extend(self._build_data_baseline_lines(results, generated_at))
        
        # 按评分排序（高分在前）
        sorted_results = sorted(
            results, 
            key=lambda x: x.sentiment_score, 
            reverse=True
        )
        normal_results, actionable_results, blocked_results = self._split_completed_results(sorted_results)
        failed_results = [r for r in sorted_results if is_failed_analysis(r)]
        try:
            overview_source = get_db().get_portfolio_overview()
        except Exception:
            overview_source = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}
        overview = self._build_report_time_portfolio_overview(
            overview=overview_source,
            results=results,
        )
        daily_summary = self.build_daily_decision_summary(
            results=sorted_results,
            report_date=report_date,
            generated_at=generated_at,
            overview=overview,
        )
        self._last_daily_decision_summary = daily_summary

        counts = self._execution_action_counts(daily_summary)
        effective_actionable_results = self._effective_actionable_results(actionable_results)
        display_actionable_results = self._display_actionable_results(actionable_results)
        avg_score = sum(r.sentiment_score for r in actionable_results) / len(actionable_results) if actionable_results else 0
        
        report_lines.extend([
            "## 📊 操作建议汇总",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 执行动作 买入 | **{counts['buy']}** 只 |",
            f"| 执行动作 加仓 | **{counts['add']}** 只 |",
            f"| 执行动作 减仓 | **{counts['reduce']}** 只 |",
            f"| 执行动作 清仓 | **{counts['close']}** 只 |",
            f"| 持有观察 | **{counts['hold_watch']}** 只 |",
            f"| 验证阻断 | **{counts['blocked']}** 只 |",
            f"| 📈 平均看多评分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
        ])
        
        # Issue #262: summary_only 时仅输出摘要，跳过个股详情
        if self._report_summary_only:
            report_lines.extend(["## 📊 分析结果摘要", ""])
            for r in display_actionable_results:
                _, emoji, _ = self._get_signal_level(r)
                report_lines.append(
                    f"{emoji} **{r.name}({r.code})**: {self._get_canonical_operation_advice(r)} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction} | 价格基准：{self._get_price_basis_label(r)}"
                )
            if blocked_results:
                report_lines.extend(["", "## ⚠️ 不可决策（仅观察）", ""])
                for r in blocked_results:
                    report_lines.append(self._format_blocked_result_line(r, truncate=120))
        else:
            report_lines.extend(["## 📈 个股详细分析", ""])
            # 逐个股票的详细分析
            for result in actionable_results:
                _, emoji, _ = self._get_signal_level(result)
                confidence_stars = result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'
                
                report_lines.extend([
                    f"### {emoji} {result.name} ({result.code})",
                    "",
                    f"**价格基准**：{self._get_price_basis_label(result)}",
                    "",
                    f"**操作建议：{self._get_canonical_operation_advice(result)}** | **综合评分：{result.sentiment_score}分** | **趋势预测：{result.trend_prediction}** | **置信度：{confidence_stars}**",
                    "",
                ])

                self._append_market_snapshot(report_lines, result)
                
                # 核心看点
                if hasattr(result, 'key_points') and result.key_points:
                    report_lines.extend([
                        f"**🎯 核心看点**：{result.key_points}",
                        "",
                    ])
                
                # 买入/卖出理由
                if hasattr(result, 'buy_reason') and result.buy_reason:
                    report_lines.extend([
                        f"**💡 操作理由**：{self._sanitize_user_facing_ai_text(result, result.buy_reason, strip_position_sizing=False)}",
                        "",
                    ])
                
                # 走势分析
                if hasattr(result, 'trend_analysis') and result.trend_analysis:
                    report_lines.extend([
                        "#### 📉 走势分析",
                        f"{result.trend_analysis}",
                        "",
                    ])
                
                # 短期/中期展望
                outlook_lines = []
                if hasattr(result, 'short_term_outlook') and result.short_term_outlook:
                    outlook_lines.append(f"- **短期（1-3日）**：{result.short_term_outlook}")
                if hasattr(result, 'medium_term_outlook') and result.medium_term_outlook:
                    outlook_lines.append(f"- **中期（1-2周）**：{result.medium_term_outlook}")
                if outlook_lines:
                    report_lines.extend([
                        "#### 🔮 市场展望",
                        *outlook_lines,
                        "",
                    ])
                
                # 技术面分析
                tech_lines = []
                if result.technical_analysis:
                    tech_lines.append(
                        f"**综合**：{self._guard_technical_analysis_volume_commentary(result, result.technical_analysis)}"
                    )
                if hasattr(result, 'ma_analysis') and result.ma_analysis:
                    tech_lines.append(f"**均线**：{result.ma_analysis}")
                if hasattr(result, 'volume_analysis') and result.volume_analysis:
                    tech_lines.append(f"**量能**：{self._guard_volume_commentary(result, result.volume_analysis)}")
                if hasattr(result, 'pattern_analysis') and result.pattern_analysis:
                    tech_lines.append(f"**形态**：{result.pattern_analysis}")
                if tech_lines:
                    report_lines.extend([
                        "#### 📊 技术面分析",
                        *tech_lines,
                        "",
                    ])
                
                # 基本面分析
                fund_lines = []
                if hasattr(result, 'fundamental_analysis') and result.fundamental_analysis:
                    fund_lines.append(result.fundamental_analysis)
                if hasattr(result, 'sector_position') and result.sector_position:
                    fund_lines.append(f"**板块地位**：{result.sector_position}")
                if hasattr(result, 'company_highlights') and result.company_highlights:
                    fund_lines.append(f"**公司亮点**：{result.company_highlights}")
                if fund_lines:
                    report_lines.extend([
                        "#### 🏢 基本面分析",
                        *fund_lines,
                        "",
                    ])
                
                # 消息面/情绪面
                news_lines = []
                if result.news_summary:
                    news_lines.append(f"**新闻摘要**：{result.news_summary}")
                if hasattr(result, 'market_sentiment') and result.market_sentiment:
                    news_lines.append(f"**市场情绪**：{result.market_sentiment}")
                if hasattr(result, 'hot_topics') and result.hot_topics:
                    news_lines.append(f"**相关热点**：{result.hot_topics}")
                if news_lines:
                    report_lines.extend([
                        "#### 📰 消息面/情绪面",
                        *news_lines,
                        "",
                    ])
                
                # 综合分析
                if result.analysis_summary:
                    report_lines.extend([
                        "#### 📝 综合分析",
                        self._sanitize_user_facing_ai_text(result, result.analysis_summary, strip_position_sizing=False),
                        "",
                    ])
                
                # 风险提示
                if hasattr(result, 'risk_warning') and result.risk_warning:
                    report_lines.extend([
                        f"⚠️ **风险提示**：{self._sanitize_user_facing_risk_text(result, result.risk_warning)}",
                        "",
                    ])
                
                # 数据来源说明
                if hasattr(result, 'search_performed') and result.search_performed:
                    report_lines.append("*🔍 已执行联网搜索*")
                if hasattr(result, 'data_sources') and result.data_sources:
                    report_lines.append(f"*📋 数据来源：{result.data_sources}*")
                
                # 错误信息（如果有）
                if not result.success and result.error_message:
                    report_lines.extend([
                        "",
                        f"❌ **分析异常**：{result.error_message[:100]}",
                    ])
                
                report_lines.extend([
                    "",
                    "---",
                    "",
                ])
            if blocked_results:
                report_lines.extend(["## ⚠️ 暂不决策（仅观察）", ""])
                for result in blocked_results:
                    report_lines.extend(self._format_non_actionable_report_lines(result))
                    report_lines.extend(["", "---", ""])
        
        if failed_results:
            report_lines.extend([
                "",
                "## ⚠️ 暂不决策（分析失败）",
                "",
            ])
            for result in failed_results:
                report_lines.extend(self._format_non_actionable_report_lines(result, failed=True))
                report_lines.extend(["", "---", ""])

        # 底部信息（去除免责声明）
        report_lines.extend([
            "",
            f"*报告生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    @staticmethod
    def _escape_md(name: str) -> str:
        """Escape markdown special characters in stock names (e.g. *ST → \\*ST)."""
        return name.replace('*', r'\*') if name else name

    @staticmethod
    def _clean_sniper_value(value: Any) -> str:
        """Normalize sniper point values and remove redundant label prefixes."""
        if value is None:
            return 'N/A'
        if isinstance(value, (int, float)):
            return str(value)
        if not isinstance(value, str):
            return str(value)
        if not value or value == 'N/A':
            return value
        prefixes = ['理想买入点：', '次优买入点：', '止损位：', '目标位：',
                     '理想买入点:', '次优买入点:', '止损位:', '目标位:']
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    @staticmethod
    def _technical_basis_date_for(result: AnalysisResult) -> str:
        snapshot = getattr(result, "market_snapshot", None) or {}
        if isinstance(snapshot, dict):
            return str(snapshot.get("date") or snapshot.get("as_of_date") or "unknown")
        return "unknown"

    def _build_conditional_plan_points(
        self,
        result: AnalysisResult,
        sniper_points: Optional[Dict[str, Any]] = None,
    ):
        """Build non-executable conditional plan points for report display."""
        raw_points = sniper_points or {}
        return build_conditional_plan_points(
            raw_points,
            price_basis=getattr(result, "execution_price_source", "close_only"),
            technical_basis_date=self._technical_basis_date_for(result),
            validation_status=getattr(result, "validation_status", "PASS"),
            reference_price=self._conditional_plan_reference_price(result),
            technical_levels=self._conditional_plan_technical_levels(result),
        )

    @staticmethod
    def _conditional_plan_reference_price(result: AnalysisResult) -> Optional[float]:
        snapshot = getattr(result, "market_snapshot", None) or {}
        if isinstance(snapshot, dict):
            for key in ("close", "price", "prev_close"):
                parsed = NotificationService._to_positive_float(snapshot.get(key))
                if parsed is not None:
                    return parsed
        return NotificationService._to_positive_float(getattr(result, "current_price", None))

    @staticmethod
    def _conditional_plan_technical_levels(result: AnalysisResult) -> Dict[str, Any]:
        """Collect deterministic technical levels used to render observation prices."""
        levels: Dict[str, Any] = {}
        snapshot = getattr(result, "market_snapshot", None) or {}
        if isinstance(snapshot, dict):
            for key in ("ma5", "ma10", "ma20", "ma50", "ma100", "ma200", "atr", "atr14"):
                if snapshot.get(key) is not None:
                    levels[key] = snapshot.get(key)

        indicators = getattr(result, "technical_indicators", None) or {}
        if isinstance(indicators, dict):
            for key in ("ma5", "ma10", "ma20", "ma50", "ma100", "ma200", "atr", "atr14"):
                if key not in levels and indicators.get(key) is not None:
                    levels[key] = indicators.get(key)

        for key in ("atr", "atr14"):
            if key not in levels and getattr(result, key, None) is not None:
                levels[key] = getattr(result, key)

        return levels

    @staticmethod
    def _to_markdown_table_cell(value: Any) -> str:
        """Normalize text for deterministic markdown table rendering."""
        if value is None:
            return "-"
        text = str(value).strip()
        if not text:
            return "-"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("|", r"\|")
        return text.replace("\n", "<br>")

    @classmethod
    def _sanitize_ai_share_count_commentary(cls, text: Any) -> str:
        """Remove executable-looking AI share-count instructions from display text."""
        if text is None:
            return ""
        normalized = str(text).strip()
        if not normalized:
            return ""
        if cls._contains_ai_position_sizing(normalized):
            sanitized = cls._strip_ai_position_sizing(normalized)
            if (
                sanitized
                and not cls._contains_ai_position_sizing(sanitized)
                and any(
                    token in sanitized.lower()
                    for token in (
                        "止损", "风险", "观察", "条件", "支撑", "压力", "突破", "回撤", "atr",
                        "stop", "risk", "watch", "condition", "support", "resistance",
                        "breakout", "pullback", "below", "above",
                    )
                )
                and re.search(r"\d", sanitized)
            ):
                return sanitized
            return "AI仓位建议（非执行）"
        return normalized

    @staticmethod
    def _extract_ai_commentary_directions(text: Any) -> Set[str]:
        """Extract action directions while keeping risk-control words neutral."""
        advice = str(text or "").strip().lower()
        if not advice:
            return set()

        directions: Set[str] = set()
        if (
            re.search(r"(卖出|卖掉|减仓|清仓|离场)", advice)
            or re.search(
                r"\b(sell|reduce|exit)\b|\bclose\s+(?:out|position|positions|the\s+position|all)\b",
                advice,
                re.IGNORECASE,
            )
        ):
            directions.add("SELL")
        if (
            re.search(r"(买入|买进|加仓|建仓|介入)", advice)
            or re.search(r"\b(buy|open|add)\b", advice, re.IGNORECASE)
        ):
            directions.add("BUY")
        if (
            re.search(r"(持有|观望)", advice)
            or re.search(r"\b(hold|watch)\b", advice, re.IGNORECASE)
        ):
            directions.add("HOLD")
        return directions

    @classmethod
    def _ai_position_sizing_patterns(cls) -> tuple[str, ...]:
        qty = cls.AI_NUMERIC_QUANTITY_PATTERN
        return (
            rf"(?:参考|目标|建议|计划|预计|测算)\s*(?:买入|购入|加仓|建仓|持仓|持有)?\s*(?:股数|数量|持仓|持有)?\s*(?:为|:|：)?\s*(?:约|大约)?\s*{qty}\s*(?:万)?\s*股",
            rf"(?:买入|买进|加仓|建仓|介入)\s*(?:股数|数量)?\s*(?:为|:|：)?\s*(?:约|大约)?\s*{qty}\s*(?:万)?\s*股",
            rf"(?:首批|分批)\s*(?:买入|买进|加仓|建仓|介入)?\s*(?:股数|数量)?\s*(?:为|:|：)?\s*(?:约|大约)?\s*{qty}\s*(?:万)?\s*股",
            rf"(?:参考|目标|建议|计划|预计|测算)\s*(?:仓位|持仓比例)\s*(?:为|:|：)?\s*{qty}\s*(?:成|%)",
            rf"(?:仓位|持仓比例)\s*(?:为|:|：)?\s*{qty}\s*%",
            rf"{qty}\s*(?:成|%)\s*(?:仓|仓位)",
            r"[一二三四五六七八九十]+成(?:仓|仓位)?",
            rf"\b(?:suggested|recommended|target|reference)\s*(?:buy|add|open|position|holding|quantity)?\s*(?:of|:)?\s*{qty}\s*shares?\b",
            rf"\b(?:buy|add|open|build|accumulate)\s*{qty}\s*shares?\b",
            rf"\b{qty}\s*shares?\s*(?:to\s*)?(?:buy|add|open|build|accumulate)\b",
            rf"\b{qty}\s*shares?\b",
        )

    @classmethod
    def _contains_ai_position_sizing(cls, text: Any) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in cls._ai_position_sizing_patterns())

    @classmethod
    def _strip_ai_position_sizing(cls, text: str) -> str:
        sanitized = str(text or "")
        for pattern in cls._ai_position_sizing_patterns():
            sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", sanitized).strip(" ；;，,。.")

    def _sanitize_ai_position_strategy_text(
        self,
        text: Any,
        action_model: Dict[str, Any],
        result: Optional[AnalysisResult] = None,
    ) -> str:
        normalized = str(text or "").strip()
        if not normalized or normalized.upper() == "N/A":
            return ""

        decision = str(action_model.get("decision") or "").upper()
        directions = self._extract_ai_commentary_directions(normalized)
        if decision in {"SELL", "HOLD"} and "BUY" in directions:
            return self.AI_POSITION_REFERENCE_DOWNGRADE

        if self._contains_ai_position_sizing(normalized):
            sanitized = self._strip_ai_position_sizing(normalized)
            if sanitized and not self._contains_ai_position_sizing(sanitized):
                sanitized_directions = self._extract_ai_commentary_directions(sanitized)
                if not (decision in {"SELL", "HOLD"} and "BUY" in sanitized_directions):
                    if result is not None:
                        return self._sanitize_user_facing_ai_text(result, sanitized, strip_position_sizing=False)
                    return self._sanitize_report_jargon(sanitized)
            return self.AI_POSITION_REFERENCE_DOWNGRADE

        if result is not None:
            return self._sanitize_user_facing_ai_text(result, normalized, strip_position_sizing=False)
        return self._sanitize_report_jargon(normalized)

    def _build_ai_position_strategy_lines(
        self,
        position: Dict[str, Any],
        action_model: Dict[str, Any],
        result: Optional[AnalysisResult] = None,
    ) -> List[str]:
        fields = (
            ("仓位测算", position.get("suggested_position")),
            ("建仓策略", position.get("entry_plan")),
            ("风控策略", position.get("risk_control")),
        )
        lines: List[str] = []
        seen: Set[str] = set()
        for label, raw_text in fields:
            sanitized = self._sanitize_ai_position_strategy_text(raw_text, action_model, result)
            if not sanitized:
                continue
            if sanitized == self.AI_POSITION_REFERENCE_DOWNGRADE:
                if sanitized in seen:
                    continue
                seen.add(sanitized)
                lines.append(f"- {sanitized}")
            else:
                lines.append(f"- {label}: {sanitized}")
        return lines

    @staticmethod
    def _is_missing_snapshot_metric(value: Any) -> bool:
        """Return True when snapshot metric should be treated as unavailable."""
        if value is None:
            return True
        if isinstance(value, (int, float)):
            try:
                if math.isnan(float(value)):
                    return True
            except (TypeError, ValueError):
                pass

        normalized = str(value).strip().lower()
        if normalized in {"", "n/a", "-", "none", "null", "未知"}:
            return True

        numeric_candidate = normalized.rstrip("%").strip()
        if not numeric_candidate:
            return True
        try:
            return math.isnan(float(numeric_candidate))
        except (TypeError, ValueError):
            return numeric_candidate == "nan"

    def _has_missing_volume_snapshot_metrics(self, result: AnalysisResult) -> bool:
        """Detect missing key volume metrics in market snapshot."""
        snapshot = getattr(result, "market_snapshot", None) or {}
        return (
            self._is_missing_snapshot_metric(snapshot.get("volume_ratio"))
            or self._is_missing_snapshot_metric(snapshot.get("turnover_rate"))
        )

    @staticmethod
    def _looks_like_volume_commentary(text: Any) -> bool:
        """Heuristic matcher for volume/turnover conclusions."""
        normalized = str(text or "").strip()
        if not normalized:
            return False
        keywords = ("量比", "换手", "放量", "缩量", "量能", "成交量")
        return any(keyword in normalized for keyword in keywords)

    def _guard_volume_commentary(self, result: AnalysisResult, text: Any) -> str:
        """Downgrade only volume-related AI commentary when key snapshot fields are missing."""
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if not self._has_missing_volume_snapshot_metrics(result):
            return normalized
        if not self._looks_like_volume_commentary(normalized):
            return normalized
        return "量能数据不足（量比/换手率缺失），不做量能结论"

    @staticmethod
    def _looks_like_non_volume_technical_signal(text: Any) -> bool:
        """Heuristic matcher for non-volume technical signals worth preserving."""
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False

        keywords = (
            "ma", "macd", "kdj", "rsi", "boll", "布林", "均线", "金叉", "死叉",
            "趋势", "形态", "支撑", "阻力", "背离", "通道", "超买", "超卖",
        )
        if any(keyword in normalized for keyword in keywords):
            return True
        return bool(re.search(r"\d+\s*日线", normalized))

    def _guard_technical_analysis_volume_commentary(self, result: AnalysisResult, text: Any) -> str:
        """Downgrade only volume fragments in technical_analysis while preserving other signals."""
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if not self._has_missing_volume_snapshot_metrics(result):
            return normalized
        if not self._looks_like_volume_commentary(normalized):
            return normalized

        clauses = [
            clause.strip()
            for clause in re.split(r"[，,；;。！？!?\n]+", normalized)
            if clause and clause.strip()
        ]

        preserved_clauses = []
        for clause in clauses:
            if not self._looks_like_volume_commentary(clause):
                preserved_clauses.append(clause)
                continue

            sanitized = re.sub(r"量比|换手率|换手|放量|缩量|量能|成交量", "", clause, flags=re.IGNORECASE)
            sanitized = re.sub(r"\s+", " ", sanitized).strip(" ：:、，,；;。")
            if sanitized and self._looks_like_non_volume_technical_signal(sanitized):
                preserved_clauses.append(sanitized)

        if preserved_clauses:
            return "，".join(preserved_clauses)
        return "量能数据不足（量比/换手率缺失），不做量能结论"

    def _build_recommended_actions_table(self, results: List[AnalysisResult]) -> List[str]:
        return build_recommended_actions_table(
            results=results,
            get_primary_action_model=self._get_primary_action_model,
            build_final_action_display=self._build_final_action_display,
            get_signal_level=self._get_signal_level,
            format_stock_display_name=notification_formatting.format_stock_display_name,
            escape_md=self._escape_md,
            to_markdown_table_cell=self._to_markdown_table_cell,
            format_position_action_label=notification_formatting.format_position_action_label,
            format_sizing_brief=notification_formatting.format_sizing_brief,
            get_conflict_safe_ai_commentary=self._get_conflict_safe_ai_commentary,
        )

    def build_daily_decision_summary(
        self,
        results: List[AnalysisResult],
        *,
        report_date: Optional[str] = None,
        generated_at: Optional[datetime] = None,
        overview: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the stable deterministic summary used by reports and archives."""
        if generated_at is None:
            generated_at = self._now_in_report_tz()
        if report_date is None:
            report_date = self._default_report_date(generated_at)
        self._remember_report_date(report_date)
        if overview is None:
            try:
                overview = get_db().get_portfolio_overview()
            except Exception:
                overview = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}
            overview = self._build_report_time_portfolio_overview(
                overview=overview,
                results=results,
            )
        return build_daily_decision_summary(
            results=results,
            report_date=report_date,
            generated_at=generated_at,
            overview=overview,
            get_primary_action_model=self._get_primary_action_model,
            classify_price_basis=self._classify_price_basis,
            format_stock_display_name=notification_formatting.format_stock_display_name,
            format_validation_issue_text=self._format_validation_issue_text,
            min_action_delta_amount=self._get_actionable_delta_amount_threshold(),
            backtest_confidence=self._build_backtest_confidence_panel(),
            score_bucket_calibration=self._build_score_bucket_calibration(),
            risk_sizing_settings=risk_sizing_settings_from_config(get_config()),
            announcement_checks=self._build_asx_announcement_checks_for_report(results),
        )

    def _build_asx_announcement_checks_for_report(self, results: List[AnalysisResult]) -> Dict[str, ASXAnnouncementCheck]:
        """Build display-only ASX announcement checks without risking report failure."""
        config = get_config()
        if not bool(getattr(config, "asx_announcements_enabled", True)):
            return {}

        codes = [getattr(result, "code", "") for result in (results or [])]
        try:
            return build_asx_announcement_checks(
                codes,
                enabled=True,
                lookback_days=getattr(config, "asx_announcements_lookback_days", 1),
                max_items=getattr(config, "asx_announcements_max_items", 5),
                timeout_seconds=getattr(config, "asx_announcements_timeout_seconds", 10),
            )
        except Exception as exc:  # pragma: no cover - defensive daily-job guard
            logger.warning("ASX announcement check failed; report will continue: %s", exc)
            checked_at = self._now_in_report_tz().isoformat(timespec="seconds")
            return {
                canonical_stock_code(code): ASXAnnouncementCheck(
                    code=code,
                    checked=False,
                    source="asx_market_announcements",
                    checked_at=checked_at,
                    status="unavailable",
                    reason="ASX 公告源不可用，执行前人工检查。",
                )
                for code in codes
                if is_asx_ticker(code)
            }

    def get_last_daily_decision_summary(self) -> Optional[Dict[str, Any]]:
        """Return the last summary generated as part of report rendering."""
        return self._last_daily_decision_summary

    @staticmethod
    def _annotate_paper_ledger_scope_notes(
        summary: Dict[str, Any],
        paper_portfolio_overview: Optional[Dict[str, Any]],
    ) -> None:
        """Add display-only notes when real-account plans differ from paper ledger state."""
        if not isinstance(summary, dict) or not isinstance(paper_portfolio_overview, dict):
            return
        holdings = paper_portfolio_overview.get("holdings")
        if not isinstance(holdings, list):
            return
        paper_holding_codes = {
            canonical_stock_code(item.get("code"))
            for item in holdings
            if isinstance(item, dict) and canonical_stock_code(item.get("code"))
        }
        if not paper_holding_codes:
            return
        for item in summary.get("actionable_items") or []:
            if not isinstance(item, dict):
                continue
            action = str(item.get("position_action") or "").upper()
            code = canonical_stock_code(item.get("code"))
            if (
                action == "OPEN"
                and code in paper_holding_codes
                and not bool(item.get("is_current_holding"))
            ):
                item["account_scope_note"] = (
                    "真实账户新开仓计划；模拟盘已有持仓，模拟结果可能为跳过/调仓"
                )

    @staticmethod
    def _build_backtest_confidence_panel() -> Dict[str, Any]:
        """Return report-only backtest confidence metadata from existing summaries."""
        try:
            from src.services.backtest_service import BacktestService

            return BacktestService().get_confidence_panel()
        except Exception as exc:
            logger.warning("回测置信面板加载失败，降级为样本不足: %s", exc)
            from src.backtest_confidence import build_backtest_confidence_panel

            return build_backtest_confidence_panel(summary=None, action_results=[], window_days=None)

    @staticmethod
    def _build_score_bucket_calibration() -> Dict[str, Any]:
        """Return report-only score bucket calibration from existing backtests."""
        try:
            from src.services.backtest_service import BacktestService

            return BacktestService().get_score_bucket_calibration()
        except Exception as exc:
            logger.warning("评分分桶校准加载失败，降级为样本不足: %s", exc)
            from src.backtest_confidence import build_score_bucket_calibration

            return build_score_bucket_calibration(score_results=[], window_days=None)

    @staticmethod
    def _get_actionable_delta_amount_threshold() -> float:
        try:
            config = get_config()
            min_delta = float(getattr(config, "min_position_delta_amount", DEFAULT_ACTIONABLE_DELTA_AMOUNT) or 0.0)
            min_notional = float(getattr(config, "min_order_notional", DEFAULT_ACTIONABLE_DELTA_AMOUNT) or 0.0)
            return max(min_delta, min_notional, 0.0)
        except Exception:
            return DEFAULT_ACTIONABLE_DELTA_AMOUNT

    @staticmethod
    def _execution_action_counts(summary: Dict[str, Any]) -> Dict[str, int]:
        counts = summary.get("action_counts") or {}
        return {
            key: int(counts.get(key, 0) or 0)
            for key in ("buy", "add", "reduce", "close", "hold_watch", "blocked", "total_actions")
        }

    @classmethod
    def _format_execution_action_counts_text(cls, summary: Dict[str, Any]) -> str:
        counts = cls._execution_action_counts(summary)
        return (
            "执行动作 买入/加仓/减仓/清仓/观察/验证阻断："
            f"{counts['buy']}/{counts['add']}/{counts['reduce']}/{counts['close']}/"
            f"{counts['hold_watch']}/{counts['blocked']}"
        )

    def _is_actionable_today(self, result: AnalysisResult) -> bool:
        """Return True when deterministic action implies execution-worthy change."""
        return self._build_final_action_display(result)["actionability"] == "actionable"

    def _effective_actionable_results(self, results: List[AnalysisResult]) -> List[AnalysisResult]:
        """Return non-blocked results that remain executable after tiny-action suppression."""
        return [result for result in results if self._is_actionable_today(result)]

    def _display_actionable_results(self, results: List[AnalysisResult]) -> List[AnalysisResult]:
        """Return report-visible non-blocked results, excluding suppressed executable noise."""
        return [result for result in results if not self._is_suppressed_executable_action_today(result)]

    def _is_suppressed_executable_action_today(self, result: AnalysisResult) -> bool:
        """Return True when an executable action is intentionally downgraded to watch."""
        action = str(self._get_primary_action_model(result).get("position_action") or "HOLD").upper()
        return action in {"OPEN", "ADD", "REDUCE", "CLOSE"} and not self._is_actionable_today(result)

    def _build_final_action_display(
        self,
        result: AnalysisResult,
        action_model: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return the single display action object for report exits."""
        return build_final_action_display(
            result,
            action_model=action_model or self._get_primary_action_model(result),
            min_delta_amount=self._get_actionable_delta_amount_threshold(),
            format_stock_display_name=notification_formatting.format_stock_display_name,
            format_validation_issue_text=self._format_validation_issue_text,
        )

    def _infer_ai_commentary_decision(self, operation_advice: str) -> Optional[str]:
        """Infer BUY/HOLD/SELL bucket from AI narrative advice text."""
        directions = self._extract_ai_commentary_directions(operation_advice)
        if not directions:
            return None
        if directions == {"SELL"}:
            return "SELL"
        if directions == {"BUY"}:
            return "BUY"
        if directions == {"HOLD"}:
            return "HOLD"
        if "BUY" in directions and "SELL" not in directions:
            return "BUY"
        if "SELL" in directions and "BUY" not in directions:
            return "SELL"
        return None

    def _get_primary_action_model(self, result: AnalysisResult) -> Dict[str, Any]:
        """Deterministic action source-of-truth model.

        Precedence rule:
        1) position_action decides executable action bucket when valid.
        2) missing/invalid position_action falls back to final_decision.
        """
        if _is_validation_blocked(result):
            current_weight = float(getattr(result, 'current_weight', 0.0) or 0.0)
            return {
                'decision': 'HOLD',
                'position_action': 'HOLD',
                'target_weight': current_weight,
                'delta_amount': 0.0,
                'ai_conflict': False,
            }
        position_action = _normalize_position_action(result)
        decision = _decision_from_position_action(position_action)
        if not decision:
            decision = _get_effective_decision(result)
            position_action = {'BUY': 'OPEN', 'HOLD': 'HOLD', 'SELL': 'CLOSE'}.get(decision, 'HOLD')

        target_weight = float(getattr(result, 'target_weight', 0.0) or 0.0)
        delta_amount = float(getattr(result, 'delta_amount', 0.0) or 0.0)
        ai_directions = self._extract_ai_commentary_directions(self._get_normalized_ai_operation_advice(result))
        opposite_directions = {
            "BUY": {"SELL"},
            "SELL": {"BUY"},
            "HOLD": {"BUY", "SELL"},
        }.get(decision, set())
        ai_conflict = bool(ai_directions & opposite_directions)
        return {
            'decision': decision,
            'position_action': position_action,
            'target_weight': target_weight,
            'delta_amount': delta_amount,
            'ai_conflict': ai_conflict,
        }

    def _get_canonical_operation_advice(self, result: AnalysisResult) -> str:
        """Return unified final advice wording aligned with deterministic decision."""
        if is_failed_analysis(result):
            return "分析失败（需重跑）"
        if _is_validation_blocked(result):
            return "不可决策/仅观察"
        decision = self._get_primary_action_model(result)['decision']
        return _decision_to_canonical_advice(decision)

    def _get_normalized_ai_operation_advice(self, result: AnalysisResult) -> str:
        """Return normalized AI narrative advice without overriding its original semantics."""
        advice = str(getattr(result, 'operation_advice', '') or '').strip()
        if not advice:
            return self._get_canonical_operation_advice(result)
        advice = advice.replace("\r\n", "\n").replace("\r", "\n")
        return " ".join(part.strip() for part in advice.split("\n") if part.strip())

    @staticmethod
    def _has_verified_backtest_summary(result: AnalysisResult) -> bool:
        summary = getattr(result, "backtest_summary", None)
        return isinstance(summary, dict) and bool(summary)

    @staticmethod
    def _looks_like_backtest_claim(text: str) -> bool:
        if not text:
            return False
        return bool(
            re.search(r"(回测|历史样本|历史).*?(胜率|准确率)|(?:胜率|准确率)\s*[0-9]", text, re.IGNORECASE)
        )

    def _sanitize_unverified_backtest_claim(self, result: AnalysisResult, text: Any) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if self._has_verified_backtest_summary(result):
            return normalized
        if not self._looks_like_backtest_claim(normalized):
            return normalized
        return "系统未检查该标的回测证据；AI 提到的历史胜率/准确率不作为已验证依据。"

    @staticmethod
    def _sanitize_report_jargon(text: Any) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        replacements = {
            "deterministic action": "今日主动作",
            "summary artifact": "完整摘要",
            "Dry Run": "试算",
            "Shadow": "观察模式",
            "non_buy_action_context": "不是买入或加仓场景",
            "无需二次确认": "必须二次确认",
            "不需要二次确认": "必须二次确认",
            "无需人工确认": "必须人工确认",
            "强制执行": "人工复核后再处理",
            "自动执行": "人工复核后再处理",
            "立即执行": "人工复核后再处理",
            "直接执行": "人工复核后再处理",
        }
        for source, replacement in replacements.items():
            normalized = normalized.replace(source, replacement)
        return normalized

    def _sanitize_user_facing_ai_text(
        self,
        result: AnalysisResult,
        text: Any,
        *,
        strip_position_sizing: bool = True,
    ) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if strip_position_sizing:
            normalized = self._sanitize_ai_share_count_commentary(normalized)
        normalized = self._sanitize_unverified_backtest_claim(result, normalized)
        return self._sanitize_report_jargon(normalized)

    def _sanitize_user_facing_risk_text(
        self,
        result: AnalysisResult,
        text: Any,
        *,
        action_model: Optional[Dict[str, Any]] = None,
    ) -> str:
        sanitized = self._sanitize_user_facing_ai_text(result, text, strip_position_sizing=False)
        return self._neutralize_hold_risk_sell_directives(
            sanitized,
            action_model or self._get_primary_action_model(result),
        )

    def _get_conflict_safe_ai_commentary(self, result: AnalysisResult) -> str:
        """Return AI commentary text safe for conflict-state presentation."""
        if _is_validation_blocked(result):
            return "验证未通过，当前只保留观察，不输出可执行动作解释。"
        action_model = self._get_primary_action_model(result)
        if action_model['ai_conflict']:
            return "AI解读与确定性主动作存在方向冲突，已转为中性说明"
        safe_advice = self._sanitize_user_facing_ai_text(result, self._get_normalized_ai_operation_advice(result))
        return self._sanitize_report_jargon(self._guard_volume_commentary(result, safe_advice))

    def _get_conflict_safe_core_conclusion(self, result: AnalysisResult, text: Any) -> str:
        """Return core conclusion text safe for conflict-state presentation."""
        if _is_validation_blocked(result):
            return "验证未通过：当前不可决策，仅可观察。"
        if self._get_primary_action_model(result)['ai_conflict']:
            return "AI总结与确定性主动作存在方向冲突，请仅按确定性主动作执行"
        normalized = str(text or '').strip()
        return self._sanitize_user_facing_ai_text(result, normalized)

    def _build_simulated_target_allocation_table(
        self,
        results: List[AnalysisResult],
        executed_weight_by_code: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        return build_simulated_target_allocation_table(
            results=results,
            executed_weight_by_code=executed_weight_by_code,
            format_stock_display_name=notification_formatting.format_stock_display_name,
            escape_md=self._escape_md,
            to_markdown_table_cell=self._to_markdown_table_cell,
            get_signal_level=self._get_signal_level,
            normalize_stock_code=canonical_stock_code,
        )

    def _build_section_c_reconciliation_lines(
        self,
        *,
        results: List[AnalysisResult],
        overview_holdings: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        return build_section_c_reconciliation_lines(
            results=results,
            overview_holdings=overview_holdings,
            normalize_stock_code=canonical_stock_code,
        )

    def _count_primary_decisions(self, results: List[AnalysisResult]) -> Dict[str, int]:
        counts = {'BUY': 0, 'HOLD': 0, 'SELL': 0}
        for result in results:
            if is_failed_analysis(result) or _is_validation_blocked(result):
                continue
            decision = self._get_primary_action_model(result)['decision']
            counts[decision] = counts.get(decision, 0) + 1
        return counts

    def _split_completed_results(
        self,
        results: List[AnalysisResult],
    ) -> tuple[List[AnalysisResult], List[AnalysisResult], List[AnalysisResult]]:
        successful_results = [r for r in results if not is_failed_analysis(r)]
        blocked_results = [r for r in successful_results if _is_validation_blocked(r)]
        actionable_results = [r for r in successful_results if not _is_validation_blocked(r)]
        return successful_results, actionable_results, blocked_results

    def _format_blocked_result_line(
        self,
        result: AnalysisResult,
        *,
        truncate: Optional[int] = None,
    ) -> str:
        stock_name = self._escape_md(notification_formatting.format_stock_display_name(result.name, result.code))
        reason = self._format_validation_issue_text(result)
        if truncate is not None:
            reason = reason[:truncate]
        return f"- {stock_name}：{reason}"

    def _format_non_actionable_report_lines(
        self,
        result: AnalysisResult,
        *,
        failed: bool = False,
    ) -> List[str]:
        stock_name = self._escape_md(notification_formatting.format_stock_display_name(result.name, result.code))
        reason = self._human_non_actionable_reason(result, failed=failed)
        return [
            f"### {stock_name}",
            "",
            "- **状态**：暂不决策",
            "- **动作**：仅观察",
            f"- **原因**：{reason}",
            "- **当前建议**：仅观察，不买入、不加仓、不减仓。",
            "- **建议人工检查**：行情数据是否完整、上一交易日收盘价是否正常、AI 分析是否生成失败。",
        ]

    def _human_non_actionable_reason(self, result: AnalysisResult, *, failed: bool = False) -> str:
        raw_parts: List[str] = []
        raw_parts.extend(str(item or "") for item in (getattr(result, "validation_issues", None) or []))
        for value in (
            getattr(result, "error_message", None),
            getattr(result, "risk_warning", None),
            getattr(result, "action_reason", None),
        ):
            if value:
                raw_parts.append(str(value))
        text = " ".join(raw_parts).lower()

        reasons: List[str] = []
        if any(token in text for token in ("schema", "json", "text_fallback", "fallback", "格式", "解析")):
            reasons.append("AI 输出格式异常，系统无法可靠读取完整分析结论。")
        if failed or any(token in text for token in ("analysis_status", "failed", "degraded", "失败", "未配置")):
            reasons.append("本次分析失败或结果不完整，可靠性不足。")
        if any(token in text for token in ("missing_critical_data", "缺少", "缺失", "关键")):
            reasons.append("关键行情数据缺失，无法形成稳定判断。")
        if any(token in text for token in ("stale_daily_context", "日线基准已过期", "过期", "不是最新")):
            reasons.append("日线数据不是最新可用交易日。")
        if any(token in text for token in ("mixed_price_basis", "价格口径混用", "口径混用", "实时价格")):
            reasons.append("报告里混用了不同价格基准，不能作为执行依据。")

        if not reasons:
            reasons.append("本次分析数据或 AI 输出不完整，结果不够可靠。")
        return " ".join(dict.fromkeys(reasons))

    def _format_primary_action_text(self, result: AnalysisResult) -> str:
        display = self._build_final_action_display(result)
        if not display["can_show_sizing"]:
            return f"{display['display_label']} | {display['reason']}"
        return (
            f"{display['position_action']} | 目标仓位 {display['target_weight']:.2%} | "
            f"模拟Δ {display['delta_amount']:,.2f}"
        )

    def _format_deterministic_sizing_text(self, result: AnalysisResult) -> str:
        """Format deterministic sizing guidance from the same target-allocation engine."""
        display = self._build_final_action_display(result)
        if not display["can_show_sizing"]:
            return f"{display['display_label']} | 不显示目标仓位、调仓金额或目标数量"
        base = self._format_primary_action_text(result)
        raw_target_quantity = getattr(result, 'target_quantity', None)
        if raw_target_quantity is None:
            return f"{base} | 目标数量 N/A（确定性引擎未提供）"
        try:
            target_quantity = float(raw_target_quantity)
        except (TypeError, ValueError):
            return f"{base} | 目标数量 N/A（确定性引擎未提供）"
        if target_quantity < 0:
            return f"{base} | 目标数量 N/A（确定性引擎未提供）"
        action = str(getattr(result, "position_action", "") or "").upper()
        action_reason = str(getattr(result, "action_reason", "") or "")
        if (
            action == "HOLD"
            and "execution_blocked=" in action_reason
            and not float(target_quantity).is_integer()
        ):
            return f"{base} | 目标数量 保持当前持仓（不执行）"
        normalized_quantity = int(round(target_quantity, 0))
        return f"{base} | 目标数量 {normalized_quantity:,d} 股"

    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """
        Get signal level and color based on deterministic primary action model.

        Returns:
            (signal_text, emoji, color_tag)
        """
        if is_failed_analysis(result):
            return ("分析失败（需重跑）", '⚠️', '失败')
        action_model = self._get_primary_action_model(result)
        decision = action_model['decision']
        if decision == 'BUY':
            return (_decision_to_canonical_advice('BUY'), '🟢', '买入')
        if decision == 'SELL':
            return (_decision_to_canonical_advice('SELL'), '🔴', '卖出')
        return (_decision_to_canonical_advice('HOLD'), '⚪', '观望')

    @staticmethod
    def _to_positive_float(value: Any) -> Optional[float]:
        """Convert value to positive float, otherwise return None."""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed > 0:
            return parsed
        return None

    def _build_report_time_portfolio_overview(
        self,
        *,
        overview: Dict[str, Any],
        results: List[AnalysisResult],
    ) -> Dict[str, Any]:
        return build_report_time_portfolio_overview(
            overview=overview,
            results=results,
            normalize_stock_code=canonical_stock_code,
            to_positive_float=self._to_positive_float,
        )

    def _get_paper_portfolio_overview_for_report(self) -> Dict[str, Any]:
        try:
            db = get_db()
            getter = getattr(db, "get_paper_portfolio_overview", None)
            if not callable(getter):
                return {"available": False, "error": "模拟盘只读入口不可用。"}
            overview = getter()
        except Exception as exc:
            return {"available": False, "error": str(exc)[:120]}
        if isinstance(overview, dict):
            overview.setdefault("available", True)
            return overview
        return {"available": True, "initialized": False}

    def _build_paper_portfolio_readonly_lines(
        self,
        overview: Dict[str, Any],
        *,
        has_plan_actions: bool,
        report_date: Optional[str] = None,
    ) -> List[str]:
        lines = [
            "## 模拟盘账本（只读）",
            "",
            "> 这里展示的是持久化模拟盘账本，不是正文的计划仓位模拟，也不代表真实账户成交。",
            "",
        ]
        if not overview.get("available", True):
            lines.extend(
                [
                    "**账本总览**",
                    "| 项目 | 内容 |",
                    "| --- | --- |",
                    f"| 状态 | 状态：读取失败（{self._to_markdown_table_cell(overview.get('error') or '未知原因')}）。 |",
                    "| 报告生成行为 | 只读展示失败，不会写入模拟盘或真实账户。 |",
                    "",
                ]
            )
            return lines

        if not bool(overview.get("initialized")):
            lines.extend(
                [
                    "**账本总览**",
                    "| 项目 | 内容 |",
                    "| --- | --- |",
                    "| 状态 | 状态：未初始化/未启用。 |",
                    "| 最近模拟 | 最近模拟：暂无模拟盘交易记录。 |",
                    "| 报告生成行为 | 只读展示，不会初始化模拟盘，也不会写入任何模拟交易。 |",
                    "",
                ]
            )
            return lines

        raw_holdings = overview.get("holdings") if isinstance(overview.get("holdings"), list) else []
        raw_trades = (
            overview.get("latest_simulated_trades")
            if isinstance(overview.get("latest_simulated_trades"), list)
            else []
        )
        holdings = [item for item in raw_holdings if isinstance(item, dict)]
        trades = [item for item in raw_trades if isinstance(item, dict)]
        malformed_row_count = (len(raw_holdings) - len(holdings)) + (len(raw_trades) - len(trades))
        last_simulation_time = overview.get("last_simulation_time")
        is_current_report_simulation = self._is_same_report_date(last_simulation_time, report_date)
        if is_current_report_simulation:
            plan_line = "模拟盘更新：本次分析已先写入模拟盘；报告只读展示写入后的账本。"
        elif last_simulation_time:
            plan_line = f"模拟盘更新：最近模拟时间 {last_simulation_time}；本报告只读展示既有账本。"
        else:
            plan_line = (
                "今日计划仓位模拟：正文目标仓位只是计划视图；当前尚无模拟盘执行记录。"
                if has_plan_actions
                else "今日计划仓位模拟：无明确调仓动作；当前尚无模拟盘执行记录。"
            )
        lines.extend(
            [
                "**账本总览**",
                "| 项目 | 内容 |",
                "| --- | --- |",
                f"| 状态 | 状态：已初始化；快照日期：{self._to_markdown_table_cell(overview.get('snapshot_date') or '暂无快照')}。 |",
                (
                    "| 资产 | "
                    f"账本资产：现金 {self._format_report_money(overview.get('cash'))}；"
                    f"持仓市值 {self._format_report_money(overview.get('equity_value'))}；"
                    f"总资产 {self._format_report_money(overview.get('total_value'))}。 |"
                ),
                (
                    "| 盈亏 | "
                    f"账本盈亏：累计 {self._format_report_signed_money(overview.get('total_pnl'))} "
                    f"({self._format_report_signed_percent(overview.get('total_pnl_pct'))})；"
                    f"浮动 {self._format_report_signed_money(overview.get('unrealized_pnl'))}；"
                    f"已实现/现金化 {self._format_report_signed_money(overview.get('realized_pnl'))}。 |"
                ),
                f"| 持仓 | 当前模拟持仓：{len(holdings)} 只。 |",
                f"| 更新 | {self._to_markdown_table_cell(plan_line)} |",
            ]
        )
        if malformed_row_count:
            lines.extend(
                [
                    "",
                    f"- 注意：部分模拟盘账本记录格式异常，已跳过 {malformed_row_count} 条；日报主体继续生成。",
                ]
            )
        if holdings:
            lines.extend(
                [
                    "",
                    "### 当前模拟持仓盈亏",
                    "",
                    "| 标的 | 数量 | 成本 | 现价 | 市值 | 浮盈亏 |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for item in holdings[:8]:
                lines.append(
                    "| "
                    f"{self._to_markdown_table_cell(canonical_stock_code(item.get('code')))} | "
                    f"{self._format_report_number(item.get('quantity'))} | "
                    f"{self._format_report_money(item.get('avg_cost'))} | "
                    f"{self._format_report_money(item.get('current_price'))} | "
                    f"{self._format_report_money(item.get('market_value'))} | "
                    f"{self._format_report_signed_money(item.get('unrealized_pnl'))} "
                    f"({self._format_report_signed_percent(item.get('unrealized_pnl_pct'))}) |"
                )
        if trades:
            lines.extend(
                [
                    "",
                    "### 最近模拟操作",
                    "",
                    "| 时间 | 标的 | 动作 | 结果 | 数量变化 | 价格 | 现金变化 | 说明 |",
                    "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
                ]
            )
            display_trades = sorted(trades, key=self._paper_trade_display_priority)
            for trade in display_trades[:8]:
                executed_text = "已模拟成交" if trade.get("executed") else "跳过"
                reason = str(trade.get("reason") or "").strip()
                if len(reason) > 80:
                    reason = reason[:77] + "..."
                lines.append(
                    "| "
                    f"{self._to_markdown_table_cell(trade.get('simulation_time') or overview.get('last_simulation_time') or '时间未知')} | "
                    f"{self._to_markdown_table_cell(canonical_stock_code(trade.get('code')) or '未知标的')} | "
                    f"{self._to_markdown_table_cell(self._format_paper_trade_action(trade.get('action'), trade))} | "
                    f"{executed_text} | "
                    f"{self._format_report_signed_number(trade.get('quantity_delta'))} | "
                    f"{self._format_report_money(trade.get('price'))} | "
                    f"{self._format_report_signed_money(trade.get('cash_delta'))} | "
                    f"{self._to_markdown_table_cell(self._format_paper_trade_reason(reason, trade))} |"
                )
        else:
            lines.append("- 最近模拟：暂无模拟盘交易记录。")

        seed_source = overview.get("seed_source") if isinstance(overview.get("seed_source"), dict) else {}
        if seed_source.get("snapshot_date"):
            lines.append("")
            lines.append(f"- 初始化来源：真实账户快照 {seed_source.get('snapshot_date')} 的只读副本。")
        lines.extend([""])
        return lines

    @staticmethod
    def _paper_trade_display_priority(trade: Any) -> int:
        if not isinstance(trade, dict):
            return 3
        action = str(trade.get("action") or "").upper()
        if trade.get("executed"):
            return 0
        if action and action != "HOLD":
            return 1
        return 2

    @staticmethod
    def _format_paper_trade_action(action: Any, trade: Optional[Dict[str, Any]] = None) -> str:
        normalized = str(action or "").strip().upper()
        if normalized == "OPEN" and NotificationService._paper_trade_before_quantity(trade) > 0:
            return "已有仓位微调/补齐目标"
        return {
            "OPEN": "新开仓",
            "ADD": "加仓",
            "HOLD": "持有/跳过",
            "REDUCE": "减仓",
            "CLOSE": "清仓",
        }.get(normalized, normalized or "未知动作")

    @staticmethod
    def _format_paper_trade_reason(reason: Any, trade: Optional[Dict[str, Any]] = None) -> str:
        text = str(reason or "").strip()
        lower_text = text.lower()
        if lower_text == "applied":
            if NotificationService._is_noise_sized_paper_trade(trade):
                return "已按计划写入模拟盘；低于有效交易阈值，仅账本微调/目标同步"
            return "已按计划写入模拟盘"
        if lower_text == "skipped: hold action":
            return "HOLD 观察，未产生模拟交易"
        if lower_text.startswith("skipped: analysis_status="):
            status = text.split("=", 1)[-1].strip() or "未知"
            normalized = status.upper()
            if normalized == "DEGRADED":
                return "分析结果不完整，跳过"
            if normalized == "FAILED":
                return "分析失败，跳过"
            return "分析状态未通过，跳过"
        if lower_text == "skipped: invalid current price":
            return "缺少有效价格，跳过"
        if lower_text == "skipped: missing/invalid target info":
            return "缺少有效目标仓位或数量，跳过"
        if lower_text.startswith("skipped: no-op"):
            return "已接近目标仓位，未产生模拟交易"
        if lower_text.startswith("skipped: insufficient cash"):
            required, available = NotificationService._paper_trade_cash_shortfall_values(text, trade)
            if required is not None and available is not None:
                return (
                    "现金不足：目标数量需要 "
                    f"{NotificationService._format_report_money(required)}，"
                    f"可用现金 {NotificationService._format_report_money(available)}，跳过"
                )
            return "现金不足，跳过"
        if lower_text.startswith("skipped: "):
            return text[len("Skipped: "):]
        return text

    @staticmethod
    def _paper_trade_before_quantity(trade: Optional[Dict[str, Any]]) -> float:
        if not isinstance(trade, dict):
            return 0.0
        return NotificationService._safe_optional_float(trade.get("before_quantity")) or 0.0

    @staticmethod
    def _is_noise_sized_paper_trade(trade: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(trade, dict) or not bool(trade.get("executed")):
            return False
        threshold = NotificationService._get_actionable_delta_amount_threshold()
        if threshold <= 0:
            return False
        notional = NotificationService._paper_trade_abs_notional(trade)
        return 0 < notional < threshold

    @staticmethod
    def _paper_trade_abs_notional(trade: Dict[str, Any]) -> float:
        explicit = NotificationService._safe_optional_float(trade.get("notional"))
        if explicit is not None:
            return abs(explicit)
        cash_delta = NotificationService._safe_optional_float(trade.get("cash_delta"))
        if cash_delta is not None:
            return abs(cash_delta)
        quantity_delta = NotificationService._safe_optional_float(trade.get("quantity_delta"))
        price = NotificationService._safe_optional_float(trade.get("price"))
        if quantity_delta is not None and price is not None:
            return abs(quantity_delta * price)
        before_quantity = NotificationService._safe_optional_float(trade.get("before_quantity")) or 0.0
        after_quantity = NotificationService._safe_optional_float(trade.get("after_quantity")) or 0.0
        if price is not None:
            return abs((after_quantity - before_quantity) * price)
        return 0.0

    @staticmethod
    def _paper_trade_cash_shortfall_values(
        reason: str,
        trade: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[float], Optional[float]]:
        required = (trade or {}).get("required_cash") if isinstance(trade, dict) else None
        available = (trade or {}).get("available_cash") if isinstance(trade, dict) else None
        if required is None or available is None:
            match = re.search(r"required=([0-9.,+-]+),\s*available=([0-9.,+-]+)", str(reason or ""), re.IGNORECASE)
            if match:
                required = required if required is not None else match.group(1)
                available = available if available is not None else match.group(2)
        return (
            NotificationService._safe_optional_float(required),
            NotificationService._safe_optional_float(available),
        )

    @staticmethod
    def _safe_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            number = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return number

    @staticmethod
    def _is_same_report_date(timestamp_value: Any, report_date: Optional[str]) -> bool:
        if not timestamp_value or not report_date:
            return False
        try:
            timestamp_date = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).date()
            expected_date = datetime.fromisoformat(str(report_date)).date()
        except Exception:
            return False
        return timestamp_date == expected_date

    @staticmethod
    def _format_report_money(value: Any) -> str:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return "0.00"
        if not math.isfinite(number):
            return "0.00"
        return f"{number:,.2f}"

    @staticmethod
    def _format_report_number(value: Any) -> str:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return "0.00"
        if not math.isfinite(number):
            return "0.00"
        return f"{number:,.2f}"

    @staticmethod
    def _format_report_signed_number(value: Any) -> str:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return "+0.00"
        if not math.isfinite(number):
            return "+0.00"
        return f"{number:+,.2f}"

    @staticmethod
    def _format_report_signed_money(value: Any) -> str:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return "+0.00"
        if not math.isfinite(number):
            return "+0.00"
        return f"{number:+,.2f}"

    @staticmethod
    def _format_report_signed_percent(value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        if not math.isfinite(number):
            return "N/A"
        return f"{number:+.2f}%"

    def _build_dashboard_observation_item(
        self,
        result: AnalysisResult,
    ) -> Dict[str, str]:
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, "dashboard") and result.dashboard else {}
        intel = dashboard.get("intelligence", {}) if dashboard else {}
        battle = dashboard.get("battle_plan", {}) if dashboard else {}
        sniper = battle.get("sniper_points", {}) if battle else {}
        plan_points = self._build_conditional_plan_points(result, sniper)
        risk_alerts = intel.get("risk_alerts", []) if intel else []
        action_model = self._get_primary_action_model(result)
        reason_text = self._sanitize_user_facing_ai_text(
            result,
            result.buy_reason or result.analysis_summary or "N/A",
            strip_position_sizing=False,
        )

        normalized_risk_alerts = []
        for item in risk_alerts:
            if item is None:
                continue
            if isinstance(item, dict):
                text = str(item.get("message") or item.get("title") or "").strip()
            else:
                text = str(item).strip()
            if text:
                normalized_risk_alerts.append(
                    self._sanitize_user_facing_risk_text(result, text, action_model=action_model)
                )

        risk_text = (
            "；".join(normalized_risk_alerts[:2])
            if normalized_risk_alerts else self._sanitize_user_facing_risk_text(
                result,
                result.risk_warning or "暂无新增高优先级风险",
                action_model=action_model,
            )
        )

        ref_text = format_conditional_plan_points_inline(plan_points)

        return {
            "heading": f"### {signal_emoji} {self._escape_md(notification_formatting.format_stock_display_name(result.name, result.code))}",
            "summary_line": f"- 核心结论：{signal_text} | 评分 {result.sentiment_score} | {result.trend_prediction}",
            "action_line": f"- 主动作：{notification_formatting.format_position_action_label(action_model['position_action'])}",
            "reason_line": f"- 关键理由：{reason_text}",
            "risk_line": f"- 风险：{risk_text}",
            "reference_line": f"- 条件化计划点位：{ref_text}",
        }

    def _build_holding_followup_review_lines(
        self,
        results: List[AnalysisResult],
        *,
        current_weight_by_code: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        if not results:
            return []
        current_weight_by_code = current_weight_by_code or {}
        lines = [
            "## 持仓后续复盘",
            "",
            "> 买入后的持仓跟踪：只展示已有动作、风险位和止盈/止损复核点，不因风险提示自动生成卖出建议。",
            "",
            "| 标的 | 今日动作 | 当前仓位 | 目标仓位 | 计划金额 | 止损/风险观察位 | 止盈观察位 | 复核重点 |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
        for result in results:
            action_model = self._get_primary_action_model(result)
            plan_points = self._build_conditional_plan_points(
                result,
                ((getattr(result, "dashboard", None) or {}).get("battle_plan", {}) or {}).get("sniper_points", {}),
            )
            stop_loss = self._display_conditional_point_value(plan_points, "stop_loss")
            take_profit = self._display_conditional_point_value(plan_points, "take_profit")
            review_focus = self._holding_followup_review_focus(result, action_model=action_model)
            current_weight = self._holding_followup_current_weight(result, current_weight_by_code)
            lines.append(
                "| "
                f"{self._to_markdown_table_cell(notification_formatting.format_stock_display_name(result.name, result.code))} | "
                f"{self._to_markdown_table_cell(notification_formatting.format_position_action_label(action_model['position_action']))} | "
                f"{current_weight:.2%} | "
                f"{float(action_model.get('target_weight') or 0.0):.2%} | "
                f"{self._format_report_signed_money(action_model.get('delta_amount'))} | "
                f"{self._to_markdown_table_cell(stop_loss)} | "
                f"{self._to_markdown_table_cell(take_profit)} | "
                f"{self._to_markdown_table_cell(review_focus)} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _holding_followup_current_weight(
        result: AnalysisResult,
        current_weight_by_code: Dict[str, float],
    ) -> float:
        code = canonical_stock_code(getattr(result, "code", ""))
        if code and code in current_weight_by_code:
            return float(current_weight_by_code.get(code) or 0.0)
        return float(getattr(result, "current_weight", 0.0) or 0.0)

    @staticmethod
    def _display_conditional_point_value(points: List[Any], label: str) -> str:
        for point in points:
            if getattr(point, "label", "") != label:
                continue
            price = getattr(point, "price", None)
            if price is not None:
                try:
                    return f"{float(price):.2f}"
                except (TypeError, ValueError):
                    pass
            raw_value = str(getattr(point, "raw_value", "") or "").strip()
            return raw_value or "需人工复核"
        return "暂无明确点位"

    def _holding_followup_review_focus(
        self,
        result: AnalysisResult,
        *,
        action_model: Optional[Dict[str, Any]] = None,
    ) -> str:
        dashboard = result.dashboard if hasattr(result, "dashboard") and result.dashboard else {}
        intel = dashboard.get("intelligence", {}) if dashboard else {}
        risk_alerts = intel.get("risk_alerts", []) if intel else []
        for item in risk_alerts:
            text = (
                str(item.get("message") or item.get("title") or "").strip()
                if isinstance(item, dict)
                else str(item or "").strip()
            )
            if text:
                return self._sanitize_user_facing_risk_text(result, text, action_model=action_model)
        return self._sanitize_user_facing_risk_text(
            result,
            getattr(result, "risk_warning", "") or getattr(result, "action_reason", "") or "开盘后复核价格、公告和新闻。",
            action_model=action_model,
        )

    @staticmethod
    def _neutralize_hold_risk_sell_directives(
        text: str,
        action_model: Optional[Dict[str, Any]] = None,
    ) -> str:
        action = str((action_model or {}).get("position_action") or "HOLD").strip().upper()
        if action not in {"", "HOLD"}:
            return text
        neutralized = re.sub(
            r"(?:建议|考虑|应当|应该|可考虑|可以|需要|必须|立即|直接)?\s*(?:全部|部分)?\s*(?:卖出|卖掉|减仓|清仓|离场)",
            "需人工复核风险",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        neutralized = re.sub(
            r"\b(?:sell|reduce|exit|close(?:\s+(?:out|position|positions|the\s+position|all))?)\b",
            "manual risk review",
            neutralized,
            flags=re.IGNORECASE,
        )
        neutralized = re.sub(r"(?:需人工复核风险[，,；;、\s]*){2,}", "需人工复核风险", neutralized)
        return neutralized.strip() or "需人工复核风险。"

    def _build_dashboard_observation_appendix_lines(
        self,
        *,
        observation_items: List[Dict[str, str]],
        section_title: str = "## 重点观察复盘（非持仓）",
        section_intro: str = "> 非持仓标的进入复盘；保留结论、理由、风险和参考位，供人工开盘前筛选。",
    ) -> List[str]:
        return build_dashboard_observation_appendix_lines(
            observation_items=observation_items,
            section_title=section_title,
            section_intro=section_intro,
        )

    def _build_dashboard_observation_items_lines(
        self,
        results: List[AnalysisResult],
    ) -> List[str]:
        lines: List[str] = []
        for result in results:
            item = self._build_dashboard_observation_item(result)
            lines.extend([
                item["heading"],
                item["summary_line"],
                item["action_line"],
                item["reason_line"],
                item["risk_line"],
                item["reference_line"],
                "",
            ])
        return lines

    def build_email_report_body(self, archive_report: str) -> str:
        """Return the concise email projection while preserving full archive content elsewhere."""
        content = str(archive_report or "").strip()
        if not content:
            return ""
        marker = f"\n{self.AUDIT_APPENDIX_HEADING}"
        if marker not in content:
            return content
        email_body = content.split(marker, 1)[0].rstrip()
        trailing_separator = "\n---"
        if email_body.endswith(trailing_separator):
            email_body = email_body[:-len(trailing_separator)].rstrip()
        email_body += (
            "\n\n---\n\n"
            "## 完整归档\n\n"
            "- 完整证据矩阵、历史校准、评分校准、风险仓位附录和审计细节已保存到本地 Markdown/HTML 归档。\n\n"
            "*免责声明：仅作计划，供人工决策辅助；系统不自动下单。*"
        )
        return email_body
    
    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None,
        portfolio_summary_section: Optional[str] = None,
    ) -> str:
        """
        生成决策仪表盘格式的日报（详细版）

        格式：市场概览 + 重要信息 + 核心结论 + 数据透视 + 作战计划

        Args:
            results: 分析结果列表
            report_date: 报告日期（默认今天）

        Returns:
            Markdown 格式的决策仪表盘日报
        """
        if report_date is None:
            report_date = self._default_report_date()
        self._remember_report_date(report_date)
        generated_at = self._now_in_report_tz()

        # 按评分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        try:
            overview = get_db().get_portfolio_overview()
        except Exception:
            overview = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}

        overview = self._build_report_time_portfolio_overview(
            overview=overview,
            results=results,
        )
        paper_portfolio_overview = self._get_paper_portfolio_overview_for_report()

        daily_summary = self.build_daily_decision_summary(
            results=sorted_results,
            report_date=report_date,
            generated_at=generated_at,
            overview=overview,
        )
        self._annotate_paper_ledger_scope_notes(daily_summary, paper_portfolio_overview)
        self._last_daily_decision_summary = daily_summary

        successful_results_for_summary, _, blocked_results_for_summary = self._split_completed_results(sorted_results)
        failed_results_for_summary = [r for r in sorted_results if is_failed_analysis(r)]

        report_lines = [
            f"# 🎯 {report_date} 决策仪表盘",
            "",
        ]
        report_lines.extend(render_preopen_decision_dashboard(daily_summary))
        if portfolio_summary_section:
            report_lines.extend([portfolio_summary_section.rstrip(), "", "---", ""])

        holdings = overview.get("holdings") or []
        executed_weight_by_code = {
            canonical_stock_code(item.get("code", "")): float(item.get("weight") or 0.0)
            for item in holdings
            if canonical_stock_code(item.get("code", ""))
        }
        holding_codes = {
            canonical_stock_code(item.get("code", ""))
            for item in holdings
            if canonical_stock_code(item.get("code", ""))
        }
        successful_results, actionable_results, blocked_results = self._split_completed_results(sorted_results)
        failed_results = [r for r in sorted_results if is_failed_analysis(r)]
        successful_codes = {
            canonical_stock_code(getattr(r, "code", ""))
            for r in successful_results
            if canonical_stock_code(getattr(r, "code", ""))
        }
        uncovered_holdings = [
            item for item in holdings
            if canonical_stock_code(item.get("code", "")) not in successful_codes
        ]
        holding_results = [
            r for r in actionable_results
            if canonical_stock_code(getattr(r, "code", "")) in holding_codes
        ]
        non_holding_results = [
            r for r in actionable_results
            if canonical_stock_code(getattr(r, "code", "")) not in holding_codes
        ]
        actionable_holding_results = self._effective_actionable_results(holding_results)
        actionable_non_holding_results = self._effective_actionable_results(non_holding_results)
        effective_actionable_results = actionable_holding_results + actionable_non_holding_results
        display_holding_results = [
            r for r in holding_results
            if not self._is_suppressed_executable_action_today(r)
        ]
        display_non_holding_results = [
            r for r in non_holding_results
            if not self._is_suppressed_executable_action_today(r)
        ]
        report_lines.extend(
            self._build_paper_portfolio_readonly_lines(
                paper_portfolio_overview,
                has_plan_actions=bool(effective_actionable_results),
                report_date=report_date,
            )
        )
        basis_counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
        for result in results:
            basis_counts[self._classify_price_basis(result)] += 1
        has_mixed_price_basis = basis_counts["realtime"] > 0 and (basis_counts["latest_close"] + basis_counts["close_only"]) > 0

        if holdings or actionable_holding_results or uncovered_holdings or failed_results or blocked_results or has_mixed_price_basis:
            report_lines.extend([
                "## 当前持仓动作",
                "",
                (
                    f"> 账户概览：可用现金 **{overview.get('cash', 0.0):,.2f}** | "
                    f"持仓市值 **{overview.get('equity_value', 0.0):,.2f}** | "
                    f"账户总值 **{overview.get('total_value', 0.0):,.2f}**"
                ),
                "",
                "> 有明确调仓动作时列出待人工处理项；无调仓动作时保留持仓复盘，供开盘前人工确认。",
                "",
            ])
            if actionable_holding_results:
                report_lines.extend(self._build_recommended_actions_table(actionable_holding_results))
            else:
                report_lines.append("- 当前持仓暂无明确调仓动作。")
                if display_holding_results:
                    report_lines.extend([
                        "",
                        "### 持仓复盘（无调仓观察）",
                        "",
                        "> 当前持仓今日没有明确调仓动作；以下保留 AI 摘要、关键理由和风险，供开盘前人工复核。",
                        "",
                    ])
                    report_lines.extend(self._build_recommended_actions_table(display_holding_results))
                    report_lines.append("")
                    report_lines.extend(self._build_dashboard_observation_items_lines(display_holding_results))
            report_lines.append("")
            if display_holding_results:
                report_lines.extend(
                    self._build_holding_followup_review_lines(
                        display_holding_results,
                        current_weight_by_code=executed_weight_by_code,
                    )
                )
            if uncovered_holdings or failed_results or blocked_results or has_mixed_price_basis:
                report_lines.extend([
                    "**待补齐 / 风险提醒**",
                    "",
                ])
                if uncovered_holdings:
                    report_lines.append(f"- 当前持仓有 **{len(uncovered_holdings)}** 只未覆盖分析，请优先补齐。")
                    report_lines.append("")
                    report_lines.append("**未覆盖持仓**")
                    for item in uncovered_holdings:
                        report_lines.append(
                            f"- {notification_formatting.format_stock_display_name(item.get('name'), item.get('code'))}"
                        )
                    report_lines.append("")
                if failed_results:
                    report_lines.append(f"- 今日有 **{len(failed_results)}** 只分析失败，建议重跑后再决策。")
                    report_lines.append("")
                    report_lines.append("**分析失败（建议重跑）**")
                    for result in failed_results:
                        stock_name = notification_formatting.format_stock_display_name(result.name, result.code)
                        error_message = str(getattr(result, "error_message", "") or "未知错误")
                        report_lines.append(f"- {stock_name}：{error_message}")
                    report_lines.append("")
                if blocked_results:
                    report_lines.append(f"- 今日有 **{len(blocked_results)}** 只触发验证阻断。")
                    report_lines.append("")
                    report_lines.append("**不可决策（仅观察）**")
                    for result in blocked_results:
                        report_lines.append(self._format_blocked_result_line(result))
                    report_lines.append("")
                if has_mixed_price_basis:
                    report_lines.append("- ⚠️ 价格口径存在“旧日线信号 + 新实时价格”混用，请谨慎下单。")
                report_lines.append("")

        if display_non_holding_results:
            report_lines.extend([
                "## 新开仓 / 观察清单",
                "",
            ])
            if display_non_holding_results:
                report_lines.extend(self._build_recommended_actions_table(display_non_holding_results))
            else:
                report_lines.append("- 今日无新开仓 / 观察标的。")
            report_lines.append("")
            observation_items = [
                self._build_dashboard_observation_item(result)
                for result in display_non_holding_results
            ]
            report_lines.extend(
                self._build_dashboard_observation_appendix_lines(
                    observation_items=observation_items,
                )
            )

        # 逐个股票的决策仪表盘（Issue #262: summary_only 时跳过详情）
        if not self._report_summary_only:
            detail_results = display_holding_results + display_non_holding_results
            detail_seen_codes = set()
            if detail_results:
                report_lines.extend([
                    "## 个股详细分析",
                    "",
                    "> 以下保留每只股票的详细分析、关键理由、风险和条件化参考；证据矩阵与校准细节仍在完整归档附录。",
                    "",
                ])
            for result in detail_results:
                code = canonical_stock_code(getattr(result, "code", ""))
                if code in detail_seen_codes:
                    continue
                detail_seen_codes.add(code)
                signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
                action_model = self._get_primary_action_model(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                
                stock_name = self._escape_md(notification_formatting.format_stock_display_name(result.name, result.code))
                
                report_lines.extend([
                    f"## {signal_emoji} {stock_name}",
                    "",
                    f"**价格基准**：{self._get_price_basis_label(result)}",
                    "",
                ])
                
                # ========== 舆情与基本面概览（放在最前面）==========
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                if intel:
                    report_lines.extend([
                        "### 📰 重要信息速览",
                        "",
                    ])
                    # 舆情情绪总结
                    if intel.get('sentiment_summary'):
                        sentiment_summary = self._sanitize_user_facing_ai_text(
                            result,
                            intel['sentiment_summary'],
                            strip_position_sizing=False,
                        )
                        report_lines.append(f"**💭 舆情情绪**: {sentiment_summary}")
                    # 业绩预期
                    if intel.get('earnings_outlook'):
                        earnings_outlook = self._sanitize_user_facing_ai_text(
                            result,
                            intel['earnings_outlook'],
                            strip_position_sizing=False,
                        )
                        report_lines.append(f"**📊 业绩预期**: {earnings_outlook}")
                    # 利好催化
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("")
                        report_lines.append("**✨ 利好催化**:")
                        for cat in catalysts:
                            cat_text = self._sanitize_user_facing_ai_text(result, cat, strip_position_sizing=False)
                            report_lines.append(f"- {cat_text}")
                    # 最新消息
                    if intel.get('latest_news'):
                        report_lines.append("")
                        latest_news = self._sanitize_user_facing_ai_text(
                            result,
                            intel['latest_news'],
                            strip_position_sizing=False,
                        )
                        report_lines.append(f"**📢 最新动态**: {latest_news}")
                    report_lines.append("")
                
                # ========== 核心结论 ==========
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = self._get_conflict_safe_core_conclusion(
                    result,
                    core.get('one_sentence', result.analysis_summary),
                )
                one_sentence = self._sanitize_user_facing_ai_text(result, one_sentence)
                time_sense = core.get('time_sensitivity', '本周内')
                pos_advice = core.get('position_advice', {})
                reason_text = self._sanitize_user_facing_ai_text(
                    result,
                    result.buy_reason or result.analysis_summary or '暂无',
                    strip_position_sizing=False,
                )
                
                report_lines.extend([
                    "### 核心结论",
                    f"- {signal_emoji} **{signal_text}** | {result.trend_prediction}",
                    f"- {one_sentence}",
                    "",
                    "### 主动作",
                    f"- {notification_formatting.format_position_action_label(action_model['position_action'])}（{notification_formatting.format_sizing_brief(action_model['target_weight'], action_model['position_action'])}）",
                    "",
                    "### 关键理由",
                    f"- {reason_text}",
                    f"- AI补充（非执行）：{self._get_conflict_safe_ai_commentary(result)}",
                    "",
                    "### 风险",
                    f"- 时效性：{time_sense}",
                ])
                risk_alerts = intel.get('risk_alerts', []) if intel else []
                canonical_risk = ""
                for risk_item in risk_alerts:
                    risk_text = (
                        str(risk_item.get("message") or risk_item.get("title") or "").strip()
                        if isinstance(risk_item, dict) else str(risk_item or "").strip()
                    )
                    if risk_text:
                        canonical_risk = self._sanitize_user_facing_risk_text(
                            result,
                            risk_text,
                            action_model=action_model,
                        )
                        break
                if canonical_risk:
                    report_lines.append(f"- ⚠️ {canonical_risk}")
                elif result.risk_warning:
                    report_lines.append(
                        f"- ⚠️ {self._sanitize_user_facing_risk_text(result, result.risk_warning, action_model=action_model)}"
                    )
                report_lines.append("")
                if action_model['ai_conflict']:
                    report_lines.extend([
                        "- ⚠️ AI解读与确定性动作不一致，请以确定性主动作作为准。",
                        "",
                    ])
                # 持仓分类建议（仅在确有差异时双分支展示）
                if pos_advice:
                    is_holding = code in holding_codes
                    no_position_text = self._sanitize_user_facing_ai_text(result, pos_advice.get('no_position'))
                    has_position_text = self._sanitize_user_facing_ai_text(result, pos_advice.get('has_position'))
                    report_lines.append("### 持仓指引")
                    if no_position_text and has_position_text and no_position_text != has_position_text:
                        if is_holding:
                            report_lines.append(f"- 持仓者怎么做：{has_position_text}")
                            report_lines.append(f"- 空仓者参考：{no_position_text}")
                        else:
                            report_lines.append(f"- 空仓者怎么做：{no_position_text}")
                            report_lines.append(f"- 持仓者参考：{has_position_text}")
                    else:
                        primary = has_position_text if is_holding else no_position_text
                        report_lines.append(f"- {'持仓者' if is_holding else '空仓者'}怎么做：{primary or self._format_deterministic_sizing_text(result)}")
                    report_lines.append("")

                self._append_market_snapshot(report_lines, result)
                
                # ========== 数据透视 ==========
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    
                    report_lines.extend([
                        "### 证据附录（技术/数据）",
                        "",
                    ])
                    # 趋势状态
                    if trend_data:
                        is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                        report_lines.extend([
                            f"**均线排列**: {trend_data.get('ma_alignment', 'N/A')} | 多头排列: {is_bullish} | 趋势强度: {trend_data.get('trend_score', 'N/A')}/100",
                            "",
                        ])
                    # 价格位置
                    if price_data:
                        bias_status = price_data.get('bias_status', 'N/A')
                        bias_emoji = "✅" if bias_status == "安全" else ("⚠️" if bias_status == "警戒" else "🚨")
                        price_metric_label = self._get_price_metric_label(result)
                        report_lines.extend([
                            "| 价格指标 | 数值 |",
                            "|---------|------|",
                            f"| {price_metric_label} | {price_data.get('current_price', 'N/A')} |",
                            f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                            f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                            f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                            f"| 乖离率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                            f"| 支撑位 | {price_data.get('support_level', 'N/A')} |",
                            f"| 压力位 | {price_data.get('resistance_level', 'N/A')} |",
                            "",
                        ])
                    # 量能分析
                    if vol_data:
                        volume_meaning = self._guard_volume_commentary(result, vol_data.get('volume_meaning', ''))
                        if volume_meaning == "量能数据不足（量比/换手率缺失），不做量能结论":
                            report_lines.extend([
                                f"**量能**: {volume_meaning}",
                                "",
                            ])
                        else:
                            report_lines.extend([
                                f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | 换手率 {vol_data.get('turnover_rate', 'N/A')}%",
                                f"💡 *{volume_meaning}*",
                                "",
                            ])
                # ========== 作战计划 ==========
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.extend([
                        "### 条件化计划点位 / 人工复核参考",
                        "",
                    ])
                    # 狙击点位
                    sniper = battle.get('sniper_points', {})
                    plan_points = self._build_conditional_plan_points(result, sniper)
                    if plan_points:
                        report_lines.extend([
                            *render_conditional_plan_points_markdown(plan_points),
                        ])
                    # 仓位策略
                    position = battle.get('position_strategy', {})
                    if position:
                        position_lines = self._build_ai_position_strategy_lines(position, action_model, result)
                        if position_lines:
                            report_lines.extend([
                                "**💰 AI作战计划（非执行参考）**",
                                *position_lines,
                                "",
                            ])
                    # 检查清单
                    checklist = battle.get('action_checklist', []) if battle else []
                    if checklist:
                        report_lines.extend([
                            "**✅ 检查清单**",
                            "",
                        ])
                        for item in checklist:
                            report_lines.append(f"- {item}")
                        report_lines.append("")
                
                # 如果没有 dashboard，显示传统格式
                if not dashboard:
                    # 操作理由
                    if result.buy_reason:
                        report_lines.extend([
                            f"**💡 操作理由**: {self._sanitize_report_jargon(self._sanitize_unverified_backtest_claim(result, result.buy_reason))}",
                            "",
                        ])
                    # 风险提示
                    if result.risk_warning:
                        report_lines.extend([
                            f"**⚠️ 风险提示**: {self._sanitize_user_facing_risk_text(result, result.risk_warning, action_model=action_model)}",
                            "",
                        ])
                    # 技术面分析
                    if result.ma_analysis or result.volume_analysis:
                        report_lines.extend([
                            "### 📊 技术面",
                            "",
                        ])
                        if result.ma_analysis:
                            report_lines.append(f"**均线**: {result.ma_analysis}")
                        if result.volume_analysis:
                            report_lines.append(f"**量能**: {self._guard_volume_commentary(result, result.volume_analysis)}")
                        report_lines.append("")
                    # 消息面
                    if result.news_summary:
                        report_lines.extend([
                            "### 📰 消息面",
                            f"{result.news_summary}",
                            "",
                        ])
                
                report_lines.extend([
                    "---",
                    "",
                ])

        appendix_lines = [
            self.AUDIT_APPENDIX_HEADING,
            "",
            "### 审计范围 / 数据基准",
            "",
            (
                f"> 审计范围：成功分析 **{len(successful_results_for_summary)}** 只 | "
                f"失败 **{len(failed_results_for_summary)}** 只 | "
                f"验证阻断 **{len(blocked_results_for_summary)}** 只 | "
                f"{self._format_execution_action_counts_text(daily_summary)}"
            ),
            "",
        ]
        appendix_lines.extend(self._build_data_baseline_lines(results, generated_at, title="### 数据时间基准"))
        if holdings:
            appendix_lines.extend([
                "### 持仓估值与覆盖（附录）",
                "",
                "> 用于审计账户快照、报告时点估值来源与今日分析覆盖范围。",
                "",
            ])
            appendix_lines.extend(
                build_holdings_audit_table(
                    holdings=holdings,
                    format_stock_display_name=notification_formatting.format_stock_display_name,
                    format_valuation_source_label=notification_formatting.format_valuation_source_label,
                    format_yes_no_label=notification_formatting.format_yes_no_label,
                    to_markdown_table_cell=self._to_markdown_table_cell,
                )
            )
            appendix_lines.append("")
        if effective_actionable_results:
            appendix_lines.extend([
                "### 计划仓位模拟（附录）",
                "",
                "> 以下目标仓位仅为模拟计划；正文动作表优先用于开盘前阅读。",
                "",
            ])
            appendix_lines.extend(
                self._build_simulated_target_allocation_table(
                    effective_actionable_results,
                    executed_weight_by_code=executed_weight_by_code,
                )
            )
            appendix_lines.extend(
                self._build_section_c_reconciliation_lines(
                    results=effective_actionable_results,
                    overview_holdings=holdings,
                )
            )
            appendix_lines.append("")
        appendix_lines.extend(render_preopen_decision_appendix(daily_summary, include_heading=False))
        report_lines.extend(appendix_lines)
        
        # 底部免责声明与时间
        report_lines.extend([
            "",
            "*免责声明：仅作计划，供人工决策辅助；系统不自动下单。*",
            f"*报告生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def generate_wechat_dashboard(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None,
    ) -> str:
        """
        生成企业微信决策仪表盘精简版（控制在4000字符内）
        
        只保留核心结论和狙击点位
        
        Args:
            results: 分析结果列表
            
        Returns:
            精简版决策仪表盘
        """
        generated_at = self._now_in_report_tz()
        if report_date is None:
            report_date = self._default_report_date(generated_at)
        self._remember_report_date(report_date)
        
        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        normal_results, actionable_results, blocked_results = self._split_completed_results(sorted_results)
        failed_results = [r for r in sorted_results if is_failed_analysis(r)]

        try:
            overview = get_db().get_portfolio_overview()
        except Exception:
            overview = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}

        overview = self._build_report_time_portfolio_overview(
            overview=overview,
            results=results,
        )
        daily_summary = self.build_daily_decision_summary(
            results=sorted_results,
            report_date=report_date,
            generated_at=generated_at,
            overview=overview,
        )
        self._last_daily_decision_summary = daily_summary

        effective_actionable_results = self._effective_actionable_results(actionable_results)
        display_actionable_results = self._display_actionable_results(actionable_results)
        
        lines = [
            f"## 🎯 {report_date} 决策仪表盘",
            "",
            f"> 成功 {len(normal_results)} 只 | 失败 {len(failed_results)} 只 | 验证阻断 {len(blocked_results)} 只 | {self._format_execution_action_counts_text(daily_summary)}",
            "",
        ]
        lines.extend(render_preopen_decision_dashboard(daily_summary))
        if blocked_results:
            lines.extend([
                f"> ⚠️ 有 {len(blocked_results)} 只触发验证阻断，统一按不可决策/仅观察输出",
                "",
            ])
        lines.extend(self._build_data_baseline_lines(results, generated_at, title="**🕒 数据时间基准**"))
        executed_weight_by_code = {
            str(item.get("code", "")).strip(): float(item.get("weight") or 0.0)
            for item in (overview.get("holdings") or [])
            if str(item.get("code", "")).strip()
        }

        lines.extend([
            "**A) 当前账户状态（已执行）**",
            f"- 现金: {overview.get('cash', 0.0):,.2f}",
            f"- 持仓市值: {overview.get('equity_value', 0.0):,.2f}",
            f"- 总资产: {overview.get('total_value', 0.0):,.2f}",
            "",
            "**B) 今日建议动作（未执行）**",
            "",
        ])
        
        # Issue #262: summary_only 时仅输出摘要列表
        if self._report_summary_only:
            for r in display_actionable_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}')
                action_model = self._get_primary_action_model(r)
                lines.append(
                    f"{signal_emoji} **{stock_name}({r.code})**: "
                    f"{notification_formatting.format_position_action_label(action_model['position_action'])} · "
                    f"{notification_formatting.format_sizing_brief(action_model['target_weight'], action_model['position_action'])} "
                    f"(AI补充: {self._get_conflict_safe_ai_commentary(r)} / 评分{r.sentiment_score})"
                )
            if blocked_results:
                lines.extend([
                    "",
                    "**B2) 不可决策（仅观察）**",
                ])
                for result in blocked_results:
                    lines.append(self._format_blocked_result_line(result, truncate=80))
            lines.extend([
                "",
                "**C) 目标仓位（模拟，不代表已成交）**",
            ])
            for r in effective_actionable_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}')
                lines.append(
                    f"{signal_emoji} {stock_name}({r.code}): 执行中 {executed_weight_by_code.get(r.code, 0.0):.2%} "
                    f"→ 模拟目标 {getattr(r, 'target_weight', 0.0):.2%} "
                    f"(Δ{getattr(r, 'delta_amount', 0.0):,.2f})"
                )
        else:
            for result in display_actionable_results:
                signal_text, signal_emoji, _ = self._get_signal_level(result)
                action_model = self._get_primary_action_model(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                
                # 股票名称
                stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
                stock_name = self._escape_md(stock_name)
                
                # 标题行：信号等级 + 股票名称
                lines.append(f"### {signal_emoji} **{signal_text}** | {stock_name}({result.code})")
                lines.append("")

                lines.append(f"📋 主动作(未执行): {self._format_primary_action_text(result)[:80]}")
                lines.append(f"📌 一句话: {self._get_conflict_safe_core_conclusion(result, core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary)[:80]}")
                lines.append(f"💬 AI补充(非执行): {self._get_conflict_safe_ai_commentary(result)[:60]}")
                if action_model['ai_conflict']:
                    lines.append("⚠️ AI解读与主动作不一致，请以确定性主动作作为准")
                lines.append("")
                
                # 重要信息区（舆情+基本面）
                info_lines = []
                
                # 业绩预期
                if intel.get('earnings_outlook'):
                    outlook = self._sanitize_user_facing_ai_text(
                        result,
                        intel['earnings_outlook'],
                        strip_position_sizing=False,
                    )[:60]
                    info_lines.append(f"📊 业绩: {outlook}")
                if intel.get('sentiment_summary'):
                    sentiment = self._sanitize_user_facing_ai_text(
                        result,
                        intel['sentiment_summary'],
                        strip_position_sizing=False,
                    )[:50]
                    info_lines.append(f"💭 舆情: {sentiment}")
                if info_lines:
                    lines.extend(info_lines)
                    lines.append("")
                
                # 风险警报（最重要，醒目显示）
                risks = intel.get('risk_alerts', []) if intel else []
                if risks:
                    lines.append("🚨 **风险**:")
                    for risk in risks[:2]:  # 最多显示2条
                        raw_risk = (
                            str(risk.get("message") or risk.get("title") or "").strip()
                            if isinstance(risk, dict) else str(risk or "").strip()
                        )
                        risk_text = self._sanitize_user_facing_risk_text(
                            result,
                            raw_risk,
                            action_model=action_model,
                        )
                        risk_text = risk_text[:50] + "..." if len(risk_text) > 50 else risk_text
                        lines.append(f"   • {risk_text}")
                    lines.append("")
                
                # 利好催化
                catalysts = intel.get('positive_catalysts', []) if intel else []
                if catalysts:
                    lines.append("✨ **利好**:")
                    for cat in catalysts[:2]:  # 最多显示2条
                        cat = self._sanitize_user_facing_ai_text(result, cat, strip_position_sizing=False)
                        cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                        lines.append(f"   • {cat_text}")
                    lines.append("")
                
                # 狙击点位
                sniper = battle.get('sniper_points', {}) if battle else {}
                plan_points = self._build_conditional_plan_points(result, sniper)
                if plan_points:
                    lines.append(f"📍 条件化计划点位: {format_conditional_plan_points_inline(plan_points)[:180]}")
                    lines.append("")
                
                # 持仓建议
                pos_advice = core.get('position_advice', {}) if core else {}
                if pos_advice:
                    deterministic_sizing = self._format_deterministic_sizing_text(result)
                    lines.append(f"🧮 确定性仓位指引: {deterministic_sizing[:80]}")
                    no_pos = pos_advice.get('no_position', '')
                    has_pos = pos_advice.get('has_position', '')
                    if no_pos:
                        ai_no_pos = self._sanitize_user_facing_ai_text(result, no_pos)
                        if action_model['ai_conflict']:
                            ai_no_pos = self._get_conflict_safe_ai_commentary(result)
                        lines.append(f"💬 AI空仓者评论(非执行): {ai_no_pos[:44]}")
                    if has_pos:
                        ai_has_pos = self._sanitize_user_facing_ai_text(result, has_pos)
                        if action_model['ai_conflict']:
                            ai_has_pos = self._get_conflict_safe_ai_commentary(result)
                        lines.append(f"💬 AI持仓者评论(非执行): {ai_has_pos[:44]}")
                    lines.append("")
                
                # 检查清单简化版
                checklist = battle.get('action_checklist', []) if battle else []
                if checklist:
                    # 只显示不通过的项目
                    failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                    if failed_checks:
                        lines.append("**检查未通过项**:")
                        for check in failed_checks[:3]:
                            lines.append(f"   {check[:40]}")
                        lines.append("")

                lines.append(
                    f"🧮 模拟仓位: 已执行 {executed_weight_by_code.get(result.code, 0.0):.2%} "
                    f"→ 目标 {getattr(result, 'target_weight', 0.0):.2%} "
                    f"(模拟Δ{getattr(result, 'delta_amount', 0.0):,.2f})"
                )
                lines.append("")
                
                lines.append("---")
                lines.append("")
        if failed_results:
            lines.extend(["**⚠️ 分析失败（建议重跑）**"])
            for result in failed_results:
                reason = str(getattr(result, "error_message", "") or "未知错误")
                lines.append(f"- {result.name}({result.code})：{reason[:80]}")
            lines.append("")
        if blocked_results and not self._report_summary_only:
            lines.extend(["**⚠️ 不可决策（仅观察）**"])
            for result in blocked_results:
                lines.append(self._format_blocked_result_line(result, truncate=80))
            lines.append("")
        
        # 底部
        lines.append(f"*生成时间: {generated_at.strftime('%H:%M')}*")
        
        content = "\n".join(lines)
        
        return content
    
    def generate_wechat_summary(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None,
    ) -> str:
        """
        生成企业微信精简版日报（控制在4000字符内）

        Args:
            results: 分析结果列表

        Returns:
            精简版 Markdown 内容
        """
        generated_at = self._now_in_report_tz()
        if report_date is None:
            report_date = self._default_report_date(generated_at)
        self._remember_report_date(report_date)

        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        normal_results, actionable_results, blocked_results = self._split_completed_results(sorted_results)
        failed_results = [r for r in sorted_results if is_failed_analysis(r)]
        try:
            overview_source = get_db().get_portfolio_overview()
        except Exception:
            overview_source = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}
        overview = self._build_report_time_portfolio_overview(
            overview=overview_source,
            results=results,
        )
        daily_summary = self.build_daily_decision_summary(
            results=sorted_results,
            report_date=report_date,
            generated_at=generated_at,
            overview=overview,
        )
        self._last_daily_decision_summary = daily_summary

        display_actionable_results = self._display_actionable_results(actionable_results)
        avg_score = sum(r.sentiment_score for r in actionable_results) / len(actionable_results) if actionable_results else 0

        lines = [
            f"## 📅 {report_date} 股票分析报告",
            "",
            f"> 成功 **{len(normal_results)}** 只 | 失败 **{len(failed_results)}** 只 | 验证阻断 **{len(blocked_results)}** 只 | {self._format_execution_action_counts_text(daily_summary)} | 均分:{avg_score:.0f}",
            "",
        ]
        lines.extend(self._build_data_baseline_lines(results, generated_at, title="**🕒 数据时间基准**"))
        
        # 每只股票精简信息（控制长度）
        for result in display_actionable_results:
            _, emoji, _ = self._get_signal_level(result)
            
            # 核心信息行
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(
                f"**{self._get_canonical_operation_advice(result)}** | 评分:{result.sentiment_score} | "
                f"{result.trend_prediction} | 价格基准：{self._get_price_basis_label(result)}"
            )
            
            # 操作理由（截断）
            if hasattr(result, 'buy_reason') and result.buy_reason:
                sanitized_reason = self._sanitize_user_facing_ai_text(result, result.buy_reason, strip_position_sizing=False)
                reason = sanitized_reason[:80] + "..." if len(sanitized_reason) > 80 else sanitized_reason
                lines.append(f"💡 {reason}")
            
            # 核心看点
            if hasattr(result, 'key_points') and result.key_points:
                points = result.key_points[:60] + "..." if len(result.key_points) > 60 else result.key_points
                lines.append(f"🎯 {points}")
            
            # 风险提示（截断）
            if hasattr(result, 'risk_warning') and result.risk_warning:
                sanitized_risk = self._sanitize_user_facing_risk_text(result, result.risk_warning)
                risk = sanitized_risk[:50] + "..." if len(sanitized_risk) > 50 else sanitized_risk
                lines.append(f"⚠️ {risk}")
            
            lines.append("")

        if blocked_results:
            lines.extend(["", "**⚠️ 不可决策（仅观察）**"])
            for result in blocked_results:
                lines.append(self._format_blocked_result_line(result, truncate=80))
            lines.append("")
        
        # 底部
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
            f"*详细报告见 reports/report_{report_date.replace('-', '')}.md*"
        ])
        if failed_results:
            lines.extend(["", "**⚠️ 分析失败（建议重跑）**"])
            for result in failed_results:
                reason = str(getattr(result, "error_message", "") or "未知错误")
                lines.append(f"- {result.name}({result.code})：{reason[:80]}")
        
        content = "\n".join(lines)
        
        return content
    
    def generate_single_stock_report(self, result: AnalysisResult) -> str:
        """
        生成单只股票的分析报告（用于单股推送模式 #55）
        
        格式精简但信息完整，适合每分析完一只股票立即推送
        
        Args:
            result: 单只股票的分析结果
            
        Returns:
            Markdown 格式的单股报告
        """
        generated_at = self._now_in_report_tz()
        report_date = generated_at.strftime('%Y-%m-%d %H:%M')
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
        core = dashboard.get('core_conclusion', {}) if dashboard else {}
        battle = dashboard.get('battle_plan', {}) if dashboard else {}
        intel = dashboard.get('intelligence', {}) if dashboard else {}
        
        # 股票名称（转义 *ST 等特殊字符）
        raw_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
        stock_name = self._escape_md(raw_name)
        
        lines = [
            f"## {signal_emoji} {stock_name} ({result.code})",
            "",
            f"> {report_date} | 评分: **{result.sentiment_score}** | {result.trend_prediction}",
            f"> 价格基准：{self._get_price_basis_label(result)}",
            "",
        ]
        lines.extend(self._build_data_baseline_lines([result], generated_at, title="### 🕒 数据时间基准"))
        if _is_validation_blocked(result):
            lines.extend([
                "### ⚠️ 验证阻断",
                "",
                "- 当前状态：**验证未通过 / 不可决策 / 仅观察**",
                f"- 原因：{self._format_validation_issue_text(result)}",
                "",
            ])

        self._append_market_snapshot(lines, result)
        
        # 核心决策（一句话）
        one_sentence = self._get_conflict_safe_core_conclusion(
            result,
            core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary,
        )
        if one_sentence:
            if _is_validation_blocked(result):
                current_weight = float(getattr(result, "current_weight", 0.0) or 0.0)
                hold_line = (
                    f"- 🧾 **持仓处理**: 保留当前持仓，不执行调仓（当前仓位 {current_weight:.2%}）"
                    if current_weight > 0
                    else "- 🧾 **持仓处理**: 当前不建立新仓位，仅观察"
                )
                lines.extend([
                    "### 📌 核心结论",
                    "",
                    "- 🧭 **当前状态**: 当前不可决策，仅观察",
                    hold_line,
                    f"- 📌 **一句话结论**: {one_sentence}",
                    f"- 💬 **AI补充（非执行）**: {self._get_conflict_safe_ai_commentary(result)}",
                    "",
                ])
            else:
                lines.extend([
                    "### 📌 核心结论",
                    "",
                    f"- 🧭 **主动作（优先执行）**: {self._format_primary_action_text(result)}",
                    f"- 📌 **一句话结论**: {one_sentence}",
                    f"- 💬 **AI补充（非执行）**: {self._get_conflict_safe_ai_commentary(result)}",
                    "",
                ])
        
        # 重要信息（舆情+基本面）
        info_added = False
        if intel:
            if intel.get('earnings_outlook'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                earnings_outlook = self._sanitize_user_facing_ai_text(
                    result,
                    intel['earnings_outlook'],
                    strip_position_sizing=False,
                )
                lines.append(f"📊 **业绩预期**: {earnings_outlook[:100]}")

            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                sentiment_summary = self._sanitize_user_facing_ai_text(
                    result,
                    intel['sentiment_summary'],
                    strip_position_sizing=False,
                )
                lines.append(f"💭 **舆情情绪**: {sentiment_summary[:80]}")

            # 风险警报
            risks = intel.get('risk_alerts', [])
            if risks:
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append("")
                lines.append("🚨 **风险警报**:")
                for risk in risks[:3]:
                    risk_text = (
                        str(risk.get("message") or risk.get("title") or "").strip()
                        if isinstance(risk, dict) else str(risk or "").strip()
                    )
                    risk_text = self._sanitize_user_facing_risk_text(result, risk_text)
                    lines.append(f"- {risk_text[:60]}")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append("✨ **利好催化**:")
                for cat in catalysts[:3]:
                    cat_text = self._sanitize_user_facing_ai_text(result, cat, strip_position_sizing=False)
                    lines.append(f"- {cat_text[:60]}")
        
        if info_added:
            lines.append("")
        
        # 狙击点位
        sniper = battle.get('sniper_points', {}) if battle else {}
        plan_points = self._build_conditional_plan_points(result, sniper)
        if plan_points:
            lines.extend(render_conditional_plan_points_markdown(plan_points))

        # 持仓建议
        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice and not _is_validation_blocked(result):
            action_model = self._get_primary_action_model(result)
            if action_model["ai_conflict"]:
                no_position_text = self._get_conflict_safe_ai_commentary(result)
                has_position_text = no_position_text
            else:
                no_position_text = self._sanitize_user_facing_ai_text(
                    result,
                    pos_advice.get('no_position', self._get_normalized_ai_operation_advice(result))
                )
                has_position_text = self._sanitize_user_facing_ai_text(
                    result,
                    pos_advice.get('has_position', '继续持有')
                )
            lines.extend([
                "### 💼 持仓建议",
                "",
                f"- 🧮 **确定性仓位指引(主指令)**: {self._format_deterministic_sizing_text(result)}",
                f"- 💬 **AI空仓者评论(非执行)**: {no_position_text}",
                f"- 💬 **AI持仓者评论(非执行)**: {has_position_text}",
                "",
            ])
        
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
        ])

        return "\n".join(lines)

    # Display name mapping for realtime data sources
    _SOURCE_DISPLAY_NAMES = {
        "yfinance": "Yahoo Finance",
        "fallback": "降级兜底",
    }

    def _append_market_snapshot(self, lines: List[str], result: AnalysisResult) -> None:
        snapshot = getattr(result, 'market_snapshot', None)
        if not snapshot:
            return

        lines.extend([
            "### 📈 当日行情",
            "",
            "| 收盘 | 昨收 | 开盘 | 最高 | 最低 | 涨跌幅 | 涨跌额 | 振幅 | 成交量 | 成交额 |",
            "|------|------|------|------|------|-------|-------|------|--------|--------|",
            f"| {snapshot.get('close', 'N/A')} | {snapshot.get('prev_close', 'N/A')} | "
            f"{snapshot.get('open', 'N/A')} | {snapshot.get('high', 'N/A')} | "
            f"{snapshot.get('low', 'N/A')} | {snapshot.get('pct_chg', 'N/A')} | "
            f"{snapshot.get('change_amount', 'N/A')} | {snapshot.get('amplitude', 'N/A')} | "
            f"{snapshot.get('volume', 'N/A')} | {snapshot.get('amount', 'N/A')} |",
        ])

        if "price" in snapshot:
            raw_source = snapshot.get('source', 'N/A')
            display_source = self._SOURCE_DISPLAY_NAMES.get(raw_source, raw_source)
            price_metric_label = self._get_price_metric_label(result)
            lines.extend([
                "",
                f"| {price_metric_label} | 量比 | 换手率 | 行情来源 |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {display_source} |",
            ])

        self._append_valuation_snapshot(lines, snapshot)
        lines.append("")

    def _append_valuation_snapshot(self, lines: List[str], snapshot: Dict[str, Any]) -> None:
        raw_snapshot = snapshot.get("valuation_snapshot")
        valuation = raw_snapshot.to_dict() if hasattr(raw_snapshot, "to_dict") else raw_snapshot
        lines.extend(["", "### 估值快照", ""])
        if not isinstance(valuation, dict) or not valuation or not self._has_valuation_snapshot_values(valuation):
            lines.append("- 估值数据缺失，不参与估值增强。")
            return
        if not self._has_core_valuation_snapshot_values(valuation):
            lines.append("- 估值关键字段缺失（PE/PB/股息率），仅保留为降级参考，不参与估值增强。")
            return

        source = str(valuation.get("source") or snapshot.get("source") or "unknown")
        display_source = self._SOURCE_DISPLAY_NAMES.get(source, source)
        if self._has_nonempty_valuation_value(valuation.get("pe_ttm")):
            lines.append(f"- PE(TTM)：{self._format_optional_number(valuation.get('pe_ttm'))}")
        if self._has_nonempty_valuation_value(valuation.get("pe_forward")):
            lines.append(f"- PE(Forward)：{self._format_optional_number(valuation.get('pe_forward'))}")
        if self._has_nonempty_valuation_value(valuation.get("pb")):
            lines.append(f"- PB：{self._format_optional_number(valuation.get('pb'))}")
        if self._has_nonempty_valuation_value(valuation.get("dividend_yield")):
            lines.append(f"- 股息率：{self._format_optional_percent(valuation.get('dividend_yield'))}")
        lines.extend(
            [
                f"- 来源：{display_source}",
                f"- 时间：{valuation.get('as_of_date') or 'missing'}",
                "- 说明：仅作估值证据展示，不改变今日主动作。",
            ]
        )

    @staticmethod
    def _format_optional_number(value: Any) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "missing"

    @staticmethod
    def _format_optional_percent(value: Any) -> str:
        try:
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return "missing"

    @staticmethod
    def _has_valuation_snapshot_values(valuation: Dict[str, Any]) -> bool:
        fields = ("pe_ttm", "pe_forward", "pb", "dividend_yield", "market_cap", "roe", "debt_to_equity")
        return any(NotificationService._has_nonempty_valuation_value(valuation.get(field)) for field in fields)

    @staticmethod
    def _has_core_valuation_snapshot_values(valuation: Dict[str, Any]) -> bool:
        fields = ("pe_ttm", "pe_forward", "pb", "dividend_yield")
        return any(NotificationService._has_nonempty_valuation_value(valuation.get(field)) for field in fields)

    @staticmethod
    def _has_nonempty_valuation_value(value: Any) -> bool:
        return value is not None and str(value).strip().lower() not in {"", "n/a", "none", "null", "unknown", "nan"}
    
    def send_to_wechat(self, content: str) -> bool:
        """
        推送消息到企业微信机器人
        
        企业微信 Webhook 消息格式：
        支持 markdown 类型以及 text 类型, markdown 类型在微信中无法展示，可以使用 text 类型,
        markdown 类型会解析 markdown 格式,text 类型会直接发送纯文本。

        markdown 类型示例：
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "## 标题\n\n内容"
            }
        }
        
        text 类型示例：
        {
            "msgtype": "text",
            "text": {
                "content": "内容"
            }
        }

        注意：企业微信 Markdown 限制 4096 字节（非字符）, Text 类型限制 2048 字节，超长内容会自动分批发送
        可通过环境变量 WECHAT_MAX_BYTES 调整限制值
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        if not self._wechat_url:
            logger.warning("企业微信 Webhook 未配置，跳过推送")
            return False
        
        # 根据消息类型动态限制上限，避免 text 类型超过企业微信 2048 字节限制
        if self._wechat_msg_type == 'text':
            max_bytes = min(self._wechat_max_bytes, 2000)  # 预留一定字节给系统/分页标记
        else:
            max_bytes = self._wechat_max_bytes  # markdown 默认 4000 字节
        
        # 检查字节长度，超长则分批发送
        content_bytes = len(content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"消息内容超长({content_bytes}字节/{len(content)}字符)，将分批发送")
            return self._send_wechat_chunked(content, max_bytes)
        
        try:
            return self._send_wechat_message(content)
        except Exception as e:
            logger.error(f"发送企业微信消息失败: {e}")
            return False

    def _send_wechat_image(self, image_bytes: bytes) -> bool:
        """Send image via WeChat Work webhook msgtype image (Issue #289)."""
        if not self._wechat_url:
            return False
        if len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "企业微信图片超限 (%d > %d bytes)，拒绝发送，调用方应 fallback 为文本",
                len(image_bytes), WECHAT_IMAGE_MAX_BYTES,
            )
            return False
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            md5_hash = hashlib.md5(image_bytes).hexdigest()
            payload = {
                "msgtype": "image",
                "image": {"base64": b64, "md5": md5_hash},
            }
            response = requests.post(
                self._wechat_url, json=payload, timeout=30, verify=self._webhook_verify_ssl
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info("企业微信图片发送成功")
                    return True
                logger.error("企业微信图片发送失败: %s", result.get("errmsg", ""))
            else:
                logger.error("企业微信请求失败: HTTP %s", response.status_code)
            return False
        except Exception as e:
            logger.error("企业微信图片发送异常: %s", e)
            return False

    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批发送长消息到企业微信
        
        按股票分析块（以 --- 或 ### 分隔）智能分割，确保每批不超过限制
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """获取字符串的 UTF-8 字节数"""
            return len(s.encode('utf-8'))
        
        # 智能分割：优先按 "---" 分隔（股票之间的分隔线）
        # 其次尝试各级标题分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        elif "\n## " in content:
            # 按 ## 分割 (兼容二级标题)
            parts = content.split("\n## ")
            sections = [parts[0]] + [f"## {p}" for p in parts[1:]]
            separator = "\n"
        elif "\n**" in content:
            # 按 ** 加粗标题分割 (兼容 AI 未输出标准 Markdown 标题的情况)
            parts = content.split("\n**")
            sections = [parts[0]] + [f"**{p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 无法智能分割，按字符强制分割
            return self._send_wechat_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        effective_max_bytes = max_bytes - 50  # 预留分页标记空间，避免边界超限
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果单个 section 就超长，需要强制截断
            if section_bytes > effective_max_bytes:
                # 先发送当前积累的内容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 强制截断这个超长 section（按字节截断）
                truncated = self._truncate_to_bytes(section, effective_max_bytes - 200)
                truncated += "\n\n...(本段内容过长已截断)"
                chunks.append(truncated)
                continue
            
            # 检查加入后是否超长
            if current_bytes + section_bytes > effective_max_bytes:
                # 保存当前块，开始新块
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最后一块
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批发送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企业微信分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分页标记
            if total_chunks > 1:
                page_marker = f"\n\n📄 *({i+1}/{total_chunks})*"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_wechat_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"企业微信第 {i+1}/{total_chunks} 批发送成功")
                else:
                    logger.error(f"企业微信第 {i+1}/{total_chunks} 批发送失败")
            except Exception as e:
                logger.error(f"企业微信第 {i+1}/{total_chunks} 批发送异常: {e}")

            # 批次间隔，避免触发频率限制
            if i < total_chunks - 1:
                time.sleep(2.5)  # 增加到 2.5s，避免企业微信限流

        return success_count == total_chunks
    
    def _send_wechat_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        强制按字节分割发送（无法智能分割时的 fallback）
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，确保不会在多字节字符中间截断
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 预留空间给分页标记
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企业微信强制分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 *({i+1}/{total_chunks})*" if total_chunks > 1 else ""
            
            try:
                if self._send_wechat_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"企业微信第 {i+1}/{total_chunks} 批发送异常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        按字节数截断字符串，确保不会在多字节字符中间截断
        
        Args:
            text: 要截断的字符串
            max_bytes: 最大字节数
            
        Returns:
            截断后的字符串
        """
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        
        # 从 max_bytes 位置往前找，确保不截断多字节字符
        truncated = encoded[:max_bytes]
        # 尝试解码，如果失败则继续往前
        while truncated:
            try:
                return truncated.decode('utf-8')
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""
    
    def _gen_wechat_payload(self, content: str) -> dict:
        """生成企业微信消息 payload"""
        if self._wechat_msg_type == 'text':
            return {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
        else:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }

    def _send_wechat_message(self, content: str) -> bool:
        """发送企业微信消息"""
        payload = self._gen_wechat_payload(content)
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=10,
            verify=self._webhook_verify_ssl
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("企业微信消息发送成功")
                return True
            else:
                logger.error(f"企业微信返回错误: {result}")
                return False
        else:
            logger.error(f"企业微信请求失败: {response.status_code}")
            return False
    
    def send_to_feishu(self, content: str) -> bool:
        """
        推送消息到飞书机器人
        
        飞书自定义机器人 Webhook 消息格式：
        {
            "msg_type": "text",
            "content": {
                "text": "文本内容"
            }
        }
        
        说明：飞书文本消息不会渲染 Markdown，需使用交互卡片（lark_md）格式
        
        注意：飞书文本消息限制约 20KB，超长内容会自动分批发送
        可通过环境变量 FEISHU_MAX_BYTES 调整限制值
        
        Args:
            content: 消息内容（Markdown 会转为纯文本）
            
        Returns:
            是否发送成功
        """
        if not self._feishu_url:
            logger.warning("飞书 Webhook 未配置，跳过推送")
            return False
        
        # 飞书 lark_md 支持有限，先做格式转换
        formatted_content = format_feishu_markdown(content)

        max_bytes = self._feishu_max_bytes  # 从配置读取，默认 20000 字节
        
        # 检查字节长度，超长则分批发送
        content_bytes = len(formatted_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"飞书消息内容超长({content_bytes}字节/{len(content)}字符)，将分批发送")
            return self._send_feishu_chunked(formatted_content, max_bytes)
        
        try:
            return self._send_feishu_message(formatted_content)
        except Exception as e:
            logger.error(f"发送飞书消息失败: {e}")
            return False
    
    def _send_feishu_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批发送长消息到飞书
        
        按股票分析块（以 --- 或 ### 分隔）智能分割，确保每批不超过限制
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """获取字符串的 UTF-8 字节数"""
            return len(s.encode('utf-8'))
        
        # 智能分割：优先按 "---" 分隔（股票之间的分隔线）
        # 如果没有分隔线，按 "### " 标题分割（每只股票的标题）
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割，但保留 ### 前缀
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 无法智能分割，按行强制分割
            return self._send_feishu_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果单个 section 就超长，需要强制截断
            if section_bytes > max_bytes:
                # 先发送当前积累的内容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 强制截断这个超长 section（按字节截断）
                truncated = self._truncate_to_bytes(section, max_bytes - 200)
                truncated += "\n\n...(本段内容过长已截断)"
                chunks.append(truncated)
                continue
            
            # 检查加入后是否超长
            if current_bytes + section_bytes > max_bytes:
                # 保存当前块，开始新块
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最后一块
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批发送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飞书分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分页标记
            if total_chunks > 1:
                page_marker = f"\n\n📄 ({i+1}/{total_chunks})"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_feishu_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"飞书第 {i+1}/{total_chunks} 批发送成功")
                else:
                    logger.error(f"飞书第 {i+1}/{total_chunks} 批发送失败")
            except Exception as e:
                logger.error(f"飞书第 {i+1}/{total_chunks} 批发送异常: {e}")
            
            # 批次间隔，避免触发频率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        强制按字节分割发送（无法智能分割时的 fallback）
        
        Args:
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，确保不会在多字节字符中间截断
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 预留空间给分页标记
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飞书强制分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 ({i+1}/{total_chunks})" if total_chunks > 1 else ""
            
            try:
                if self._send_feishu_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"飞书第 {i+1}/{total_chunks} 批发送异常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_message(self, content: str) -> bool:
        """发送单条飞书消息（优先使用 Markdown 卡片）"""
        def _post_payload(payload: Dict[str, Any]) -> bool:
            logger.debug("飞书请求 URL: [redacted-url]")
            logger.debug(f"飞书请求 payload 长度: {len(content)} 字符")

            response = requests.post(
                self._feishu_url,
                json=payload,
                timeout=30,
                verify=self._webhook_verify_ssl
            )

            logger.debug(f"飞书响应状态码: {response.status_code}")
            logger.debug(
                summarize_http_response_for_log(
                    "Feishu",
                    status_code=response.status_code,
                    body=response.text,
                )
            )

            if response.status_code == 200:
                result = response.json()
                code = result.get('code') if 'code' in result else result.get('StatusCode')
                if code == 0:
                    logger.info("飞书消息发送成功")
                    return True
                else:
                    error_msg = result.get('msg') or result.get('StatusMessage', '未知错误')
                    error_code = result.get('code') or result.get('StatusCode', 'N/A')
                    logger.error(f"飞书返回错误 [code={error_code}]: {redact_log_text(error_msg)}")
                    logger.error(
                        summarize_http_response_for_log(
                            "Feishu",
                            status_code=response.status_code,
                            body=response.text,
                            message=error_msg,
                        )
                    )
                    return False
            else:
                logger.error(f"飞书请求失败: HTTP {response.status_code}")
                logger.error(
                    summarize_http_response_for_log(
                        "Feishu",
                        status_code=response.status_code,
                        body=response.text,
                    )
                )
                return False

        # 1) 优先使用交互卡片（支持 Markdown 渲染）
        card_payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "ASX澳股智能分析报告"
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }

        if _post_payload(card_payload):
            return True

        # 2) 回退为普通文本消息
        text_payload = {
            "msg_type": "text",
            "content": {
                "text": content
            }
        }

        return _post_payload(text_payload)

    def send_to_email(
        self, content: str, subject: Optional[str] = None, receivers: Optional[List[str]] = None
    ) -> bool:
        """
        通过 SMTP 发送邮件（自动识别 SMTP 服务器）
        
        Args:
            content: 邮件内容（支持 Markdown，会转换为 HTML）
            subject: 邮件主题（可选，默认自动生成）
            receivers: 收件人列表（可选，默认使用配置的 receivers）
            
        Returns:
            是否发送成功
        """
        if not self._is_email_configured():
            logger.warning("邮件配置不完整，跳过推送")
            return False
        
        sender = self._email_config['sender']
        password = self._email_config['password']
        receivers = receivers or self._email_config['receivers']
        
        try:
            # 生成主题
            if subject is None:
                date_str = self._now_in_report_tz().strftime('%Y-%m-%d')
                subject = f"📈 股票智能分析报告 - {date_str}"
            
            # 将 Markdown 转换为简单 HTML
            html_content = self._markdown_to_html(content)
            
            # 构建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = formataddr((self._email_config.get('sender_name', '股票分析助手'), sender))
            msg['To'] = ', '.join(receivers)
            
            # 添加纯文本和 HTML 两个版本
            text_part = MIMEText(content, 'plain', 'utf-8')
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(text_part)
            msg.attach(html_part)
            
            # 自动识别 SMTP 配置
            domain = sender.split('@')[-1].lower()
            smtp_config = SMTP_CONFIGS.get(domain)
            
            if smtp_config:
                smtp_server = smtp_config['server']
                smtp_port = smtp_config['port']
                use_ssl = smtp_config['ssl']
                logger.info(f"自动识别邮箱类型: {domain} -> {smtp_server}:{smtp_port}")
            else:
                # 未知邮箱，尝试通用配置
                smtp_server = f"smtp.{domain}"
                smtp_port = 465
                use_ssl = True
                logger.warning(f"未知邮箱类型 {domain}，尝试通用配置: {smtp_server}:{smtp_port}")
            
            # 根据配置选择连接方式
            if use_ssl:
                # SSL 连接（端口 465）
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                # TLS 连接（端口 587）
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()
            
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            
            logger.info(f"邮件发送成功，收件人: {receivers}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("邮件发送失败：认证错误，请检查邮箱和授权码是否正确")
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"邮件发送失败：无法连接 SMTP 服务器 - {e}")
            return False
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return False

    def _send_email_with_inline_image(
        self, image_bytes: bytes, receivers: Optional[List[str]] = None
    ) -> bool:
        """Send email with inline image attachment (Issue #289)."""
        if not self._is_email_configured():
            return False
        sender = self._email_config['sender']
        password = self._email_config['password']
        receivers = receivers or self._email_config['receivers']
        try:
            date_str = self._now_in_report_tz().strftime('%Y-%m-%d')
            subject = f"📈 股票智能分析报告 - {date_str}"
            msg = MIMEMultipart('related')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = formataddr(
                (self._email_config.get('sender_name', '股票分析助手'), sender)
            )
            msg['To'] = ', '.join(receivers)

            alt = MIMEMultipart('alternative')
            alt.attach(MIMEText('报告已生成，详见下方图片。', 'plain', 'utf-8'))
            html_body = (
                '<p>报告已生成，详见下方图片（点击可查看大图）：</p>'
                '<p><img src="cid:report-image" alt="股票分析报告" style="max-width:100%%;" /></p>'
            )
            alt.attach(MIMEText(html_body, 'html', 'utf-8'))
            msg.attach(alt)

            img_part = MIMEImage(image_bytes, _subtype='png')
            img_part.add_header('Content-Disposition', 'inline', filename='report.png')
            img_part.add_header('Content-ID', '<report-image>')
            msg.attach(img_part)

            domain = sender.split('@')[-1].lower()
            smtp_config = SMTP_CONFIGS.get(domain)
            if smtp_config:
                smtp_server, smtp_port = smtp_config['server'], smtp_config['port']
                use_ssl = smtp_config['ssl']
            else:
                smtp_server, smtp_port = f"smtp.{domain}", 465
                use_ssl = True

            if use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            logger.info("邮件（内联图片）发送成功，收件人: %s", receivers)
            return True
        except Exception as e:
            logger.error("邮件（内联图片）发送失败: %s", e)
            return False

    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        Convert Markdown to HTML for email, with tables and compact layout.

        Delegates to formatters.markdown_to_html_document for shared logic.
        """
        return markdown_to_html_document(markdown_text)
    
    def send_to_telegram(self, content: str) -> bool:
        """
        推送消息到 Telegram 机器人
        
        Telegram Bot API 格式：
        POST https://api.telegram.org/bot<token>/sendMessage
        {
            "chat_id": "xxx",
            "text": "消息内容",
            "parse_mode": "Markdown"
        }
        
        Args:
            content: 消息内容（Markdown 格式）
            
        Returns:
            是否发送成功
        """
        if not self._is_telegram_configured():
            logger.warning("Telegram 配置不完整，跳过推送")
            return False
        
        bot_token = self._telegram_config['bot_token']
        chat_id = self._telegram_config['chat_id']
        message_thread_id = self._telegram_config.get('message_thread_id')
        
        try:
            # Telegram API 端点
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            # Telegram 消息最大长度 4096 字符
            max_length = 4096
            
            if len(content) <= max_length:
                # 单条消息发送
                return self._send_telegram_message(api_url, chat_id, content, message_thread_id)
            else:
                # 分段发送长消息
                return self._send_telegram_chunked(api_url, chat_id, content, max_length, message_thread_id)
                
        except Exception as e:
            logger.error(f"发送 Telegram 消息失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _send_telegram_message(self, api_url: str, chat_id: str, text: str, message_thread_id: Optional[str] = None) -> bool:
        """Send a single Telegram message with exponential backoff retry (Fixes #287)"""
        # Convert Markdown to Telegram-compatible format
        telegram_text = self._convert_to_telegram_markdown(text)
        
        payload = {
            "chat_id": chat_id,
            "text": telegram_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        if message_thread_id:
            payload['message_thread_id'] = message_thread_id

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(api_url, json=payload, timeout=10)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    delay = 2 ** attempt  # 2s, 4s
                    logger.warning(f"Telegram request failed (attempt {attempt}/{max_retries}): {e}, "
                                   f"retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Telegram request failed after {max_retries} attempts: {e}")
                    return False
        
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    logger.info("Telegram 消息发送成功")
                    return True
                else:
                    error_desc = result.get('description', '未知错误')
                    logger.error(f"Telegram 返回错误: {error_desc}")
                    
                    # If Markdown parsing failed, fall back to plain text
                    if 'parse' in error_desc.lower() or 'markdown' in error_desc.lower():
                        logger.info("尝试使用纯文本格式重新发送...")
                        plain_payload = dict(payload)
                        plain_payload.pop('parse_mode', None)
                        plain_payload['text'] = text  # Use original text
                        
                        try:
                            response = requests.post(api_url, json=plain_payload, timeout=10)
                            if response.status_code == 200 and response.json().get('ok'):
                                logger.info("Telegram 消息发送成功（纯文本）")
                                return True
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                            logger.error(f"Telegram plain-text fallback failed: {e}")
                    
                    return False
            elif response.status_code == 429:
                # Rate limited — respect Retry-After header
                retry_after = int(response.headers.get('Retry-After', 2 ** attempt))
                if attempt < max_retries:
                    logger.warning(f"Telegram rate limited, retrying in {retry_after}s "
                                   f"(attempt {attempt}/{max_retries})...")
                    time.sleep(retry_after)
                    continue
                else:
                    logger.error(f"Telegram rate limited after {max_retries} attempts")
                    return False
            else:
                if attempt < max_retries and response.status_code >= 500:
                    delay = 2 ** attempt
                    logger.warning(f"Telegram server error HTTP {response.status_code} "
                                   f"(attempt {attempt}/{max_retries}), retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                logger.error(f"Telegram 请求失败: HTTP {response.status_code}")
                logger.error(f"响应内容: {response.text}")
                return False

        return False
    
    def _send_telegram_chunked(self, api_url: str, chat_id: str, content: str, max_length: int, message_thread_id: Optional[str] = None) -> bool:
        """分段发送长 Telegram 消息"""
        # 按段落分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_length = len(section) + 5  # +5 for "\n---\n"
            
            if current_length + section_length > max_length:
                # 发送当前块
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"发送 Telegram 消息块 {chunk_index}...")
                    if not self._send_telegram_message(api_url, chat_id, chunk_content, message_thread_id):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 发送最后一块
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"发送 Telegram 消息块 {chunk_index}...")
            if not self._send_telegram_message(api_url, chat_id, chunk_content, message_thread_id):
                all_success = False
                
        return all_success

    def _send_telegram_photo(self, image_bytes: bytes) -> bool:
        """Send image via Telegram sendPhoto API (Issue #289)."""
        if not self._is_telegram_configured():
            return False
        bot_token = self._telegram_config['bot_token']
        chat_id = self._telegram_config['chat_id']
        message_thread_id = self._telegram_config.get('message_thread_id')
        api_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        try:
            data = {"chat_id": chat_id}
            if message_thread_id:
                data['message_thread_id'] = message_thread_id
            files = {"photo": ("report.png", image_bytes, "image/png")}
            response = requests.post(api_url, data=data, files=files, timeout=30)
            if response.status_code == 200 and response.json().get('ok'):
                logger.info("Telegram 图片发送成功")
                return True
            logger.error("Telegram 图片发送失败: %s", response.text[:200])
            return False
        except Exception as e:
            logger.error("Telegram 图片发送异常: %s", e)
            return False

    def _convert_to_telegram_markdown(self, text: str) -> str:
        """
        将标准 Markdown 转换为 Telegram 支持的格式
        
        Telegram Markdown 限制：
        - 不支持 # 标题
        - 使用 *bold* 而非 **bold**
        - 使用 _italic_ 
        """
        result = text
        
        # 移除 # 标题标记（Telegram 不支持）
        result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
        
        # 转换 **bold** 为 *bold*
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result)
        
        # 转义特殊字符（Telegram Markdown 需要）
        # 注意：不转义已经用于格式的 * _ `
        for char in ['[', ']', '(', ')']:
            result = result.replace(char, f'\\{char}')
        
        return result
    
    def send_to_pushover(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 Pushover
        
        Pushover API 格式：
        POST https://api.pushover.net/1/messages.json
        {
            "token": "应用 API Token",
            "user": "用户 Key",
            "message": "消息内容",
            "title": "标题（可选）"
        }
        
        Pushover 特点：
        - 支持 iOS/Android/桌面多平台推送
        - 消息限制 1024 字符
        - 支持优先级设置
        - 支持 HTML 格式
        
        Args:
            content: 消息内容（Markdown 格式，会转为纯文本）
            title: 消息标题（可选，默认为"股票分析报告"）
            
        Returns:
            是否发送成功
        """
        if not self._is_pushover_configured():
            logger.warning("Pushover 配置不完整，跳过推送")
            return False
        
        user_key = self._pushover_config['user_key']
        api_token = self._pushover_config['api_token']
        
        # Pushover API 端点
        api_url = "https://api.pushover.net/1/messages.json"
        
        # 处理消息标题
        if title is None:
            date_str = self._now_in_report_tz().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        
        # Pushover 消息限制 1024 字符
        max_length = 1024
        
        # 转换 Markdown 为纯文本（Pushover 支持 HTML，但纯文本更通用）
        plain_content = self._markdown_to_plain_text(content)
        
        if len(plain_content) <= max_length:
            # 单条消息发送
            return self._send_pushover_message(api_url, user_key, api_token, plain_content, title)
        else:
            # 分段发送长消息
            return self._send_pushover_chunked(api_url, user_key, api_token, plain_content, title, max_length)
    
    def _markdown_to_plain_text(self, markdown_text: str) -> str:
        """
        将 Markdown 转换为纯文本
        
        移除 Markdown 格式标记，保留可读性
        """
        text = markdown_text
        
        # 移除标题标记 # ## ###
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        
        # 移除加粗 **text** -> text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        
        # 移除斜体 *text* -> text
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        
        # 移除引用 > text -> text
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        
        # 移除列表标记 - item -> item
        text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)
        
        # 移除分隔线 ---
        text = re.sub(r'^---+$', '────────', text, flags=re.MULTILINE)
        
        # 移除表格语法 |---|---|
        text = re.sub(r'\|[-:]+\|[-:|\s]+\|', '', text)
        text = re.sub(r'^\|(.+)\|$', r'\1', text, flags=re.MULTILINE)
        
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def _send_pushover_message(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        message: str, 
        title: str,
        priority: int = 0
    ) -> bool:
        """
        发送单条 Pushover 消息
        
        Args:
            api_url: Pushover API 端点
            user_key: 用户 Key
            api_token: 应用 API Token
            message: 消息内容
            title: 消息标题
            priority: 优先级 (-2 ~ 2，默认 0)
        """
        try:
            payload = {
                "token": api_token,
                "user": user_key,
                "message": message,
                "title": title,
                "priority": priority,
            }
            
            response = requests.post(api_url, data=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 1:
                    logger.info("Pushover 消息发送成功")
                    return True
                else:
                    errors = result.get('errors', ['未知错误'])
                    logger.error(f"Pushover 返回错误: {errors}")
                    return False
            else:
                logger.error(f"Pushover 请求失败: HTTP {response.status_code}")
                logger.debug(f"响应内容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"发送 Pushover 消息失败: {e}")
            return False
    
    def _send_pushover_chunked(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        content: str, 
        title: str,
        max_length: int
    ) -> bool:
        """
        分段发送长 Pushover 消息
        
        按段落分割，确保每段不超过最大长度
        """
        import time
        
        # 按段落（分隔线或双换行）分割
        if "────────" in content:
            sections = content.split("────────")
            separator = "────────"
        else:
            sections = content.split("\n\n")
            separator = "\n\n"
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for section in sections:
            # 计算添加这个 section 后的实际长度
            # join() 只在元素之间放置分隔符，不是每个元素后面
            # 所以：第一个元素不需要分隔符，后续元素需要一个分隔符连接
            if current_chunk:
                # 已有元素，添加新元素需要：当前长度 + 分隔符 + 新 section
                new_length = current_length + len(separator) + len(section)
            else:
                # 第一个元素，不需要分隔符
                new_length = len(section)
            
            if new_length > max_length:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_length = len(section)
            else:
                current_chunk.append(section)
                current_length = new_length
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"Pushover 分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分页标记到标题
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            
            if self._send_pushover_message(api_url, user_key, api_token, chunk, chunk_title):
                success_count += 1
                logger.info(f"Pushover 第 {i+1}/{total_chunks} 批发送成功")
            else:
                logger.error(f"Pushover 第 {i+1}/{total_chunks} 批发送失败")
            
            # 批次间隔，避免触发频率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def send_to_custom(self, content: str) -> bool:
        """
        推送消息到自定义 Webhook
        
        支持任意接受 POST JSON 的 Webhook 端点
        默认发送格式：{"text": "消息内容", "content": "消息内容"}
        
        适用于：
        - 钉钉机器人
        - Discord Webhook
        - Slack Incoming Webhook
        - 自建通知服务
        - 其他支持 POST JSON 的服务
        
        Args:
            content: 消息内容（Markdown 格式）
            
        Returns:
            是否至少有一个 Webhook 发送成功
        """
        if not self._custom_webhook_urls:
            logger.warning("未配置自定义 Webhook，跳过推送")
            return False
        
        success_count = 0
        
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # 通用 JSON 格式，兼容大多数 Webhook
                # 钉钉格式: {"msgtype": "text", "text": {"content": "xxx"}}
                # Slack 格式: {"text": "xxx"}
                # Discord 格式: {"content": "xxx"}
                
                # 钉钉机器人对 body 有字节上限（约 20000 bytes），超长需要分批发送
                if self._is_dingtalk_webhook(url):
                    if self._send_dingtalk_chunked(url, content, max_bytes=20000):
                        logger.info(f"自定义 Webhook {i+1}（钉钉）推送成功")
                        success_count += 1
                    else:
                        logger.error(f"自定义 Webhook {i+1}（钉钉）推送失败")
                    continue

                # 其他 Webhook：单次发送
                payload = self._build_custom_webhook_payload(url, content)
                if self._post_custom_webhook(url, payload, timeout=30):
                    logger.info(f"自定义 Webhook {i+1} 推送成功")
                    success_count += 1
                else:
                    logger.error(f"自定义 Webhook {i+1} 推送失败")
                    
            except Exception as e:
                logger.error(f"自定义 Webhook {i+1} 推送异常: {e}")
        
        logger.info(f"自定义 Webhook 推送完成：成功 {success_count}/{len(self._custom_webhook_urls)}")
        return success_count > 0

    @staticmethod
    def _is_dingtalk_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower

    @staticmethod
    def _is_discord_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return (
            'discord.com/api/webhooks' in url_lower
            or 'discordapp.com/api/webhooks' in url_lower
        )

    def _send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        """Send image to Custom Webhooks; Discord supports file attachment (Issue #289)."""
        if not self._custom_webhook_urls:
            return False
        success_count = 0
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                if self._is_discord_webhook(url):
                    files = {"file": ("report.png", image_bytes, "image/png")}
                    data = {"content": "📈 股票智能分析报告"}
                    headers = {"User-Agent": "StockAnalysis/1.0"}
                    if self._custom_webhook_bearer_token:
                        headers["Authorization"] = (
                            f"Bearer {self._custom_webhook_bearer_token}"
                        )
                    response = requests.post(
                        url, data=data, files=files, headers=headers, timeout=30,
                        verify=self._webhook_verify_ssl
                    )
                    if response.status_code in (200, 204):
                        logger.info("自定义 Webhook %d（Discord 图片）推送成功", i + 1)
                        success_count += 1
                    else:
                        logger.error(
                            "自定义 Webhook %d（Discord 图片）推送失败: HTTP %s",
                            i + 1, response.status_code,
                        )
                else:
                    if fallback_content:
                        payload = self._build_custom_webhook_payload(url, fallback_content)
                        if self._post_custom_webhook(url, payload, timeout=30):
                            logger.info(
                                "自定义 Webhook %d（图片不支持，回退文本）推送成功", i + 1
                            )
                            success_count += 1
                    else:
                        logger.warning(
                            "自定义 Webhook %d 不支持图片，且无回退内容，跳过", i + 1
                        )
            except Exception as e:
                logger.error("自定义 Webhook %d 图片推送异常: %s", i + 1, e)
        return success_count > 0

    def _post_custom_webhook(self, url: str, payload: dict, timeout: int = 30) -> bool:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        # 支持 Bearer Token 认证（#51）
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response = requests.post(url, data=body, headers=headers, timeout=timeout, verify=self._webhook_verify_ssl)
        if response.status_code == 200:
            return True
        logger.error(f"自定义 Webhook 推送失败: HTTP {response.status_code}")
        logger.debug(f"响应内容: {response.text[:200]}")
        return False

    def _chunk_markdown_by_bytes(self, content: str, max_bytes: int) -> List[str]:
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))

        def split_by_bytes(text: str, limit: int) -> List[str]:
            parts: List[str] = []
            remaining = text
            while remaining:
                part = self._truncate_to_bytes(remaining, limit)
                if not part:
                    break
                parts.append(part)
                remaining = remaining[len(part):]
            return parts

        # 优先按分隔线/标题分割，保证分页自然
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # fallback：按行拼接
            sections = content.split("\n")
            separator = "\n"

        chunks: List[str] = []
        current_chunk: List[str] = []
        current_bytes = 0
        sep_bytes = get_bytes(separator)

        for section in sections:
            section_bytes = get_bytes(section)
            extra = sep_bytes if current_chunk else 0

            # 单段超长：截断
            if section_bytes + extra > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0

                # 无法按结构拆分时，按字节强制拆分，避免整段被截断丢失
                for part in split_by_bytes(section, max(200, max_bytes - 200)):
                    chunks.append(part)
                continue

            if current_bytes + section_bytes + extra > max_bytes:
                chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                if current_chunk:
                    current_bytes += sep_bytes
                current_chunk.append(section)
                current_bytes += section_bytes

        if current_chunk:
            chunks.append(separator.join(current_chunk))

        # 移除空块
        return [c for c in (c.strip() for c in chunks) if c]

    def _send_dingtalk_chunked(self, url: str, content: str, max_bytes: int = 20000) -> bool:
        import time as _time

        # 为 payload 开销预留空间，避免 body 超限
        budget = max(1000, max_bytes - 1500)
        chunks = self._chunk_markdown_by_bytes(content, budget)
        if not chunks:
            return False

        total = len(chunks)
        ok = 0

        for idx, chunk in enumerate(chunks):
            marker = f"\n\n📄 *({idx+1}/{total})*" if total > 1 else ""
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析报告",
                    "text": chunk + marker,
                },
            }

            # 如果仍超限（极端情况下），再按字节硬截断一次
            body_bytes = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            if body_bytes > max_bytes:
                hard_budget = max(200, budget - (body_bytes - max_bytes) - 200)
                payload["markdown"]["text"] = self._truncate_to_bytes(payload["markdown"]["text"], hard_budget)

            if self._post_custom_webhook(url, payload, timeout=30):
                ok += 1
            else:
                logger.error(f"钉钉分批发送失败: 第 {idx+1}/{total} 批")

            if idx < total - 1:
                _time.sleep(1)

        return ok == total
    
    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        根据 URL 构建对应的 Webhook payload
        
        自动识别常见服务并使用对应格式
        """
        url_lower = url.lower()
        
        # 钉钉机器人
        if 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析报告",
                    "text": content
                }
            }
        
        # Discord Webhook
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            # Discord 限制 2000 字符
            truncated = content[:1900] + "..." if len(content) > 1900 else content
            return {
                "content": truncated
            }
        
        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": content,
                "mrkdwn": True
            }
        
        # Bark (iOS 推送)
        if 'api.day.app' in url_lower:
            return {
                "title": "股票分析报告",
                "body": content[:4000],  # Bark 限制
                "group": "stock"
            }
        
        # 通用格式（兼容大多数服务）
        return {
            "text": content,
            "content": content,
            "message": content,
            "body": content
        }

    def _send_via_source_context(self, content: str) -> bool:
        """
        使用消息上下文（如钉钉/飞书会话）发送一份报告
        
        主要用于从机器人 Stream 模式触发的任务，确保结果能回到触发的会话。
        """
        success = False
        
        # 尝试钉钉会话
        session_webhook = self._extract_dingtalk_session_webhook()
        if session_webhook:
            try:
                if self._send_dingtalk_chunked(session_webhook, content, max_bytes=20000):
                    logger.info("已通过钉钉会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("钉钉会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"钉钉会话（Stream）推送异常: {e}")

        # 尝试飞书会话
        feishu_info = self._extract_feishu_reply_info()
        if feishu_info:
            try:
                if self._send_feishu_stream_reply(feishu_info["chat_id"], content):
                    logger.info("已通过飞书会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("飞书会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"飞书会话（Stream）推送异常: {e}")

        return success

    def _send_feishu_stream_reply(self, chat_id: str, content: str) -> bool:
        """
        通过飞书 Stream 模式发送消息到指定会话
        
        Args:
            chat_id: 飞书会话 ID
            content: 消息内容
            
        Returns:
            是否发送成功
        """
        try:
            from bot.platforms.feishu_stream import FeishuReplyClient, FEISHU_SDK_AVAILABLE
            if not FEISHU_SDK_AVAILABLE:
                logger.warning("飞书 SDK 不可用，无法发送 Stream 回复")
                return False
            
            from src.config import get_config
            config = get_config()
            
            app_id = getattr(config, 'feishu_app_id', None)
            app_secret = getattr(config, 'feishu_app_secret', None)
            
            if not app_id or not app_secret:
                logger.warning("飞书 APP_ID 或 APP_SECRET 未配置")
                return False
            
            # 创建回复客户端
            reply_client = FeishuReplyClient(app_id, app_secret)
            
            # 飞书文本消息有长度限制，需要分批发送
            max_bytes = getattr(config, 'feishu_max_bytes', 20000)
            content_bytes = len(content.encode('utf-8'))
            
            if content_bytes > max_bytes:
                return self._send_feishu_stream_chunked(reply_client, chat_id, content, max_bytes)
            
            return reply_client.send_to_chat(chat_id, content)
            
        except ImportError as e:
            logger.error(f"导入飞书 Stream 模块失败: {e}")
            return False
        except Exception as e:
            logger.error(f"飞书 Stream 回复异常: {e}")
            return False

    def _send_feishu_stream_chunked(
        self, 
        reply_client, 
        chat_id: str, 
        content: str, 
        max_bytes: int
    ) -> bool:
        """
        分批发送长消息到飞书（Stream 模式）
        
        Args:
            reply_client: FeishuReplyClient 实例
            chat_id: 飞书会话 ID
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))
        
        # 按段落或分隔线分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 按行分割
            sections = content.split("\n")
            separator = "\n"
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            if current_bytes + section_bytes > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 发送每个分块
        success = True
        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(0.5)  # 避免请求过快
            
            if not reply_client.send_to_chat(chat_id, chunk):
                success = False
                logger.error(f"飞书 Stream 分块 {i+1}/{len(chunks)} 发送失败")
        
        return success
    
    def send_to_pushplus(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 PushPlus

        PushPlus API 格式：
        POST http://www.pushplus.plus/send
        {
            "token": "用户令牌",
            "title": "消息标题",
            "content": "消息内容",
            "template": "html/txt/json/markdown"
        }

        PushPlus 特点：
        - 国内推送服务，免费额度充足
        - 支持微信公众号推送
        - 支持多种消息格式

        Args:
            content: 消息内容（Markdown 格式）
            title: 消息标题（可选）

        Returns:
            是否发送成功
        """
        if not self._pushplus_token:
            logger.warning("PushPlus Token 未配置，跳过推送")
            return False

        # PushPlus API 端点
        api_url = "http://www.pushplus.plus/send"

        # 处理消息标题
        if title is None:
            date_str = self._now_in_report_tz().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"

        try:
            payload = {
                "token": self._pushplus_token,
                "title": title,
                "content": content,
                "template": "markdown"  # 使用 Markdown 格式
            }

            response = requests.post(api_url, json=payload, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 200:
                    logger.info("PushPlus 消息发送成功")
                    return True
                else:
                    error_msg = result.get('msg', '未知错误')
                    logger.error(f"PushPlus 返回错误: {error_msg}")
                    return False
            else:
                logger.error(f"PushPlus 请求失败: HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"发送 PushPlus 消息失败: {e}")
            return False

    def send_to_serverchan3(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 Server酱3 (支持多账号同时推送)
        """
        # 获取所有已配置的 Key
        keys = []
        if self._serverchan3_sendkey:
            keys.append(self._serverchan3_sendkey)
        # 尝试获取你在 __init__ 中新增的第二个变量
        sckey2 = getattr(self, '_serverchan3_sendkey_2', None)
        if sckey2:
            keys.append(sckey2)

        if not keys:
            logger.warning("Server酱3 所有 SendKey 均未配置，跳过推送")
            return False

        # 处理消息标题
        if title is None:
            date_str = self._now_in_report_tz().strftime('%Y-%m-%d')
            display_title = f"📈 股票分析报告 - {date_str}"
        else:
            display_title = title

        overall_success = False

        # 核心逻辑：循环发送给列表里的每一个 Key
        for sendkey in keys:
            try:
                # 根据 sendkey 格式构造 URL
                if sendkey.startswith('sctp'):
                    match = re.match(r'sctp(\d+)t', sendkey)
                    if match:
                        num = match.group(1)
                        url = f"https://{num}.push.ft07.com/send/{sendkey}.send"
                    else:
                        logger.error(f"Server酱3 Key 格式错误: {sendkey[:10]}...")
                        continue
                else:
                    url = f"https://sctapi.ftqq.com/{sendkey}.send"

                params = {
                    'title': display_title,
                    'desp': content,
                    'options': {}
                }

                headers = {'Content-Type': 'application/json;charset=utf-8'}
                # 增加到 15 秒超时，防止网络波动影响第二个推送
                response = requests.post(url, json=params, headers=headers, timeout=15)

                if response.status_code == 200:
                    logger.info(f"Server酱3 消息发送成功 (账号: {sendkey[:10]}...)")
                    overall_success = True
                else:
                    logger.error(f"Server酱3 请求失败: HTTP {response.status_code} ({sendkey[:10]}...)")
            except Exception as e:
                logger.error(f"发送 Server酱3 消息异常 ({sendkey[:10]}...): {e}")

        return overall_success


   
    def send_to_discord(self, content: str) -> bool:
        """
        推送消息到 Discord（支持 Webhook 和 Bot API）
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        # 优先使用 Webhook（配置简单，权限低）
        if self._discord_config['webhook_url']:
            return self._send_discord_webhook(content)
        
        # 其次使用 Bot API（权限高，需要 channel_id）
        if self._discord_config['bot_token'] and self._discord_config['channel_id']:
            return self._send_discord_bot(content)
        
        logger.warning("Discord 配置不完整，跳过推送")
        return False


    def send_to_astrbot(self, content: str) -> bool:
        """
        推送消息到 AstrBot（通过适配器支持）

        Args:
            content: Markdown 格式的消息内容

        Returns:
            是否发送成功
        """
        if self._astrbot_config['astrbot_url']:
            return self._send_astrbot(content)

        logger.warning("AstrBot 配置不完整，跳过推送")
        return False
    
    def _send_discord_webhook(self, content: str) -> bool:
        """
        使用 Webhook 发送消息到 Discord
        
        Discord Webhook 支持 Markdown 格式
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        try:
            payload = {
                'content': content,
                'username': 'ASX分析机器人',
                'avatar_url': 'https://picsum.photos/200'
            }
            
            response = requests.post(
                self._discord_config['webhook_url'],
                json=payload,
                timeout=10,
                verify=self._webhook_verify_ssl
            )
            
            if response.status_code in [200, 204]:
                logger.info("Discord Webhook 消息发送成功")
                return True
            else:
                logger.error(f"Discord Webhook 发送失败: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Discord Webhook 发送异常: {e}")
            return False
    
    def _send_discord_bot(self, content: str) -> bool:
        """
        使用 Bot API 发送消息到 Discord
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        try:
            headers = {
                'Authorization': f'Bot {self._discord_config["bot_token"]}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'content': content
            }
            
            url = f'https://discord.com/api/v10/channels/{self._discord_config["channel_id"]}/messages'
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                logger.info("Discord Bot 消息发送成功")
                return True
            else:
                logger.error(f"Discord Bot 发送失败: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Discord Bot 发送异常: {e}")
            return False

    def _send_astrbot(self, content: str) -> bool:
        import time
        """
        使用 Bot API 发送消息到 AstrBot

        Args:
            content: Markdown 格式的消息内容

        Returns:
            是否发送成功
        """

        html_content = self._markdown_to_html(content)

        try:
            payload = {
                'content': html_content
            }
            signature =  ""
            timestamp = str(int(time.time()))
            if self._astrbot_config['astrbot_token']:
                """计算请求签名"""
                payload_json = json.dumps(payload, sort_keys=True)
                sign_data = f"{timestamp}.{payload_json}".encode('utf-8')
                key = self._astrbot_config['astrbot_token']
                signature = hmac.new(
                    key.encode('utf-8'),
                    sign_data,
                    hashlib.sha256
                ).hexdigest()
            url = self._astrbot_config['astrbot_url']
            response = requests.post(
                url, json=payload, timeout=10,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                    "X-Timestamp": timestamp
                },
                verify=self._webhook_verify_ssl
            )

            if response.status_code == 200:
                logger.info("AstrBot 消息发送成功")
                return True
            else:
                logger.error(f"AstrBot 发送失败: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"AstrBot 发送异常: {e}")
            return False

    def _should_use_image_for_channel(
        self, channel: NotificationChannel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        - WeChat: image exceeds ~2MB limit
        """
        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        if channel == NotificationChannel.WECHAT and len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "企业微信图片超限 (%d bytes)，回退为 Markdown 文本发送",
                len(image_bytes),
            )
            return False
        return True

    def send(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False
    ) -> bool:
        """
        统一发送接口 - 向所有已配置的渠道发送

        遍历所有已配置的渠道，逐一发送消息

        Fallback rules (Markdown-to-image, Issue #289):
        - When image_bytes is None (conversion failed / imgkit not installed /
          content over max_chars): all channels configured for image will send
          as Markdown text instead.
        - When WeChat image exceeds ~2MB: that channel falls back to Markdown text.

        Args:
            content: 消息内容（Markdown 格式）
            email_stock_codes: 股票代码列表（可选，用于邮件渠道路由到对应分组邮箱，Issue #268）
            email_send_to_all: 邮件是否发往所有配置邮箱（用于大盘复盘等无股票归属的内容）

        Returns:
            是否至少有一个渠道发送成功
        """
        context_success = self.send_to_context(content)

        if not self._available_channels:
            if context_success:
                logger.info("已通过消息上下文渠道完成推送（无其他通知渠道）")
                return True
            logger.warning("通知服务不可用，跳过推送")
            return False

        # Markdown to image (Issue #289): convert once if any channel needs it.
        # Per-channel decision via _should_use_image_for_channel (see send() docstring for fallback rules).
        image_bytes = None
        channels_needing_image = {
            ch for ch in self._available_channels
            if ch.value in self._markdown_to_image_channels
        }
        if channels_needing_image:
            from src.md2img import markdown_to_image
            image_bytes = markdown_to_image(
                content, max_chars=self._markdown_to_image_max_chars
            )
            if image_bytes:
                logger.info("Markdown 已转换为图片，将向 %s 发送图片",
                            [ch.value for ch in channels_needing_image])
            elif channels_needing_image:
                logger.warning("Markdown 转图片失败，将回退为文本发送")

        channel_names = self.get_channel_names()
        logger.info(f"正在向 {len(self._available_channels)} 个渠道发送通知：{channel_names}")

        success_count = 0
        fail_count = 0

        for channel in self._available_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            use_image = self._should_use_image_for_channel(channel, image_bytes)
            try:
                if channel == NotificationChannel.WECHAT:
                    if use_image:
                        result = self._send_wechat_image(image_bytes)
                    else:
                        result = self.send_to_wechat(content)
                elif channel == NotificationChannel.FEISHU:
                    result = self.send_to_feishu(content)
                elif channel == NotificationChannel.TELEGRAM:
                    if use_image:
                        result = self._send_telegram_photo(image_bytes)
                    else:
                        result = self.send_to_telegram(content)
                elif channel == NotificationChannel.EMAIL:
                    receivers = None
                    if email_send_to_all and self._stock_email_groups:
                        receivers = self.get_all_email_receivers()
                    elif email_stock_codes and self._stock_email_groups:
                        receivers = self.get_receivers_for_stocks(email_stock_codes)
                    if use_image:
                        result = self._send_email_with_inline_image(
                            image_bytes, receivers=receivers
                        )
                    else:
                        result = self.send_to_email(content, receivers=receivers)
                elif channel == NotificationChannel.PUSHOVER:
                    result = self.send_to_pushover(content)
                elif channel == NotificationChannel.PUSHPLUS:
                    result = self.send_to_pushplus(content)
                elif channel == NotificationChannel.SERVERCHAN3:
                    result = self.send_to_serverchan3(content)
                elif channel == NotificationChannel.CUSTOM:
                    if use_image:
                        result = self._send_custom_webhook_image(
                            image_bytes, fallback_content=content
                        )
                    else:
                        result = self.send_to_custom(content)
                elif channel == NotificationChannel.DISCORD:
                    result = self.send_to_discord(content)
                elif channel == NotificationChannel.ASTRBOT:
                    result = self.send_to_astrbot(content)
                else:
                    logger.warning(f"不支持的通知渠道: {channel}")
                    result = False

                if result:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                logger.error(f"{channel_name} 发送失败: {e}")
                fail_count += 1

        logger.info(f"通知发送完成：成功 {success_count} 个，失败 {fail_count} 个")
        return success_count > 0 or context_success
    
    def _send_chunked_messages(self, content: str, max_length: int) -> bool:
        """
        分段发送长消息
        
        按段落（---）分割，确保每段不超过最大长度
        """
        # 按分隔线分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_with_divider = section + "\n---\n"
            section_length = len(section_with_divider)
            
            if current_length + section_length > max_length:
                # 发送当前块
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"发送消息块 {chunk_index}...")
                    if not self.send(chunk_content):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 发送最后一块
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"发送消息块 {chunk_index}（最后）...")
            if not self.send(chunk_content):
                all_success = False
        
        return all_success
    
    def save_report_to_file(
        self, 
        content: str, 
        filename: Optional[str] = None,
        reports_dir: Optional[Any] = None,
        *,
        report_date: Optional[str] = None,
    ) -> str:
        """
        保存日报到本地文件
        
        Args:
            content: 日报内容
            filename: 文件名（可选，默认按日期生成）
            
        Returns:
            保存的文件路径
        """
        from pathlib import Path
        
        if filename is None:
            resolved_report_date = report_date or getattr(self, "_last_report_date", None) or self._default_report_date()
            date_str = resolved_report_date.replace("-", "")
            filename = f"report_{date_str}.md"
        
        # 确保 reports 目录存在（默认使用项目根目录下的 reports）
        reports_dir = Path(reports_dir) if reports_dir is not None else Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日报已保存到: {filepath}")
        return str(filepath)

    def save_report_archive_html(
        self,
        content: str,
        filename: Optional[str] = None,
        *,
        markdown_filepath: Optional[str] = None,
        reports_dir: Optional[Any] = None,
        report_date: Optional[str] = None,
    ) -> str:
        """Save a text-based, print-friendly HTML archive for the daily report."""
        from pathlib import Path

        if filename is None and markdown_filepath:
            filename = Path(markdown_filepath).with_suffix(".html").name
        if filename is None:
            resolved_report_date = report_date or getattr(self, "_last_report_date", None) or self._default_report_date()
            date_str = resolved_report_date.replace("-", "")
            filename = f"report_{date_str}.html"
        if not filename.endswith(".html"):
            filename = f"{Path(filename).stem}.html"

        reports_path = Path(reports_dir) if reports_dir is not None else Path(__file__).parent.parent / "reports"
        reports_path.mkdir(parents=True, exist_ok=True)
        filepath = reports_path / filename
        html = markdown_to_archive_html_document(content)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"HTML归档报告已保存到: {filepath}")
        return str(filepath)

    def save_daily_decision_summary_to_file(
        self,
        summary: Dict[str, Any],
        filename: Optional[str] = None,
        *,
        reports_dir: Optional[Any] = None,
    ) -> str:
        """Save the stable daily_decision_summary JSON artifact."""
        from pathlib import Path

        if filename is None:
            report_date = str(
                summary.get("report_date")
                or getattr(self, "_last_report_date", None)
                or self._default_report_date()
            )
            filename = f"daily_decision_summary_{report_date.replace('-', '')}.json"
        reports_path = Path(reports_dir) if reports_dir is not None else Path(__file__).parent.parent / "reports"
        reports_path.mkdir(parents=True, exist_ok=True)
        filepath = reports_path / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        logger.info(f"daily_decision_summary 已保存到: {filepath}")
        return str(filepath)


class NotificationBuilder:
    """
    通知消息构建器
    
    提供便捷的消息构建方法
    """
    
    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        构建简单的提醒消息
        
        Args:
            title: 标题
            content: 内容
            alert_type: 类型（info, warning, error, success）
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")
        
        return f"{emoji} **{title}**\n\n{content}"
    
    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        构建股票摘要（简短版）
        
        适用于快速通知
        """
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        snapshot_dates = sorted(
            {
                str((getattr(r, "market_snapshot", None) or {}).get("date")).strip()
                for r in results
                if str((getattr(r, "market_snapshot", None) or {}).get("date", "")).strip()
                and str((getattr(r, "market_snapshot", None) or {}).get("date")).strip() != "未知"
            }
        )
        if len(snapshot_dates) == 1:
            daily_anchor = f"{snapshot_dates[0]} 日线（收盘口径）"
        elif len(snapshot_dates) > 1:
            daily_anchor = f"混合日线日期（{', '.join(snapshot_dates)}）"
        else:
            daily_anchor = "最新可用日线（通常为昨日收盘）"

        normal_results = [r for r in results if not is_failed_analysis(r)]
        actionable_results = [r for r in normal_results if not _is_validation_blocked(r)]
        blocked_results = [r for r in normal_results if _is_validation_blocked(r)]
        failed_results = [r for r in results if is_failed_analysis(r)]
        total_count = len(actionable_results)
        basis_counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
        for result in actionable_results:
            basis_counts[NotificationService._classify_price_basis(result)] += 1
        lines = [
            "📊 **今日自选股摘要**",
            "",
            (
                f"🕒 基准：技术面={daily_anchor}；新闻截至 {now_str}；"
                f"执行参考价=实时 {basis_counts['realtime']}/{total_count}，"
                f"latest close {basis_counts['latest_close']}/{total_count}，"
                f"close-only {basis_counts['close_only']}/{total_count}。"
            ),
            "",
        ]
        
        for r in sorted(actionable_results, key=lambda x: x.sentiment_score, reverse=True):
            decision = _get_effective_decision(r)
            emoji = _decision_to_signal_emoji(decision)
            basis = notification_formatting.format_price_basis_label(NotificationService._classify_price_basis(r))
            lines.append(
                f"{emoji} {r.name}({r.code}): {_decision_to_canonical_advice(decision)} | "
                f"评分 {r.sentiment_score} | 价格基准：{basis}"
            )

        if blocked_results:
            lines.extend(["", "⚠️ 不可决策（仅观察）:"])
            for r in blocked_results:
                lines.append(
                    f"- {r.name}({r.code}): {NotificationService._format_validation_issue_text(r)[:80]}"
                )
        
        if failed_results:
            lines.extend(["", "⚠️ 分析失败（建议重跑）:"])
            for r in failed_results:
                reason = str(getattr(r, "error_message", "") or "未知错误")
                lines.append(f"- {r.name}({r.code}): {reason[:80]}")

        return "\n".join(lines)


# 便捷函数
def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> bool:
    """
    发送每日报告的快捷方式
    
    自动识别渠道并推送
    """
    service = get_notification_service()
    
    # 生成报告
    report = service.generate_daily_report(results)
    
    # 保存到本地
    service.save_report_to_file(report)
    
    # 推送到配置的渠道（自动识别）
    return service.send(report)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    # 模拟分析结果
    test_results = [
        AnalysisResult(
            code='600519',
            name='贵州茅台',
            sentiment_score=75,
            trend_prediction='看多',
            analysis_summary='技术面强势，消息面利好',
            operation_advice='买入',
            technical_analysis='放量突破 MA20，MACD 金叉',
            news_summary='公司发布分红公告，业绩超预期',
        ),
        AnalysisResult(
            code='000001',
            name='平安银行',
            sentiment_score=45,
            trend_prediction='震荡',
            analysis_summary='横盘整理，等待方向',
            operation_advice='持有',
            technical_analysis='均线粘合，成交量萎缩',
            news_summary='近期无重大消息',
        ),
        AnalysisResult(
            code='300750',
            name='宁德时代',
            sentiment_score=35,
            trend_prediction='看空',
            analysis_summary='技术面走弱，注意风险',
            operation_advice='卖出',
            technical_analysis='跌破 MA10 支撑，量能不足',
            news_summary='行业竞争加剧，毛利率承压',
        ),
    ]
    
    service = NotificationService()
    
    # 显示检测到的渠道
    print("=== 通知渠道检测 ===")
    print(f"当前渠道: {service.get_channel_names()}")
    print(f"渠道列表: {service.get_available_channels()}")
    print(f"服务可用: {service.is_available()}")
    
    # 生成日报
    print("\n=== 生成日报测试 ===")
    report = service.generate_daily_report(test_results)
    print(report)
    
    # 保存到文件
    print("\n=== 保存日报 ===")
    filepath = service.save_report_to_file(report)
    print(f"保存成功: {filepath}")
    
    # 推送测试
    if service.is_available():
        print(f"\n=== 推送测试（{service.get_channel_names()}）===")
        success = service.send(report)
        print(f"推送结果: {'成功' if success else '失败'}")
    else:
        print("\n通知渠道未配置，跳过推送测试")
