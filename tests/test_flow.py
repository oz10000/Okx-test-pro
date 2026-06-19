#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tests/test_flow.py - Pruebas integradas para OKX sandbox.
"""

import os
import sys
import time
import pytest
import logging

# Añadir directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.exchange_engine import ExchangeEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================== FIXTURE ========================

@pytest.fixture(scope="module")
def engine():
    """Fixture que proporciona un engine conectado a sandbox."""
    api_key = os.getenv('OKX_API_KEY')
    secret_key = os.getenv('OKX_SECRET_KEY')
    passphrase = os.getenv('OKX_PASSPHRASE')

    if not all([api_key, secret_key, passphrase]):
        pytest.skip("Credenciales no configuradas")

    eng = ExchangeEngine(sandbox=True)
    assert eng.connect(), "❌ Fallo de conexión a OKX"
    return eng

@pytest.fixture
def symbol():
    return 'BTC-USDT-SWAP'

# ======================== PRUEBAS ========================

def test_connectivity(engine):
    """Prueba básica de conectividad."""
    try:
        server_time = engine.exchange.fetch_time()
        assert server_time > 0
        logger.info(f"✅ OKX time: {server_time}")
    except Exception as e:
        pytest.fail(f"❌ Fallo fetch_time: {e}")

def test_fetch_balance(engine):
    """Prueba de obtención de balance."""
    bal = engine.fetch_balance('USDT')
    assert isinstance(bal, float)
    assert bal >= 0
    logger.info(f"✅ Balance USDT: {bal}")

def test_market_order_flow(engine, symbol):
    """
    Flujo completo:
    1. Abrir orden de mercado
    2. Verificar llenado
    3. Colocar TP/SL
    4. Cancelar todo
    5. Cerrar posición
    """
    logger.info("🧪 Iniciando test de flujo de órdenes")

    # 1. Limpiar estado previo
    engine.close_position(symbol)
    engine.cancel_all_orders(symbol)
    time.sleep(1)

    # 2. Obtener precio actual
    ticker = engine.fetch_ticker(symbol)
    current_price = ticker.get('last', 0)
    if current_price <= 0:
        current_price = 65000.0  # fallback

    logger.info(f"📊 Precio actual BTC: {current_price}")

    # 3. Abrir posición
    result = engine.create_market_order(symbol, 'buy', 1)
    assert result.get('success'), f"❌ Fallo en market order: {result}"
    assert result.get('ordId') is not None
    avg_px = result.get('avgPx', current_price)
    logger.info(f"✅ Orden abierta: {result['ordId']}, avgPx={avg_px}")

    time.sleep(1)

    # 4. Verificar posición
    positions = engine.fetch_positions(symbol)
    assert len(positions) > 0, "❌ No se detectó posición"
    logger.info(f"✅ Posición verificada: {positions[0]}")

    # 5. Colocar TP/SL (dinámicos)
    tp_price = avg_px * 1.02
    sl_price = avg_px * 0.97
    ok = engine.set_tp_sl(symbol, tp_price, sl_price)
    assert ok, "❌ Fallo al colocar TP/SL"
    logger.info(f"✅ TP={tp_price}, SL={sl_price} colocados")

    time.sleep(1)

    # 6. Cancelar todo
    ok = engine.cancel_all_orders(symbol)
    assert ok, "❌ Fallo al cancelar órdenes"
    logger.info("✅ Órdenes canceladas")

    # 7. Cerrar posición
    ok = engine.close_position(symbol)
    assert ok, "❌ Fallo al cerrar posición"
    time.sleep(1)

    # 8. Verificar que no hay posición
    final_positions = engine.fetch_positions(symbol)
    assert len(final_positions) == 0, f"❌ Posición residual: {final_positions}"

    logger.info("✅ Test de flujo completado exitosamente")

def test_reconcile_state(engine, symbol):
    """Prueba de reconciliación de estado."""
    # Abrir posición con TP/SL
    engine.close_position(symbol)
    time.sleep(1)

    ticker = engine.fetch_ticker(symbol)
    price = ticker.get('last', 65000)
    result = engine.create_market_order(symbol, 'buy', 1)
    assert result.get('success')
    time.sleep(1)

    avg_px = result.get('avgPx', price)
    engine.set_tp_sl(symbol, avg_px * 1.02, avg_px * 0.97)
    time.sleep(1)

    # Reconciliar
    state = engine.reconcile_state(symbol)
    assert state['has_position'] is True
    assert state['tp_exists'] is True or state['sl_exists'] is True
    logger.info(f"✅ Estado reconciliado: {state}")

    # Limpiar
    engine.cancel_all_orders(symbol)
    engine.close_position(symbol)
