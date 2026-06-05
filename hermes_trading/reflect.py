"""
Reflection cycle: analyzes trades and proposes ONE strategy change.
"""
import json
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def reflect(trades: list, strategy_path: str = "state/strategy.yaml") -> dict:
    """Analyze trades and propose ONE variable change."""
    if not trades or len(trades) < 5:
        return {"status": "waiting", "trades_count": len(trades)}
    
    if not Path(strategy_path).exists():
        strategy_path = f"/app/{strategy_path}"
    
    with open(strategy_path) as f:
        strategy = yaml.safe_load(f)
    
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(trades) if trades else 0
    
    hypothesis = None
    if win_rate < 0.5:
        hypothesis = {
            "variable": "entry_conditions.rule_5_risk_reward",
            "old_value": 2.5,
            "new_value": 3.0,
            "reason": f"Win rate {win_rate:.1%} below 50%, raising R:R minimum to filter lower probability setups",
        }
    elif win_rate >= 0.7:
        hypothesis = {
            "variable": "layer_2_trend_strength.period",
            "old_value": 75,
            "new_value": 50,
            "reason": f"Win rate {win_rate:.1%} strong, shortening RSI period to catch earlier trend confirmation",
        }
    
    return {
        "status": "proposed" if hypothesis else "waiting",
        "trades_analyzed": len(trades),
        "win_rate": win_rate,
        "hypothesis": hypothesis,
    }
