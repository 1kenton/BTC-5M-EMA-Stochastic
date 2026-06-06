"""
EMA + RSI + Stochastic Oscillator strategy — BTC/USD 5-minute chart.

Entry logic (youtu.be/wf6s7HHUP_8):
  Layer 1 (Trend)    — All three EMAs (short/medium/long) slope the same direction
                       and price is on the correct side of all three.
  Layer 2 (Strength) — RSI(period) above 50 = bullish, below 50 = bearish.
  Layer 3 (Timing)   — Stochastic %K enters oversold zone (<stoch_os) then crosses
                       above %D → long.  Enters overbought (>stoch_ob) then crosses
                       below %D → short.

Stop  : ema_short ± sl_buffer_pct
Target: entry ± abs(entry - stop) * rr_ratio
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from hermes_trading.adapters.price import fetch_ohlcv

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

PAPER_MODE    = os.getenv("HERMES_TRADING_MODE", "paper") == "paper"
STATE_FILE    = Path("state/worker_state.json")
TRADES_FILE   = Path("state/trades.jsonl")
STRATEGY_FILE = Path("state/strategy.yaml")
GOAL_FILE     = Path("state/goal.yaml")
GRANULARITY   = 300  # 5-minute candles


def load_params() -> dict:
    try:
        raw = yaml.safe_load(STRATEGY_FILE.read_text()) or {}
        e = raw.get("entry", {})
        return {
            "ema_short":      int(e.get("ema_short",      25)),
            "ema_medium":     int(e.get("ema_medium",     75)),
            "ema_long":       int(e.get("ema_long",      140)),
            "rsi_period":     int(e.get("rsi_period",     75)),
            "stoch_k":        int(e.get("stoch_k",        14)),
            "stoch_d":        int(e.get("stoch_d",         3)),
            "stoch_ob":     float(e.get("stoch_ob",      80.0)),
            "stoch_os":     float(e.get("stoch_os",      20.0)),
            "rr_ratio":     float(e.get("rr_ratio",       2.5)),
            "slope_lookback": int(e.get("slope_lookback",  3)),
            "sl_buffer_pct":float(e.get("sl_buffer_pct", 0.002)),
        }
    except Exception:
        return {
            "ema_short": 25, "ema_medium": 75, "ema_long": 140,
            "rsi_period": 75, "stoch_k": 14, "stoch_d": 3,
            "stoch_ob": 80.0, "stoch_os": 20.0, "rr_ratio": 2.5,
            "slope_lookback": 3, "sl_buffer_pct": 0.002,
        }


def reflection_due() -> bool:
    try:
        goal = yaml.safe_load(GOAL_FILE.read_text()) or {}
    except Exception:
        goal = {}
    every = int(goal.get("reflection_every", 5))
    if not TRADES_FILE.exists():
        return False
    closed = sum(1 for line in TRADES_FILE.read_text().splitlines() if line.strip())
    return closed > 0 and closed % every == 0


def load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"current_trade": None, "prev_k": None, "prev_d": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log_trade(record: dict) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── indicators ─────────────────────────────────────────────────────────────────

def _ema(closes: list, period: int) -> list:
    if len(closes) < period:
        return [None] * len(closes)
    mult = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(closes[:period]) / period)
    for c in closes[period:]:
        result.append(result[-1] * (1 - mult) + c * mult)
    return result


def _rsi(closes: list, period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


def _stochastic(candles: list, k_period: int, d_period: int):
    """Return (k_curr, d_curr, k_prev, d_prev) or (None, None, None, None)."""
    k_vals = []
    for i, c in enumerate(candles):
        if i < k_period - 1:
            k_vals.append(None)
            continue
        window = candles[i - k_period + 1: i + 1]
        ll = min(w["low"] for w in window)
        hh = max(w["high"] for w in window)
        k_vals.append(50.0 if hh == ll else (c["close"] - ll) / (hh - ll) * 100)

    d_vals = []
    for i, k in enumerate(k_vals):
        if k is None:
            d_vals.append(None)
            continue
        seg = [k_vals[j] for j in range(max(0, i - d_period + 1), i + 1)
               if k_vals[j] is not None]
        d_vals.append(sum(seg) / len(seg) if len(seg) == d_period else None)

    k_valid = [v for v in k_vals if v is not None]
    d_valid = [v for v in d_vals if v is not None]
    if len(k_valid) < 2 or len(d_valid) < 2:
        return None, None, None, None
    return k_valid[-1], d_valid[-1], k_valid[-2], d_valid[-2]


def _slope(ema_series: list, lookback: int) -> float | None:
    valid = [v for v in ema_series if v is not None]
    if len(valid) < lookback + 1:
        return None
    return valid[-1] - valid[-(lookback + 1)]


# ── main loop tick ─────────────────────────────────────────────────────────────

async def loop_once(state: dict) -> dict:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    p = load_params()

    candles = await fetch_ohlcv(granularity=GRANULARITY, limit=220)
    if len(candles) < p["ema_long"] + 10:
        logger.warning(f"Only {len(candles)} candles — need {p['ema_long']+10}+, skipping")
        return state

    completed = candles[:-1]  # exclude in-progress candle
    closes    = [c["close"] for c in completed]
    last      = completed[-1]
    price     = last["close"]

    ema_s_ser = _ema(closes, p["ema_short"])
    ema_m_ser = _ema(closes, p["ema_medium"])
    ema_l_ser = _ema(closes, p["ema_long"])
    rsi_val   = _rsi(closes, p["rsi_period"])
    k_curr, d_curr, k_prev, d_prev = _stochastic(completed, p["stoch_k"], p["stoch_d"])

    e_s = next((v for v in reversed(ema_s_ser) if v is not None), None)
    e_m = next((v for v in reversed(ema_m_ser) if v is not None), None)
    e_l = next((v for v in reversed(ema_l_ser) if v is not None), None)

    if None in (e_s, e_m, e_l, rsi_val, k_curr, d_curr):
        logger.info("Indicators not ready — need more candle history")
        return state

    slope_s = _slope(ema_s_ser, p["slope_lookback"])
    slope_m = _slope(ema_m_ser, p["slope_lookback"])
    slope_l = _slope(ema_l_ser, p["slope_lookback"])

    # ── exit check ─────────────────────────────────────────────────────────────
    if state["current_trade"]:
        trade = state["current_trade"]
        sl = trade["stop_loss"]
        tp = trade["target"]
        closed = None

        if trade["direction"] == "long":
            if last["high"] >= tp:
                pnl = (tp - trade["entry_price"]) / trade["entry_price"]
                closed = {**trade, "exit_price": tp, "exit_reason": "tp", "pnl_pct": round(pnl, 6)}
            elif last["low"] <= sl:
                pnl = (sl - trade["entry_price"]) / trade["entry_price"]
                closed = {**trade, "exit_price": sl, "exit_reason": "sl", "pnl_pct": round(pnl, 6)}
        else:
            if last["low"] <= tp:
                pnl = (trade["entry_price"] - tp) / trade["entry_price"]
                closed = {**trade, "exit_price": tp, "exit_reason": "tp", "pnl_pct": round(pnl, 6)}
            elif last["high"] >= sl:
                pnl = (trade["entry_price"] - sl) / trade["entry_price"]
                closed = {**trade, "exit_price": sl, "exit_reason": "sl", "pnl_pct": round(pnl, 6)}

        if closed:
            closed["close_ts"] = now_ts
            log_trade(closed)
            logger.info(
                f"Trade CLOSED | {closed['direction']} | entry={closed['entry_price']:.2f} "
                f"exit={closed['exit_price']:.2f} reason={closed['exit_reason']} "
                f"pnl={closed['pnl_pct']*100:.3f}%"
            )
            state["current_trade"] = None
            if reflection_due():
                logger.info("Reflection triggered")
                try:
                    from hermes_trading.reflect import run_reflection
                    run_reflection()
                except Exception as exc:
                    logger.error(f"Reflection failed: {exc}")
        else:
            logger.info(
                f"Trade OPEN | {trade['direction']} @ {trade['entry_price']:.2f} "
                f"SL={sl:.2f} TP={tp:.2f} | price={price:.2f}"
            )
        state["prev_k"] = k_curr
        state["prev_d"] = d_curr
        return state

    # ── trend determination ────────────────────────────────────────────────────
    uptrend = (None not in (slope_s, slope_m, slope_l)
               and slope_s > 0 and slope_m > 0 and slope_l > 0
               and price > e_s > e_m > e_l)
    downtrend = (None not in (slope_s, slope_m, slope_l)
                 and slope_s < 0 and slope_m < 0 and slope_l < 0
                 and price < e_s < e_m < e_l)
    trend = "bullish" if uptrend else ("bearish" if downtrend else None)

    # ── entry check ────────────────────────────────────────────────────────────
    pk = state.get("prev_k")
    pd = state.get("prev_d")
    new_trade = None

    if pk is not None and pd is not None:
        buf = p["sl_buffer_pct"]
        if trend == "bullish" and rsi_val > 50:
            # K was oversold AND crosses up through D
            if pk < p["stoch_os"] and k_curr > d_curr and pk <= pd:
                sl_price = e_s * (1 - buf)
                risk = price - sl_price
                if risk > 0:
                    new_trade = {
                        "direction": "long",
                        "entry_price": round(price, 2),
                        "stop_loss": round(sl_price, 2),
                        "target": round(price + risk * p["rr_ratio"], 2),
                        "entry_ts": now_ts,
                        "open_ts": now_ts,
                        "mode": "paper",
                        "stoch_k": round(k_curr, 2),
                        "rsi": round(rsi_val, 2),
                    }

        elif trend == "bearish" and rsi_val < 50:
            # K was overbought AND crosses down through D
            if pk > p["stoch_ob"] and k_curr < d_curr and pk >= pd:
                sl_price = e_s * (1 + buf)
                risk = sl_price - price
                if risk > 0:
                    new_trade = {
                        "direction": "short",
                        "entry_price": round(price, 2),
                        "stop_loss": round(sl_price, 2),
                        "target": round(price - risk * p["rr_ratio"], 2),
                        "entry_ts": now_ts,
                        "open_ts": now_ts,
                        "mode": "paper",
                        "stoch_k": round(k_curr, 2),
                        "rsi": round(rsi_val, 2),
                    }

    if new_trade:
        state["current_trade"] = new_trade
        logger.info(
            f"ENTRY | {new_trade['direction']} @ {new_trade['entry_price']:.2f} "
            f"SL={new_trade['stop_loss']:.2f} TP={new_trade['target']:.2f} "
            f"stoch_k={new_trade['stoch_k']} rsi={new_trade['rsi']}"
        )
    else:
        logger.info(
            f"Waiting | trend={trend} | price={price:.2f} | "
            f"ema_s={e_s:.1f} ema_m={e_m:.1f} ema_l={e_l:.1f} | "
            f"rsi={rsi_val:.1f} stoch_k={k_curr:.1f}/{d_curr:.1f}"
        )

    state["prev_k"] = k_curr
    state["prev_d"] = d_curr
    return state


async def loop_forever() -> None:
    logger.info("Booting hermes-trading worker | BTC-5M-EMA-Stochastic | paper mode")
    logger.info("Strategy: 5m EMA(25/75/140) + RSI(75) + Stochastic(14,3,3)")

    state = load_state()
    tick = 0

    while True:
        tick += 1
        logger.info(f"[{datetime.now(timezone.utc).isoformat()}] Tick {tick}")
        try:
            state = await loop_once(state)
            save_state(state)
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
        await asyncio.sleep(GRANULARITY)
