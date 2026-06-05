"""Entry point for the trading worker."""
from hermes_trading.loop import loop_forever
import asyncio

if __name__ == "__main__":
    asyncio.run(loop_forever())
