import os
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
    assert eng.connect(), "Connect failed"
    return eng

def test_connectivity(engine):
    assert engine.health_check()['status'] == 'online'

def test_fetch_balance(engine):
    balance = engine.get_balance('USDT')
    assert isinstance(balance, float)
    assert balance >= 0
