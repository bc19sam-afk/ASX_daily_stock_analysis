# -*- coding: utf-8 -*-
"""
===================================
YfinanceFetcher - 完整功能修复版
===================================

数据来源：Yahoo Finance（通过 yfinance 库）
特点：国际数据源、可能有延迟或缺失
定位：当所有国内数据源都失败时的最后保障

关键策略：
1. 自动将 A 股代码转换为 yfinance 格式（.SS / .SZ）
2. 处理 Yahoo Finance 的数据格式差异
3. 失败后指数退避重试
"""

import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

import pandas as pd
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
    Yahoo Finance 数据源实现
    
    优先级：4（最低，作为兜底）
    数据来源：Yahoo Finance
    
    关键策略：
    - 自动转换股票代码格式
    - 处理时区和数据格式差异
    - 失败后指数退避重试
    
    注意事项：
    - A 股数据可能有延迟
    - 某些股票可能无数据
    - 数据精度可能与国内源略有差异
    """
    
    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))
    
    def __init__(self):
        """初始化 YfinanceFetcher"""
        pass
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Yahoo Finance 格式

        Yahoo Finance 代码格式：
        - A股沪市：600519.SS (Shanghai Stock Exchange)
        - A股深市：000001.SZ (Shenzhen Stock Exchange)
        - 港股：0700.HK (Hong Kong Stock Exchange)
        - 澳洲股：BHP.AX (修复支持)
        - 美股：AAPL, TSLA, GOOGL (无需后缀)
        """
        import re

        code = stock_code.strip().upper()

        # === 修复 1: 修正正则，允许 .AX 这种两位字母后缀 ===
        if re.match(r'^[A-Z]{1,5}(\.[A-Z]+)?$', code):
            logger.debug(f"识别为国际/标准代码: {code}")
            return code

        # 港股：hk前缀 -> .HK后缀
        if code.startswith('HK'):
            hk_code = code[2:].lstrip('0') or '0'  # 去除前导0
            hk_code = hk_code.zfill(4)  # 补齐到4位
            logger.debug(f"转换港股代码: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # 已经包含后缀的情况
        if any(suffix in code for suffix in ['.SS', '.SZ', '.HK', '.AX', '.TW']):
            return code

        # 去除可能的 .SH 后缀
        code = code.replace('.SH', '')

        # ETF: Shanghai ETF (51xx, 52xx, 56xx, 58xx) -> .SS; Shenzhen ETF (15xx, 16xx, 18xx) -> .SZ
        if len(code) == 6:
            if code.startswith(('51', '52', '56', '58')):
                return f"{code}.SS"
            if code.startswith(('15', '16', '18')):
                return f"{code}.SZ"

        # A股：根据代码前缀判断市场
        if code.startswith(('600', '601', '603', '688')):
            return f"{code}.SS"
        elif code.startswith(('000', '002', '300')):
            return f"{code}.SZ"
        else:
            logger.warning(f"无法确定股票 {code} 的市场，默认使用深市")
            return f"{code}.SZ"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Yahoo Finance 获取原始数据
        """
        import yfinance as yf
        
        # 转换代码格式
        yf_code = self._convert_stock_code(stock_code)
        
        logger.debug(f"正在通过 yf.Ticker({yf_code}) 获取近期数据")
        
        try:
            # === 修复 2: 使用 history(period='3mo') 避开死板日期的时差坑 ===
            ticker = yf.Ticker(yf_code)
            df = ticker.history(period="3mo", auto_adjust=True)
            
            if df.empty:
                # 备用方案：如果 history 失败，尝试原来的 download 方式下载
                df = yf.download(
                    tickers=yf_code,
                    period="3mo",
                    progress=False,
                    auto_adjust=True,
                )
            
            if df.empty:
                raise DataFetchError(f"Yahoo Finance 未查询到 {stock_code} 的数据")
            
            return df
            
        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Yahoo Finance 数据
        """
        df = df.copy()
        
        # === 修复 3: 彻底解决 MultiIndex 导致的 pct_chg 赋值报错 ===
        # 如果列名是多级的（例如包含代码），强制取第一级并扁平化
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 统一转成小写列名并去除空格，防止雅虎返回格式波动
        df.columns = [str(c).lower().strip() for c in df.columns]
        
        # 重置索引，将日期从索引变为列
        if 'date' not in df.columns:
            df = df.reset_index()
            df.columns = [str(c).lower().strip() for c in df.columns]
        
        # 扩充列名映射映射（处理雅虎常见的变体）
        column_mapping = {
            'date': 'date',
            'timestamp': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'adj close': 'close',
            'volume': 'volume',
        }
        df = df.rename(columns=column_mapping)
        
        # === 修复 4: 剥离日期时区信息，防止后续合并失败 ===
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # === 修复 5: 安全地计算涨跌幅，确保取到的是 Series ===
        if 'close' in df.columns:
            close_series = df['close']
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            
            df['pct_chg'] = close_series.pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        
        # 计算成交额（估算）
        if 'volume' in df.columns and 'close' in df.columns:
            # 同样防止 volume 或 close 还是多列的情况
            v = df['volume'].iloc[:, 0] if isinstance(df['volume'], pd.DataFrame) else df['volume']
            c = df['close'].iloc[:, 0] if isinstance(df['close'], pd.DataFrame) else df['close']
            df['amount'] = v * c
        else:
            df['amount'] = 0
        
        # 添加股票代码列
        df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df

    def get_main_indices(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数行情 (Yahoo Finance)
        """
        import yfinance as yf

        # 映射关系：akshare代码 -> (yfinance代码, 名称)
        yf_mapping = {
            'sh000001': ('000001.SS', '上证指数'),
            'sz399001': ('399001.SZ', '深证成指'),
            'sz399006': ('399006.SZ', '创业板指'),
            'sh000688': ('000688.SS', '科创50'),
            'sh000016': ('000016.SS', '上证50'),
            'sh000300': ('000300.SS', '沪深300'),
        }

        results = []
        try:
            for ak_code, (yf_code, name) in yf_mapping.items():
                try:
                    ticker = yf.Ticker(yf_code)
                    # 获取最近5天数据以计算涨跌
                    hist = ticker.history(period='5d')
                    if hist.empty:
                        continue

                    today = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else today

                    price = float(today['Close'])
                    prev_close = float(prev['Close'])
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100 if prev_close else 0

                    # 振幅
                    high = float(today['High'])
                    low = float(today['Low'])
                    amplitude = ((high - low) / prev_close * 100) if prev_close else 0

                    results.append({
                        'code': ak_code,
                        'name': name,
                        'current': price,
                        'change': change,
                        'change_pct': change_pct,
                        'open': float(today['Open']),
                        'high': high,
                        'low': low,
                        'prev_close': prev_close,
                        'volume': float(today['Volume']),
                        'amount': 0.0, # Yahoo Finance 可能不提供准确的成交额
                        'amplitude': amplitude
                    })
                    logger.debug(f"[Yfinance] 获取指数 {name} 成功")

                except Exception as e:
                    logger.warning(f"[Yfinance] 获取指数 {name} 失败: {e}")
                    continue

            if results:
                logger.info(f"[Yfinance] 成功获取 {len(results)} 个指数行情")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] 获取指数行情失败: {e}")

        return None

    def _is_us_stock(self, stock_code: str) -> bool:
        """
        判断代码是否为美股或国际股票
        """
        code = stock_code.strip().upper()
        # 同样使用修正后的正则，支持 .AX
        return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z]+)?$', code))

    def _get_enhanced_data(self, stock_code: str, df: pd.DataFrame) -> pd.DataFrame:
        """
        获取内部人交易和机构持仓数据，注入到 DataFrame 中。
        失败时静默降级，不影响主流程。
        """
        import yfinance as yf
        try:
            ticker_symbol = self._convert_stock_code(stock_code)
            ticker = yf.Ticker(ticker_symbol)

            # --- 1. 内部人交易 ---
            insider_net_shares = 0
            insider_desc = "无数据"
            try:
                insiders = ticker.insider_transactions
                if isinstance(insiders, pd.DataFrame) and not insiders.empty and 'Shares' in insiders.columns:
                    recent = insiders.head(10).copy()
                    # 只对 Transaction 列填充空字符串，避免污染数值列
                    if 'Transaction' in recent.columns:
                        recent['Transaction'] = recent['Transaction'].fillna('')
                        buy_mask = recent['Transaction'].str.contains('Purchase', case=False, na=False)
                        sell_mask = recent['Transaction'].str.contains('Sale', case=False, na=False)
                    else:
                        buy_mask = pd.Series([False] * len(recent), index=recent.index)
                        sell_mask = pd.Series([False] * len(recent), index=recent.index)

                    buy_shares = recent.loc[buy_mask, 'Shares'].sum() if buy_mask.any() else 0
                    sell_shares = recent.loc[sell_mask, 'Shares'].sum() if sell_mask.any() else 0
                    insider_net_shares = buy_shares - sell_shares
                    direction = '买入' if insider_net_shares > 0 else '卖出'
                    insider_desc = f"近期内部人净{direction} {abs(insider_net_shares):.0f} 股"
            except Exception as e:
                logger.debug(f"[{stock_code}] 内部人数据获取失败: {e}")

            # --- 2. 机构持仓 ---
            inst_percent = 0.0
            inst_desc = "无数据"
            try:
                institutions = ticker.institutional_holders
                if isinstance(institutions, pd.DataFrame) and not institutions.empty:
                    if '% Holdings' in institutions.columns:
                        inst_percent = float(institutions['% Holdings'].sum())
                        inst_desc = f"机构合计持股 {inst_percent * 100:.2f}%"
                    elif 'Shares' in institutions.columns:
                        total_shares = institutions['Shares'].sum()
                        inst_desc = f"机构合计持有 {total_shares:.0f} 股"
            except Exception as e:
                logger.debug(f"[{stock_code}] 机构持仓数据获取失败: {e}")

            # --- 3. 注入 DataFrame ---
            df = df.copy()
            df['Insider_Net'] = insider_net_shares
            df['Insider_Desc'] = insider_desc
            df['Inst_Percent'] = inst_percent
            df['Inst_Desc'] = inst_desc

            logger.info(f"[{stock_code}] 资金面增强数据：{insider_desc} | {inst_desc}")
            return df

        except Exception as e:
            logger.warning(f"[{stock_code}] 获取增强数据失败（已降级）：{e}")
            return df

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def get_daily_data(self, stock_code: str, start_date: str = None, end_date: str = None, days: int = 300) -> pd.DataFrame:
        """
        获取日线数据（含资金面增强）
        兼容 base 类的 start_date/end_date 调用方式
        """
        import yfinance as yf
        try:
            ticker_symbol = self._convert_stock_code(stock_code)
            logger.info(f"[{stock_code}] 正在从 Yahoo Finance 获取数据...")
            ticker = yf.Ticker(ticker_symbol)
            if start_date and end_date:
                df = ticker.history(start=start_date, end=end_date)
            else:
                df = ticker.history(period=f"{days}d")

            if df.empty:
                raise DataFetchError(f"[{stock_code}] 未获取到数据")

            # 获取股票名称
            stock_name = ''
            try:
                info = ticker.info
                stock_name = info.get('shortName', '') or info.get('longName', '') or ''
            except Exception:
                pass

            # 注入资金面数据，同时缓存结果到 attrs 避免 pipeline 重复调用
            df = self._get_enhanced_data(stock_code, df)
            # 将资金面摘要缓存到 attrs，pipeline 直接读取，无需二次请求
            df.attrs['insider_desc'] = df['Insider_Desc'].iloc[0] if 'Insider_Desc' in df.columns and len(df) > 0 else ''
            df.attrs['inst_desc'] = df['Inst_Desc'].iloc[0] if 'Inst_Desc' in df.columns and len(df) > 0 else ''
            df.attrs['stock_name'] = stock_name

            # 重置索引，使 Date 成为列
            df = df.reset_index()

            # 重命名列
            rename_map = {
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume", "Date": "date",
            }
            df = df.rename(columns=rename_map)

            # 格式化日期
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")

            # 确保按日期升序排列（旧→新），pct_change() 依赖此顺序
            if "date" in df.columns:
                df = df.sort_values("date").reset_index(drop=True)

            # 计算涨跌幅
            if "close" in df.columns:
                df["pct_chg"] = df["close"].pct_change() * 100
                df["pct_chg"] = df["pct_chg"].fillna(0).round(2)

            # 计算成交额（估算）
            if "volume" in df.columns and "close" in df.columns:
                df["amount"] = (df["volume"] * df["close"]).round(0)
            else:
                df["amount"] = 0

            # 价格精度统一到2位小数
            for col in ["open", "high", "low", "close"]:
                if col in df.columns:
                    df[col] = df[col].round(2)

            # 保留标准列 + 资金面列
            extra_cols = [c for c in ['Insider_Net', 'Insider_Desc', 'Inst_Percent', 'Inst_Desc'] if c in df.columns]
            available_cols = [c for c in STANDARD_COLUMNS if c in df.columns]
            df = df[available_cols + extra_cols]

            return df

        except Exception as e:
            logger.error(f"[{stock_code}] 获取数据失败：{e}")
            raise DataFetchError(f"Yahoo Finance 获取数据失败：{e}")

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取美股/国际股票实时行情数据
        """
        import yfinance as yf
        
        yf_code = self._convert_stock_code(stock_code)
        
        try:
            symbol = yf_code.strip().upper()
            logger.debug(f"[Yfinance] 获取 {symbol} 实时行情")
            
            ticker = yf.Ticker(symbol)
            
            # 尝试获取 fast_info
            try:
                info = ticker.fast_info
                price = info.last_price
                if price is None:
                    raise ValueError("fast_info returned None")
                
                prev_close = info.previous_close
                open_price = info.open
                high = info.day_high
                low = info.day_low
                volume = info.last_volume
                market_cap = getattr(info, 'market_cap', None)
                
            except Exception:
                # 回退到 history 方法获取最新数据
                logger.debug(f"[Yfinance] fast_info 失败，尝试 history 方法")
                hist = ticker.history(period='5d')
                if hist.empty:
                    logger.warning(f"[Yfinance] 无法获取 {symbol} 的数据")
                    return None
                
                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                
                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])
                market_cap = None
            
            # 计算涨跌幅
            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100
            
            # 计算振幅
            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100
            
            # 获取股票名称与核心基本面（ASX极度依赖股息率）
            try:
                info = ticker.info
                name = info.get('shortName', '') or info.get('longName', '') or symbol
                
                # 抓取市盈率、市净率和股息率
                pe_val = info.get('trailingPE', 'N/A')
                pb_val = info.get('priceToBook', None)
                div_yield = info.get('dividendYield', 0)
                
                if isinstance(pe_val, float):
                    pe_val = round(pe_val, 2)
                if isinstance(pb_val, float):
                    pb_val = round(pb_val, 2)
                    
                # 巧妙利用 pe_ratio 字段将股息率拼接进去，确保 AI 能直接看到
                pe_str = f"{pe_val} | 💰股息率: {div_yield * 100:.2f}%" if div_yield else str(pe_val)
                
            except Exception:
                name = symbol
                pe_str = None
                pb_val = None
            
            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=name,
                source=RealtimeSource.FALLBACK,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None, 
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=pe_str,    # <--- 带有股息率的核心数据被传出
                pb_ratio=pb_val,    # <--- 真实的市净率
                total_mv=market_cap,
                circ_mv=None,
            )
            
            logger.info(f"[Yfinance] 获取实时行情成功: {symbol} = {price}")
            return quote
            
        except Exception as e:
            logger.warning(f"[Yfinance] 获取 {stock_code} 实时行情失败: {e}")
            return None


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    fetcher = YfinanceFetcher()
    try:
        df = fetcher.get_daily_data('CBA.AX')
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"获取失败: {e}")
