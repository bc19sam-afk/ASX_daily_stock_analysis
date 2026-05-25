# -*- coding: utf-8 -*-
"""Guardrails for readable HTML table rendering in email and archive output."""

from src.formatters import markdown_to_archive_html_document, markdown_to_html_document


TABLE_MARKDOWN = """# 报告

| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |
| --- | --- | --- |
| BHP (BHP.AX) | 加仓 | 评分 75 |

## 条件化计划点位 / 人工复核参考

| 点位 | 价格/参考 | 来源 | 触发条件 | 失效条件 | 执行前 | 价格口径 | 技术基准日 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 理想买入观察位 | 60.20 | 这是一段很长的来源说明，用来模拟条件化计划表格里的长文本，必须在邮件和归档 HTML 中稳定换行。 | 开盘后复核 | 跌破关键位 | 人工复核 | 昨收计划 | 2026-05-22 |
"""


def test_email_html_keeps_tables_and_adds_scannable_table_styles():
    html = markdown_to_html_document(TABLE_MARKDOWN)

    assert "<table>" in html
    assert "<th>标的</th>" in html
    assert "<td>BHP (BHP.AX)</td>" in html
    assert "border-right: 1px solid #e2e8f0" in html
    assert "td:first-child" in html
    assert "font-variant-numeric: tabular-nums" in html
    assert "overflow-wrap: anywhere" in html
    assert "word-break: break-word" in html
    assert "display: block" in html
    assert "overflow-x: auto" in html
    assert "white-space: nowrap" in html
    assert "max-width: 100%" in html
    assert "line-height: 1.58" in html
    assert "@media (max-width: 640px)" in html


def test_archive_html_keeps_tables_and_adds_print_safe_table_styles():
    html = markdown_to_archive_html_document(TABLE_MARKDOWN)

    assert "<table>" in html
    assert "<th>今日主动作（确定性/未执行）</th>" in html
    assert "<td>评分 75</td>" in html
    assert "border-right: 1px solid #d0d7de" in html
    assert "break-inside: avoid" in html
    assert "display: block" in html
    assert "overflow-x: auto" in html
    assert "display: table" in html
    assert "overflow: visible" in html
    assert "font-variant-numeric: tabular-nums" in html
    assert "overflow-wrap: anywhere" in html
    assert "max-width: 100%" in html
    assert "@media screen and (max-width: 640px)" in html
