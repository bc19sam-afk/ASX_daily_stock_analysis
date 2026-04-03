# -*- coding: utf-8 -*-
"""Tests for SPA fallback behavior in integrated frontend/backend deploy."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


class SpaFallbackTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.static_dir = Path(self.temp_dir.name) / "static"
        self.static_dir.mkdir(parents=True, exist_ok=True)
        (self.static_dir / "index.html").write_text(
            "<html><body>spa-entry</body></html>",
            encoding="utf-8",
        )

        self.app = create_app(static_dir=self.static_dir)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_unknown_api_path_returns_404_not_found_payload(self) -> None:
        response = self.client.get("/api/does-not-exist")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"], "not_found")
        self.assertEqual(payload["message"], "API endpoint not found")

    def test_non_api_path_still_serves_index_html(self) -> None:
        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("spa-entry", response.text)


if __name__ == "__main__":
    unittest.main()
