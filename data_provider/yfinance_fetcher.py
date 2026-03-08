# -*- coding: utf-8 -*-
"""
===================================
YfinanceFetcher - 澳股增强版 (Insider + Institutional)
===================================

数据来源：Yahoo Finance（通过 yfinance 库）
定位：澳股专用数据源，支持 .AX 后缀

新增功能：
1. 自动获取内部人交易 (Insider Transactions)
2. 自动获取机构持仓 (Institutional Holders)
3. 将上述数据注入到返回的 DataFrame 中
"""

import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource
import os

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """
    Yahoo Finance 数据源实现 (澳股增强版)
    
    优先级：4 (最低，作为兜底)
    数据来源：Yahoo Finance
    
    关键策略：
    - 自动转换股票代码格式 (.AX, .HK 等)
    - 处理时区和数据格式差异
    - 失败后指数退避重试
    - 【新增】自动获取 Insider 和 Institutional 数据
    """
    
    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))
    
    def __init__(self):
        """初始化 YfinanceFetcher"""
        pass
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Yahoo Finance 格式
        """
        code = stock_code.strip().upper()

        # 识别国际/标准代码 (包括 .AX)
        if re.match(r'^[A-Z]{1,5}(\.[A-Z]+)?$', code):
            logger.debug(f"识别为国际/标准代码：{code}")
            return code

        # 港股：hk 前缀 -> .HK 后缀
        if code.startswith('HK'):
            hk_code = code[2:].lstrip('0') or '0'
            hk_code = hk_code.zfill(4)
            logger.debug(f"转换港股代码：{stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # 已经包含后缀的情况
        if any(suffix in code for suffix in ['.SS', '.SZ', '.HK', '.AX', '.TW']):
            return code

        # 去除可能的 .SH 后缀
        code = code.replace('.SH', '')

        # ETF: Sha (保留原有逻辑)
        if code.startswith('ETF') or code.startswith('FUND'):
             return code # 简单处理，视情况完善

        # 默认情况：假设是 A 股 (保留原有逻辑)
        if code.startswith('6') or code.startswith('5'):
            return f"{code}.SS"
        elif code.startswith('3') or code.startswith('0'):
            return f"{code}.SZ"
        
        # 如果都不匹配，原样返回 (让 yfinance 自己处理)
        return code

    def _get_enhanced_data(self, stock_code: str, df: pd.DataFrame) -> pd.DataFrame:
        """
        【核心增强】获取内部人交易和机构持仓数据，并注入到 DataFrame
        
        Args:
            stock_code: 股票代码 (如 "EGH.AX")
            df: 原始价格数据 DataFrame
            
        Returns:
            包含额外列的 DataFrame (如果获取成功)
        """
        try:
            ticker_symbol = self._convert_stock_code(stock_code)
            ticker = yf.Ticker(ticker_symbol)
            
            # --- 1. 获取内部人交易 (Insider Transactions) ---
            insider_net_shares = 0
            insider_desc = "无数据"
            
            insiders = ticker.insider_transactions
            if isinstance(insiders, pd.DataFrame) and not insiders.empty:
                recent = insiders.head(10)  # 取最近 10 条
                # 简单计算：Purchase 为正，Sale 为负
                if 'Shares' in recent.columns:
                    # 尝试识别买卖方向
                    if 'Transaction' in recent.columns:
                        # 处理 NaN 情况
                        recent = recent.fillna('')
                        buy_mask = recent['Transaction'].str.contains('Purchase', case=False, na=False)
                        sell_mask = recent['Transaction'].str.contains('Sale', case=False, na=False)
                    else:
                        buy_mask = pd.Series([False]*len(recent))
                        sell_mask = pd.Series([False]*len(recent))
                    
                    buy_shares = recent[buy_mask]['Shares'].sum() if buy_mask.any() else 0
                    sell_shares = recent[sell_mask]['Shares'].sum() if sell_mask.any() else 0
                    
                    insider_net_shares = buy_shares - sell_shares
                    insider_desc = f"净{'买' if insider_net_shares > 0 else '卖'} {abs(insider_net_shares):.0f}股"
            
            # --- 2. 获取机构持仓 (Institutional Holders) ---
            inst_percent = 0.0
            inst_desc = "无数据"
            
            institutions = ticker.institutional_holders
            if isinstance(institutions, pd.DataFrame) and not institutions.empty:
                if '% Holdings' in institutions.columns:
                    inst_percent = institutions['% Holdings'].sum()
                    inst_desc = f"机构持股 {inst_percent*100:.2f}%"
                else:
                    total_shares = institutions['Shares'].sum()
                    inst_desc = f"机构持有 {total_shares:.0f}股"
            
            # --- 3. 注入 DataFrame ---
            df_copy = df.copy()
            df_copy['Insider_Net'] = insider_net_shares
            df_copy['Insider_Desc'] = insider_desc
            df_copy['Inst_Percent'] = inst_percent
            df_copy['Inst_Desc'] = inst_desc
            
            logger.info(f"[{stock_code}] 增强数据：{insider_desc}, {inst_desc}")
            return df_copy
            
        except Exception as e:
            logger.warning(f"[{stock_code}] 获取增强数据失败：{e}")
            return df

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def get_daily_data(self, stock_code: str, days: int = 300) -> pd.DataFrame:
        """
        获取日线数据 (增强版)
        """
        try:
            ticker_symbol = self._convert_stock_code(stock_code)
            logger.info(f"[{stock_code}] 正在从 Yahoo Finance 获取数据...")
            
            ticker = yf.Ticker(ticker_symbol)
            # 获取历史价格数据
            df = ticker.history(period=f"{days}d")
            
            if df.empty:
                raise DataFetchError(f"[{stock_code}] 未获取到数据")
            
            # 【关键调用】获取增强数据
            df = self._get_enhanced_data(stock_code, df)
            
            # 重置索引，使 Date 成为列
            df = df.reset_index()
            
            # 重命名列以匹配标准列名
            rename_map = {
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
                "Date": "date",
            }
            df = df.rename(columns=rename_map)
            
            # 选择标准列
            available_cols = [col for col in STANDARD_COLUMNS if col in df.columns]
            # 额外保留我们新增的列
            extra_cols = ['Insider_Net', 'Insider_Desc', 'Inst_Percent', 'Inst_Desc']
            extra_cols = [col for col in extra_cols if col in df.columns]
            
            keep_cols = available_cols + extra_cols
            df = df[keep_cols]
            
            # 格式化日期
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            
            return df
            
        except Exception as e:
            logger.error(f"[{stock_code}] 获取数据失败：{e}")
            raise DataFetchError(f"Yahoo Finance 获取数据失败：{e}")

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote:
        """
        获取实时行情 (澳股)
        """
        try:
            ticker_symbol = self._convert_stock_code(stock_code)
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.fast_info
            # 简单返回一个示例，具体请保留你原有的实现
            return UnifiedRealtimeQuote(
                code=stock_code,
                price=info.last_price if hasattr(info, 'last_price') else 0.0,
                change=0.0,
                change_percent=0.0,
                volume=0,
                timestamp=datetime.now(),
                source=RealtimeSource.YFINANCE
            )
        except Exception as e:
            logger.error(f"[{stock_code}] 获取实时行情失败：{e}")
            raise