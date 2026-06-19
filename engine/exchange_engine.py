#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
exchange_engine.py - Motor OKX determinista SIN clOrdId
OKX es la única fuente de verdad.
"""

import ccxt
import time
import logging
import json
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class ExchangeEngine:
    """Motor OKX para sandbox/real. Sin estado local crítico."""

    def __init__(self, sandbox: bool = True):
        self.sandbox = sandbox
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_SECRET_KEY'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
            }
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info("🔬 OKX Sandbox activado.")
        else:
            logger.warning("🔥 OKX REAL activado. ¡Precaución!")

        # Para telemetría
        self.api_log = []
        self.max_log_entries = 1000

    # ======================== CONEXIÓN ========================

    def connect(self) -> bool:
        """Verifica credenciales."""
        try:
            self.exchange.fetch_balance()
            logger.info("✅ Conexión OKX establecida.")
            return True
        except ccxt.AuthenticationError as e:
            logger.error(f"❌ Error de autenticación: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error de conexión: {e}")
            return False

    # ======================== DATOS ========================

    def fetch_balance(self, currency: str = 'USDT') -> float:
        """Devuelve saldo disponible."""
        try:
            bal = self.exchange.fetch_balance()
            return bal.get(currency, {}).get('free', 0.0)
        except Exception as e:
            logger.error(f"Error en fetch_balance: {e}")
            return 0.0

    def fetch_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Devuelve posiciones abiertas."""
        try:
            positions = self.exchange.fetch_positions([symbol] if symbol else None)
            return [p for p in positions if abs(p.get('contracts', 0)) > 0.0001]
        except Exception as e:
            logger.error(f"Error en fetch_positions: {e}")
            return []

    def fetch_ticker(self, symbol: str) -> Dict:
        """Obtiene ticker actual (precio, volumen)."""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Error en fetch_ticker: {e}")
            return {'last': 0.0, 'bid': 0.0, 'ask': 0.0}

    # ======================== EJECUCIÓN ========================

    def create_market_order(self, symbol: str, side: str, size: float) -> Dict:
        """
        Abre orden de mercado.
        - NO usa clOrdId (evita error 51000)
        - Espera confirmación de llenado (polling)
        """
        params = {
            'tdMode': 'isolated',
            'posSide': 'long' if side == 'buy' else 'short'
        }
        # clOrdId ELIMINADO - OKX asigna ordId automáticamente

        try:
            # 1. Enviar orden
            order = self.exchange.create_order(symbol, 'market', side, size, None, params)
            ord_id = order.get('id') or order.get('ordId')
            if not ord_id:
                self._log_api('create_order', params, {'error': 'No ordId'}, 0)
                return {'success': False, 'error': 'No se recibió ordId'}

            # 2. Esperar llenado (polling)
            start = time.time()
            avg_px = 0.0
            filled = 0.0

            while time.time() - start < 10:
                try:
                    fetch_resp = self.exchange.fetch_order(ord_id, symbol)
                    status = fetch_resp.get('status')
                    avg_px = fetch_resp.get('average') or fetch_resp.get('price') or 0.0
                    filled = fetch_resp.get('filled', 0.0) or 0.0

                    if status in ('closed', 'filled'):
                        self._log_api('fetch_order', {'ordId': ord_id}, fetch_resp, 0)
                        return {
                            'success': True,
                            'ordId': ord_id,
                            'avgPx': avg_px,
                            'filled': filled,
                            'status': status
                        }
                    elif status in ('cancelled', 'rejected'):
                        return {'success': False, 'error': f'Orden {status}'}
                except Exception as e:
                    logger.debug(f"Polling fetch_order falló: {e}")
                time.sleep(0.5)

            return {'success': False, 'error': 'Timeout esperando llenado'}

        except Exception as e:
            logger.error(f"Error en create_market_order: {e}")
            self._log_api('create_order', params, {'exception': str(e)}, 0)
            return {'success': False, 'error': str(e)}

    def close_position(self, symbol: str, size: Optional[float] = None) -> bool:
        """Cierra posición (total o parcial)."""
        positions = self.fetch_positions(symbol)
        if not positions:
            logger.info(f"No hay posición en {symbol}")
            return True

        pos = positions[0]
        side = 'sell' if pos['contracts'] > 0 else 'buy'
        size_to_close = abs(pos['contracts']) if size is None else min(abs(pos['contracts']), size)

        params = {
            'tdMode': 'isolated',
            'reduceOnly': True
        }
        # Sin clOrdId

        try:
            order = self.exchange.create_order(symbol, 'market', side, size_to_close, None, params)
            if order.get('id') or order.get('ordId'):
                logger.info(f"Orden de cierre enviada para {symbol}, size={size_to_close}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error cerrando posición: {e}")
            return False

    def set_tp_sl(self, symbol: str, tp_price: float, sl_price: float) -> bool:
        """
        Coloca Take Profit y Stop Loss (órdenes condicionales reduceOnly).
        """
        positions = self.fetch_positions(symbol)
        if not positions:
            logger.warning(f"No hay posición para {symbol}")
            return False

        pos = positions[0]
        side = 'long' if pos['contracts'] > 0 else 'short'
        size = abs(pos['contracts'])
        close_side = 'sell' if side == 'long' else 'buy'

        params_base = {
            'tdMode': 'isolated',
            'reduceOnly': True,
            'ordType': 'conditional'
        }
        # Sin clOrdId

        success = True

        # Take Profit
        try:
            tp_params = {**params_base, 'tpTriggerPx': str(tp_price), 'tpOrdPx': str(tp_price)}
            resp = self.exchange.create_order(symbol, 'market', close_side, size, None, tp_params)
            self._log_api('place_tp', tp_params, resp, 0)
            logger.info(f"TP colocado en {tp_price}")
        except Exception as e:
            logger.error(f"Error colocando TP: {e}")
            success = False

        # Stop Loss
        try:
            sl_params = {**params_base, 'slTriggerPx': str(sl_price), 'slOrdPx': str(sl_price)}
            resp = self.exchange.create_order(symbol, 'market', close_side, size, None, sl_params)
            self._log_api('place_sl', sl_params, resp, 0)
            logger.info(f"SL colocado en {sl_price}")
        except Exception as e:
            logger.error(f"Error colocando SL: {e}")
            success = False

        return success

    def cancel_all_orders(self, symbol: str) -> bool:
        """Cancela órdenes normales y algorítmicas."""
        try:
            self.exchange.cancel_all_orders(symbol)
            logger.info(f"Órdenes normales canceladas para {symbol}")
        except Exception as e:
            logger.warning(f"Error cancelando órdenes normales: {e}")

        try:
            resp = self.exchange.request('/api/v5/trade/order-algos-pending', 'GET', {'instId': symbol})
            if resp.get('code') == '0':
                algos = resp.get('data', [])
                for algo in algos:
                    cancel = self.exchange.request('/api/v5/trade/cancel-algos', 'POST', {
                        'instId': symbol,
                        'algoId': algo['algoId']
                    })
                    logger.info(f"Algo {algo['algoId']} cancelado: {cancel.get('code') == '0'}")
        except Exception as e:
            logger.error(f"Error cancelando algos: {e}")
            return False

        return True

    # ======================== RECONCILIACIÓN ========================

    def reconcile_state(self, symbol: str) -> Dict:
        """Reconcilia el estado real en OKX con el sistema."""
        positions = self.fetch_positions(symbol)
        algos = []
        try:
            resp = self.exchange.request('/api/v5/trade/order-algos-pending', 'GET', {'instId': symbol})
            if resp.get('code') == '0':
                algos = resp.get('data', [])
        except Exception:
            pass

        has_tp = any(a.get('tpTriggerPx') for a in algos)
        has_sl = any(a.get('slTriggerPx') for a in algos)

        return {
            'symbol': symbol,
            'has_position': len(positions) > 0,
            'position': positions[0] if positions else None,
            'tp_exists': has_tp,
            'sl_exists': has_sl,
            'algo_count': len(algos)
        }

    # ======================== TELEMETRÍA ========================

    def _log_api(self, endpoint: str, payload: dict, response: dict, latency_ms: float):
        """Registra llamadas API internamente."""
        entry = {
            'timestamp': time.time(),
            'endpoint': endpoint,
            'payload': payload,
            'response': response,
            'latency_ms': latency_ms
        }
        self.api_log.append(entry)
        if len(self.api_log) > self.max_log_entries:
            self.api_log.pop(0)
        # Guardar en archivo
        try:
            with open('logs/api_calls.jsonl', 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    def get_api_log(self) -> List[Dict]:
        """Devuelve el log de API."""
        return self.api_log

    def get_audit_trail(self) -> List[Dict]:
        """Alias para compatibilidad."""
        return self.api_log
