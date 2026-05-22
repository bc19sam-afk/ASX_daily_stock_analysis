# -*- coding: utf-8 -*-
"""Guardrails for readable HTML table rendering in email and archive output."""

from src.formatters import markdown_to_archive_html_document, markdown_to_html_document


TABLE_MARKDOWN = """# 报告

| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |
| --- | --- | --- |
| BHP (BHP.AX) | 加仓 | 评分 75 |
"""


def test_email_html_keeps_tables_and_adds_scannable_table_styles():
    html = markdown_to_html_document(TABLE_MARKDOWN)

    assert "<table>" in html
    assert "<th>标的</th>" in html
    assert "<td>BHP (BHP.AX)</td>" in html
    assert "border-right: 1px solid #dfe2e5" in html
    assert "td:first-child" in html
    assert "box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06)" in html
    assert "line-height: 1.45" in html
    assert "@media (max-width: 640px)" in html


def test_archive_html_keeps_tables_and_adds_print_safe_table_styles():
    html = markdown_to_archive_html_document(TABLE_MARKDOWN)

    assert "<table>" in html
    assert "<th>今日主动作（确定性/未执行）</th>" in html
    assert "<td>评分 75</td>" in html
    assert "border-right: 1px solid #d0d7de" in html
    assert "break-inside: avoid" in html
    assert "box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06)" in html
    assert "@media screen and (max-width: 640px)" in html
