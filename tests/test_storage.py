# -*- coding: utf-8 -*-
import os
import tempfile
import threading
import time
import unittest
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import text

# Ensure src module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import Config
from src.storage import DatabaseManager

class TestStorage(unittest.TestCase):
    
    def test_parse_sniper_value_accepts_only_structured_numeric_values(self):
        """狙击点位落库只接受结构化数值，不从自然语言提取价格。"""
        
        self.assertEqual(DatabaseManager._parse_sniper_value(100), 100.0)
        self.assertEqual(DatabaseManager._parse_sniper_value(100.5), 100.5)

        self.assertIsNone(DatabaseManager._parse_sniper_value("100"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("100.5"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("建议在 100 元附近买入"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("价格：100.5元"))

        text_bug = "无法给出。需等待MA5数据恢复，在股价回踩MA5且乖离率<2%时考虑100元"
        self.assertIsNone(DatabaseManager._parse_sniper_value(text_bug))

        text_complex = "MA10为20.5，建议在30元买入"
        self.assertIsNone(DatabaseManager._parse_sniper_value(text_complex))
        self.assertIsNone(DatabaseManager._parse_sniper_value("30元"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("MA5 10 20元"))

        self.assertIsNone(DatabaseManager._parse_sniper_value(None))
        self.assertIsNone(DatabaseManager._parse_sniper_value(""))
        self.assertIsNone(DatabaseManager._parse_sniper_value("没有数字"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("MA5但没有元"))

    def test_get_instance_initializes_once_under_concurrent_first_call(self):
        """首次并发获取数据库单例时，只允许一个线程执行初始化。"""
        old_database_path = os.environ.get("DATABASE_PATH")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "concurrent.db")
            Config.reset_instance()
            DatabaseManager.reset_instance()
            ensure_calls = []
            original_ensure_history = DatabaseManager._ensure_analysis_history_columns

            def slow_ensure_history(manager):
                ensure_calls.append(id(manager._engine))
                time.sleep(0.02)
                return original_ensure_history(manager)

            barrier = threading.Barrier(8)

            def use_instance(_):
                barrier.wait()
                manager = DatabaseManager.get_instance()
                with manager.get_session() as session:
                    result = session.execute(text("SELECT 1")).scalar()
                return id(manager), result

            try:
                with (
                    patch.object(DatabaseManager, "_ensure_analysis_history_columns", slow_ensure_history),
                    ThreadPoolExecutor(max_workers=8) as executor,
                ):
                    results = list(executor.map(use_instance, range(8)))

                instance_ids = [item[0] for item in results]
                self.assertEqual(len(set(instance_ids)), 1)
                self.assertEqual([item[1] for item in results], [1] * 8)
                self.assertEqual(len(ensure_calls), 1)
            finally:
                DatabaseManager.reset_instance()
                Config.reset_instance()
                if old_database_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_database_path

if __name__ == '__main__':
    unittest.main()
