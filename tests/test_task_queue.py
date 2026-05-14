# -*- coding: utf-8 -*-
"""Regression tests for async task queue failure payloads."""

import pytest

from src.services.task_queue import AnalysisTaskQueue, DuplicateTaskError, TaskInfo, TaskStatus


def _new_queue() -> AnalysisTaskQueue:
    AnalysisTaskQueue._instance = None
    queue = AnalysisTaskQueue(max_workers=1)
    queue._executor = None
    return queue


def test_execute_task_failure_preserves_original_error_for_existing_task(monkeypatch):
    queue = _new_queue()
    task = TaskInfo(task_id="task_existing", stock_code="BHP.AX")
    queue._tasks[task.task_id] = task
    queue._analyzing_stocks[task.stock_code] = task.task_id
    events = []
    queue._broadcast_event = lambda event_type, data: events.append((event_type, data))

    class _FailingService:
        def analyze_stock(self, **_kwargs):
            raise RuntimeError("original analysis failure")

    monkeypatch.setattr(
        "src.services.analysis_service.AnalysisService",
        lambda: _FailingService(),
    )

    assert queue._execute_task(task.task_id, task.stock_code, "full", False) is None

    assert task.status is TaskStatus.FAILED
    assert task.error == "original analysis failure"
    assert events[-1][0] == "task_failed"
    assert events[-1][1]["task_id"] == "task_existing"
    assert events[-1][1]["status"] == "failed"
    assert events[-1][1]["error"] == "original analysis failure"


def test_execute_task_failure_when_task_disappears_broadcasts_safe_error(monkeypatch):
    queue = _new_queue()
    task = TaskInfo(task_id="task_missing", stock_code="CBA.AX")
    queue._tasks[task.task_id] = task
    queue._analyzing_stocks[task.stock_code] = task.task_id
    events = []
    queue._broadcast_event = lambda event_type, data: events.append((event_type, data))

    class _FailingService:
        def analyze_stock(self, **_kwargs):
            queue._tasks.pop("task_missing", None)
            raise RuntimeError("original disappeared-task failure")

    monkeypatch.setattr(
        "src.services.analysis_service.AnalysisService",
        lambda: _FailingService(),
    )

    assert queue._execute_task("task_missing", "CBA.AX", "full", False) is None

    assert events[-1][0] == "task_failed"
    assert events[-1][1] == {
        "task_id": "task_missing",
        "stock_code": "CBA.AX",
        "stock_name": None,
        "status": "failed",
        "progress": 0,
        "message": "分析失败: original disappeared-task failure",
        "report_type": "full",
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "error": "original disappeared-task failure",
    }
    assert queue._analyzing_stocks.get("CBA.AX") is None


def test_submit_task_rejects_common_asx_alias_duplicate():
    class _ExecutorStub:
        def submit(self, *_args, **_kwargs):
            return object()

    queue = _new_queue()
    queue._executor = _ExecutorStub()
    queue._broadcast_event = lambda *_args, **_kwargs: None

    first = queue.submit_task("NHF.AX")

    assert first.stock_code == "NHF.AX"
    assert queue.is_analyzing("NHF.ASX")
    assert queue.get_analyzing_task_id("NHF.ASX") == first.task_id

    with pytest.raises(DuplicateTaskError) as exc_info:
        queue.submit_task("NHF.ASX")

    assert exc_info.value.stock_code == "NHF.AX"
    assert exc_info.value.existing_task_id == first.task_id
