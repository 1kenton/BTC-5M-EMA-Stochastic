"""
Price data adapter — Coinbase Exchange public OHLCV API.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"


async def fetch_ohlcv(granularity: int = 300, limit: int = 220) -> list:
    """
    Return OHLCV candles sorted oldest-first as list of dicts.
    Each dict: {timestamp, open, high, low, close, volume}
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=granularity * (limit + 2))
    params = {
        "granularity": granularity,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(_BASE, params=params)
                resp.raise_for_status()
                rows = resp.json()  # [[ts, low, high, open, close, vol], ...]
                candles = [
                    {
                        "timestamp": r[0],
                        "open": r[3],
                        "high": r[2],
                        "low": r[1],
                        "close": r[4],
                        "volume": r[5],
                    }
                    for r in rows
                ]
                candles.sort(key=lambda c: c["timestamp"])
                return candles
        except Exception as e:
            if attempt == 2:
                logger.error(f"fetch_ohlcv failed after 3 attempts: {e}")
                return []
            await asyncio.sleep(2 ** attempt)
    return []
