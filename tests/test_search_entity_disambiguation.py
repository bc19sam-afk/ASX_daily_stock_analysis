# -*- coding: utf-8 -*-
"""Search / News 实体消歧测试。"""

import unittest

from src.search_service import SearchService, SearchResponse, SearchResult


class SearchEntityDisambiguationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SearchService()
        self.code = "CBA.AX"
        self.name = "Commonwealth Bank of Australia"

    def _resp(self, *results: SearchResult) -> SearchResponse:
        return SearchResponse(
            query="test query",
            results=list(results),
            provider="mock",
            success=True,
        )

    def test_homonym_cross_market_result_is_filtered(self) -> None:
        """同名异股回放：跨市场结果应被过滤。"""
        asx_result = SearchResult(
            title="CBA.AX on ASX gains after earnings",
            snippet="Commonwealth Bank of Australia posted strong results in Australia",
            url="https://example.com/asx-cba",
            source="example.com",
        )
        wrong_market = SearchResult(
            title="CBA climbs on NASDAQ amid fintech rally",
            snippet="CBA Corp announced expansion in US market",
            url="https://example.com/nasdaq-cba",
            source="example.com",
        )

        filtered = self.service._filter_entity_consistent_results(
            self._resp(asx_result, wrong_market),
            stock_code=self.code,
            stock_name=self.name,
        )

        self.assertEqual(len(filtered.results), 1)
        self.assertEqual(filtered.results[0].url, "https://example.com/asx-cba")

    def test_case_and_suffix_variants_not_over_filtered(self) -> None:
        """大小写/后缀差异不应误杀正确结果。"""
        lower_case_hit = SearchResult(
            title="cba.ax shares edge higher on asx",
            snippet="commonwealth bank of australia outlook remains stable",
            url="https://example.com/lowercase-hit",
            source="example.com",
        )

        filtered = self.service._filter_entity_consistent_results(
            self._resp(lower_case_hit),
            stock_code=self.code,
            stock_name=self.name,
        )
        self.assertEqual(len(filtered.results), 1)
        self.assertEqual(filtered.results[0].url, "https://example.com/lowercase-hit")

    def test_wrong_market_result_not_in_intel_context(self) -> None:
        """错误市场结果不会进入最终 intel context。"""
        wrong_market = SearchResult(
            title="CBA surges on NYSE",
            snippet="US-listed CBA company reports guidance",
            url="https://example.com/nyse-cba",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(wrong_market),
            stock_code=self.code,
            stock_name=self.name,
        )

        report = self.service.format_intel_report({"latest_news": filtered}, stock_name=self.name)
        self.assertIn("未找到相关信息", report)
        self.assertNotIn("NYSE", report)

    def test_asx_result_kept_in_intel_context(self) -> None:
        """正确 ASX 结果仍可进入上下文。"""
        asx_result = SearchResult(
            title="ASX: CBA.AX extends rally",
            snippet="Commonwealth Bank of Australia benefited from improving margins",
            url="https://example.com/asx-ok",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(asx_result),
            stock_code=self.code,
            stock_name=self.name,
        )

        report = self.service.format_intel_report({"latest_news": filtered}, stock_name=self.name)
        self.assertIn("ASX: CBA.AX extends rally", report)

    def test_grounded_query_contains_entity_constraints(self) -> None:
        """query 同时包含 ticker/exchange/company/market 约束。"""
        query = self.service._build_grounded_query(
            stock_code=self.code,
            stock_name=self.name,
            intent_terms=["latest news events"],
        )

        self.assertIn("CBA.AX", query)
        self.assertIn("CBA", query)
        self.assertIn("Commonwealth Bank of Australia", query)
        self.assertIn("ASX", query)
        self.assertIn("Australia", query)


if __name__ == "__main__":
    unittest.main()
