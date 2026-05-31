# -*- coding: utf-8 -*-
"""Default-off guard for future portfolio ledger v2 migrations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

LEDGER_V2_MIGRATION_FLAG = "ASX_LEDGER_V2_MIGRATION_ENABLED"
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}


@dataclass(frozen=True)
class LedgerV2MigrationStatus:
    enabled: bool
    flag_name: str
    flag_value: Optional[str]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "flag_name": self.flag_name,
            "flag_value": self.flag_value,
            "reason": self.reason,
        }


class PortfolioLedgerMigrationBlocked(RuntimeError):
    """Raised when a ledger v2 migration runner attempts to execute while disabled."""


class PortfolioLedgerMigrationGuard:
    """Evaluate whether future ledger v2 migration code may run.

    The guard is a small planning scaffold. PR6 does not include a migration
    runner; future migration entry points should call ``require_enabled`` before
    touching any database state.
    """

    def __init__(self, env: Optional[Mapping[str, str]] = None):
        self.env = env if env is not None else os.environ

    def status(self) -> LedgerV2MigrationStatus:
        raw_value = self.env.get(LEDGER_V2_MIGRATION_FLAG)
        normalized = str(raw_value or "").strip().lower()
        enabled = normalized in _TRUE_VALUES
        if enabled:
            reason = (
                f"Ledger v2 migration is explicitly enabled by {LEDGER_V2_MIGRATION_FLAG}; "
                "callers still need a reviewed migration runner."
            )
        else:
            reason = (
                f"Ledger v2 migration is disabled by default and must be explicitly enabled with "
                f"{LEDGER_V2_MIGRATION_FLAG}=true before any migration runner can execute."
            )
        return LedgerV2MigrationStatus(
            enabled=enabled,
            flag_name=LEDGER_V2_MIGRATION_FLAG,
            flag_value=raw_value,
            reason=reason,
        )

    def require_enabled(self) -> LedgerV2MigrationStatus:
        status = self.status()
        if not status.enabled:
            raise PortfolioLedgerMigrationBlocked(status.reason)
        return status


def get_ledger_v2_migration_status(env: Optional[Mapping[str, str]] = None) -> LedgerV2MigrationStatus:
    """Return the default-off migration status without side effects."""
    return PortfolioLedgerMigrationGuard(env=env).status()
