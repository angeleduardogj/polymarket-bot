"""
binance_websocket.py
====================
Connects to Binance kline_5m WebSocket streams for each crypto symbol.
Falls back to REST API if a candle is missed.
Pushes closed-candle events to an asyncio.Queue for the main loop.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import aiohttp
import websockets


# ── Data types ────────────────────────────────────────────────────────

@dataclass
class Candle:
    """Represents a single closed 5-minute candle."""
    symbol: str           # e.g. "BTC"
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float
    open_time: int        # ms timestamp
    close_time: int       # ms timestamp

    @property
    def is_green(self) -> bool:
        return self.close_price > self.open_price

    @property
    def is_red(self) -> bool:
        return self.close_price < self.open_price

    @property
    def change_percent(self) -> float:
        if self.open_price == 0:
            return 0.0
        return abs(self.close_price - self.open_price) / self.open_price * 100


# ── Candle buffer ─────────────────────────────────────────────────────

class CandleBuffer:
    """Keeps the last N closed candles per symbol."""

    def __init__(self, max_size: int = 2):
        self._max = max_size
        self._buffers: Dict[str, List[Candle]] = {}

    def add(self, candle: Candle) -> None:
        buf = self._buffers.setdefault(candle.symbol, [])
        buf.append(candle)
        if len(buf) > self._max:
            buf.pop(0)

    def get(self, symbol: str) -> List[Candle]:
        return list(self._buffers.get(symbol, []))

    def has_enough(self, symbol: str) -> bool:
        return len(self._buffers.get(symbol, [])) >= self._max


# ── REST fallback ─────────────────────────────────────────────────────

BINANCE_REST_URL = "https://api.binance.com/api/v3/klines"


async def fetch_candles_rest(
    symbol: str, interval: str = "5m", limit: int = 2
) -> List[Candle]:
    """Fetch recent closed candles from Binance REST as a fallback."""
    pair = f"{symbol.upper()}USDT"
    params = {"symbol": pair, "interval": interval, "limit": limit}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BINANCE_REST_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"[WARN] Binance REST returned {resp.status} for {pair}")
                    return []
                data = await resp.json()
                candles = []
                for k in data:
                    candles.append(Candle(
                        symbol=symbol.upper(),
                        open_price=float(k[1]),
                        high_price=float(k[2]),
                        low_price=float(k[3]),
                        close_price=float(k[4]),
                        volume=float(k[5]),
                        open_time=int(k[0]),
                        close_time=int(k[6]),
                    ))
                return candles
    except Exception as e:
        print(f"[ERROR] Binance REST fallback failed for {pair}: {e}")
        return []


# ── WebSocket stream ──────────────────────────────────────────────────

async def _stream_symbol(
    symbol: str,
    queue: asyncio.Queue,
    candle_buffer: CandleBuffer,
    stop_event: asyncio.Event,
):
    """
    Connect to Binance kline_5m WebSocket for one symbol.
    Pushes Candle objects to queue when a candle closes (k.x == true).
    Reconnects with exponential backoff on failure.
    """
    pair = symbol.lower() + "usdt"
    url = f"wss://stream.binance.com:9443/ws/{pair}@kline_5m"
    backoff = 1

    while not stop_event.is_set():
        try:
            print(f"[WS-BIN] Connecting to {url} ...")
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                print(f"[WS-BIN] ✓ Connected: {symbol}")
                backoff = 1  # reset on success

                # If the buffer is empty, seed it with REST data
                if not candle_buffer.has_enough(symbol):
                    print(f"[WS-BIN] Seeding buffer for {symbol} via REST ...")
                    rest_candles = await fetch_candles_rest(symbol)
                    for c in rest_candles:
                        candle_buffer.add(c)
                    if candle_buffer.has_enough(symbol):
                        print(f"[WS-BIN] ✓ Buffer seeded for {symbol}")

                async for msg in ws:
                    if stop_event.is_set():
                        break
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue

                    k = data.get("k")
                    if k is None:
                        continue

                    # Only process when the candle is closed
                    if not k.get("x", False):
                        continue

                    candle = Candle(
                        symbol=symbol.upper(),
                        open_price=float(k["o"]),
                        close_price=float(k["c"]),
                        high_price=float(k["h"]),
                        low_price=float(k["l"]),
                        volume=float(k["v"]),
                        open_time=int(k["t"]),
                        close_time=int(k["T"]),
                    )
                    candle_buffer.add(candle)

                    # Push to main loop queue if we have 2 candles
                    if candle_buffer.has_enough(symbol):
                        await queue.put(candle_buffer.get(symbol))

        except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
            print(f"[WS-BIN] Connection lost for {symbol}: {e}")
        except Exception as e:
            print(f"[WS-BIN] Unexpected error for {symbol}: {e}")

        if not stop_event.is_set():
            wait = min(backoff, 30)
            print(f"[WS-BIN] Reconnecting {symbol} in {wait}s ...")
            await asyncio.sleep(wait)
            backoff *= 2


async def start_binance_streams(
    symbols: List[str],
    queue: asyncio.Queue,
    candle_buffer: CandleBuffer,
    stop_event: asyncio.Event,
) -> List[asyncio.Task]:
    """Start a WebSocket task for each symbol. Returns list of tasks."""
    tasks = []
    for sym in symbols:
        t = asyncio.create_task(
            _stream_symbol(sym, queue, candle_buffer, stop_event),
            name=f"binance-ws-{sym}",
        )
        tasks.append(t)
    return tasks
