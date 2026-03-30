"""
risk_manager.py
===============
Tracks daily wagering, consecutive losses, locked balances,
and enforces safety limits.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RiskState:
    """Current risk management state (serialisable snapshot)."""
    total_wagered_today: float = 0.0
    total_pnl_today: float = 0.0
    consecutive_loss_amount: float = 0.0
    consecutive_loss_count: int = 0
    max_drawdown: float = 0.0
    locked_balance: float = 0.0
    simulated_balance: float = 100.0      # starting sim balance
    trades_today: int = 0
    stopped: bool = False
    stop_reason: str = ""
    day_key: str = ""                      # YYYY-MM-DD in UTC


class RiskManager:
    """
    Enforces:
      - MAX_DAILY_RISK: total USD wagered in a day
      - MAX_CONSECUTIVE_LOSS: cumulative loss from consecutive losing trades
      - Balance locking: funds held until market resolves (real mode)
    """

    def __init__(
        self,
        max_daily_risk: float,
        max_consecutive_loss: float,
        initial_balance: float = 100.0,
    ):
        self.max_daily_risk = max_daily_risk
        self.max_consecutive_loss = max_consecutive_loss
        self.state = RiskState(
            simulated_balance=initial_balance,
            day_key=self._today_key(),
        )

    # ── Public API ────────────────────────────────────────────────────

    def can_trade(self, amount: float) -> tuple[bool, str]:
        """
        Check if a trade of `amount` USD is allowed.
        Returns (allowed, reason).
        """
        self._check_day_reset()

        if self.state.stopped:
            return False, f"Parada diaria: {self.state.stop_reason}"

        if self.state.total_wagered_today + amount > self.max_daily_risk:
            remaining = self.max_daily_risk - self.state.total_wagered_today
            return False, (
                f"Límite diario alcanzado: apostado={self.state.total_wagered_today:.2f} "
                f"+ {amount:.2f} > máx={self.max_daily_risk:.2f} "
                f"(disponible={remaining:.2f})"
            )

        if self.state.consecutive_loss_amount >= self.max_consecutive_loss:
            self.state.stopped = True
            self.state.stop_reason = (
                f"Pérdida consecutiva acumulada: "
                f"{self.state.consecutive_loss_amount:.2f} >= {self.max_consecutive_loss:.2f}"
            )
            return False, self.state.stop_reason

        available = self.state.simulated_balance - self.state.locked_balance
        if available < amount:
            return False, (
                f"Saldo insuficiente: disponible={available:.2f}, "
                f"necesario={amount:.2f}"
            )

        return True, "OK"

    def record_trade(self, amount: float, pnl: float) -> None:
        """Record a completed trade (after market resolves or sim settles)."""
        self._check_day_reset()
        self.state.total_wagered_today += amount
        self.state.total_pnl_today += pnl
        self.state.trades_today += 1

        if pnl < 0:
            self.state.consecutive_loss_amount += abs(pnl)
            self.state.consecutive_loss_count += 1
        else:
            # Win resets the consecutive loss counter
            self.state.consecutive_loss_amount = 0.0
            self.state.consecutive_loss_count = 0

        # Update drawdown
        if self.state.total_pnl_today < self.state.max_drawdown:
            self.state.max_drawdown = self.state.total_pnl_today

        # Update balance
        self.state.simulated_balance += pnl

    def lock_balance(self, amount: float) -> None:
        """Mark funds as locked until market resolves (real mode)."""
        self.state.locked_balance += amount

    def unlock_balance(self, amount: float) -> None:
        """Release locked funds when market resolves."""
        self.state.locked_balance = max(0.0, self.state.locked_balance - amount)

    def get_balance(self) -> float:
        """Current available (unlocked) balance."""
        return self.state.simulated_balance - self.state.locked_balance

    def get_status(self) -> dict:
        """Return current risk state as a dict for logging."""
        self._check_day_reset()
        return {
            "total_wagered_today": round(self.state.total_wagered_today, 4),
            "total_pnl_today": round(self.state.total_pnl_today, 4),
            "consecutive_loss_amount": round(self.state.consecutive_loss_amount, 4),
            "consecutive_loss_count": self.state.consecutive_loss_count,
            "max_drawdown": round(self.state.max_drawdown, 4),
            "locked_balance": round(self.state.locked_balance, 4),
            "simulated_balance": round(self.state.simulated_balance, 4),
            "available_balance": round(self.get_balance(), 4),
            "trades_today": self.state.trades_today,
            "stopped": self.state.stopped,
            "stop_reason": self.state.stop_reason,
        }

    # ── Internals ─────────────────────────────────────────────────────

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_day_reset(self) -> None:
        """Auto-reset counters at UTC midnight."""
        today = self._today_key()
        if self.state.day_key != today:
            print(f"[RISK] ✨ New day ({today}). Resetting daily counters.")
            self.state.total_wagered_today = 0.0
            self.state.total_pnl_today = 0.0
            self.state.consecutive_loss_amount = 0.0
            self.state.consecutive_loss_count = 0
            self.state.max_drawdown = 0.0
            self.state.trades_today = 0
            self.state.stopped = False
            self.state.stop_reason = ""
            self.state.locked_balance = 0.0
            self.state.day_key = today
