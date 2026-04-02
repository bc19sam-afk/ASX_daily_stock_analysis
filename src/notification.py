# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 通知层
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
import smtplib
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
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
from src.formatters import format_feishu_markdown, markdown_to_html_document
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
    
    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        初始化通知服务
        
        检测所有已配置的渠道，推送时会向所有渠道发送
        """
        config = get_config()
        self._source_message = source_message
        self._context_channels: List[str] = []
        
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
        if explicit_source in {"realtime", "latest_close", "close_only"}:
            return explicit_source

        if NotificationService._is_realtime_price_available(result):
            return "realtime"
        close_value = (getattr(result, "market_snapshot", None) or {}).get("close")
        if NotificationService._has_valid_price(close_value):
            return "latest_close"
        return "close_only"

    @staticmethod
    def _format_price_basis_label(basis: str) -> str:
        return {
            "realtime": "实时价格",
            "latest_close": "最新收盘",
            "close_only": "仅收盘口径（无实时价格）",
        }.get(basis, "仅收盘口径（无实时价格）")

    @staticmethod
    def _format_valuation_source_label(source: str) -> str:
        return {
            "report_time_price": "报告时点价格",
            "stored_market_value_fallback": "账户快照市值回退",
        }.get(source, "账户快照市值回退")

    @staticmethod
    def _format_yes_no_label(flag: Any) -> str:
        return "是" if bool(flag) else "否"

    @staticmethod
    def _format_position_action_label(action: str) -> str:
        action_text = str(action or "").strip().upper()
        return {
            "OPEN": "建仓",
            "ADD": "加仓",
            "HOLD": "持有",
            "TRIM": "减仓",
            "REDUCE": "减仓",
            "CLOSE": "清仓",
        }.get(action_text, action_text or "持有")

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
        total_count = len(results)
        basis_counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
        for result in results:
            basis_counts[self._classify_price_basis(result)] += 1
        realtime_count = basis_counts["realtime"]
        latest_close_count = basis_counts["latest_close"]
        close_only_count = basis_counts["close_only"]
        has_realtime = realtime_count > 0

        lines = [
            title,
            "",
            f"- 技术面判断：基于 **{daily_anchor}**。",
            f"- 新闻更新：截至 **{news_cutoff}**。",
            (
                f"- 执行参考价格：**{realtime_count}/{total_count}** 只使用实时价格；"
                f"**{latest_close_count}/{total_count}** 只使用最新收盘；"
                f"**{close_only_count}/{total_count}** 只按收盘口径。"
            ),
        ]
        if has_mixed_dates:
            lines.append(f"- 日期说明：本次技术面涉及多个日线日期（{', '.join(snapshot_dates)}）。")
        if has_realtime:
            lines.append(
                f"- 说明：当前报告存在“旧日线信号 + 新实时价格”混用（实时 {realtime_count} 只，非实时 {latest_close_count + close_only_count} 只），已在此披露。"
            )
        lines.append("")
        return lines

    def _get_price_basis_label(self, result: AnalysisResult) -> str:
        """返回单只股票的价格口径标签（仅用于展示层披露）。"""
        return self._format_price_basis_label(self._classify_price_basis(result))
    
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
            report_date = datetime.now().strftime('%Y-%m-%d')
        generated_at = datetime.now()

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
        
        # 统计信息 - 使用主决策（优先 final_decision）
        decision_counts = self._count_primary_decisions(results)
        buy_count = decision_counts['BUY']
        sell_count = decision_counts['SELL']
        hold_count = decision_counts['HOLD']
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0
        
        report_lines.extend([
            "## 📊 操作建议汇总",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 🟢 建议买入/加仓 | **{buy_count}** 只 |",
            f"| 🟡 建议持有/观望 | **{hold_count}** 只 |",
            f"| 🔴 建议减仓/卖出 | **{sell_count}** 只 |",
            f"| 📈 平均看多评分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
        ])
        
        # Issue #262: summary_only 时仅输出摘要，跳过个股详情
        if self._report_summary_only:
            report_lines.extend(["## 📊 分析结果摘要", ""])
            for r in sorted_results:
                _, emoji, _ = self._get_signal_level(r)
                report_lines.append(
                    f"{emoji} **{r.name}({r.code})**: {self._get_canonical_operation_advice(r)} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction} | 价格基准：{self._get_price_basis_label(r)}"
                )
        else:
            report_lines.extend(["## 📈 个股详细分析", ""])
            # 逐个股票的详细分析
            for result in sorted_results:
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
                        f"**💡 操作理由**：{result.buy_reason}",
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
                    tech_lines.append(f"**综合**：{result.technical_analysis}")
                if hasattr(result, 'ma_analysis') and result.ma_analysis:
                    tech_lines.append(f"**均线**：{result.ma_analysis}")
                if hasattr(result, 'volume_analysis') and result.volume_analysis:
                    tech_lines.append(f"**量能**：{result.volume_analysis}")
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
                        result.analysis_summary,
                        "",
                    ])
                
                # 风险提示
                if hasattr(result, 'risk_warning') and result.risk_warning:
                    report_lines.extend([
                        f"⚠️ **风险提示**：{result.risk_warning}",
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

    @staticmethod
    def _sanitize_ai_share_count_commentary(text: Any) -> str:
        """Remove executable-looking AI share-count instructions from display text."""
        if text is None:
            return ""
        normalized = str(text).strip()
        if not normalized:
            return ""
        patterns = (
            r"(建议)?买入\s*\d+(?:\.\d+)?\s*股",
            r"buy\s*\d+(?:\.\d+)?\s*shares?",
        )
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            return "AI仓位建议（非执行）"
        return normalized

    def _build_recommended_actions_table(self, results: List[AnalysisResult]) -> List[str]:
        """Build recommended actions table (analysis output; not yet executed)."""
        lines = [
            "| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |",
            "|---|---|---|",
        ]

        for r in results:
            action_model = self._get_primary_action_model(r)
            _, signal_emoji, _ = self._get_signal_level(r)
            stock_cell = self._to_markdown_table_cell(
                f"{signal_emoji} **{self._escape_md(r.name)}({r.code})**"
            )
            action_cell = self._to_markdown_table_cell(
                f"{self._format_position_action_label(action_model['position_action'])} · 目标{action_model['target_weight']:.2%} · "
                f"模拟Δ{action_model['delta_amount']:,.2f}"
            )
            ai_view_text = (
                f"{self._get_conflict_safe_ai_commentary(r)} · "
                f"评分 {r.sentiment_score} · {r.trend_prediction}"
            )
            if action_model['ai_conflict']:
                ai_view_text += " ⚠️(已抑制冲突态AI操作措辞)"
            ai_view_cell = self._to_markdown_table_cell(ai_view_text)

            lines.append(
                "| "
                f"{stock_cell} | "
                f"{action_cell} | "
                f"{ai_view_cell} "
                "|"
            )
        return lines

    def _infer_ai_commentary_decision(self, operation_advice: str) -> Optional[str]:
        """Infer BUY/HOLD/SELL bucket from AI narrative advice text."""
        advice = str(operation_advice or '').strip().lower()
        if not advice:
            return None
        if any(token in advice for token in ('卖', '减仓', '止损', 'sell', 'reduce', 'close')):
            return 'SELL'
        if any(token in advice for token in ('买', '加仓', 'buy', 'open', 'add')):
            return 'BUY'
        if any(token in advice for token in ('持有', '观望', 'hold', 'watch')):
            return 'HOLD'
        return None

    def _get_primary_action_model(self, result: AnalysisResult) -> Dict[str, Any]:
        """Deterministic action source-of-truth model.

        Precedence rule:
        1) position_action decides executable action bucket when valid.
        2) missing/invalid position_action falls back to final_decision.
        """
        position_action = _normalize_position_action(result)
        decision = _decision_from_position_action(position_action)
        if not decision:
            decision = _get_effective_decision(result)
            position_action = {'BUY': 'OPEN', 'HOLD': 'HOLD', 'SELL': 'CLOSE'}.get(decision, 'HOLD')

        target_weight = float(getattr(result, 'target_weight', 0.0) or 0.0)
        delta_amount = float(getattr(result, 'delta_amount', 0.0) or 0.0)
        ai_decision = self._infer_ai_commentary_decision(self._get_normalized_ai_operation_advice(result))
        ai_conflict = bool(ai_decision and ai_decision != decision)
        return {
            'decision': decision,
            'position_action': position_action,
            'target_weight': target_weight,
            'delta_amount': delta_amount,
            'ai_conflict': ai_conflict,
        }

    def _get_canonical_operation_advice(self, result: AnalysisResult) -> str:
        """Return unified final advice wording aligned with deterministic decision."""
        decision = self._get_primary_action_model(result)['decision']
        return _decision_to_canonical_advice(decision)

    def _get_normalized_ai_operation_advice(self, result: AnalysisResult) -> str:
        """Return normalized AI narrative advice without overriding its original semantics."""
        advice = str(getattr(result, 'operation_advice', '') or '').strip()
        if not advice:
            return self._get_canonical_operation_advice(result)
        advice = advice.replace("\r\n", "\n").replace("\r", "\n")
        return " ".join(part.strip() for part in advice.split("\n") if part.strip())

    def _get_conflict_safe_ai_commentary(self, result: AnalysisResult) -> str:
        """Return AI commentary text safe for conflict-state presentation."""
        action_model = self._get_primary_action_model(result)
        if action_model['ai_conflict']:
            return "AI解读与确定性主动作存在方向冲突，已转为中性说明"
        return self._get_normalized_ai_operation_advice(result)

    def _get_conflict_safe_core_conclusion(self, result: AnalysisResult, text: Any) -> str:
        """Return core conclusion text safe for conflict-state presentation."""
        if self._get_primary_action_model(result)['ai_conflict']:
            return "AI总结与确定性主动作存在方向冲突，请仅按确定性主动作执行"
        normalized = str(text or '').strip()
        return normalized

    def _build_simulated_target_allocation_table(
        self,
        results: List[AnalysisResult],
        executed_weight_by_code: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        """Build simulated target allocation table; clearly separated from executed state."""
        executed_weight_by_code = executed_weight_by_code or {}
        lines = [
            "| 标的 | 当前已执行权重 | 模拟目标权重 | 模拟调仓金额 |",
            "|---|---:|---:|---:|",
        ]

        for r in results:
            _, signal_emoji, _ = self._get_signal_level(r)
            stock_cell = self._to_markdown_table_cell(
                f"{signal_emoji} **{self._escape_md(r.name)}({r.code})**"
            )
            lines.append(
                "| "
                f"{stock_cell} | "
                f"{executed_weight_by_code.get(self._normalize_stock_code(r.code), 0.0):.2%} | "
                f"{getattr(r, 'target_weight', 0.0):.2%} | "
                f"{getattr(r, 'delta_amount', 0.0):,.2f} "
                "|"
            )
        return lines

    def _build_section_c_reconciliation_lines(
        self,
        *,
        results: List[AnalysisResult],
        overview_holdings: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Build reconciliation summary so Section C closes to 100% explicitly."""
        holdings = overview_holdings or []
        analyzed_target_weight_sum = sum(float(getattr(r, "target_weight", 0.0) or 0.0) for r in results)
        analyzed_codes = {
            self._normalize_stock_code(getattr(r, "code", ""))
            for r in results
            if self._normalize_stock_code(getattr(r, "code", ""))
        }
        unmanaged_holdings_weight = sum(
            float(item.get("weight") or 0.0)
            for item in holdings
            if self._normalize_stock_code(item.get("code", "")) not in analyzed_codes
        )
        raw_target_cash_weight = 1.0 - analyzed_target_weight_sum - unmanaged_holdings_weight
        target_cash_weight = max(raw_target_cash_weight, 0.0)
        residual = 1.0 - analyzed_target_weight_sum - unmanaged_holdings_weight - target_cash_weight
        tolerance = 1e-6

        lines = [
            "",
            "### C 段闭环说明（为什么目标仓位不一定等于 100%）",
            "",
            f"- 已分析标的目标仓位合计：**{analyzed_target_weight_sum:.2%}**",
            f"- 未纳入今日分析的持仓权重：**{unmanaged_holdings_weight:.2%}**",
            f"- 目标现金权重：**{target_cash_weight:.2%}**",
            f"- 闭环残差：**{residual:.4%}**",
            "- 闭环关系：**已分析标的目标仓位合计 + 未纳入今日分析的持仓权重 + 目标现金权重 + 闭环残差 = 100%**",
        ]
        if abs(residual) <= tolerance:
            lines.append(
                "- 说明：残差在四舍五入/容差范围内，可视为数值舍入带来的极小差异。"
            )
        else:
            lines.append(
                "- 说明：残差超出容差范围，表示仅靠舍入无法完全解释差异，请结合账户与分析覆盖范围进一步核对。"
            )
        return lines

    def _count_primary_decisions(self, results: List[AnalysisResult]) -> Dict[str, int]:
        counts = {'BUY': 0, 'HOLD': 0, 'SELL': 0}
        for result in results:
            decision = self._get_primary_action_model(result)['decision']
            counts[decision] = counts.get(decision, 0) + 1
        return counts

    def _format_primary_action_text(self, result: AnalysisResult) -> str:
        model = self._get_primary_action_model(result)
        return (
            f"{model['position_action']} | 目标仓位 {model['target_weight']:.2%} | "
            f"模拟Δ {model['delta_amount']:,.2f}"
        )

    def _format_deterministic_sizing_text(self, result: AnalysisResult) -> str:
        """Format deterministic sizing guidance from the same target-allocation engine."""
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

    @staticmethod
    def _normalize_stock_code(code: Any) -> str:
        """Normalize stock code for cross-source matching (e.g. bhp.ax vs BHP.AX)."""
        return str(code or "").strip().upper()

    def _build_report_time_portfolio_overview(
        self,
        *,
        overview: Dict[str, Any],
        results: List[AnalysisResult],
    ) -> Dict[str, Any]:
        """Build read-only mark-to-market overview using executed holdings and report-time prices.

        Price priority per holding:
        1) result.current_price (realtime preferred, else today.close already resolved in pipeline)
        2) fallback to stored market_value for that holding
        """
        cash = round(float((overview or {}).get("cash") or 0.0), 2)
        original_holdings = (overview or {}).get("holdings") or []

        report_time_prices: Dict[str, float] = {}
        analyzed_codes: Set[str] = set()
        for result in results or []:
            code = self._normalize_stock_code(getattr(result, "code", ""))
            if not code:
                continue
            analyzed_codes.add(code)
            price = self._to_positive_float(getattr(result, "current_price", None))
            if price is not None:
                report_time_prices[code] = price

        holdings: List[Dict[str, Any]] = []
        equity_value = 0.0
        fallback_codes: List[str] = []

        for holding in original_holdings:
            code = self._normalize_stock_code(holding.get("code", ""))
            quantity = float(holding.get("quantity") or 0.0)
            report_time_price = report_time_prices.get(code)

            if report_time_price is not None:
                market_value = round(max(quantity, 0.0) * report_time_price, 2)
                valuation_source = "report_time_price"
            else:
                market_value = round(float(holding.get("market_value") or 0.0), 2)
                valuation_source = "stored_market_value_fallback"
                if code:
                    fallback_codes.append(code)

            equity_value += max(market_value, 0.0)
            holdings.append(
                {
                    "code": code,
                    "name": holding.get("name"),
                    "quantity": quantity,
                    "avg_cost": float(holding.get("avg_cost") or 0.0),
                    "current_price": report_time_price if report_time_price is not None else holding.get("current_price"),
                    "market_value": market_value,
                    "valuation_source": valuation_source,
                    "analyzed_today": code in analyzed_codes,
                }
            )

        equity_value = round(equity_value, 2)
        total_value = round(cash + equity_value, 2)
        for item in holdings:
            item["weight"] = (item["market_value"] / total_value) if total_value > 0 else 0.0

        if fallback_codes:
            logger.info(
                "Portfolio overview price fallback to stored market_value for holdings without report-time price: %s",
                ",".join(fallback_codes),
            )

        return {
            "snapshot_date": (overview or {}).get("snapshot_date"),
            "cash": cash,
            "equity_value": equity_value,
            "total_value": total_value,
            "holdings": holdings,
        }
    
    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
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
            report_date = datetime.now().strftime('%Y-%m-%d')
        generated_at = datetime.now()

        # 按评分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 统计信息 - 使用主决策（优先 final_decision）
        decision_counts = self._count_primary_decisions(results)
        buy_count = decision_counts['BUY']
        sell_count = decision_counts['SELL']
        hold_count = decision_counts['HOLD']

        report_lines = [
            f"# 🎯 {report_date} 决策仪表盘",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
            "",
        ]
        report_lines.extend(self._build_data_baseline_lines(results, generated_at))

        try:
            overview = get_db().get_portfolio_overview()
        except Exception:
            overview = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}

        overview = self._build_report_time_portfolio_overview(
            overview=overview,
            results=results,
        )

        report_lines.extend([
            "## A. 当前账户总览（已执行）",
            "",
            f"- 可用现金: **{overview.get('cash', 0.0):,.2f}**",
            f"- 持仓市值: **{overview.get('equity_value', 0.0):,.2f}**",
            f"- 账户总值: **{overview.get('total_value', 0.0):,.2f}**",
            "",
        ])
        holdings = overview.get("holdings") or []
        executed_weight_by_code = {
            self._normalize_stock_code(item.get("code", "")): float(item.get("weight") or 0.0)
            for item in holdings
            if self._normalize_stock_code(item.get("code", ""))
        }
        if holdings:
            report_lines.extend([
                "| 当前持仓 | 数量 | 权重 | 估值来源 | 今日分析覆盖 |",
                "|---------|------|------|----------|--------------|",
            ])
            for h in holdings:
                valuation_source = self._format_valuation_source_label(h.get("valuation_source"))
                analyzed_today = self._format_yes_no_label(h.get("analyzed_today"))
                report_lines.append(
                    f"| {h.get('name', h.get('code'))}({h.get('code')}) | {h.get('quantity', 0):,.2f} | {h.get('weight', 0.0):.2%} | {valuation_source} | {analyzed_today} |"
                )
            report_lines.extend([
                "",
                "注：估值来源“报告时点价格”表示直接按报告时点行情估值；“账户快照市值回退”表示缺少报告时点价格时回退到账户快照。今日分析覆盖：是/否。",
                "",
            ])

        # === 分离展示：实际账户状态 vs 今日建议/模拟结果 ===
        if results:
            report_lines.extend([
                "## B. 今日建议动作（未执行）",
                "",
                "> 以下以确定性动作为主（final_decision / position_action / target_weight / delta_amount），仅用于今日计划，不代表账户已变化。",
                "",
            ])
            report_lines.extend(self._build_recommended_actions_table(sorted_results))
            report_lines.extend([
                "",
                "## C. 目标仓位模拟（计划视图）",
                "",
                "> 以下目标仓位仅为模拟计划；A 段始终展示已执行的真实账户状态。",
                "",
            ])
            report_lines.extend(
                self._build_simulated_target_allocation_table(
                    sorted_results,
                    executed_weight_by_code=executed_weight_by_code,
                )
            )
            report_lines.extend(
                self._build_section_c_reconciliation_lines(
                    results=sorted_results,
                    overview_holdings=holdings,
                )
            )
            report_lines.extend([
                "",
                "---",
                "",
            ])

        # 逐个股票的决策仪表盘（Issue #262: summary_only 时跳过详情）
        if not self._report_summary_only:
            for result in sorted_results:
                signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
                action_model = self._get_primary_action_model(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                
                # 股票名称（优先使用 dashboard 或 result 中的名称，转义 *ST 等特殊字符）
                raw_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
                stock_name = self._escape_md(raw_name)
                
                report_lines.extend([
                    f"## {signal_emoji} {stock_name} ({result.code})",
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
                        report_lines.append(f"**💭 舆情情绪**: {intel['sentiment_summary']}")
                    # 业绩预期
                    if intel.get('earnings_outlook'):
                        report_lines.append(f"**📊 业绩预期**: {intel['earnings_outlook']}")
                    # 风险警报（醒目显示）
                    risk_alerts = intel.get('risk_alerts', [])
                    if risk_alerts:
                        report_lines.append("")
                        report_lines.append("**🚨 风险警报**:")
                        for alert in risk_alerts:
                            report_lines.append(f"- {alert}")
                    # 利好催化
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("")
                        report_lines.append("**✨ 利好催化**:")
                        for cat in catalysts:
                            report_lines.append(f"- {cat}")
                    # 最新消息
                    if intel.get('latest_news'):
                        report_lines.append("")
                        report_lines.append(f"**📢 最新动态**: {intel['latest_news']}")
                    report_lines.append("")
                
                # ========== 核心结论 ==========
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = self._get_conflict_safe_core_conclusion(
                    result,
                    core.get('one_sentence', result.analysis_summary),
                )
                time_sense = core.get('time_sensitivity', '本周内')
                pos_advice = core.get('position_advice', {})
                
                report_lines.extend([
                    "### 📌 核心结论",
                    "",
                    f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                    "",
                    f"**🧭 主动作（优先执行）**: {self._format_primary_action_text(result)}",
                    "",
                    f"> **一句话结论**: {one_sentence}",
                    "",
                    f"**💬 AI补充（非执行）**: {self._get_conflict_safe_ai_commentary(result)}",
                    "",
                    f"⏰ **时效性**: {time_sense}",
                    "",
                ])
                if action_model['ai_conflict']:
                    report_lines.extend([
                        "⚠️ AI解读与确定性动作不一致；请以“确定性动作(主指令)”为准。",
                        "",
                    ])
                # 持仓分类建议
                if pos_advice:
                    deterministic_sizing_text = self._to_markdown_table_cell(
                        self._format_deterministic_sizing_text(result)
                    )
                    no_position_text = deterministic_sizing_text
                    has_position_text = deterministic_sizing_text
                    report_lines.extend([
                        "| 持仓情况 | 操作建议 |",
                        "|---------|---------|",
                        f"| 🆕 **空仓者** | {no_position_text} |",
                        f"| 💼 **持仓者** | {has_position_text} |",
                        "",
                    ])
                    ai_no_position_text = pos_advice.get('no_position')
                    ai_has_position_text = pos_advice.get('has_position')
                    if ai_no_position_text or ai_has_position_text:
                        report_lines.extend([
                            "**💬 AI仓位解读（次要评论，非执行指令）**",
                            "",
                        ])
                        if ai_no_position_text:
                            report_lines.append(
                                f"- 🆕 空仓者: {self._sanitize_ai_share_count_commentary(ai_no_position_text)}"
                            )
                        if ai_has_position_text:
                            report_lines.append(
                                f"- 💼 持仓者: {self._sanitize_ai_share_count_commentary(ai_has_position_text)}"
                            )
                        report_lines.append("")

                self._append_market_snapshot(report_lines, result)
                
                # ========== 数据透视 ==========
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    chip_data = data_persp.get('chip_structure', {})
                    
                    report_lines.extend([
                        "### 📊 数据透视",
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
                        report_lines.extend([
                            "| 价格指标 | 数值 |",
                            "|---------|------|",
                            f"| 当前价 | {price_data.get('current_price', 'N/A')} |",
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
                        report_lines.extend([
                            f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | 换手率 {vol_data.get('turnover_rate', 'N/A')}%",
                            f"💡 *{vol_data.get('volume_meaning', '')}*",
                            "",
                        ])
                    # 筹码结构
                    if chip_data:
                        chip_health = chip_data.get('chip_health', 'N/A')
                        chip_emoji = "✅" if chip_health == "健康" else ("⚠️" if chip_health == "一般" else "🚨")
                        report_lines.extend([
                            f"**筹码**: 获利比例 {chip_data.get('profit_ratio', 'N/A')} | 平均成本 {chip_data.get('avg_cost', 'N/A')} | 集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}",
                            "",
                        ])
                
                # ========== 作战计划 ==========
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.extend([
                        "### 🎯 作战计划",
                        "",
                    ])
                    # 狙击点位
                    sniper = battle.get('sniper_points', {})
                    if sniper:
                        report_lines.extend([
                            "**📍 AI参考点位（非系统执行指令）**",
                            "",
                            "| 点位类型 | 价格 |",
                            "|---------|------|",
                            f"| 🎯 参考买入位（AI估计） | {self._clean_sniper_value(sniper.get('ideal_buy', 'N/A'))} |",
                            f"| 🔵 观察买入位（AI估计） | {self._clean_sniper_value(sniper.get('secondary_buy', 'N/A'))} |",
                            f"| 🛑 风险提示位（AI估计） | {self._clean_sniper_value(sniper.get('stop_loss', 'N/A'))} |",
                            f"| 🎊 参考目标位（AI估计） | {self._clean_sniper_value(sniper.get('take_profit', 'N/A'))} |",
                            "",
                        ])
                    # 仓位策略
                    position = battle.get('position_strategy', {})
                    if position:
                        report_lines.extend([
                            f"**💰 AI仓位评论（次要评论，非执行指令）**: {position.get('suggested_position', 'N/A')}",
                            f"- 建仓策略: {position.get('entry_plan', 'N/A')}",
                            f"- 风控策略: {position.get('risk_control', 'N/A')}",
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
                            f"**💡 操作理由**: {result.buy_reason}",
                            "",
                        ])
                    # 风险提示
                    if result.risk_warning:
                        report_lines.extend([
                            f"**⚠️ 风险提示**: {result.risk_warning}",
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
                            report_lines.append(f"**量能**: {result.volume_analysis}")
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
        
        # 底部（去除免责声明）
        report_lines.extend([
            "",
            f"*报告生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def generate_wechat_dashboard(self, results: List[AnalysisResult]) -> str:
        """
        生成企业微信决策仪表盘精简版（控制在4000字符内）
        
        只保留核心结论和狙击点位
        
        Args:
            results: 分析结果列表
            
        Returns:
            精简版决策仪表盘
        """
        generated_at = datetime.now()
        report_date = generated_at.strftime('%Y-%m-%d')
        
        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 统计 - 使用主决策（优先 final_decision）
        decision_counts = self._count_primary_decisions(results)
        buy_count = decision_counts['BUY']
        sell_count = decision_counts['SELL']
        hold_count = decision_counts['HOLD']
        
        lines = [
            f"## 🎯 {report_date} 决策仪表盘",
            "",
            f"> {len(results)}只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
            "",
        ]
        lines.extend(self._build_data_baseline_lines(results, generated_at, title="**🕒 数据时间基准**"))

        try:
            overview = get_db().get_portfolio_overview()
        except Exception:
            overview = {"cash": 0.0, "equity_value": 0.0, "total_value": 0.0, "holdings": []}

        overview = self._build_report_time_portfolio_overview(
            overview=overview,
            results=results,
        )
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
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}')
                action_model = self._get_primary_action_model(r)
                lines.append(
                    f"{signal_emoji} **{stock_name}({r.code})**: "
                    f"{self._format_position_action_label(action_model['position_action'])} · 目标{action_model['target_weight']:.2%} · "
                    f"模拟Δ{action_model['delta_amount']:,.2f} "
                    f"(AI补充: {self._get_conflict_safe_ai_commentary(r)} / 评分{r.sentiment_score})"
                )
            lines.extend([
                "",
                "**C) 目标仓位（模拟，不代表已成交）**",
            ])
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}')
                lines.append(
                    f"{signal_emoji} {stock_name}({r.code}): 执行中 {executed_weight_by_code.get(r.code, 0.0):.2%} "
                    f"→ 模拟目标 {getattr(r, 'target_weight', 0.0):.2%} "
                    f"(Δ{getattr(r, 'delta_amount', 0.0):,.2f})"
                )
        else:
            for result in sorted_results:
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
                    lines.append("⚠️ AI解读与主动作不一致，请以主动作为准")
                lines.append("")
                
                # 重要信息区（舆情+基本面）
                info_lines = []
                
                # 业绩预期
                if intel.get('earnings_outlook'):
                    outlook = intel['earnings_outlook'][:60]
                    info_lines.append(f"📊 业绩: {outlook}")
                if intel.get('sentiment_summary'):
                    sentiment = intel['sentiment_summary'][:50]
                    info_lines.append(f"💭 舆情: {sentiment}")
                if info_lines:
                    lines.extend(info_lines)
                    lines.append("")
                
                # 风险警报（最重要，醒目显示）
                risks = intel.get('risk_alerts', []) if intel else []
                if risks:
                    lines.append("🚨 **风险**:")
                    for risk in risks[:2]:  # 最多显示2条
                        risk_text = risk[:50] + "..." if len(risk) > 50 else risk
                        lines.append(f"   • {risk_text}")
                    lines.append("")
                
                # 利好催化
                catalysts = intel.get('positive_catalysts', []) if intel else []
                if catalysts:
                    lines.append("✨ **利好**:")
                    for cat in catalysts[:2]:  # 最多显示2条
                        cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                        lines.append(f"   • {cat_text}")
                    lines.append("")
                
                # 狙击点位
                sniper = battle.get('sniper_points', {}) if battle else {}
                if sniper:
                    ideal_buy = sniper.get('ideal_buy', '')
                    stop_loss = sniper.get('stop_loss', '')
                    take_profit = sniper.get('take_profit', '')
                    points = []
                    if ideal_buy:
                        points.append(f"🎯参考位(AI):{ideal_buy[:12]}")
                    if stop_loss:
                        points.append(f"🛑风险位(AI):{stop_loss[:12]}")
                    if take_profit:
                        points.append(f"🎊目标参考(AI):{take_profit[:12]}")
                    if points:
                        lines.append(" | ".join(points))
                        lines.append("")
                
                # 持仓建议
                pos_advice = core.get('position_advice', {}) if core else {}
                if pos_advice:
                    deterministic_sizing = self._format_deterministic_sizing_text(result)
                    lines.append(f"🧮 确定性仓位指引: {deterministic_sizing[:80]}")
                    no_pos = pos_advice.get('no_position', '')
                    has_pos = pos_advice.get('has_position', '')
                    if no_pos:
                        ai_no_pos = self._sanitize_ai_share_count_commentary(no_pos)
                        if action_model['ai_conflict']:
                            ai_no_pos = self._get_conflict_safe_ai_commentary(result)
                        lines.append(f"💬 AI空仓者评论(非执行): {ai_no_pos[:44]}")
                    if has_pos:
                        ai_has_pos = self._sanitize_ai_share_count_commentary(has_pos)
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
        
        # 底部
        lines.append(f"*生成时间: {generated_at.strftime('%H:%M')}*")
        
        content = "\n".join(lines)
        
        return content
    
    def generate_wechat_summary(self, results: List[AnalysisResult]) -> str:
        """
        生成企业微信精简版日报（控制在4000字符内）

        Args:
            results: 分析结果列表

        Returns:
            精简版 Markdown 内容
        """
        generated_at = datetime.now()
        report_date = generated_at.strftime('%Y-%m-%d')

        # 按评分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 统计 - 使用主决策（优先 final_decision）
        decision_counts = self._count_primary_decisions(results)
        buy_count = decision_counts['BUY']
        sell_count = decision_counts['SELL']
        hold_count = decision_counts['HOLD']
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        lines = [
            f"## 📅 {report_date} 股票分析报告",
            "",
            f"> 共 **{len(results)}** 只 | 🟢买入:{buy_count} 🟡持有:{hold_count} 🔴卖出:{sell_count} | 均分:{avg_score:.0f}",
            "",
        ]
        lines.extend(self._build_data_baseline_lines(results, generated_at, title="**🕒 数据时间基准**"))
        
        # 每只股票精简信息（控制长度）
        for result in sorted_results:
            _, emoji, _ = self._get_signal_level(result)
            
            # 核心信息行
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(
                f"**{self._get_canonical_operation_advice(result)}** | 评分:{result.sentiment_score} | "
                f"{result.trend_prediction} | 价格基准：{self._get_price_basis_label(result)}"
            )
            
            # 操作理由（截断）
            if hasattr(result, 'buy_reason') and result.buy_reason:
                reason = result.buy_reason[:80] + "..." if len(result.buy_reason) > 80 else result.buy_reason
                lines.append(f"💡 {reason}")
            
            # 核心看点
            if hasattr(result, 'key_points') and result.key_points:
                points = result.key_points[:60] + "..." if len(result.key_points) > 60 else result.key_points
                lines.append(f"🎯 {points}")
            
            # 风险提示（截断）
            if hasattr(result, 'risk_warning') and result.risk_warning:
                risk = result.risk_warning[:50] + "..." if len(result.risk_warning) > 50 else result.risk_warning
                lines.append(f"⚠️ {risk}")
            
            lines.append("")
        
        # 底部
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
            f"*详细报告见 reports/report_{report_date.replace('-', '')}.md*"
        ])
        
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
        generated_at = datetime.now()
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

        self._append_market_snapshot(lines, result)
        
        # 核心决策（一句话）
        one_sentence = self._get_conflict_safe_core_conclusion(
            result,
            core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary,
        )
        if one_sentence:
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
                lines.append(f"📊 **业绩预期**: {intel['earnings_outlook'][:100]}")
            
            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"💭 **舆情情绪**: {intel['sentiment_summary'][:80]}")
            
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
                    lines.append(f"- {risk[:60]}")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append("✨ **利好催化**:")
                for cat in catalysts[:3]:
                    lines.append(f"- {cat[:60]}")
        
        if info_added:
            lines.append("")
        
        # 狙击点位
        sniper = battle.get('sniper_points', {}) if battle else {}
        if sniper:
            lines.extend([
                "### 🎯 操作点位",
                "",
                "| AI参考买入位 | AI风险提示位 | AI参考目标位 |",
                "|------|------|------|",
            ])
            ideal_buy = sniper.get('ideal_buy', '-')
            stop_loss = sniper.get('stop_loss', '-')
            take_profit = sniper.get('take_profit', '-')
            lines.append(f"| {ideal_buy} | {stop_loss} | {take_profit} |")
            lines.append("")
        
        # 持仓建议
        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice:
            lines.extend([
                "### 💼 持仓建议",
                "",
                f"- 🧮 **确定性仓位指引(主指令)**: {self._format_deterministic_sizing_text(result)}",
                f"- 💬 **AI空仓者评论(非执行)**: {self._get_conflict_safe_ai_commentary(result) if self._get_primary_action_model(result)['ai_conflict'] else pos_advice.get('no_position', self._get_normalized_ai_operation_advice(result))}",
                f"- 💬 **AI持仓者评论(非执行)**: {self._get_conflict_safe_ai_commentary(result) if self._get_primary_action_model(result)['ai_conflict'] else pos_advice.get('has_position', '继续持有')}",
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
        "tencent": "腾讯财经",
        "akshare_em": "东方财富",
        "akshare_sina": "新浪财经",
        "akshare_qq": "腾讯财经",
        "efinance": "东方财富(efinance)",
        "tushare": "Tushare Pro",
        "sina": "新浪财经",
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
            lines.extend([
                "",
                "| 当前价 | 量比 | 换手率 | 行情来源 |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {display_source} |",
            ])

        lines.append("")
    
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
            logger.debug(f"飞书请求 URL: {self._feishu_url}")
            logger.debug(f"飞书请求 payload 长度: {len(content)} 字符")

            response = requests.post(
                self._feishu_url,
                json=payload,
                timeout=30,
                verify=self._webhook_verify_ssl
            )

            logger.debug(f"飞书响应状态码: {response.status_code}")
            logger.debug(f"飞书响应内容: {response.text}")

            if response.status_code == 200:
                result = response.json()
                code = result.get('code') if 'code' in result else result.get('StatusCode')
                if code == 0:
                    logger.info("飞书消息发送成功")
                    return True
                else:
                    error_msg = result.get('msg') or result.get('StatusMessage', '未知错误')
                    error_code = result.get('code') or result.get('StatusCode', 'N/A')
                    logger.error(f"飞书返回错误 [code={error_code}]: {error_msg}")
                    logger.error(f"完整响应: {result}")
                    return False
            else:
                logger.error(f"飞书请求失败: HTTP {response.status_code}")
                logger.error(f"响应内容: {response.text}")
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
                date_str = datetime.now().strftime('%Y-%m-%d')
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
            date_str = datetime.now().strftime('%Y-%m-%d')
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
            date_str = datetime.now().strftime('%Y-%m-%d')
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
            date_str = datetime.now().strftime('%Y-%m-%d')
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
            date_str = datetime.now().strftime('%Y-%m-%d')
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
        filename: Optional[str] = None
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
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"
        
        # 确保 reports 目录存在（使用项目根目录下的 reports）
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日报已保存到: {filepath}")
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

        total_count = len(results)
        basis_counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
        for result in results:
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
        
        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            decision = _get_effective_decision(r)
            emoji = _decision_to_signal_emoji(decision)
            basis = NotificationService._format_price_basis_label(NotificationService._classify_price_basis(r))
            lines.append(
                f"{emoji} {r.name}({r.code}): {_decision_to_canonical_advice(decision)} | "
                f"评分 {r.sentiment_score} | 价格基准：{basis}"
            )
        
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
