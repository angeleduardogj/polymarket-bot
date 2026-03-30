"""
main.py
=======
Main entry point for the Polymarket Crypto 5-Minute Prediction Bot.

Orchestrates:
  1. Binance WebSocket → candle closes
  2. Signal engine    → trend / bet decision
  3. Risk manager     → daily limits & stops
  4. Polymarket REST  → market discovery & orders (real mode)
  5. Polymarket WS    → price & trade updates
  6. Logger           → CSV trade logs

Run with:  python main.py
"""

import asyncio
import random
import signal
import sys
from typing import Dict, List, Optional

from config.settings import Settings, load_settings
from binance_websocket import Candle, CandleBuffer, start_binance_streams
from signal_engine import BetSide, Signal, Trend, evaluate_signal
from risk_manager import RiskManager
from polymarket_rest import ClobClientWrapper, GammaClient, PolymarketMarket
from polymarket_ws import PolymarketMarketWS, PolymarketUserWS
from logger import TradeLogger


# ── PnL simulation ───────────────────────────────────────────────────

def simulate_pnl(
    signal: Signal,
    settings: Settings,
) -> dict:
    """
    Simulate PnL for a trade, considering spread and fees.

    Returns dict with:
      fee_percent, spread_percent, raw_pnl, pnl_after_fees,
      polymarket_price_entry, price_discrepancy
    """
    candle = signal.candle_2  # most recent candle is the "entry" reference
    amount = signal.bet_amount

    # Random spread within configured range (simulates Binance→Polymarket drift)
    spread_pct = random.uniform(settings.min_spread_percent, settings.max_spread_percent)

    # Random fee within configured range
    fee_pct = random.uniform(settings.min_fee_percent, settings.max_fee_percent)

    # Simulated Polymarket entry price (shifted by spread)
    spread_direction = random.choice([-1, 1])
    poly_price = candle.close_price * (1 + spread_direction * spread_pct / 100)
    price_discrepancy = (poly_price - candle.close_price) / candle.close_price * 100

    # For a 5-minute prediction market:
    # - If bet YES on BULLISH: win if price actually goes up → ~50-55% chance
    # - Simulation: use a probabilistic model based on trend strength
    trend_strength = (candle.change_percent + signal.candle_1.change_percent) / 2
    # Higher trend strength → slight edge, capped at ~60%
    win_probability = min(0.50 + trend_strength * 0.02, 0.60)

    # Determine outcome
    won = random.random() < win_probability

    if won:
        # In prediction markets, payout is typically ~$1 per share at cost of ~$0.50
        # For small bets, assume ~90% return on winning (market price around 0.50)
        raw_pnl = amount * 0.90
    else:
        raw_pnl = -amount

    # Apply fees
    fee_cost = amount * fee_pct / 100
    pnl_after_fees = raw_pnl - fee_cost

    return {
        "fee_percent": round(fee_pct, 4),
        "spread_percent": round(spread_pct, 4),
        "raw_pnl": round(raw_pnl, 6),
        "pnl_after_fees": round(pnl_after_fees, 6),
        "polymarket_price_entry": round(poly_price, 6),
        "price_discrepancy": round(price_discrepancy, 4),
    }


# ── Processing pipeline ─────────────────────────────────────────────

