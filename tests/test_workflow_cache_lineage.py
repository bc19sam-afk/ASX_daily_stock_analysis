# -*- coding: utf-8 -*-

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_cache_key_lineage_is_aligned_across_manual_and_daily_workflows():
    daily = _read(".github/workflows/daily_analysis.yml")
    init_workflow = _read(".github/workflows/init-portfolio.yml")
    paper_workflow = _read(".github/workflows/init-paper-portfolio.yml")
    record_workflow = _read(".github/workflows/record-trade.yml")
    cash_workflow = _read(".github/workflows/record-cash.yml")

    expected_key = "stock-db-${{ runner.os }}-${{ github.ref_name }}-${{ github.run_id }}"
    expected_restore_prefix = "stock-db-${{ runner.os }}-${{ github.ref_name }}-"

    assert f"key: {expected_key}" in daily
    assert f"key: {expected_key}" in init_workflow
    assert f"key: {expected_key}" in paper_workflow
    assert f"key: {expected_key}" in record_workflow
    assert f"key: {expected_key}" in cash_workflow

    assert expected_restore_prefix in daily
    assert expected_restore_prefix in init_workflow
    assert expected_restore_prefix in paper_workflow
    assert expected_restore_prefix in record_workflow
    assert expected_restore_prefix in cash_workflow


def test_cache_path_is_consistent_for_portfolio_db():
    daily = _read(".github/workflows/daily_analysis.yml")
    init_workflow = _read(".github/workflows/init-portfolio.yml")
    paper_workflow = _read(".github/workflows/init-paper-portfolio.yml")
    record_workflow = _read(".github/workflows/record-trade.yml")
    cash_workflow = _read(".github/workflows/record-cash.yml")

    expected_path_line = "path: data/stock_analysis.db"

    assert expected_path_line in daily
    assert expected_path_line in init_workflow
    assert expected_path_line in paper_workflow
    assert expected_path_line in record_workflow
    assert expected_path_line in cash_workflow


def test_db_cache_writing_workflows_share_concurrency_group():
    workflows = [
        _read(".github/workflows/daily_analysis.yml"),
        _read(".github/workflows/init-portfolio.yml"),
        _read(".github/workflows/init-paper-portfolio.yml"),
        _read(".github/workflows/record-trade.yml"),
        _read(".github/workflows/record-cash.yml"),
    ]

    for workflow in workflows:
        assert "concurrency:" in workflow
        assert "group: stock-analysis" in workflow
        assert "cancel-in-progress: false" in workflow


def test_daily_analysis_uses_timezone_aware_weekday_schedule():
    daily = _read(".github/workflows/daily_analysis.yml")

    assert "cron: '0 8 * * 1-5'" in daily
    assert "timezone: 'Australia/Sydney'" in daily
    assert "20 20 * * 0-4" not in daily
    assert "20 21 * * 0-4" not in daily


def test_daily_analysis_gate_no_longer_requires_exact_time_match():
    daily = _read(".github/workflows/daily_analysis.yml")

    assert 'local_time=$(TZ=\'Australia/Melbourne\' date \'+%H:%M\')' not in daily
    assert '[ "$local_time" =' not in daily
    assert "matched timezone-aware Australia/Sydney weekday schedule" in daily


def test_daily_analysis_seeds_paper_portfolio_before_report_when_enabled():
    daily = _read(".github/workflows/daily_analysis.yml")

    assert "启用模拟盘账本（如未初始化）" in daily
    assert "PAPER_PORTFOLIO_AUTO_INIT" in daily
    assert "python -m scripts.manual_portfolio_workflows init-paper-portfolio" in daily
    assert daily.index("init-paper-portfolio") < daily.index("执行股票分析")
