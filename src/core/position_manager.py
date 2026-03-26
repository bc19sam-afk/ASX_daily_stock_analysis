# -*- coding: utf-8 -*-
"""Position manager for converting final decision into portfolio-aware actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class PositionDecision:
    action: str
    target_weight: float
    delta_amount: float
    reason: str


class PositionManager:
    """Minimal deterministic rules for position-aware actions."""

    def decide(
        self,
        *,
        current_weight: float,
        avg_cost: float,
        available_cash: float,
        final_decision: str,
        market_regime: str,
        event_risk: str,
        data_quality_flag: str,
    ) -> PositionDecision:
        current_weight = max(float(current_weight or 0.0), 0.0)
        available_cash = max(float(available_cash or 0.0), 0.0)
        final_decision = str(final_decision or "HOLD").upper()

        risk_cap = self._risk_cap(
            market_regime=market_regime,
            event_risk=event_risk,
            data_quality_flag=data_quality_flag,
        )

        if final_decision == "SELL":
            target_weight = 0.0
        elif final_decision == "BUY":
            base_target = 0.10 if current_weight <= 0 else min(current_weight + 0.05, 0.35)
            target_weight = min(base_target, risk_cap)
        else:
            target_weight = min(current_weight, risk_cap)

        target_weight = max(round(target_weight, 4), 0.0)
        delta_weight = round(target_weight - current_weight, 4)

        # Minimal现金约束：只能用当前可用现金加仓
        if delta_weight > 0 and available_cash <= 0:
            target_weight = current_weight
            delta_weight = 0.0

        nav_guess = max(available_cash / 0.30, available_cash)
        delta_amount = round(delta_weight * nav_guess, 2)

        action = self._derive_action(current_weight=current_weight, delta_weight=delta_weight)
        reason = (
            f"final_decision={final_decision}, regime={market_regime}, risk={event_risk}, "
            f"data_quality={data_quality_flag}, avg_cost={round(float(avg_cost or 0.0), 4)}"
        )
        return PositionDecision(
            action=action,
            target_weight=target_weight,
            delta_amount=delta_amount,
            reason=reason,
        )

    @staticmethod
    def _risk_cap(*, market_regime: str, event_risk: str, data_quality_flag: str) -> float:
        if data_quality_flag == "MISSING":
            return 0.0
        if market_regime == "RISK_OFF":
            return 0.10
        if event_risk == "HIGH":
            return 0.10
        if event_risk == "MEDIUM":
            return 0.20
        return 0.35

    @staticmethod
    def _derive_action(*, current_weight: float, delta_weight: float) -> str:
        if current_weight <= 0 and delta_weight > 0:
            return "OPEN"
        if current_weight > 0 and delta_weight > 0:
            return "ADD"
        if current_weight > 0 and delta_weight < 0:
            return "CLOSE" if current_weight + delta_weight <= 0 else "REDUCE"
        return "HOLD"


def position_decision_to_dict(value: PositionDecision) -> Dict[str, Any]:
    return {
        "action": value.action,
        "target_weight": value.target_weight,
        "delta_amount": value.delta_amount,
        "reason": value.reason,
    }
