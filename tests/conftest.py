# -*- coding: utf-8 -*-
"""Shared offline test safeguards."""

import pytest


@pytest.fixture(autouse=True)
def _disable_notification_asx_network_fetch(monkeypatch):
    """Keep non-network report-rendering tests from touching ASX pages."""
    monkeypatch.setattr("src.notification.build_asx_announcement_checks", lambda *args, **kwargs: {})
