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
    SearchResponse,
    SearchResult,
    SearchService,
    SerpAPISearchProvider,
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

    def test_serpapi_non_asx_parameters_are_unchanged(self) -> None:
        captured = {}

        class FakeGoogleSearch:
            def __init__(self, params):
                captured.update(params)

            def get_dict(self):
                return {"organic_results": []}

        with patch.dict(sys.modules, {"serpapi": SimpleNamespace(GoogleSearch=FakeGoogleSearch)}):
            response = SerpAPISearchProvider(["fake-key"]).search("Apple Inc AAPL latest news", max_results=3, days=1)

        self.assertTrue(response.success)
        self.assertEqual(captured["google_domain"], "google.com.hk")
        self.assertEqual(captured["hl"], "zh-cn")
        self.assertEqual(captured["gl"], "cn")

    def test_serpapi_non_asx_query_with_australia_keeps_existing_parameters(self) -> None:
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
        self.assertEqual(captured["google_domain"], "google.com.hk")
        self.assertEqual(captured["hl"], "zh-cn")
        self.assertEqual(captured["gl"], "cn")

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
