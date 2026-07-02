# -*- coding: utf-8 -*-
"""Tests for the optional email report footer renderer."""

import sys
from pathlib import Path
from types import SimpleNamespace

from src.notification import NotificationService
from src.services import report_renderer
from tests.test_report_readability_guardrail import _service


def _literal_footer() -> str:
    return (
        "\n\n---\n\n"
        "## 完整归档\n\n"
        "- 完整证据矩阵、历史校准、评分校准、风险仓位附录和审计细节已保存到本地 Markdown/HTML 归档。\n\n"
        "*免责声明：仅作计划，供人工决策辅助；系统不自动下单。*"
    )


def _archive_report_with_audit_marker() -> str:
    return (
        "# 2026-05-18 决策仪表盘\n\n"
        "## 开盘前决策驾驶舱\n\n"
        "今日人工复核重点。\n\n"
        "---\n\n"
        f"{NotificationService.AUDIT_APPENDIX_HEADING}\n\n"
        "审计明细"
    )


def _expected_email_body() -> str:
    return (
        "# 2026-05-18 决策仪表盘\n\n"
        "## 开盘前决策驾驶舱\n\n"
        "今日人工复核重点。"
        f"{_literal_footer()}"
    )


def _install_file_backed_fake_jinja(monkeypatch) -> None:
    class FakeFileSystemLoader:
        def __init__(self, searchpath: str) -> None:
            self.searchpath = Path(searchpath)

    class FakeStrictUndefined:
        pass

    class FakeTemplate:
        def __init__(self, path: Path) -> None:
            self.path = path

        def render(self, **context) -> str:
            return self.path.read_text(encoding="utf-8")

    class FakeEnvironment:
        def __init__(self, loader: FakeFileSystemLoader, **kwargs) -> None:
            self.loader = loader

        def get_template(self, template_name: str) -> FakeTemplate:
            template_path = self.loader.searchpath / template_name
            if not template_path.exists():
                raise FileNotFoundError(template_path)
            return FakeTemplate(template_path)

    monkeypatch.setitem(
        sys.modules,
        "jinja2",
        SimpleNamespace(
            Environment=FakeEnvironment,
            FileSystemLoader=FakeFileSystemLoader,
            StrictUndefined=FakeStrictUndefined,
        ),
    )


def test_email_report_footer_template_renders_equivalent_literal(monkeypatch):
    _install_file_backed_fake_jinja(monkeypatch)

    assert report_renderer.render_email_report_footer() == _literal_footer()


def test_report_renderer_returns_none_when_template_missing(tmp_path, monkeypatch):
    _install_file_backed_fake_jinja(monkeypatch)

    assert report_renderer.render_email_report_footer(template_dir=tmp_path) is None


def test_report_renderer_returns_none_when_jinja2_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "jinja2", None)

    assert report_renderer.render_email_report_footer() is None


def test_build_email_report_body_uses_renderer_footer(monkeypatch):
    called = {"renderer": False}

    def fake_render_footer() -> str:
        called["renderer"] = True
        return _literal_footer()

    monkeypatch.setattr("src.notification.render_email_report_footer", fake_render_footer)

    assert _service().build_email_report_body(_archive_report_with_audit_marker()) == _expected_email_body()
    assert called["renderer"] is True


def test_build_email_report_body_falls_back_when_renderer_returns_none(monkeypatch):
    monkeypatch.setattr("src.notification.render_email_report_footer", lambda: None)

    assert _service().build_email_report_body(_archive_report_with_audit_marker()) == _expected_email_body()


def test_build_email_report_body_falls_back_when_renderer_raises(monkeypatch):
    def raise_renderer_error() -> str:
        raise RuntimeError("template render failed")

    monkeypatch.setattr("src.notification.render_email_report_footer", raise_renderer_error)

    assert _service().build_email_report_body(_archive_report_with_audit_marker()) == _expected_email_body()
