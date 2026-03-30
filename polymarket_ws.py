"""
polymarket_ws.py
================
WebSocket integration with Polymarket:
  - Market channel (no auth): subscribe to price updates for active tokens
  - User channel (auth, real mode): receive trade confirmations

Both channels implement PING/PONG every 10 seconds and auto-reconnect.
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Optional, Set

import websockets


class PolymarketMarketWS:
    """
    Connect to the Polymarket Market WebSocket channel (no auth).
    Subscribes to price_change and last_trade_price for given asset IDs.
    """

    def __init__(
        self,
        url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    ):
        self.url = url
        self._subscribed_assets: Set[str] = set()
        self._latest_prices: Dict[str, float] = {}
        self._ws = None
        self._connected = False
        self._on_price_update: Optional[Callable] = None

    def set_price_callback(self, callback: Callable) -> None:
        """Set a callback function(asset_id, price) for price updates."""
        self._on_price_update = callback

    async def subscribe(self, asset_ids: List[str]) -> None:
        """Add asset IDs to subscription list."""
        for aid in asset_ids:
            if aid:
                self._subscribed_assets.add(aid)

    def get_price(self, asset_id: str) -> Optional[float]:
        """Get the latest cached price for an asset."""
        return self._latest_prices.get(asset_id)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Main connection loop with auto-reconnect."""
        # No assets to track → skip connection entirely to avoid spam
        if not self._subscribed_assets:
            print("[WS-MKT] No hay assets suscritos — canal de mercado inactivo")
            # Wait until stop so we don't exit the task
            await stop_event.wait()
            return

        backoff = 5

        while not stop_event.is_set():
            try:
                print(f"[WS-MKT] Connecting to {self.url} ...")
                async with websockets.connect(
                    self.url, ping_interval=None  # We handle ping manually
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = 5
                    print(f"[WS-MKT] ✓ Connected")

                    # Subscribe to assets
                    if self._subscribed_assets:
                        sub_msg = {
                            "type": "subscribe",
                            "channel": "price",
                            "assets_ids": list(self._subscribed_assets),
                        }
                        await ws.send(json.dumps(sub_msg))
                        print(f"[WS-MKT] Subscribed to {len(self._subscribed_assets)} assets")

                    # Start ping task
                    ping_task = asyncio.create_task(self._ping_loop(ws, stop_event))

                    try:
                        async for msg in ws:
                            if stop_event.is_set():
                                break
                            self._handle_message(msg)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                print(f"[WS-MKT] Connection lost: {e}")
            except Exception as e:
                print(f"[WS-MKT] Error: {e}")
            finally:
                self._connected = False
                self._ws = None

            if not stop_event.is_set():
                wait = min(backoff, 30)
                print(f"[WS-MKT] Reconnecting in {wait}s ...")
                await asyncio.sleep(wait)
                backoff *= 2

    async def _ping_loop(self, ws, stop_event: asyncio.Event) -> None:
        """Send PING every 10 seconds."""
        while not stop_event.is_set():
            try:
                await asyncio.sleep(10)
                if self._connected:
                    await ws.send("PING")
            except (websockets.ConnectionClosed, asyncio.CancelledError):
                break

    def _handle_message(self, raw: str) -> None:
        """Process incoming WebSocket messages."""
        if raw == "PONG":
            return  # Expected response to our PING

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Polymarket sometimes sends arrays — we only handle dicts
        if not isinstance(data, dict):
            return

        # Handle price update messages
        msg_type = data.get("type", "")
        if msg_type in ("price_change", "last_trade_price"):
            asset_id = data.get("asset_id", "")
            price = data.get("price")
            if asset_id and price is not None:
                try:
                    self._latest_prices[asset_id] = float(price)
                    if self._on_price_update:
                        self._on_price_update(asset_id, float(price))
                except (ValueError, TypeError):
                    pass


class PolymarketUserWS:
    """
    Connect to the Polymarket User WebSocket channel (requires auth).
    Receives trade confirmations and order status updates.
    Used only in real mode.
    """

    def __init__(
        self,
        url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user",
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
    ):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self._ws = None
        self._connected = False
        self._on_trade: Optional[Callable] = None
        self._on_order: Optional[Callable] = None

    def set_trade_callback(self, callback: Callable) -> None:
        """Set callback for trade events: callback(trade_data)."""
        self._on_trade = callback

    def set_order_callback(self, callback: Callable) -> None:
        """Set callback for order events: callback(order_data)."""
        self._on_order = callback

    async def run(self, stop_event: asyncio.Event) -> None:
        """Main connection loop with auto-reconnect."""
        if not self.api_key:
            print("[WS-USR] No API key configured — user channel disabled")
            return

        backoff = 1

        while not stop_event.is_set():
            try:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                print(f"[WS-USR] Connecting to {self.url} ...")
                async with websockets.connect(
                    self.url,
                    additional_headers=headers,
                    ping_interval=None,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = 1
                    print("[WS-USR] ✓ Connected (authenticated)")

                    # Subscribe to user events
                    sub_msg = {
                        "type": "subscribe",
                        "channel": "user",
                        "auth": {
                            "apiKey": self.api_key,
                            "secret": self.api_secret,
                            "passphrase": self.passphrase,
                        },
                    }
                    await ws.send(json.dumps(sub_msg))

                    # Start ping task
                    ping_task = asyncio.create_task(self._ping_loop(ws, stop_event))

                    try:
                        async for msg in ws:
                            if stop_event.is_set():
                                break
                            self._handle_message(msg)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                print(f"[WS-USR] Connection lost: {e}")
            except Exception as e:
                print(f"[WS-USR] Error: {e}")
            finally:
                self._connected = False
                self._ws = None

            if not stop_event.is_set():
                wait = min(backoff, 30)
                print(f"[WS-USR] Reconnecting in {wait}s ...")
                await asyncio.sleep(wait)
                backoff *= 2

    async def _ping_loop(self, ws, stop_event: asyncio.Event) -> None:
        """Send PING every 10 seconds."""
        while not stop_event.is_set():
            try:
                await asyncio.sleep(10)
                if self._connected:
                    await ws.send("PING")
            except (websockets.ConnectionClosed, asyncio.CancelledError):
                break

    def _handle_message(self, raw: str) -> None:
        """Process incoming messages from the user channel."""
        if raw == "PONG":
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        event_type = data.get("type", "")

        if event_type in ("trade", "MATCHED", "CONFIRMED"):
            print(f"[WS-USR] Trade event: {event_type}")
            if self._on_trade:
                self._on_trade(data)

        elif event_type in ("order", "ORDER_PLACED", "ORDER_CANCELLED"):
            print(f"[WS-USR] Order event: {event_type}")
            if self._on_order:
                self._on_order(data)
