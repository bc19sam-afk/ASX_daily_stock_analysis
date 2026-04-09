# -*- coding: utf-8 -*-

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_cache_key_lineage_is_aligned_across_manual_and_daily_workflows():
    daily = _read(".github/workflows/daily_analysis.yml")
    init_workflow = _read(".github/workflows/init-portfolio.yml")
    record_workflow = _read(".github/workflows/record-trade.yml")

    expected_key = "stock-db-${{ runner.os }}-${{ github.ref_name }}-${{ github.run_id }}"
    expected_restore_prefix = "stock-db-${{ runner.os }}-${{ github.ref_name }}-"

    assert f"key: {expected_key}" in daily
    assert f"key: {expected_key}" in init_workflow
    assert f"key: {expected_key}" in record_workflow

    assert expected_restore_prefix in daily
    assert expected_restore_prefix in init_workflow
    assert expected_restore_prefix in record_workflow


def test_cache_path_is_consistent_for_portfolio_db():
    daily = _read(".github/workflows/daily_analysis.yml")
    init_workflow = _read(".github/workflows/init-portfolio.yml")
    record_workflow = _read(".github/workflows/record-trade.yml")

    expected_path_line = "path: data/stock_analysis.db"

    assert expected_path_line in daily
    assert expected_path_line in init_workflow
    assert expected_path_line in record_workflow


def test_daily_analysis_uses_timezone_aware_weekday_schedule():
    daily = _read(".github/workflows/daily_analysis.yml")

    assert "cron: '20 7 * * 1-5'" in daily
    assert "timezone: 'Australia/Sydney'" in daily
    assert "20 20 * * 0-4" not in daily
    assert "20 21 * * 0-4" not in daily


def test_daily_analysis_gate_no_longer_requires_exact_0720_match():
    daily = _read(".github/workflows/daily_analysis.yml")

    assert 'local_time=$(TZ=\'Australia/Melbourne\' date \'+%H:%M\')' not in daily
    assert '[ "$local_time" = "07:20" ]' not in daily
    assert "matched timezone-aware Australia/Sydney weekday schedule" in daily
