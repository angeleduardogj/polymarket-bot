# 🤖 Polymarket Crypto 5-Min Prediction Bot

Bot conservador en Python que apuesta en mercados de predicción de Polymarket (BTC, ETH, SOL, XRP en 5 minutos) usando datos de precios de Binance en tiempo real.

## ⚡ Inicio rápido

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Configurar entorno

```bash
cp .env.example .env
# Edita .env con tus preferencias (el modo simulación funciona sin claves)
```

### 3. Ejecutar en modo simulación

```bash
python main.py
```

El bot se conecta a Binance vía WebSocket, recibe velas de 5 minutos, analiza tendencia y simula apuestas con PnL realista (incluyendo spread y fees).

---

## 🏗️ Estructura del proyecto

```
├── .env.example             # Template de configuración
├── requirements.txt         # Dependencias Python
├── config/
│   ├── __init__.py
│   └── settings.py          # Carga y validación de .env
├── binance_websocket.py     # WebSocket Binance kline_5m + REST fallback
├── signal_engine.py         # Detección de tendencia (2 velas) + filtro de volatilidad
├── risk_manager.py          # Límites diarios, parada por pérdida consecutiva
├── polymarket_rest.py       # Gamma API (descubrimiento) + CLOB (órdenes)
├── polymarket_ws.py         # WebSocket de mercado y usuario de Polymarket
├── logger.py                # Logs CSV estructurados por día
├── main.py                  # Loop principal async
└── logs/                    # CSVs diarios (auto-creado)
```

---

## 🔧 Variables del `.env`

| Variable | Default | Descripción |
|---|---|---|
| `TEST_MODE` | `true` | `true` = simulación, `false` = trading real |
| `RISK_PER_TRADE` | `1.0` | USD por apuesta (tendencia clara) |
| `MIN_RISK_PER_TRADE` | `0.25` | USD por apuesta (tendencia débil) |
| `MAX_DAILY_RISK` | `10.0` | Máximo USD apostados por día |
| `MAX_CONSECUTIVE_LOSS` | `5.0` | Parada si pérdida consecutiva ≥ este valor |
| `CRYPTO_LIST` | `BTC,ETH,SOL,XRP` | Criptos a monitorear |
| `MIN_VOLATILITY_PERCENT` | `0.2` | Ignorar velas con < este % de cambio |
| `AGGRESSIVE_MODE` | `false` | Si `true`, apuesta mínima en señales neutras |
| `MIN_FEE_PERCENT` | `0.5` | Fee mínimo simulado de Polymarket (%) |
| `MAX_FEE_PERCENT` | `1.5` | Fee máximo simulado de Polymarket (%) |
| `MIN_SPREAD_PERCENT` | `0.5` | Spread mínimo Binance→Polymarket (%) |
| `MAX_SPREAD_PERCENT` | `2.0` | Spread máximo Binance→Polymarket (%) |

---

## 📊 Analizar los logs

Los logs se guardan en `logs/trades_YYYY_MM_DD.csv` con 25 columnas. Para analizarlos:

### Con pandas (Python)

```python
import pandas as pd

df = pd.read_csv("logs/trades_2026_03_29.csv")

# PnL del día
print(f"PnL total: ${df['pnl_after_fees'].sum():.2f}")

# PnL por moneda
print(df.groupby('moneda')['pnl_after_fees'].sum())

# Win rate
trades = df[df['apuesta'] != 'N/A']
wins = trades[trades['pnl_after_fees'] > 0]
print(f"Win rate: {len(wins)/len(trades)*100:.1f}%")

# Ajuste recomendado de fees/spread
print(f"Fee promedio: {df['fee_percent'].mean():.2f}%")
print(f"Spread promedio: {df['spread_percent'].mean():.2f}%")
```

### Con Excel/Google Sheets

1. Abre el archivo CSV directamente
2. Ordena por `pnl_after_fees` para ver las mejores y peores operaciones
3. Filtra por `moneda` para comparar rendimiento por cripto
4. Compara `simulado_pnl` vs `real_pnl` para calibrar la simulación

---

## 🔄 Cambiar a modo real

1. Edita `.env`:
   ```
   TEST_MODE=false
   POLYMARKET_PRIVATE_KEY=tu_clave_privada_polygon
   POLYMARKET_FUNDER_ADDRESS=tu_dirección_de_fondos
   ```
2. Asegúrate de tener USDC en tu wallet de Polygon
3. Ejecuta `python main.py`
4. Compara `simulado_pnl` vs `real_pnl` en los logs para calibrar

> ⚠️ **Importante**: Usa simulación extensivamente antes de arriesgar capital real. Los mercados de predicción conllevan riesgo financiero.

---

## 🛡️ Gestión de riesgo

- **Límite diario**: El bot para cuando `total_apostado >= MAX_DAILY_RISK`
- **Parada por pérdida**: Se detiene si las pérdidas consecutivas suman ≥ `MAX_CONSECUTIVE_LOSS`
- **Bloqueo de saldo**: En modo real, el dinero apostado queda bloqueado hasta que el mercado se resuelve
- **Filtro de volatilidad**: Ignora señales de velas con cambio < `MIN_VOLATILITY_PERCENT`
- **Reset diario**: Todos los contadores se reinician a medianoche UTC
