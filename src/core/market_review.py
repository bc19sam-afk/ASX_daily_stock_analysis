# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 大盘复盘模块
===================================

职责：
1. 执行大盘复盘分析
2. 生成复盘报告
3. 保存和发送复盘报告
"""

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.notification import NotificationService
from src.market_analyzer import MarketAnalyzer
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer
from src.config import get_config


logger = logging.getLogger(__name__)


def run_market_review(
    notifier: NotificationService,
    analyzer: Optional[GeminiAnalyzer] = None,
    search_service: Optional[SearchService] = None,
    send_notification: bool = True,
    merge_notification: bool = False,
) -> Optional[str]:
    """
    执行大盘复盘分析

    Args:
        notifier: 通知服务
        analyzer: AI分析器（可选）
        search_service: 搜索服务（可选）
        send_notification: 是否发送通知
        merge_notification: 是否合并推送（跳过本次推送，由 main 层合并个股+大盘后统一发送，Issue #190）

    Returns:
        复盘报告文本
    """
    logger.info("开始执行大盘复盘分析...")
    
    try:
        market_analyzer = MarketAnalyzer(
            search_service=search_service,
            analyzer=analyzer
        )
        
        # 执行复盘
        review_report = market_analyzer.run_daily_review()
        
        if review_report:
            config = get_config()
            allow_standalone_push = getattr(config, "market_review_push_enabled", True)
            # 保存报告到文件
            market_tz = getattr(config, "market_timezone", "Australia/Sydney")
            date_str = datetime.now(ZoneInfo(market_tz)).strftime('%Y%m%d')
            report_filename = f"market_review_{date_str}.md"
            filepath = notifier.save_report_to_file(
                f"# 🎯 大盘复盘\n\n{review_report}", 
                report_filename
            )
            logger.info(f"大盘复盘报告已保存: {filepath}")
            
            # 推送通知（合并模式下跳过，由 main 层统一发送）
            if merge_notification and send_notification:
                logger.info("合并推送模式：跳过大盘复盘单独推送，将在个股+大盘复盘后统一发送")
            elif send_notification and notifier.is_available() and allow_standalone_push:
                # 添加标题
                report_content = f"🎯 大盘复盘\n\n{review_report}"

                success = notifier.send(report_content, email_send_to_all=True)
                if success:
                    logger.info("大盘复盘推送成功")
                else:
                    logger.warning("大盘复盘推送失败")
            elif send_notification and not allow_standalone_push:
                logger.info("已禁用大盘复盘单独推送（MARKET_REVIEW_PUSH_ENABLED=false）")
            elif not send_notification:
                logger.info("已跳过推送通知 (--no-notify)")
            
            return review_report
        
    except Exception as e:
        logger.error(f"大盘复盘分析失败: {e}")
    
    return None