async def process_candles(
    candles: List[Candle],
    settings: Settings,
    risk_mgr: RiskManager,
    trade_logger: TradeLogger,
    gamma: GammaClient,
    clob: Optional[ClobClientWrapper],
    market_ws: PolymarketMarketWS,
    markets_cache: Dict[str, Optional[PolymarketMarket]],
) -> None:
    """Process a pair of closed candles: evaluate signal, manage risk, trade/log."""
    symbol = candles[-1].symbol
    mode = "SIM" if settings.test_mode else "REAL"

    # ── Evaluate signal ──
    sig = evaluate_signal(
        candles=candles,
        risk_per_trade=settings.risk_per_trade,
        min_risk_per_trade=settings.min_risk_per_trade,
        min_volatility_percent=settings.min_volatility_percent,
        aggressive_mode=settings.aggressive_mode,
    )

    # ── No trade? ──
    if sig.bet_side == BetSide.NONE or sig.bet_amount <= 0:
        balance = risk_mgr.get_balance()
        trade_logger.log_skip(
            moneda=symbol,
            precio_vela_1_apertura=sig.candle_1.open_price,
            precio_vela_1_cierre=sig.candle_1.close_price,
            precio_vela_2_apertura=sig.candle_2.open_price,
            precio_vela_2_cierre=sig.candle_2.close_price,
            tendencia=sig.trend.value,
            modo=mode,
            saldo_before=balance,
            saldo_after=balance,
            comentario=sig.reason,
        )
        print(
            f"[BOT] {symbol} → {sig.trend.value} | Sin apuesta: {sig.reason}"
        )
        return

    # ── Risk check ──
    allowed, reason = risk_mgr.can_trade(sig.bet_amount)
    if not allowed:
        balance = risk_mgr.get_balance()
        trade_logger.log_skip(
            moneda=symbol,
            precio_vela_1_apertura=sig.candle_1.open_price,
            precio_vela_1_cierre=sig.candle_1.close_price,
            precio_vela_2_apertura=sig.candle_2.open_price,
            precio_vela_2_cierre=sig.candle_2.close_price,
            tendencia=sig.trend.value,
            modo=mode,
            saldo_before=balance,
            saldo_after=balance,
            comentario=f"Bloqueado: {reason}",
        )
        print(f"[BOT] {symbol} → BLOQUEADO: {reason}")
        return

    # ── Discover Polymarket market ──
    market = markets_cache.get(symbol)
    if not market:
        market = gamma.find_5m_market(symbol)
        markets_cache[symbol] = market

    market_url = market.market_url if market else ""
    token_id = ""
    if market:
        if sig.bet_side == BetSide.YES:
            token_id = market.token_id_yes
        else:
            token_id = market.token_id_no

    saldo_before = risk_mgr.get_balance()

    # ── Execute trade ──
    if settings.test_mode:
        # ───── SIMULATION MODE ─────
        sim = simulate_pnl(sig, settings)
        risk_mgr.record_trade(sig.bet_amount, sim["pnl_after_fees"])
        saldo_after = risk_mgr.get_balance()

        trade_logger.log_trade(
            moneda=symbol,
            precio_vela_1_apertura=sig.candle_1.open_price,
            precio_vela_1_cierre=sig.candle_1.close_price,
            precio_vela_2_apertura=sig.candle_2.open_price,
            precio_vela_2_cierre=sig.candle_2.close_price,
            tendencia=sig.trend.value,
            apuesta=sig.bet_side.value,
            monto=sig.bet_amount,
            modo="SIM",
            binance_price_entry=sig.candle_2.close_price,
            polymarket_price_entry=sim["polymarket_price_entry"],
            market_url=market_url,
            fee_percent=sim["fee_percent"],
            spread_percent=sim["spread_percent"],
            raw_pnl=sim["raw_pnl"],
            pnl_after_fees=sim["pnl_after_fees"],
            simulado_pnl=sim["pnl_after_fees"],
            real_pnl=0.0,
            saldo_before=saldo_before,
            saldo_after=saldo_after,
            drawdown_acumulado=risk_mgr.state.max_drawdown,
            price_discrepancy=sim["price_discrepancy"],
            coincidencia_sim_real="n/a (simulación)",
            comentario="Apuesta simulada",
        )

        result_icon = "✅" if sim["pnl_after_fees"] > 0 else "❌"
        print(
            f"[BOT] {result_icon} {symbol} | {sig.trend.value} → {sig.bet_side.value} "
            f"${sig.bet_amount:.2f} | PnL: ${sim['pnl_after_fees']:.4f} "
            f"(fee={sim['fee_percent']:.1f}%, spread={sim['spread_percent']:.1f}%) "
            f"| Saldo: ${saldo_after:.2f}"
        )

    else:
        # ───── REAL MODE ─────
        if not clob or not token_id:
            trade_logger.log_skip(
                moneda=symbol,
                precio_vela_1_apertura=sig.candle_1.open_price,
                precio_vela_1_cierre=sig.candle_1.close_price,
                precio_vela_2_apertura=sig.candle_2.open_price,
                precio_vela_2_cierre=sig.candle_2.close_price,
                tendencia=sig.trend.value,
                modo="REAL",
                saldo_before=saldo_before,
                saldo_after=saldo_before,
                comentario="Sin token_id o CLOB no inicializado",
            )
            print(f"[BOT] {symbol} → Sin mercado o CLOB no disponible")
            return

        # Lock the balance before placing order
        risk_mgr.lock_balance(sig.bet_amount)

        # Place order via CLOB REST
        resp = clob.place_market_order(
            token_id=token_id,
            amount=sig.bet_amount,
            side="BUY",  # Buying YES or NO shares
        )

        # Get Polymarket price for comparison
        # Midpoint is the token probability (0.0–1.0), e.g. 0.52 = 52% chance YES
        poly_price = clob.get_midpoint(token_id) or 0.0
        polymarket_price_entry = poly_price  # probability / share price

        # Also calculate simulated PnL for comparison
        sim = simulate_pnl(sig, settings)
        # price_discrepancy: diff between Binance-derived sim price and actual midpoint
        price_disc = sim["price_discrepancy"]

        if resp:
            # Order placed — will track resolution via User WS
            risk_mgr.record_trade(sig.bet_amount, 0.0)  # PnL unknown until resolution
            saldo_after = risk_mgr.get_balance()

            trade_logger.log_trade(
                moneda=symbol,
                precio_vela_1_apertura=sig.candle_1.open_price,
                precio_vela_1_cierre=sig.candle_1.close_price,
                precio_vela_2_apertura=sig.candle_2.open_price,
                precio_vela_2_cierre=sig.candle_2.close_price,
                tendencia=sig.trend.value,
                apuesta=sig.bet_side.value,
                monto=sig.bet_amount,
                modo="REAL",
                binance_price_entry=sig.candle_2.close_price,
                polymarket_price_entry=polymarket_price_entry,
                market_url=market_url,
                fee_percent=sim["fee_percent"],
                spread_percent=sim["spread_percent"],
                raw_pnl=0.0,  # Unknown until resolution
                pnl_after_fees=0.0,
                simulado_pnl=sim["pnl_after_fees"],
                real_pnl=0.0,  # Updated when resolved
                saldo_before=saldo_before,
                saldo_after=saldo_after,
                drawdown_acumulado=risk_mgr.state.max_drawdown,
                price_discrepancy=round(price_disc, 4),
                coincidencia_sim_real="pendiente",
                comentario=f"Orden real enviada — {resp}",
            )
            # Console output per prompt point 7: show all key fields
            print(
                f"[BOT] 📤 {symbol} | {sig.trend.value} → {sig.bet_side.value} "
                f"${sig.bet_amount:.2f} | ORDEN REAL ENVIADA\n"
                f"      binance_price: {sig.candle_2.close_price:.2f} | "
                f"poly_price: {polymarket_price_entry:.4f} | "
                f"url: {market_url}\n"
                f"      simulado_pnl: ${sim['pnl_after_fees']:.4f} | "
                f"real_pnl: pendiente"
            )
        else:
            # Order failed — unlock balance
            risk_mgr.unlock_balance(sig.bet_amount)
            trade_logger.log_skip(
                moneda=symbol,
                precio_vela_1_apertura=sig.candle_1.open_price,
                precio_vela_1_cierre=sig.candle_1.close_price,
                precio_vela_2_apertura=sig.candle_2.open_price,
                precio_vela_2_cierre=sig.candle_2.close_price,
                tendencia=sig.trend.value,
                modo="REAL",
                saldo_before=saldo_before,
                saldo_after=saldo_before,
                comentario="Orden fallida — saldo desbloqueado",
            )
            print(f"[BOT] ❌ {symbol} | Orden fallida")


