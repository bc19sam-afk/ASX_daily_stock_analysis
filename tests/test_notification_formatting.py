# -*- coding: utf-8 -*-
"""Focused display-format guardrails for report labels."""

from src.notification_formatting import format_stock_display_name


def test_stock_display_name_deduplicates_asx_alias_name():
    assert format_stock_display_name("NHF.ASX", "NHF.AX") == "NHF (NHF.AX)"


def test_stock_display_name_deduplicates_same_code_name():
    assert format_stock_display_name("BHP.AX", "BHP.AX") == "BHP (BHP.AX)"


def test_stock_display_name_canonicalizes_asx_code_suffix():
    assert format_stock_display_name("NHF.ASX", "NHF.ASX") == "NHF (NHF.AX)"


def test_stock_display_name_preserves_real_company_name_with_ticker_hint():
    assert format_stock_display_name("NIBHOLDING [NHF]", "NHF.AX") == "NIBHOLDING [NHF] (NHF.AX)"


def test_stock_display_name_preserves_non_asx_code_display():
    assert format_stock_display_name("AAPL", "AAPL") == "AAPL (AAPL)"


def test_stock_display_name_preserves_non_asx_dotted_code_display():
    assert format_stock_display_name("BRK.B", "BRK.B") == "BRK.B (BRK.B)"
