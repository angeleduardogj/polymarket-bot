"""
polymarket_rest.py
==================
REST integration with Polymarket:
  - Gamma API: discover active 5-minute crypto markets (public, no auth)
  - CLOB API: place orders, get trades, get prices (auth required for trading)

Uses `py-clob-client` for authenticated CLOB operations in real mode.
Uses `requests` for public Gamma API calls.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests


# ── Data types ────────────────────────────────────────────────────────

@dataclass
class PolymarketMarket:
    """Represents a discovered 5-minute prediction market."""
    condition_id: str
    question: str
    slug: str
    token_id_yes: str
    token_id_no: str
    end_date: str
    market_url: str
    active: bool = True
    outcomes: List[str] = field(default_factory=lambda: ["Yes", "No"])


# ── Gamma API (public, no auth) ──────────────────────────────────────

class GammaClient:
    """Query Polymarket Gamma API for market discovery."""

    def __init__(self, base_url: str = "https://gamma-api.polymarket.com"):
        self.base_url = base_url
        self._cache: Dict[str, tuple] = {}  # symbol -> (market, timestamp)
        self._cache_ttl = 60  # seconds

    def find_5m_market(self, symbol: str) -> Optional[PolymarketMarket]:
        """
        Search for an active 5-minute prediction market for the given crypto.

        Args:
            symbol: e.g. "BTC", "ETH"

        Returns:
            A PolymarketMarket if found, else None.
        """
        # Check cache
        cached = self._cache.get(symbol)
        if cached:
            market, ts = cached
            if time.time() - ts < self._cache_ttl:
                return market

        try:
            # Search for 5-minute crypto markets via the events endpoint
            url = f"{self.base_url}/events"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 50,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            events = resp.json()

            # Search through events for matching 5-minute market
            for event in events:
                title = (event.get("title", "") or "").lower()
                # Also search individual markets within the event
                markets = event.get("markets", [])
                for m in markets:
                    question = (m.get("question", "") or "").lower()
                    combined = title + " " + question

                    # Look for the crypto symbol AND a 5-minute indicator
                    sym_lower = symbol.lower()
                    full_name = {
                        "btc": "bitcoin",
                        "eth": "ethereum",
                        "sol": "solana",
                        "xrp": "xrp",
                    }.get(sym_lower, sym_lower)

                    has_symbol = (sym_lower in combined) or (full_name in combined)
                    has_5min = any(kw in combined for kw in [
                        "5 min", "5min", "five min", "5-min", "5 minute",
                    ])

                    if has_symbol and has_5min and m.get("active", False):
                        # Extract token IDs from clobTokenIds
                        clob_ids = m.get("clobTokenIds", [])
                        outcomes = m.get("outcomes", ["Yes", "No"])
                        token_yes = clob_ids[0] if len(clob_ids) > 0 else ""
                        token_no = clob_ids[1] if len(clob_ids) > 1 else ""

                        slug = m.get("slug", event.get("slug", ""))
                        market = PolymarketMarket(
                            condition_id=m.get("conditionId", ""),
                            question=m.get("question", event.get("title", "")),
                            slug=slug,
                            token_id_yes=token_yes,
                            token_id_no=token_no,
                            end_date=m.get("endDate", ""),
                            market_url=f"https://polymarket.com/event/{slug}" if slug else "",
                            active=True,
                            outcomes=outcomes,
                        )
                        self._cache[symbol] = (market, time.time())
                        return market

            # Not found
            self._cache[symbol] = (None, time.time())  # type: ignore
            return None

        except requests.RequestException as e:
            print(f"[GAMMA] Error fetching markets for {symbol}: {e}")
            return None

    def find_all_5m_markets(self, symbols: List[str]) -> Dict[str, Optional[PolymarketMarket]]:
        """Find 5-minute markets for all symbols."""
        result: Dict[str, Optional[PolymarketMarket]] = {}
        for sym in symbols:
            result[sym] = self.find_5m_market(sym)
            if result[sym]:
                print(f"[GAMMA] ✓ Found market for {sym}: {result[sym].question}")
            else:
                print(f"[GAMMA] ✗ No 5-minute market found for {sym}")
        return result


# ── CLOB Client wrapper (real mode only) ─────────────────────────────

class ClobClientWrapper:
    """
    Wrapper around py-clob-client for authenticated operations.
    Only initialized in real mode (TEST_MODE=false).
    """

    def __init__(
        self,
        host: str,
        private_key: str,
        chain_id: int = 137,
        signature_type: int = 0,
        funder: str = "",
    ):
        self._initialized = False
        self._client = None
        self._host = host
        self._private_key = private_key
        self._chain_id = chain_id
        self._signature_type = signature_type
        self._funder = funder

    def initialize(self) -> bool:
        """Initialize the CLOB client with authentication."""
        try:
            from py_clob_client.client import ClobClient

            kwargs = {
                "host": self._host,
                "key": self._private_key,
                "chain_id": self._chain_id,
                "signature_type": self._signature_type,
            }
            if self._funder:
                kwargs["funder"] = self._funder

            self._client = ClobClient(**kwargs)
            self._client.set_api_creds(self._client.create_or_derive_api_creds())
            self._initialized = True
            print("[CLOB] ✓ Authenticated with Polymarket CLOB")
            return True
        except Exception as e:
            print(f"[CLOB] ✗ Failed to initialize CLOB client: {e}")
            return False

    def place_market_order(
        self,
        token_id: str,
        amount: float,
        side: str,  # "BUY" or "SELL"
    ) -> Optional[dict]:
        """
        Place a Fill-Or-Kill market order.
        Returns the order response dict or None on failure.
        """
        if not self._initialized or self._client is None:
            print("[CLOB] Client not initialized. Cannot place order.")
            return None

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL
            mo = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=order_side,
                order_type=OrderType.FOK,
            )
            signed_order = self._client.create_market_order(mo)
            resp = self._client.post_order(signed_order, OrderType.FOK)
            print(f"[CLOB] ✓ Order placed: {side} ${amount:.2f} on {token_id[:16]}...")
            return resp
        except Exception as e:
            print(f"[CLOB] ✗ Order failed: {e}")
            return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get the current midpoint price for a token."""
        if not self._initialized or self._client is None:
            return None
        try:
            mid = self._client.get_midpoint(token_id)
            return float(mid)
        except Exception as e:
            print(f"[CLOB] Error getting midpoint: {e}")
            return None

    def get_last_trade_price(self, token_id: str) -> Optional[float]:
        """Get the last trade price for a token."""
        if not self._initialized or self._client is None:
            return None
        try:
            result = self._client.get_last_trade_price(token_id)
            return float(result.get("price", 0)) if result else None
        except Exception as e:
            print(f"[CLOB] Error getting last trade price: {e}")
            return None

    def get_trades(self) -> List[dict]:
        """Get recent trades for the authenticated user."""
        if not self._initialized or self._client is None:
            return []
        try:
            return self._client.get_trades() or []
        except Exception as e:
            print(f"[CLOB] Error getting trades: {e}")
            return []
