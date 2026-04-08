# -*- coding: utf-8 -*-
"""Unit tests for system configuration service."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import ConfigConflictError, SystemConfigService


class SystemConfigServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_get_config_returns_raw_sensitive_values(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("GEMINI_API_KEY", items)
        self.assertEqual(items["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(items["GEMINI_API_KEY"]["is_masked"])
        self.assertTrue(items["GEMINI_API_KEY"]["raw_value_exists"])

    def test_update_preserves_masked_secret(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[
                {"key": "GEMINI_API_KEY", "value": "******"},
                {"key": "STOCK_LIST", "value": "600519,300750"},
            ],
            mask_token="******",
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["applied_count"], 1)
        self.assertEqual(response["skipped_masked_count"], 1)
        self.assertIn("STOCK_LIST", response["updated_keys"])

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "600519,300750")
        self.assertEqual(current_map["GEMINI_API_KEY"], "secret-key-value")

    def test_update_without_reload_reports_runtime_and_restart_scopes(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[
                {"key": "STOCK_LIST", "value": "600519,300750"},
                {"key": "LOG_LEVEL", "value": "DEBUG"},
            ],
            reload_now=False,
        )

        warning_text = "\n".join(response["warnings"])
        self.assertIn("reload_now=false", warning_text)
        self.assertIn("STOCK_LIST", warning_text)
        self.assertIn("require the next process restart", warning_text)
        self.assertIn("LOG_LEVEL", warning_text)

    def test_update_with_reload_only_warns_for_process_start_scope(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[{"key": "LOG_LEVEL", "value": "DEBUG"}],
            reload_now=True,
        )

        warning_text = "\n".join(response["warnings"])
        self.assertTrue(response["reload_triggered"])
        self.assertIn("require the next process restart", warning_text)
        self.assertIn("LOG_LEVEL", warning_text)
        self.assertNotIn("reload_now=false", warning_text)

    def test_validate_reports_invalid_time(self) -> None:
        validation = self.service.validate(items=[{"key": "SCHEDULE_TIME", "value": "25:70"}])
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_format" for issue in validation["issues"]))

    def test_update_reports_runtime_refreshable_keys_reloaded_in_process(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "BHP.AX,CBA.AX"}],
            reload_now=True,
        )

        self.assertTrue(response["reload_triggered"])
        self.assertTrue(
            any(
                "Runtime-refreshable settings were reloaded in-process: STOCK_LIST" in warning
                for warning in response["warnings"]
            )
        )

    def test_update_reload_failure_does_not_claim_in_process_reload(self) -> None:
        with mock.patch("src.services.system_config_service.Config.get_instance", side_effect=RuntimeError("boom")):
            response = self.service.update(
                config_version=self.manager.get_config_version(),
                items=[{"key": "STOCK_LIST", "value": "BHP.AX,CBA.AX"}],
                reload_now=True,
            )

        warning_text = "\n".join(response["warnings"])
        self.assertFalse(response["reload_triggered"])
        self.assertIn("Configuration updated but reload failed", warning_text)
        self.assertIn("current process keeps old values", warning_text)
        self.assertNotIn("reloaded in-process", warning_text)

    def test_update_reports_process_start_keys_as_restart_bound(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "LOG_LEVEL", "value": "DEBUG"}],
            reload_now=False,
        )

        self.assertFalse(response["reload_triggered"])
        self.assertTrue(
            any(
                "process-start configuration" in warning and "LOG_LEVEL" in warning
                for warning in response["warnings"]
            )
        )

    def test_update_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.update(
                config_version="stale-version",
                items=[{"key": "STOCK_LIST", "value": "600519"}],
                reload_now=False,
            )

    def test_stale_version_returns_conflict_before_validation(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.update(
                config_version="stale-version",
                items=[{"key": "SCHEDULE_TIME", "value": "invalid-time"}],
                reload_now=False,
            )

    def test_apply_updates_if_version_fails_when_version_changed_before_write(self) -> None:
        initial_version = self.manager.get_config_version()
        self.manager.apply_updates(
            updates=[("LOG_LEVEL", "DEBUG")],
            sensitive_keys=set(),
            mask_token="******",
        )

        update_result = self.manager.apply_updates_if_version(
            expected_version=initial_version,
            updates=[("STOCK_LIST", "600519,300750")],
            sensitive_keys=set(),
            mask_token="******",
        )

        self.assertIsNone(update_result)

    def test_two_racing_updates_with_same_version_do_not_both_succeed(self) -> None:
        shared_version = self.manager.get_config_version()
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def worker(value: str) -> None:
            barrier.wait()
            try:
                response = self.service.update(
                    config_version=shared_version,
                    items=[{"key": "STOCK_LIST", "value": value}],
                    reload_now=False,
                )
                result = ("success", response["config_version"])
            except ConfigConflictError as exc:
                result = ("conflict", exc.current_version)
            with lock:
                outcomes.append(result)

        first = threading.Thread(target=worker, args=("600519,300750",))
        second = threading.Thread(target=worker, args=("600519,000858",))
        first.start()
        second.start()
        first.join()
        second.join()

        success_count = sum(1 for status, _ in outcomes if status == "success")
        conflict_count = sum(1 for status, _ in outcomes if status == "conflict")
        self.assertEqual(success_count, 1)
        self.assertEqual(conflict_count, 1)

    def test_version_change_during_validation_window_returns_conflict_via_cas(self) -> None:
        original_collect_issues = self.service._collect_issues

        def mutate_config_during_validation(*args, **kwargs):
            self.manager.apply_updates(
                updates=[("LOG_LEVEL", "DEBUG")],
                sensitive_keys=set(),
                mask_token="******",
            )
            return original_collect_issues(*args, **kwargs)

        with mock.patch.object(self.service, "_collect_issues", side_effect=mutate_config_during_validation):
            with self.assertRaises(ConfigConflictError):
                self.service.update(
                    config_version=self.manager.get_config_version(),
                    items=[{"key": "STOCK_LIST", "value": "600519,300750"}],
                    reload_now=False,
                )


if __name__ == "__main__":
    unittest.main()
