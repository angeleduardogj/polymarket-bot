"""
config/settings.py
==================
Loads .env and exposes a typed Settings dataclass with validation.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv


def _bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def _float(val: str, default: float) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _int(val: str, default: int) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


@dataclass
class Settings:
    """All bot configuration in one place."""

    # --- Mode ---
    test_mode: bool = True

    # --- Risk ---
    risk_per_trade: float = 1.0
    min_risk_per_trade: float = 0.25
    max_daily_risk: float = 10.0
    max_consecutive_loss: float = 5.0

    # --- Crypto assets ---
    crypto_list: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])

    # --- Signal filters ---
    min_volatility_percent: float = 0.2
    aggressive_mode: bool = False

    # --- Fee & spread simulation ---
    min_fee_percent: float = 0.5
    max_fee_percent: float = 1.5
    min_spread_percent: float = 0.5
    max_spread_percent: float = 2.0

    # --- Binance ---
    binance_api_key: str = ""
    binance_api_secret: str = ""

    # --- Polymarket auth ---
    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""
    polymarket_signature_type: int = 0

    # --- Polymarket endpoints ---
    polymarket_gamma_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_base_url: str = "https://clob.polymarket.com"
    polymarket_chain_id: int = 137
    polymarket_wss_market: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_wss_user: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    # --- Logging ---
    log_dir: str = "logs"

    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Ensure configuration is sane. Exits if real mode is misconfigured."""
        if self.risk_per_trade <= 0:
            sys.exit("[ERROR] RISK_PER_TRADE must be > 0.")
        if self.max_daily_risk < self.risk_per_trade:
            sys.exit("[ERROR] MAX_DAILY_RISK must be >= RISK_PER_TRADE.")
        if not self.crypto_list:
            sys.exit("[ERROR] CRYPTO_LIST cannot be empty.")
        if not self.test_mode:
            if not self.polymarket_private_key:
                sys.exit(
                    "[ERROR] TEST_MODE=false but POLYMARKET_PRIVATE_KEY is not set. "
                    "Set it in .env or switch to TEST_MODE=true."
                )
            print("[INFO] *** REAL TRADING MODE *** — orders will be sent to Polymarket.")
        else:
            print("[INFO] Simulation mode — no real orders will be placed.")


def load_settings(env_path: str = ".env") -> Settings:
    """Load settings from .env file and return a Settings instance."""
    load_dotenv(env_path)

    crypto_raw = os.getenv("CRYPTO_LIST", "BTC,ETH,SOL,XRP")
    crypto_list = [c.strip().upper() for c in crypto_raw.split(",") if c.strip()]

    s = Settings(
        test_mode=_bool(os.getenv("TEST_MODE", "true")),
        risk_per_trade=_float(os.getenv("RISK_PER_TRADE", ""), 1.0),
        min_risk_per_trade=_float(os.getenv("MIN_RISK_PER_TRADE", ""), 0.25),
        max_daily_risk=_float(os.getenv("MAX_DAILY_RISK", ""), 10.0),
        max_consecutive_loss=_float(os.getenv("MAX_CONSECUTIVE_LOSS", ""), 5.0),
        crypto_list=crypto_list,
        min_volatility_percent=_float(os.getenv("MIN_VOLATILITY_PERCENT", ""), 0.2),
        aggressive_mode=_bool(os.getenv("AGGRESSIVE_MODE", "false")),
        min_fee_percent=_float(os.getenv("MIN_FEE_PERCENT", ""), 0.5),
        max_fee_percent=_float(os.getenv("MAX_FEE_PERCENT", ""), 1.5),
        min_spread_percent=_float(os.getenv("MIN_SPREAD_PERCENT", ""), 0.5),
        max_spread_percent=_float(os.getenv("MAX_SPREAD_PERCENT", ""), 2.0),
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        polymarket_private_key=os.getenv("POLYMARKET_PRIVATE_KEY", ""),
        polymarket_funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS", ""),
        polymarket_signature_type=_int(os.getenv("POLYMARKET_SIGNATURE_TYPE", ""), 0),
        polymarket_gamma_base_url=os.getenv(
            "POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com"
        ),
        polymarket_clob_base_url=os.getenv(
            "POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com"
        ),
        polymarket_chain_id=_int(os.getenv("POLYMARKET_CHAIN_ID", ""), 137),
        polymarket_wss_market=os.getenv(
            "POLYMARKET_WSS_MARKET",
            "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        ),
        polymarket_wss_user=os.getenv(
            "POLYMARKET_WSS_USER",
            "wss://ws-subscriptions-clob.polymarket.com/ws/user",
        ),
        log_dir=os.getenv("LOG_DIR", "logs"),
    )

    s.validate()
    return s
