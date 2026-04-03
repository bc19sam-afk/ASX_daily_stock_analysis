# -*- coding: utf-8 -*-

from bot.commands.analyze import AnalyzeCommand
from bot.models import BotMessage, ChatType
from src.services.task_queue import DuplicateTaskError


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


def test_analyze_command_submits_task_via_task_queue(monkeypatch):
    command = AnalyzeCommand()
    called = {}

    class DummyTask:
        task_id = "task_queue_1234567890abcdef"

    class DummyQueue:
        def submit_task(self, stock_code, report_type):
            called["stock_code"] = stock_code
            called["report_type"] = report_type
            return DummyTask()

    monkeypatch.setattr("src.services.task_queue.get_task_queue", lambda: DummyQueue())

    response = command.execute(_build_message(), ["600519", "full"])

    assert called == {"stock_code": "600519", "report_type": "full"}
    assert response.markdown is True
    assert "✅ **分析任务已提交**" in response.text
    assert "task_queue_123456789..." in response.text


def test_analyze_command_duplicate_submit_still_returns_success(monkeypatch):
    command = AnalyzeCommand()

    class DummyQueue:
        def submit_task(self, stock_code, report_type):
            raise DuplicateTaskError(stock_code, "existing_task_id_1234567890")

    monkeypatch.setattr("src.services.task_queue.get_task_queue", lambda: DummyQueue())

    response = command.execute(_build_message(), ["600519"])

    assert response.markdown is True
    assert "✅ **分析任务已提交**" in response.text
    assert "existing_task_id_123..." in response.text
