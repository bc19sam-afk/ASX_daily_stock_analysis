# -*- coding: utf-8 -*-
import unittest
import sys
import os

# Ensure src module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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

if __name__ == '__main__':
    unittest.main()
