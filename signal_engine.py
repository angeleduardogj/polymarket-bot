"""
signal_engine.py
================
Receives 2 consecutive closed candles and decides:
  - Trend: BULLISH / BEARISH / NEUTRAL
  - Bet side: YES / NO / NONE
  - Bet amount based on trend clarity
"""

from dataclasses import dataclass
from enum import Enum
from typing import List

from binance_websocket import Candle


class Trend(Enum):
    BULLISH = "alza"
    BEARISH = "baja"
    NEUTRAL = "sin_clara"


class BetSide(Enum):
    YES = "YES"
    NO = "NO"
    NONE = "N/A"


@dataclass
class Signal:
    """Output of the signal engine for one cycle."""
    symbol: str
    trend: Trend
    bet_side: BetSide
    bet_amount: float          # USD. 0 means do not trade.
    candle_1: Candle
    candle_2: Candle
    reason: str                # Human-readable explanation


def evaluate_signal(
    candles: List[Candle],
    risk_per_trade: float,
    min_risk_per_trade: float,
    min_volatility_percent: float,
    aggressive_mode: bool,
) -> Signal:
    """
    Evaluate two consecutive candles and produce a trading signal.

    Rules:
      - Both green → BULLISH → YES
      - Both red   → BEARISH → NO
      - Mixed/flat → NEUTRAL → skip (or min bet if aggressive)
      - Low volatility on either candle → skip

    Args:
        candles: List of 2 Candle objects (oldest first).
        risk_per_trade: Full bet size (USD) for clear trends.
        min_risk_per_trade: Reduced bet size for weak/neutral signals.
        min_volatility_percent: Skip if change% below this.
        aggressive_mode: If True, bet MIN on neutral signals.

    Returns:
        A Signal dataclass.
    """
    assert len(candles) == 2, f"Expected 2 candles, got {len(candles)}"
    c1, c2 = candles[0], candles[1]
    symbol = c2.symbol

    # ── Volatility filter ──
    if c1.change_percent < min_volatility_percent or c2.change_percent < min_volatility_percent:
        return Signal(
            symbol=symbol,
            trend=Trend.NEUTRAL,
            bet_side=BetSide.NONE,
            bet_amount=0.0,
            candle_1=c1,
            candle_2=c2,
            reason=f"Volatilidad baja (c1={c1.change_percent:.3f}%, c2={c2.change_percent:.3f}%, umbral={min_volatility_percent}%)",
        )

    # ── Trend detection ──
    both_green = c1.is_green and c2.is_green
    both_red = c1.is_red and c2.is_red

    if both_green:
        return Signal(
            symbol=symbol,
            trend=Trend.BULLISH,
            bet_side=BetSide.YES,
            bet_amount=risk_per_trade,
            candle_1=c1,
            candle_2=c2,
            reason="Ambas velas verdes → tendencia alcista",
        )
    elif both_red:
        return Signal(
            symbol=symbol,
            trend=Trend.BEARISH,
            bet_side=BetSide.NO,
            bet_amount=risk_per_trade,
            candle_1=c1,
            candle_2=c2,
            reason="Ambas velas rojas → tendencia bajista",
        )
    else:
        # Mixed / flat
        if aggressive_mode:
            # Determine a weak direction
            net = (c1.close_price - c1.open_price) + (c2.close_price - c2.open_price)
            if net > 0:
                side = BetSide.YES
                trend = Trend.BULLISH
            elif net < 0:
                side = BetSide.NO
                trend = Trend.BEARISH
            else:
                side = BetSide.NONE
                trend = Trend.NEUTRAL

            return Signal(
                symbol=symbol,
                trend=trend,
                bet_side=side,
                bet_amount=min_risk_per_trade if side != BetSide.NONE else 0.0,
                candle_1=c1,
                candle_2=c2,
                reason=f"Tendencia mixta, modo agresivo → apuesta mínima ({side.value})",
            )
        else:
            return Signal(
                symbol=symbol,
                trend=Trend.NEUTRAL,
                bet_side=BetSide.NONE,
                bet_amount=0.0,
                candle_1=c1,
                candle_2=c2,
                reason="Tendencia mixta → sin apuesta",
            )
