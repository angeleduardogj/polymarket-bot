"""
logger.py
=========
Writes structured CSV trade logs with 25+ fields per row.
Creates one file per day: logs/trades_YYYY_MM_DD.csv
"""

import csv
import os
from datetime import datetime, timezone
from typing import Optional


# All CSV columns in order
CSV_COLUMNS = [
    "timestamp",
    "moneda",
    "precio_vela_1_apertura",
    "precio_vela_1_cierre",
    "precio_vela_2_apertura",
    "precio_vela_2_cierre",
    "tendencia",
    "apuesta",
    "monto",
    "modo",
    "binance_price_entry",
    "polymarket_price_entry",
    "market_url",
    "fee_percent",
    "spread_percent",
    "raw_pnl",
    "pnl_after_fees",
    "simulado_pnl",
    "real_pnl",
    "saldo_before",
    "saldo_after",
    "drawdown_acumulado",
    "price_discrepancy",
    "coincidencia_sim_real",
    "comentario",
]


class TradeLogger:
    """Write structured CSV logs, one file per UTC day."""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._current_file: Optional[str] = None
        self._current_date: Optional[str] = None

    # ── Public API ────────────────────────────────────────────────────

    def log_trade(
        self,
        *,
        moneda: str,
        precio_vela_1_apertura: float,
        precio_vela_1_cierre: float,
        precio_vela_2_apertura: float,
        precio_vela_2_cierre: float,
        tendencia: str,
        apuesta: str,
        monto: float,
        modo: str,
        binance_price_entry: float,
        polymarket_price_entry: float = 0.0,
        market_url: str = "",
        fee_percent: float = 0.0,
        spread_percent: float = 0.0,
        raw_pnl: float = 0.0,
        pnl_after_fees: float = 0.0,
        simulado_pnl: float = 0.0,
        real_pnl: float = 0.0,
        saldo_before: float = 0.0,
        saldo_after: float = 0.0,
        drawdown_acumulado: float = 0.0,
        price_discrepancy: float = 0.0,
        coincidencia_sim_real: str = "",
        comentario: str = "",
    ) -> None:
        """Append one trade row to today's CSV."""
        row = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "moneda": moneda,
            "precio_vela_1_apertura": f"{precio_vela_1_apertura:.6f}",
            "precio_vela_2_apertura": f"{precio_vela_2_apertura:.6f}",
            "precio_vela_1_cierre": f"{precio_vela_1_cierre:.6f}",
            "precio_vela_2_cierre": f"{precio_vela_2_cierre:.6f}",
            "tendencia": tendencia,
            "apuesta": apuesta,
            "monto": f"{monto:.4f}",
            "modo": modo,
            "binance_price_entry": f"{binance_price_entry:.6f}",
            "polymarket_price_entry": f"{polymarket_price_entry:.6f}",
            "market_url": market_url,
            "fee_percent": f"{fee_percent:.4f}",
            "spread_percent": f"{spread_percent:.4f}",
            "raw_pnl": f"{raw_pnl:.6f}",
            "pnl_after_fees": f"{pnl_after_fees:.6f}",
            "simulado_pnl": f"{simulado_pnl:.6f}",
            "real_pnl": f"{real_pnl:.6f}",
            "saldo_before": f"{saldo_before:.4f}",
            "saldo_after": f"{saldo_after:.4f}",
            "drawdown_acumulado": f"{drawdown_acumulado:.4f}",
            "price_discrepancy": f"{price_discrepancy:.4f}",
            "coincidencia_sim_real": coincidencia_sim_real,
            "comentario": comentario,
        }
        self._write_row(row)

    def log_skip(
        self,
        *,
        moneda: str,
        precio_vela_1_apertura: float = 0.0,
        precio_vela_1_cierre: float = 0.0,
        precio_vela_2_apertura: float = 0.0,
        precio_vela_2_cierre: float = 0.0,
        tendencia: str = "sin_clara",
        modo: str = "SIM",
        saldo_before: float = 0.0,
        saldo_after: float = 0.0,
        comentario: str = "Sin apuesta este ciclo",
    ) -> None:
        """Log a 'no trade' event."""
        row = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "moneda": moneda,
            "precio_vela_1_apertura": f"{precio_vela_1_apertura:.6f}",
            "precio_vela_1_cierre": f"{precio_vela_1_cierre:.6f}",
            "precio_vela_2_apertura": f"{precio_vela_2_apertura:.6f}",
            "precio_vela_2_cierre": f"{precio_vela_2_cierre:.6f}",
            "tendencia": tendencia,
            "apuesta": "N/A",
            "monto": "0.0000",
            "modo": modo,
            "binance_price_entry": "0.000000",
            "polymarket_price_entry": "0.000000",
            "market_url": "",
            "fee_percent": "0.0000",
            "spread_percent": "0.0000",
            "raw_pnl": "0.000000",
            "pnl_after_fees": "0.000000",
            "simulado_pnl": "0.000000",
            "real_pnl": "0.000000",
            "saldo_before": f"{saldo_before:.4f}",
            "saldo_after": f"{saldo_after:.4f}",
            "drawdown_acumulado": "0.0000",
            "price_discrepancy": "0.0000",
            "coincidencia_sim_real": "",
            "comentario": comentario,
        }
        self._write_row(row)

    # ── Internals ─────────────────────────────────────────────────────

    def _get_filepath(self) -> str:
        """Return today's CSV file path, creating the file with headers if new."""
        today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
        if self._current_date != today:
            self._current_date = today
            self._current_file = os.path.join(
                self.log_dir, f"trades_{today}.csv"
            )
            # Write header if file doesn't exist yet
            if not os.path.exists(self._current_file):
                with open(self._current_file, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    writer.writeheader()
                print(f"[LOG] Created new log file: {self._current_file}")
        return self._current_file  # type: ignore

    def _write_row(self, row: dict) -> None:
        filepath = self._get_filepath()
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(row)
