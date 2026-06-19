#!/usr/bin/env python3
"""
Main entry point for the OKX bot.
"""
import os
import sys
import logging
import time
from engine.exchange_engine import ExchangeEngine
from strategies.example_strategy import ExampleStrategy
from core.bot_runner import BotRunner
from core.telemetry import Telemetry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Load credentials from environment (or .env)
    api_key = os.getenv("OKX_API_KEY")
    secret_key = os.getenv("OKX_SECRET_KEY")
    passphrase = os.getenv("OKX_PASSPHRASE")
    demo = os.getenv("OKX_DEMO", "True") == "True"
    ci_mode = os.getenv("CI_MODE", "0") == "1"
    max_cycles = int(os.getenv("MAX_CYCLES", "0")) or None

    if not api_key or not secret_key or not passphrase:
        logger.error("Missing API credentials. Set OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE")
        sys.exit(1)

    # Initialize engine
    engine = ExchangeEngine(api_key, secret_key, passphrase, demo=demo)
    if not engine.connect():
        logger.error("Failed to connect to OKX sandbox.")
        sys.exit(1)

    # Telemetry
    telemetry = Telemetry()

    # Strategy
    strategy = ExampleStrategy()

    # Symbol
    symbol = "BTC-USDT-SWAP"

    # Runner
    runner = BotRunner(engine, strategy, symbol, telemetry, cycle_interval=5.0)

    # Run (if CI mode, limit cycles)
    logger.info(f"Starting bot in {'CI' if ci_mode else 'normal'} mode.")
    runner.run(max_cycles=max_cycles if ci_mode else None)

if __name__ == "__main__":
    main()
