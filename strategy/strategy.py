#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
strategy.py - Estrategia de ejemplo completamente independiente del engine.
Recibe context y devuelve señal pura.
"""

import logging
logger = logging.getLogger(__name__)

def generate_signal(context: dict) -> dict:
    """
    Estrategia de ejemplo:
    - Si no hay posición → abrir LONG con 1 contrato
    - TP/SL calculados con 2% y 3% (si no hay precio, usa defaults)
    """
    symbol = context.get('symbol', 'BTC-USDT-SWAP')
    positions = context.get('positions', [])
    ticker_price = context.get('ticker_price', 65000.0)

    if not positions:
        # Determinar precio de entrada
        entry_price = ticker_price if ticker_price > 0 else 65000.0

        # Calcular TP y SL con márgenes fijos
        # En una estrategia real se usaría ATR o volatilidad
        tp = entry_price * 1.02   # 2% arriba
        sl = entry_price * 0.97   # 3% abajo

        logger.info(f"🔵 Estrategia: BUY a {entry_price}, TP={tp}, SL={sl}")

        return {
            'action': 'buy',
            'size': 1.0,
            'tp': tp,
            'sl': sl,
            'entry_price': entry_price
        }
    else:
        pos = positions[0]
        side = 'long' if pos['contracts'] > 0 else 'short'
        logger.info(f"🟡 Estrategia: Posición existente {side}, manteniendo")
        return {
            'action': 'hold',
            'size': 0,
            'tp': None,
            'sl': None,
            'position': pos
        }