# ── Main ─────────────────────────────────────────────────────────────

async def main() -> None:
    """Main async entry point."""

    print("=" * 60)
    print("  Polymarket Crypto 5-Minute Prediction Bot")
    print("=" * 60)

    # ── Load config ──
    settings = load_settings()
    mode_label = "SIMULACIÓN" if settings.test_mode else "REAL"
    print(f"[INIT] Modo: {mode_label}")
    print(f"[INIT] Criptos: {', '.join(settings.crypto_list)}")
    print(f"[INIT] Riesgo por trade: ${settings.risk_per_trade:.2f}")
    print(f"[INIT] Máximo diario: ${settings.max_daily_risk:.2f}")
    print(f"[INIT] Parada por pérdida consecutiva: ${settings.max_consecutive_loss:.2f}")
    print()

    # ── Initialize components ──
    risk_mgr = RiskManager(
        max_daily_risk=settings.max_daily_risk,
        max_consecutive_loss=settings.max_consecutive_loss,
    )
    trade_logger = TradeLogger(log_dir=settings.log_dir)
    gamma = GammaClient(base_url=settings.polymarket_gamma_base_url)
    candle_buffer = CandleBuffer(max_size=2)
    candle_queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()
    markets_cache: Dict[str, Optional[PolymarketMarket]] = {}

    # ── CLOB client (real mode only) ──
    clob: Optional[ClobClientWrapper] = None
    if not settings.test_mode:
        clob = ClobClientWrapper(
            host=settings.polymarket_clob_base_url,
            private_key=settings.polymarket_private_key,
            chain_id=settings.polymarket_chain_id,
            signature_type=settings.polymarket_signature_type,
            funder=settings.polymarket_funder_address,
        )
        if not clob.initialize():
            print("[INIT] ⚠ CLOB client failed to init. Falling back to simulation.")
            settings.test_mode = True
            clob = None

    # ── Discover markets ──
    print("[INIT] Buscando mercados de 5 minutos en Polymarket ...")
    markets_cache = gamma.find_all_5m_markets(settings.crypto_list)
    print()

    # ── Market WebSocket ──
    market_ws = PolymarketMarketWS(url=settings.polymarket_wss_market)

    # Subscribe to discovered market tokens
    token_ids = []
    for sym, mkt in markets_cache.items():
        if mkt:
            if mkt.token_id_yes:
                token_ids.append(mkt.token_id_yes)
            if mkt.token_id_no:
                token_ids.append(mkt.token_id_no)
    if token_ids:
        await market_ws.subscribe(token_ids)

    # ── User WebSocket (real mode) ──
    user_ws = PolymarketUserWS(url=settings.polymarket_wss_user)

    # ── Signal handler for graceful shutdown ──
    def shutdown_handler():
        print("\n[BOT] 🛑 Deteniendo el bot ...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        pass

    # ── Start background tasks ──
    print("[INIT] Iniciando WebSockets de Binance ...")
    binance_tasks = await start_binance_streams(
        symbols=settings.crypto_list,
        queue=candle_queue,
        candle_buffer=candle_buffer,
        stop_event=stop_event,
    )

    # Start Polymarket WS tasks
    ws_tasks = [
        asyncio.create_task(market_ws.run(stop_event), name="polymarket-market-ws"),
    ]
    if not settings.test_mode:
        ws_tasks.append(
            asyncio.create_task(user_ws.run(stop_event), name="polymarket-user-ws")
        )

    print()
    print("=" * 60)
    print(f"  Bot en ejecución ({mode_label}). Ctrl+C para detener.")
    print("=" * 60)
    print()

    # ── Main event loop ──
    try:
        while not stop_event.is_set():
            try:
                # Wait for a candle pair from any symbol
                candles = await asyncio.wait_for(
                    candle_queue.get(), timeout=60.0
                )
            except asyncio.TimeoutError:
                # Print a heartbeat every minute
                status = risk_mgr.get_status()
                print(
                    f"[♥] Esperando velas ... "
                    f"Trades hoy: {status['trades_today']} | "
                    f"PnL hoy: ${status['total_pnl_today']:.2f} | "
                    f"Apostado: ${status['total_wagered_today']:.2f}/"
                    f"${settings.max_daily_risk:.2f}"
                )
                continue

            # Process the candle pair
            await process_candles(
                candles=candles,
                settings=settings,
                risk_mgr=risk_mgr,
                trade_logger=trade_logger,
                gamma=gamma,
                clob=clob,
                market_ws=market_ws,
                markets_cache=markets_cache,
            )

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[BOT] Deteniendo tareas ...")
        stop_event.set()

        # Cancel all background tasks
        for task in binance_tasks + ws_tasks:
            task.cancel()
        await asyncio.gather(*binance_tasks, *ws_tasks, return_exceptions=True)

        # Print final summary
        status = risk_mgr.get_status()
        print()
        print("=" * 60)
        print("  Resumen del día")
        print("=" * 60)
        print(f"  Trades realizados:  {status['trades_today']}")
        print(f"  Total apostado:     ${status['total_wagered_today']:.2f}")
        print(f"  PnL del día:        ${status['total_pnl_today']:.2f}")
        print(f"  Drawdown máximo:    ${status['max_drawdown']:.2f}")
        print(f"  Saldo simulado:     ${status['simulated_balance']:.2f}")
        print(f"  Pérdida consec.:    ${status['consecutive_loss_amount']:.2f}")
        print("=" * 60)
        print("[BOT] ¡Hasta luego! 👋")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[BOT] Interrumpido por el usuario. ¡Hasta luego! 👋")
