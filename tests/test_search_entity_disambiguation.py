# -*- coding: utf-8 -*-
"""Search / News 实体消歧测试。"""

import unittest

from src.search_service import (
    BaseSearchProvider,
    SearchService,
    SearchResponse,
    SearchResult,
)


class FakeSearchProvider(BaseSearchProvider):
    def __init__(self, name: str, scripted_responses):
        super().__init__(api_keys=["fake-key"], name=name)
        self._scripted_responses = list(scripted_responses)
        self.call_count = 0

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        self.call_count += 1
        if self._scripted_responses:
            response = self._scripted_responses.pop(0)
            response.query = query
            response.provider = self.name
            return response
        return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message="no scripted response")


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

    def test_search_stock_news_continue_when_first_provider_filtered_empty(self) -> None:
        """第一个 provider 过滤后为空时，继续后续 provider 且不缓存空结果。"""
        wrong_market = SearchResponse(
            query="wrong",
            results=[
                SearchResult(
                    title="CBA rises on NYSE",
                    snippet="US CBA stock jumps",
                    url="https://example.com/wrong",
                    source="example.com",
                )
            ],
            provider="p1",
            success=True,
        )
        valid_asx = SearchResponse(
            query="right",
            results=[
                SearchResult(
                    title="ASX: CBA.AX gains",
                    snippet="Commonwealth Bank of Australia advances",
                    url="https://example.com/right",
                    source="example.com",
                )
            ],
            provider="p2",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [wrong_market])
        p2 = FakeSearchProvider("p2", [valid_asx])
        self.service._providers = [p1, p2]

        first = self.service.search_stock_news(self.code, self.name, max_results=3)
        self.assertTrue(first.success)
        self.assertEqual(len(first.results), 1)
        self.assertEqual(first.provider, "p2")
        self.assertEqual(first.results[0].url, "https://example.com/right")
        self.assertEqual(p1.call_count, 1)
        self.assertEqual(p2.call_count, 1)

        # 第二次应命中缓存（缓存的是 p2 的有效结果），不再调用 provider
        second = self.service.search_stock_news(self.code, self.name, max_results=3)
        self.assertEqual(second.provider, "p2")
        self.assertEqual(second.results[0].url, "https://example.com/right")
        self.assertEqual(p1.call_count, 1)
        self.assertEqual(p2.call_count, 1)

    def test_search_comprehensive_intel_continue_on_filtered_empty(self) -> None:
        """某维度首个 provider 过滤后为空时，不应提前 break。"""
        wrong_market = SearchResponse(
            query="wrong",
            results=[
                SearchResult(
                    title="CBA on NASDAQ",
                    snippet="US CBA ticker",
                    url="https://example.com/wrong-dim",
                    source="example.com",
                )
            ],
            provider="p1",
            success=True,
        )
        valid_result = SearchResponse(
            query="right",
            results=[
                SearchResult(
                    title="ASX: CBA.AX analysts lift target",
                    snippet="Commonwealth Bank of Australia coverage",
                    url="https://example.com/right-dim",
                    source="example.com",
                )
            ],
            provider="p2",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [wrong_market] * 5)
        p2 = FakeSearchProvider("p2", [valid_result] * 5)
        self.service._providers = [p1, p2]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=5)
        self.assertIn("latest_news", intel)
        self.assertTrue(intel["latest_news"].results)
        self.assertEqual(intel["latest_news"].provider, "p2")
        self.assertGreaterEqual(p2.call_count, 1)

    def test_search_stock_news_cache_when_filtered_results_non_empty(self) -> None:
        """过滤后仍有结果时保持正常返回与缓存。"""
        valid_asx = SearchResponse(
            query="right",
            results=[
                SearchResult(
                    title="ASX: CBA.AX steady",
                    snippet="Commonwealth Bank of Australia remains resilient",
                    url="https://example.com/cached-right",
                    source="example.com",
                )
            ],
            provider="p1",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [valid_asx])
        self.service._providers = [p1]

        first = self.service.search_stock_news(self.code, self.name, max_results=3)
        self.assertTrue(first.results)
        self.assertEqual(p1.call_count, 1)

        second = self.service.search_stock_news(self.code, self.name, max_results=3)
        self.assertTrue(second.results)
        self.assertEqual(p1.call_count, 1)


if __name__ == "__main__":
    unittest.main()
