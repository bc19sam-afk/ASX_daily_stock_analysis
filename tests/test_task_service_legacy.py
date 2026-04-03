import logging

from src.services import task_service


def test_get_task_service_emits_legacy_warning_once(caplog):
    # isolate singleton and one-time warning state for this test
    task_service.TaskService._instance = None
    task_service._LEGACY_WARNING_EMITTED = False

    caplog.set_level(logging.WARNING)

    task_service.get_task_service()
    task_service.get_task_service()

    legacy_records = [
        r for r in caplog.records
        if "Legacy compatibility layer only" in r.getMessage()
    ]
    assert len(legacy_records) == 1
