# -*- coding: utf-8 -*-
"""ASX-first search localisation tests."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import src.search_service as search_service_module
from src.search_service import (
    BraveSearchProvider,
    GeminiGroundingSearchProvider,
    SearchResponse,
    SearchResult,
    SearchService,
    SerpAPISearchProvider,
    TavilySearchProvider,
)


class CaptureProvider:
    name = "Capture"
    is_available = True

    def __init__(self, response: SearchResponse):
        self.response = response
        self.calls = []

    def search(self, query, max_results, days=7):
        self.calls.append({"query": query, "max_results": max_results, "days": days})
        self.response.query = query
        self.response.provider = self.name
        return self.response


class SearchAsxLocalisationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fresh_published_date = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

    def test_asx_stock_news_query_contains_asx_australia_and_english_context(self) -> None:
        service = SearchService(news_max_age_days=3, market_timezone="Australia/Sydney")
        provider = CaptureProvider(
            SearchResponse(
                query="",
                results=[
                    SearchResult(
                        title="ASX: CBA.AX shares steady",
                        snippet="Commonwealth Bank of Australia update",
                        url="https://example.com/asx-cba",
                        source="example.com",
                        published_date=self.fresh_published_date,
                    )
                ],
                provider="capture",
                success=True,
            )
        )
        service._providers = [provider]

        response = service.search_stock_news("CBA.AX", "Commonwealth Bank of Australia", max_results=3)

        self.assertTrue(response.success)
        query = provider.calls[0]["query"]
        self.assertIn("CBA.AX", query)
        self.assertIn("ASX", query)
        self.assertIn("Australia", query)
        self.assertIn("English", query)
        self.assertIn("latest news", query)

    def test_non_asx_query_keeps_existing_non_localised_shape(self) -> None:
        service = SearchService(news_max_age_days=3, market_timezone="Australia/Sydney")
        provider = CaptureProvider(SearchResponse(query="", results=[], provider="capture", success=False))
        service._providers = [provider]

        service.search_stock_news("AAPL", "Apple Inc", max_results=3)

        query = provider.calls[0]["query"]
        self.assertIn("AAPL", query)
        self.assertNotIn("ASX", query)
        self.assertNotIn("Australia", query)
        self.assertNotIn("English-first", query)

    def test_serpapi_uses_australia_english_parameters_for_asx_query(self) -> None:
        captured = {}

        class FakeGoogleSearch:
            def __init__(self, params):
                captured.update(params)

            def get_dict(self):
                return {"organic_results": []}

        with patch.dict(sys.modules, {"serpapi": SimpleNamespace(GoogleSearch=FakeGoogleSearch)}):
            response = SerpAPISearchProvider(["fake-key"]).search(
                "Commonwealth Bank of Australia CBA.AX CBA ASX Australia English-first latest news",
                max_results=3,
                days=1,
            )

        self.assertTrue(response.success)
        self.assertEqual(captured["google_domain"], "google.com.au")
        self.assertEqual(captured["hl"], "en")
        self.assertEqual(captured["gl"], "au")

    def test_tavily_search_depth_remains_advanced(self) -> None:
        captured = {}

        class FakeTavilyClient:
            def __init__(self, api_key):
                captured["api_key"] = api_key

            def search(self, **kwargs):
                captured.update(kwargs)
                return {"results": []}

        with patch.dict(sys.modules, {"tavily": SimpleNamespace(TavilyClient=FakeTavilyClient)}):
            response = TavilySearchProvider(["fake-key"]).search("CBA.AX ASX latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(captured["search_depth"], "advanced")

    def test_default_provider_order_is_tavily_gemini_serpapi(self) -> None:
        service = SearchService(
            tavily_keys=["tavily-key"],
            gemini_keys=["gemini-key-1234567890"],
            serpapi_keys=["serpapi-key"],
            brave_keys=["brave-key"],
            bocha_keys=["bocha-key"],
            gemini_grounding_enabled=True,
        )

        self.assertEqual(
            [provider.name for provider in service._providers],
            ["Tavily", "Gemini Grounding", "SerpAPI"],
        )

    def test_gemini_grounding_is_first_provider_when_tavily_is_missing(self) -> None:
        service = SearchService(
            gemini_keys=["gemini-key-1234567890"],
            serpapi_keys=["serpapi-key"],
            brave_keys=["brave-key"],
            bocha_keys=["bocha-key"],
            gemini_grounding_enabled=True,
        )

        self.assertEqual(
            [provider.name for provider in service._providers],
            ["Gemini Grounding", "SerpAPI"],
        )

    def test_gemini_grounding_extracts_search_results_from_grounding_chunks(self) -> None:
        class FakeModels:
            @staticmethod
            def generate_content(*, model, contents, config):
                web = SimpleNamespace(uri="https://www.asx.com.au/markets/company/CBA", title="CBA ASX profile")
                chunk = SimpleNamespace(web=web)
                metadata = SimpleNamespace(grounding_chunks=[chunk], web_search_queries=["CBA.AX ASX latest news"])
                candidate = SimpleNamespace(grounding_metadata=metadata)
                return SimpleNamespace(text='{"results": []}', candidates=[candidate])

        class FakeClient:
            def __init__(self, api_key):
                self.models = FakeModels()

        fake_types = SimpleNamespace(
            Tool=lambda google_search: SimpleNamespace(google_search=google_search),
            GoogleSearch=lambda: SimpleNamespace(),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        fake_genai = SimpleNamespace(Client=FakeClient, types=fake_types)

        with patch.dict(sys.modules, {"google": SimpleNamespace(genai=fake_genai), "google.genai": fake_genai}):
            response = GeminiGroundingSearchProvider(
                ["gemini-key-1234567890"],
                model="gemini-3.5-flash",
                max_results=3,
            ).search("CBA.AX ASX latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Gemini Grounding")
        self.assertEqual(response.results[0].url, "https://www.asx.com.au/markets/company/CBA")
        self.assertEqual(response.results[0].title, "CBA ASX profile")
        self.assertEqual(response.results[0].source, "asx.com.au")

    def test_gemini_grounding_failure_falls_back_to_serpapi(self) -> None:
        fresh = self.fresh_published_date
        gemini = GeminiGroundingSearchProvider(
            ["gemini-key-1234567890"],
            model="gemini-3.5-flash",
            max_results=3,
        )
        serpapi = CaptureProvider(
            SearchResponse(
                query="",
                results=[
                    SearchResult(
                        title="ASX: CBA.AX fallback result",
                        snippet="Commonwealth Bank of Australia update",
                        url="https://example.com/serpapi-fallback",
                        source="example.com",
                        published_date=fresh,
                    )
                ],
                provider="SerpAPI",
                success=True,
            )
        )
        serpapi.name = "SerpAPI"
        service = SearchService(news_max_age_days=3, market_timezone="Australia/Sydney")
        service._providers = [gemini, serpapi]

        with patch.object(gemini, "search", return_value=SearchResponse("", [], "Gemini Grounding", False, "quota")):
            response = service.search_stock_news("CBA.AX", "Commonwealth Bank of Australia", max_results=3)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "SerpAPI")
        self.assertEqual(response.results[0].url, "https://example.com/serpapi-fallback")

    def test_serpapi_non_asx_parameters_use_non_cn_defaults(self) -> None:
        captured = {}

        class FakeGoogleSearch:
            def __init__(self, params):
                captured.update(params)

            def get_dict(self):
                return {"organic_results": []}

        with patch.dict(sys.modules, {"serpapi": SimpleNamespace(GoogleSearch=FakeGoogleSearch)}):
            response = SerpAPISearchProvider(["fake-key"]).search("Apple Inc AAPL latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(captured["google_domain"], "google.com")
        self.assertEqual(captured["hl"], "en")
        self.assertEqual(captured["gl"], "us")

    def test_serpapi_non_asx_query_with_australia_uses_non_cn_defaults(self) -> None:
        captured = {}

        class FakeGoogleSearch:
            def __init__(self, params):
                captured.update(params)

            def get_dict(self):
                return {"organic_results": []}

        with patch.dict(sys.modules, {"serpapi": SimpleNamespace(GoogleSearch=FakeGoogleSearch)}):
            response = SerpAPISearchProvider(["fake-key"]).search(
                "Apple Australia AAPL latest news",
                max_results=3,
                days=1,
            )

        self.assertTrue(response.success)
        self.assertEqual(captured["google_domain"], "google.com")
        self.assertEqual(captured["hl"], "en")
        self.assertEqual(captured["gl"], "us")

    def test_brave_uses_australia_english_parameters_for_asx_query(self) -> None:
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"web": {"results": []}}

        def fake_get(url, headers, params, timeout):
            captured.update(params)
            return FakeResponse()

        with patch.object(search_service_module.requests, "get", side_effect=fake_get):
            response = BraveSearchProvider(["fake-key"]).search(
                "Commonwealth Bank of Australia CBA.AX CBA ASX Australia English-first latest news",
                max_results=3,
                days=1,
            )

        self.assertTrue(response.success)
        self.assertEqual(captured["search_lang"], "en")
        self.assertEqual(captured["country"], "AU")

    def test_brave_non_asx_parameters_are_unchanged(self) -> None:
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"web": {"results": []}}

        def fake_get(url, headers, params, timeout):
            captured.update(params)
            return FakeResponse()

        with patch.object(search_service_module.requests, "get", side_effect=fake_get):
            response = BraveSearchProvider(["fake-key"]).search("Apple Inc AAPL latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(captured["search_lang"], "en")
        self.assertEqual(captured["country"], "US")

    def test_brave_non_asx_query_with_australia_keeps_existing_parameters(self) -> None:
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"web": {"results": []}}

        def fake_get(url, headers, params, timeout):
            captured.update(params)
            return FakeResponse()

        with patch.object(search_service_module.requests, "get", side_effect=fake_get):
            response = BraveSearchProvider(["fake-key"]).search("Apple Australia AAPL latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(captured["search_lang"], "en")
        self.assertEqual(captured["country"], "US")

    def test_asx_entity_disambiguation_filters_cross_market_results(self) -> None:
        service = SearchService()
        fresh = self.fresh_published_date
        provider = CaptureProvider(
            SearchResponse(
                query="",
                results=[
                    SearchResult(
                        title="CBA climbs on NASDAQ",
                        snippet="US company update",
                        url="https://example.com/wrong-market",
                        source="example.com",
                        published_date=fresh,
                    ),
                    SearchResult(
                        title="ASX: CBA.AX gains",
                        snippet="Commonwealth Bank of Australia update",
                        url="https://example.com/asx-market",
                        source="example.com",
                        published_date=fresh,
                    ),
                ],
                provider="capture",
                success=True,
            )
        )
        service._providers = [provider]

        response = service.search_stock_news("CBA.AX", "Commonwealth Bank of Australia", max_results=3)

        self.assertEqual([result.url for result in response.results], ["https://example.com/asx-market"])


if __name__ == "__main__":
    unittest.main()
