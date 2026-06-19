import os
import time
import pytest
from engine.exchange_engine import ExchangeEngine

@pytest.fixture(scope="module")
def engine():
    api_key = os.getenv("OKX_API_KEY")
    secret_key = os.getenv("OKX_SECRET_KEY")
    passphrase = os.getenv("OKX_PASSPHRASE")
    demo = os.getenv("OKX_DEMO", "True") == "True"
    if not api_key or not secret_key or not passphrase:
        pytest.skip("Missing API credentials")
    eng = ExchangeEngine(api_key, secret_key, passphrase, demo=demo)
    assert eng.connect()
    return eng

def test_create_market_order(engine):
    symbol = "BTC-USDT-SWAP"
    # Ensure no position first
    positions = engine.get_positions(symbol)
    if positions:
        engine.close_position(symbol)
        time.sleep(2)

    result = engine.open_position(symbol, "buy", 1, sl_price=60000)
    assert result['success'] is True
    assert 'ord_id' in result
    assert result['avg_px'] > 0

    # Verify protection (SL)
    algos = engine.get_algo_orders(symbol)
    assert any(a.get('slTriggerPx') for a in algos)

    # Clean up
    engine.close_position(symbol)

def test_cancel_protection(engine):
    symbol = "BTC-USDT-SWAP"
    # Open position with SL
    result = engine.open_position(symbol, "buy", 1, sl_price=60000)
    assert result['success']
    algos = engine.get_algo_orders(symbol)
    sl_algo = next((a for a in algos if a.get('slTriggerPx')), None)
    assert sl_algo is not None
    # Cancel SL
    assert engine.cancel_algo(symbol, sl_algo['algoId'])
    # Verify gone
    algos_after = engine.get_algo_orders(symbol)
    assert not any(a.get('slTriggerPx') for a in algos_after)
    engine.close_position(symbol)
