# -*- coding: utf-8 -*-
"""
===================================
数据源策略层 - 包初始化
===================================

本包默认只暴露当前 ASX/AU/US 主链路需要的数据源，实现：
1. 统一的数据获取接口
2. 默认 YFinance 数据获取
3. ASX-first 路由与数据源管理

CN legacy provider 文件仍保留在仓库中，可通过显式模块路径导入；
但不会再随 `import data_provider` 或 `from data_provider import ...` 默认加载。
"""

from .base import BaseFetcher, DataFetcherManager
from .yfinance_fetcher import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'YfinanceFetcher',
]
