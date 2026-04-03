# -*- coding: utf-8 -*-

from bot.commands.analyze import AnalyzeCommand
from bot.models import BotMessage, ChatType
from src.enums import ReportType


def _build_message() -> BotMessage:
    return BotMessage(
        platform="dingtalk",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
    )


def test_analyze_command_uses_task_service_with_source_message(monkeypatch):
    command = AnalyzeCommand()
    message = _build_message()
    captured = {}

    class DummyService:
        def submit_analysis(self, code, report_type, source_message):
            captured["code"] = code
            captured["report_type"] = report_type
            captured["source_message"] = source_message
            return {"success": True, "task_id": "task_1234567890abcdef"}

    monkeypatch.setattr("src.services.task_service.get_task_service", lambda: DummyService())

    response = command.execute(message, ["600519", "full"])

    assert captured["code"] == "600519"
    assert captured["report_type"] == ReportType.FULL
    assert captured["source_message"] is message
    assert response.markdown is True
    assert "✅ **分析任务已提交**" in response.text
