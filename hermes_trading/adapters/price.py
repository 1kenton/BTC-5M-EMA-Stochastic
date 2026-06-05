"""
Price data adapter for Coinbase. Pulls 5m OHLCV candles for BTC/USD.
"""
import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)

async def fetch(asset: str = "BTC/USD", timeframe: str = "5m") -> dict:
    """
    Fetch price data from Coinbase.
    
    For now, returns mock data (paper mode).
    In live mode, this would call Coinbase REST API.
    """
    try:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "timestamp": None,
            "ohlcv": []
        }
    except Exception as e:
        logger.error(f"Price fetch failed: {e}")
        return {}
