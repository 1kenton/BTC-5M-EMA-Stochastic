"""
Scoring function: evaluates trade outcomes against goal.yaml
"""
import yaml
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def load_goal(goal_path: str = "state/goal.yaml") -> dict:
    """Load goal thresholds"""
    if not Path(goal_path).exists():
        goal_path = f"/app/{goal_path}"
    with open(goal_path) as f:
        return yaml.safe_load(f)

def score(trades: list, goal: dict) -> float:
    """Score trades against goals. Returns float in [-1, +1]."""
    if not trades:
        return 0.0
    
    returns = [t.get("pnl", 0) for t in trades]
    total_return = sum(returns)
    
    target = goal.get("target_return_30d", 0.10)
    failure = goal.get("failure_below", -0.04)
    
    if total_return < failure:
        return -1.0
    elif total_return >= target:
        return 1.0
    else:
        return (total_return - failure) / (target - failure) * 2 - 1
