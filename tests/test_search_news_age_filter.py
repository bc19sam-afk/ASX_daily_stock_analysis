# -*- coding: utf-8 -*-
"""新闻发布时间硬过滤测试。"""

import unittest
from datetime import datetime, timezone

from src.search_service import SearchResponse, SearchResult, SearchService


class SearchNewsAgeFilterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SearchService(news_max_age_days=3)
        self.now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _response(result: SearchResult) -> SearchResponse:
        return SearchResponse(query="test", results=[result], provider="mock", success=True)

    def test_keeps_news_within_window(self) -> None:
        result = SearchResult(
            title="in-window",
            snippet="",
            url="https://example.com/1",
            source="example.com",
            published_date="2026-04-02",
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 1)

    def test_drops_news_older_than_window(self) -> None:
        result = SearchResult(
            title="too-old",
            snippet="",
            url="https://example.com/2",
            source="example.com",
            published_date="2026-03-20",
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 0)

    def test_drops_news_without_published_time(self) -> None:
        result = SearchResult(
            title="missing-time",
            snippet="",
            url="https://example.com/3",
            source="example.com",
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 0)

    def test_drops_news_with_invalid_published_time(self) -> None:
        result = SearchResult(
            title="invalid-time",
            snippet="",
            url="https://example.com/4",
            source="example.com",
            published_fields={"publish_time": "not-a-date"},
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 0)

    def test_drops_news_too_far_in_future(self) -> None:
        result = SearchResult(
            title="future-2-days",
            snippet="",
            url="https://example.com/5",
            source="example.com",
            published_fields={"publish_time": "2026-04-05T13:00:00Z"},
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 0)

    def test_keeps_news_within_one_day_future_tolerance(self) -> None:
        result = SearchResult(
            title="future-within-tolerance",
            snippet="",
            url="https://example.com/6",
            source="example.com",
            published_fields={"published_at": "2026-04-04T08:00:00Z"},
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 1)

    def test_keeps_relative_time_two_hours_ago(self) -> None:
        result = SearchResult(
            title="relative-2-hours",
            snippet="",
            url="https://example.com/7",
            source="example.com",
            published_fields={"publish_time": "2 hours ago"},
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 1)

    def test_drops_relative_time_five_days_ago(self) -> None:
        result = SearchResult(
            title="relative-5-days",
            snippet="",
            url="https://example.com/8",
            source="example.com",
            published_fields={"publish_time": "5 days ago"},
        )

        filtered = self.service._filter_by_news_age(self._response(result), now=self.now)
        self.assertEqual(len(filtered.results), 0)


if __name__ == "__main__":
    unittest.main()
