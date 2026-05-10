# -*- coding: utf-8 -*-
"""
===================================
get_latest_data 测试
===================================

职责：
1. 验证 get_latest_data 方法
2. 测试返回数据按日期降序排列
3. 测试 days 参数限制
"""

import os
import tempfile
import unittest
from datetime import date, timedelta

import pandas as pd

from src.config import Config
from src.storage import DatabaseManager, StockDaily


class GetLatestDataTestCase(unittest.TestCase):
    """get_latest_data 方法测试"""

    def setUp(self) -> None:
        """Initialize an isolated database for each test case."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_get_latest_data.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """Clean up resources."""
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _insert_stock_data(self, code: str, days_ago: int, close: float) -> None:
        """插入测试用股票数据"""
        target_date = date.today() - timedelta(days=days_ago)
        df = pd.DataFrame([{
            'date': target_date,
            'open': close - 1,
            'high': close + 1,
            'low': close - 2,
            'close': close,
            'volume': 1000000,
            'amount': 10000000,
            'pct_chg': 1.5,
        }])
        self.db.save_daily_data(df, code, data_source="TestData")

    def test_get_latest_data_returns_empty_when_no_data(self) -> None:
        """无数据时返回空列表"""
        result = self.db.get_latest_data("999999", days=2)
        self.assertEqual(result, [])

    def test_get_latest_data_returns_correct_count(self) -> None:
        """返回正确数量的数据"""
        # 插入5天数据
        for i in range(5):
            self._insert_stock_data("600519", days_ago=i, close=100.0 + i)

        # 请求2天数据
        result = self.db.get_latest_data("600519", days=2)
        self.assertEqual(len(result), 2)

        # 请求5天数据
        result = self.db.get_latest_data("600519", days=5)
        self.assertEqual(len(result), 5)

    def test_get_latest_data_ordered_by_date_desc(self) -> None:
        """验证数据按日期降序排列"""
        # 插入3天数据
        for i in range(3):
            self._insert_stock_data("600519", days_ago=i, close=100.0 + i)

        result = self.db.get_latest_data("600519", days=3)

        # 验证日期降序（最新日期在前）
        self.assertEqual(len(result), 3)
        self.assertGreater(result[0].date, result[1].date)
        self.assertGreater(result[1].date, result[2].date)

    def test_get_latest_data_filters_by_code(self) -> None:
        """验证按股票代码过滤"""
        # 插入不同股票的数据
        self._insert_stock_data("600519", days_ago=0, close=100.0)
        self._insert_stock_data("000001", days_ago=0, close=50.0)

        result = self.db.get_latest_data("600519", days=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "600519")

    def test_get_analysis_context_target_date_excludes_future_daily_rows(self) -> None:
        """target_date 历史上下文不得读取目标日之后的日线。"""
        with self.db.get_session() as session:
            session.add_all([
                StockDaily(code="BHP.AX", date=date(2024, 1, 1), open=10.0, high=11.0, low=9.0, close=10.0, volume=1000),
                StockDaily(code="BHP.AX", date=date(2024, 1, 2), open=11.0, high=12.0, low=10.0, close=11.0, volume=1100),
                StockDaily(code="BHP.AX", date=date(2024, 1, 3), open=12.0, high=13.0, low=11.0, close=12.0, volume=1200),
            ])
            session.commit()

        context = self.db.get_analysis_context("BHP.AX", target_date=date(2024, 1, 2))

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["date"], "2024-01-02")
        self.assertEqual(context["today"]["date"], date(2024, 1, 2))
        self.assertEqual(context["yesterday"]["date"], date(2024, 1, 1))
        raw_dates = [row["date"] for row in context["raw_data"]]
        self.assertEqual(raw_dates, [date(2024, 1, 1), date(2024, 1, 2)])
        self.assertNotIn("2024-01-03", context["price_history_table"])


if __name__ == "__main__":
    unittest.main()
