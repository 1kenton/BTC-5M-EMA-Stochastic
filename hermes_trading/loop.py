"""
Main loop: every 60 seconds, evaluate EMA + RSI + Stochastic strategy, take trades.
"""
import asyncio
import json
import yaml
import os
import logging
from datetime import datetime
from pathlib import Path
from hermes_trading.adapters.price import fetch as fetch_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_strategy(strategy_path: str = "state/strategy.yaml") -> dict:
    """Load strategy from YAML"""
    if not Path(strategy_path).exists():
        strategy_path = f"/app/{strategy_path}"
    with open(strategy_path) as f:
        return yaml.safe_load(f)

def log_trade(trade: dict, trades_path: str = "state/trades.jsonl"):
    """Append trade to jsonl"""
    if not Path(trades_path).exists():
        trades_path = f"/app/{trades_path}"
    Path(trades_path).parent.mkdir(parents=True, exist_ok=True)
    with open(trades_path, "a") as f:
        f.write(json.dumps(trade) + "\n")

def log_heartbeat(heartbeat: dict, heartbeat_path: str = "state/heartbeat.json"):
    """Write heartbeat"""
    if not Path(heartbeat_path).exists():
        heartbeat_path = f"/app/{heartbeat_path}"
    Path(heartbeat_path).parent.mkdir(parents=True, exist_ok=True)
    with open(heartbeat_path, "w") as f:
        json.dump(heartbeat, f)

async def evaluate_ema_rsi_stochastic_strategy(price_data: dict, strategy: dict) -> dict:
    """
    Evaluate EMA + RSI + Stochastic strategy.
    
    For now, returns mock trade (paper mode).
    """
    trade = {
        "timestamp": datetime.now().isoformat(),
        "entry_price": 42500.0,
        "exit_price": 42750.0,
        "direction": "long",
        "stop_loss": 42400.0,
        "target": 42750.0,
        "pnl": 250.0,
        "reason": "EMA + RSI + Stochastic triple confirmation (mock)"
    }
    return trade

async def loop_forever():
    """Main loop: tick every 60 seconds."""
    consecutive_failures = 0
    tick = 0
    
    while True:
        tick += 1
        now = datetime.now()
        
        try:
            logger.info(f"[{now.isoformat()}] Tick {tick}: fetching price data...")
            
            price_data = await fetch_price()
            consecutive_failures = 0
            
            strategy = load_strategy()
            trade = await evaluate_ema_rsi_stochastic_strategy(price_data, strategy)
            
            mode = os.getenv("HERMES_TRADING_MODE", "paper")
            if mode == "paper":
                log_trade(trade)
                logger.info(f"Paper trade logged: {trade['direction']} @ {trade['entry_price']}")
            
            log_heartbeat({
                "tick": tick,
                "timestamp": now.isoformat(),
                "status": "ok",
                "trades_logged": 1
            })
            
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"ERROR (attempt {consecutive_failures}/5): {e}")
            
            if consecutive_failures >= 5:
                logger.critical("Circuit-breaker triggered. Exiting.")
                break
        
        await asyncio.sleep(60)

if __name__ == "__main__":
    Path("state").mkdir(exist_ok=True)
    
    logger.info("Booting hermes-trading worker | asset=BTC/USD | exchange=Coinbase | timeframe=5m")
    logger.info("  Mode: paper")
    logger.info("  Strategy: EMA + RSI + Stochastic Oscillator")
    logger.info("")
    
    asyncio.run(loop_forever())
