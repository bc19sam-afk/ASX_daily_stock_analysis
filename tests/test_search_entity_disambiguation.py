# -*- coding: utf-8 -*-
"""Search / News 实体消歧测试。"""

import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from src.search_service import (
    BaseSearchProvider,
    SearchService,
    SearchResponse,
    SearchResult,
    SerpAPISearchProvider,
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
        self.fresh_published_date = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

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

    def test_latest_news_keeps_name_only_true_positive(self) -> None:
        """latest_news: 仅公司名命中但无冲突市场信号时，受控兜底保留。"""
        code = "WES.AX"
        name = "Wesfarmers Limited"
        name_only = SearchResult(
            title="Wesfarmers Limited announces digital operations update",
            snippet="The bank said the rollout improves customer onboarding",
            url="https://example.com/name-only-latest",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(name_only),
            stock_code=code,
            stock_name=name,
            dimension="latest_news",
        )

        self.assertEqual(len(filtered.results), 1)
        self.assertEqual(filtered.results[0].url, "https://example.com/name-only-latest")

    def test_name_only_wrong_market_still_filtered(self) -> None:
        """仅公司名命中但出现冲突市场信号时，仍必须过滤。"""
        code = "WES.AX"
        name = "Wesfarmers Limited"
        name_with_conflict = SearchResult(
            title="Wesfarmers Limited discussed on NYSE podcast",
            snippet="Analysts compared exposure to NASDAQ peers",
            url="https://example.com/name-conflict",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(name_with_conflict),
            stock_code=code,
            stock_name=name,
            dimension="latest_news",
        )

        self.assertEqual(len(filtered.results), 0)

    def test_market_analysis_name_only_not_relaxed(self) -> None:
        """非 latest_news 维度保持原阈值，不放宽 name-only。"""
        code = "WES.AX"
        name = "Wesfarmers Limited"
        name_only = SearchResult(
            title="Wesfarmers Limited sector outlook summary",
            snippet="General banking outlook without ticker/exchange signal",
            url="https://example.com/name-only-analysis",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(name_only),
            stock_code=code,
            stock_name=name,
            dimension="market_analysis",
        )

        self.assertEqual(len(filtered.results), 0)

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
                    published_date=self.fresh_published_date,
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
                    published_date=self.fresh_published_date,
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

    def test_search_comprehensive_intel_uses_one_provider_per_dimension(self) -> None:
        """某维度过滤为空时，不应继续在同一维度铺开更多 provider。"""
        wrong_market = SearchResponse(
            query="wrong",
            results=[
                SearchResult(
                    title="CBA on NASDAQ",
                    snippet="US CBA ticker",
                    url="https://example.com/wrong-dim",
                    source="example.com",
                    published_date=self.fresh_published_date,
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
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p2",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [wrong_market] * 5)
        p2 = FakeSearchProvider("p2", [valid_result] * 5)
        self.service._providers = [p1, p2]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=1)
        self.assertIn("latest_news", intel)
        self.assertFalse(intel["latest_news"].results)
        self.assertEqual(intel["latest_news"].provider, "None")
        self.assertEqual(p1.call_count, 1)
        self.assertEqual(p2.call_count, 0)

    def test_search_comprehensive_intel_round_robins_providers_across_dimensions(self) -> None:
        """多个维度应在可用 provider 间轮换，而不是单 provider 吃满所有维度。"""
        provider_response = SearchResponse(
            query="ok",
            results=[
                SearchResult(
                    title="ASX: CBA.AX coverage",
                    snippet="Commonwealth Bank of Australia update",
                    url="https://example.com/round-robin",
                    source="example.com",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [provider_response] * 5)
        p2 = FakeSearchProvider("p2", [provider_response] * 5)
        self.service._providers = [p1, p2]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=3)

        self.assertEqual(list(intel.keys()), ["latest_news", "market_analysis", "risk_check"])
        self.assertEqual(p1.call_count, 2)
        self.assertEqual(p2.call_count, 1)

    def test_search_comprehensive_intel_excludes_serpapi_from_primary_rotation(self) -> None:
        """SerpAPI 配额少，Tavily/Gemini 可用时不应进入多维度轮换池。"""

        def make_response(url_suffix: str) -> SearchResponse:
            return SearchResponse(
                query="ok",
                results=[
                    SearchResult(
                        title="ASX: CBA.AX coverage",
                        snippet="Commonwealth Bank of Australia update",
                        url=f"https://example.com/{url_suffix}",
                        source="example.com",
                        published_date=self.fresh_published_date,
                    )
                ],
                provider="mock",
                success=True,
            )

        tavily = FakeSearchProvider("Tavily", [make_response(f"tavily-{i}") for i in range(3)])
        gemini = FakeSearchProvider("Gemini Grounding", [make_response(f"gemini-{i}") for i in range(2)])
        serpapi = FakeSearchProvider("SerpAPI", [make_response(f"serpapi-{i}") for i in range(5)])
        serpapi.supports_comprehensive_intel_rotation = False
        self.service._providers = [tavily, gemini, serpapi]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=5)

        self.assertEqual(list(intel.keys()), ["latest_news", "market_analysis", "risk_check", "earnings", "industry"])
        self.assertEqual([resp.provider for resp in intel.values()], ["Tavily", "Gemini Grounding", "Tavily", "Gemini Grounding", "Tavily"])
        self.assertEqual(tavily.call_count, 3)
        self.assertEqual(gemini.call_count, 2)
        self.assertEqual(serpapi.call_count, 0)

    def test_search_comprehensive_intel_uses_serpapi_when_only_fallback_available(self) -> None:
        """只有 SerpAPI 可用时，保留最后兜底能力。"""
        provider_response = SearchResponse(
            query="ok",
            results=[
                SearchResult(
                    title="ASX: CBA.AX coverage",
                    snippet="Commonwealth Bank of Australia update",
                    url="https://example.com/serpapi-only",
                    source="example.com",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="mock",
            success=True,
        )
        serpapi = FakeSearchProvider("SerpAPI", [provider_response])
        serpapi.supports_comprehensive_intel_rotation = False
        self.service._providers = [serpapi]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=1)

        self.assertEqual(intel["latest_news"].provider, "SerpAPI")
        self.assertEqual(serpapi.call_count, 1)

    def test_real_serpapi_provider_marks_itself_out_of_routine_rotation(self) -> None:
        """真实 SerpAPI provider 应声明自己只做低频兜底。"""
        provider = SerpAPISearchProvider(["fake-key"])

        self.assertFalse(provider.supports_comprehensive_intel_rotation)

    def test_search_comprehensive_intel_keeps_undated_non_news_dimension(self) -> None:
        """非新闻类维度不应因为 provider 未给发布日期就被时效过滤清空。"""
        response = SearchResponse(
            query="analysis",
            results=[
                SearchResult(
                    title="ASX: CBA.AX analyst coverage",
                    snippet="Commonwealth Bank of Australia analyst report",
                    url="https://example.com/no-date-analysis",
                    source="example.com",
                )
            ],
            provider="p1",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [response])
        self.service._providers = [p1]

        intel = self.service.search_comprehensive_intel(
            self.code,
            self.name,
            max_searches=1,
            dimensions=[
                {
                    "name": "market_analysis",
                    "query": "CBA.AX analyst rating target price report",
                    "desc": "机构分析",
                    "strict_freshness": False,
                }
            ],
        )

        self.assertTrue(intel["market_analysis"].results)
        self.assertEqual(intel["market_analysis"].results[0].url, "https://example.com/no-date-analysis")

    def test_search_comprehensive_intel_default_dimensions_and_result_count_are_unchanged(self) -> None:
        """默认情报搜索仍覆盖 5 个维度，每维请求 3 条结果。"""
        calls = []

        class RecordingProvider(FakeSearchProvider):
            def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
                calls.append({"query": query, "max_results": max_results})
                return SearchResponse(
                    query=query,
                    results=[
                        SearchResult(
                            title="ASX: CBA.AX coverage",
                            snippet="Commonwealth Bank of Australia update",
                            url=f"https://example.com/{len(calls)}",
                            source="example.com",
                            published_date=self_outer.fresh_published_date,
                        )
                    ],
                    provider=self.name,
                    success=True,
                )

        self_outer = self
        provider = RecordingProvider("p1", [])
        self.service._providers = [provider]

        intel = self.service.search_comprehensive_intel(self.code, self.name)

        self.assertEqual(list(intel.keys()), ["latest_news", "market_analysis", "risk_check", "earnings", "industry"])
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(call["max_results"] == 3 for call in calls))

    def test_search_comprehensive_intel_honors_smaller_max_searches(self) -> None:
        """调用方显式传更小 max_searches 时，只搜索前 N 个维度。"""
        calls = []

        class RecordingProvider(FakeSearchProvider):
            def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
                calls.append(query)
                return SearchResponse(
                    query=query,
                    results=[
                        SearchResult(
                            title="ASX: CBA.AX coverage",
                            snippet="Commonwealth Bank of Australia update",
                            url=f"https://example.com/small-max-{len(calls)}",
                            source="example.com",
                            published_date=self_outer.fresh_published_date,
                        )
                    ],
                    provider=self.name,
                    success=True,
                )

        self_outer = self
        self.service._providers = [RecordingProvider("p1", [])]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=2)

        self.assertEqual(list(intel.keys()), ["latest_news", "market_analysis"])
        self.assertEqual(len(calls), 2)

    def test_search_comprehensive_intel_uses_cached_dimension_without_provider(self) -> None:
        """已命中的持久缓存维度不再触发 provider 搜索。"""
        cached = {
            dim["name"]: SearchResponse(
                query=dim["query"],
                results=[
                    SearchResult(
                        title=f"ASX: CBA.AX cached {dim['name']}",
                        snippet="Commonwealth Bank of Australia cached intelligence",
                        url=f"https://example.com/cached-{dim['name']}",
                        source="example.com",
                        published_date=self.fresh_published_date,
                    )
                ],
                provider="news_intel_cache",
                success=True,
            )
            for dim in self.service.build_comprehensive_intel_dimensions(self.code, self.name)
        }
        provider = FakeSearchProvider("p1", [])
        self.service._providers = [provider]

        intel = self.service.search_comprehensive_intel(
            self.code,
            self.name,
            max_searches=5,
            cached_intel=cached,
        )

        self.assertEqual(list(intel.keys()), ["latest_news", "market_analysis", "risk_check", "earnings", "industry"])
        self.assertTrue(all(resp.provider == "news_intel_cache" for resp in intel.values()))
        self.assertEqual(provider.call_count, 0)

        report = self.service.format_intel_report(intel, stock_name=self.name)
        self.assertIn("来源: news_intel_cache", report)
        self.assertIn("来源: example.com", report)
        self.assertIn("URL: https://example.com/cached-latest_news", report)
        self.assertIn(self.fresh_published_date.split(" ")[0], report)

    def test_search_comprehensive_intel_falls_back_for_missing_cached_dimension(self) -> None:
        """部分维度无缓存时，缺口维度继续走 provider fallback。"""
        dims = self.service.build_comprehensive_intel_dimensions(self.code, self.name)
        cached = {
            "latest_news": SearchResponse(
                query=dims[0]["query"],
                results=[
                    SearchResult(
                        title="ASX: CBA.AX cached latest",
                        snippet="Commonwealth Bank of Australia cached intelligence",
                        url="https://example.com/cached-latest",
                        source="example.com",
                        published_date=self.fresh_published_date,
                    )
                ],
                provider="news_intel_cache",
                success=True,
            )
        }
        provider_response = SearchResponse(
            query="provider",
            results=[
                SearchResult(
                    title="ASX: CBA.AX analysts update",
                    snippet="Commonwealth Bank of Australia coverage",
                    url="https://example.com/provider-market-analysis",
                    source="provider.example",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p1",
            success=True,
        )
        provider = FakeSearchProvider("p1", [provider_response])
        self.service._providers = [provider]

        intel = self.service.search_comprehensive_intel(
            self.code,
            self.name,
            max_searches=2,
            cached_intel=cached,
        )

        self.assertEqual(intel["latest_news"].provider, "news_intel_cache")
        self.assertEqual(intel["market_analysis"].provider, "p1")
        self.assertEqual(provider.call_count, 1)

    def test_search_stock_news_inflight_cache_coalesces_concurrent_same_query(self) -> None:
        """并发相同 query 时，只允许一个 provider 填充进程内 cache。"""

        class BlockingProvider(BaseSearchProvider):
            def __init__(self) -> None:
                super().__init__(api_keys=["fake-key"], name="blocking")
                self.call_count = 0
                self.lock = threading.Lock()
                self.started = threading.Event()
                self.release = threading.Event()

            def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
                with self.lock:
                    self.call_count += 1
                self.started.set()
                self.release.wait(timeout=2)
                return SearchResponse(
                    query=query,
                    results=[
                        SearchResult(
                            title="ASX: CBA.AX concurrent cache hit",
                            snippet="Commonwealth Bank of Australia update",
                            url="https://example.com/concurrent-cache",
                            source="example.com",
                            published_date=self_outer.fresh_published_date,
                        )
                    ],
                    provider=self.name,
                    success=True,
                )

        self_outer = self
        provider = BlockingProvider()
        self.service._providers = [provider]

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.service.search_stock_news, self.code, self.name, 3)
            self.assertTrue(provider.started.wait(timeout=1))
            second = executor.submit(self.service.search_stock_news, self.code, self.name, 3)
            time.sleep(0.05)
            provider.release.set()
            first_response = first.result(timeout=2)
            second_response = second.result(timeout=2)

        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first_response.results[0].url, "https://example.com/concurrent-cache")
        self.assertEqual(second_response.results[0].url, "https://example.com/concurrent-cache")

    def test_search_comprehensive_intel_latest_news_name_only_fallback(self) -> None:
        """latest_news 维度应修复 name-only 误杀。"""
        code = "WES.AX"
        name = "Wesfarmers Limited"
        name_only_latest = SearchResponse(
            query="name-only",
            results=[
                SearchResult(
                    title="Wesfarmers Limited launches customer remediation program",
                    snippet="Program details released without ticker symbol mention",
                    url="https://example.com/latest-name-only",
                    source="example.com",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p1",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [name_only_latest] * 5)
        self.service._providers = [p1]

        intel = self.service.search_comprehensive_intel(code, name, max_searches=5)
        self.assertTrue(intel["latest_news"].results)
        self.assertEqual(intel["latest_news"].results[0].url, "https://example.com/latest-name-only")

    def test_latest_news_name_only_fallback_not_applied_for_non_asx(self) -> None:
        """非 ASX 股票不应启用 name-only fallback。"""
        code = "WMT"
        name = "Walmart Inc"
        name_only = SearchResult(
            title="Walmart Inc expands logistics automation",
            snippet="Company announced new warehouse initiative",
            url="https://example.com/us-name-only",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(name_only),
            stock_code=code,
            stock_name=name,
            dimension="latest_news",
        )

        self.assertEqual(len(filtered.results), 0)

    def test_non_asx_latest_news_weak_or_wrong_market_result_still_filtered(self) -> None:
        """非 ASX latest_news 中弱相关/错误市场结果继续被挡住。"""
        code = "WMT"
        name = "Walmart Inc"
        weak_or_wrong = SearchResult(
            title="Walmart Inc discussed with NYSE retail basket volatility",
            snippet="No ticker symbol match in this weakly-related article",
            url="https://example.com/us-weak",
            source="example.com",
        )
        filtered = self.service._filter_entity_consistent_results(
            self._resp(weak_or_wrong),
            stock_code=code,
            stock_name=name,
            dimension="latest_news",
        )

        self.assertEqual(len(filtered.results), 0)

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
                    published_date=self.fresh_published_date,
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

    def test_search_comprehensive_intel_all_filtered_empty_returns_empty_dimension(self) -> None:
        """所有 provider 都 filtered-empty 时，维度必须保持空结果。"""
        wrong_market_1 = SearchResponse(
            query="wrong1",
            results=[
                SearchResult(
                    title="CBA surges on NYSE",
                    snippet="US listing CBA up",
                    url="https://example.com/wrong1",
                    source="example.com",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p1",
            success=True,
        )
        wrong_market_2 = SearchResponse(
            query="wrong2",
            results=[
                SearchResult(
                    title="CBA jumps on NASDAQ",
                    snippet="US CBA stock gains",
                    url="https://example.com/wrong2",
                    source="example.com",
                    published_date=self.fresh_published_date,
                )
            ],
            provider="p2",
            success=True,
        )
        p1 = FakeSearchProvider("p1", [wrong_market_1] * 5)
        p2 = FakeSearchProvider("p2", [wrong_market_2] * 5)
        self.service._providers = [p1, p2]

        intel = self.service.search_comprehensive_intel(self.code, self.name, max_searches=5)
        self.assertIn("latest_news", intel)
        self.assertFalse(intel["latest_news"].results)

        report = self.service.format_intel_report({"latest_news": intel["latest_news"]}, stock_name=self.name)
        self.assertIn("未找到相关信息", report)
        self.assertNotIn("NYSE", report)
        self.assertNotIn("NASDAQ", report)


if __name__ == "__main__":
    unittest.main()
