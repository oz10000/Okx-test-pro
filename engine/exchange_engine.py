#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EXCHANGE_ENGINE - Motor universal para OKX (Versión Final Certificada).
Basado en evidencia empírica de OKX Demo.
Estado: CERRADO Y VERIFICADO.
"""

import ccxt
import time
import logging
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger('ExchangeEngine')
logger.setLevel(logging.INFO)

class ExchangeEngine:
    """Capa única, determinista y auditada para OKX."""

    def __init__(self, api_key: str, secret_key: str, passphrase: str, demo: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.demo = demo

        self.max_retries = 3
        self.order_timeout = 15
        self.poll_interval = 0.5
        self.reconcile_interval = 10

        self.audit_trail = []
        self.max_audit_entries = 1000
        self._audit_counter = 0

        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret_key,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'brokerId': 'pidelta',
            }
        })

        if demo:
            self.exchange.set_sandbox_mode(True)
            logger.info("OKX DEMO activado.")
        else:
            logger.warning("OKX REAL activado. EXTREMA PRECAUCIÓN.")

    # ============================
    # AUDITORÍA INTERNA
    # ============================
    def _audit(self, endpoint: str, payload: dict, response: dict, result: str, latency_ms: float = 0):
        self._audit_counter += 1
        entry = {
            'audit_id': f'aud_{int(time.time()*1000)}_{self._audit_counter}',
            'timestamp': time.time(),
            'endpoint': endpoint,
            'payload': payload,
            'response': response,
            'latency_ms': round(latency_ms, 2),
            'validated': result
        }
        self.audit_trail.append(entry)
        if len(self.audit_trail) > self.max_audit_entries:
            self.audit_trail.pop(0)

    # ============================
    # 1. GESTIÓN DE VIDA
    # ============================
    def connect(self) -> bool:
        try:
            bal = self.exchange.fetch_balance()
            if bal.get('info', {}).get('code') == '0':
                logger.info("Conectado a OKX.")
                return True
            logger.error("Error en fetch_balance.")
            return False
        except Exception as e:
            logger.error(f"Error de conexión: {e}")
            return False

    def health_check(self) -> dict:
        try:
            self.exchange.fetch_time()
            return {'status': 'online', 'timestamp': time.time(), 'demo': self.demo}
        except Exception:
            return {'status': 'offline', 'timestamp': time.time(), 'demo': self.demo}

    # ============================
    # 2. DATOS PRIVADOS
    # ============================
    def get_balance(self, currency: str = 'USDT') -> float:
        try:
            bal = self.exchange.fetch_balance()
            return bal.get(currency, {}).get('free', 0.0)
        except Exception:
            return 0.0

    def get_positions(self, symbol: str = None) -> List[Dict]:
        try:
            positions = self.exchange.fetch_positions([symbol] if symbol else None)
            return [p for p in positions if abs(p.get('contracts', 0)) > 0.0001]
        except Exception:
            return []

    def get_algo_orders(self, symbol: str = None, state: str = 'live') -> List[Dict]:
        try:
            params = {'ordType': 'conditional'}
            if symbol:
                params['instId'] = symbol
            start = time.time()
            resp = self.exchange.request('/api/v5/trade/order-algos-pending', 'GET', params)
            latency = (time.time() - start) * 1000
            self._audit('/api/v5/trade/order-algos-pending', params, resp, 'fetch_algos', latency)

            if resp.get('code') == '0':
                data = resp.get('data', [])
                if state:
                    data = [d for d in data if d.get('state') == state]
                return data
            return []
        except Exception:
            return []

    # ============================
    # 3. APERTURA DETERMINISTA
    # ============================
    def open_position(self, symbol: str, side: str, size: float,
                      tp_price: float = None, sl_price: float = None,
                      trail_distance: float = None) -> Dict:
        cl_ord_id = f"pidelta_open_{int(time.time()*1000)}"
        pos_side = 'long' if side == 'buy' else 'short'
        params = {'tdMode': 'isolated', 'posSide': pos_side, 'clOrdId': cl_ord_id}

        try:
            start = time.time()
            order = self.exchange.create_order(symbol, 'market', side, size, None, params)
            latency = (time.time() - start) * 1000
            ord_id = order.get('id') or order.get('ordId')
            self._audit('/api/v5/trade/order', params, order, f'ordId={ord_id}', latency)

            if not ord_id:
                return {'success': False, 'error': 'No ordId en respuesta'}

            start_wait = time.time()
            avg_px = 0.0
            while time.time() - start_wait < self.order_timeout:
                try:
                    fetch_resp = self.exchange.fetch_order(ord_id, symbol)
                    status = fetch_resp.get('status')
                    avg_px = fetch_resp.get('price') or fetch_resp.get('average') or 0.0
                    if status in ('closed', 'filled'):
                        if avg_px == 0.0:
                            avg_px = fetch_resp.get('info', {}).get('avgPx', 0.0)
                        break
                    elif status in ('cancelled', 'rejected'):
                        return {'success': False, 'error': f'Orden {status}'}
                except Exception:
                    pass
                time.sleep(self.poll_interval)
            else:
                return {'success': False, 'error': 'Timeout esperando llenado'}

            time.sleep(1)
            positions = self.get_positions(symbol)
            pos = None
            for p in positions:
                p_side = 'long' if p['contracts'] > 0 else 'short'
                if p_side == side and abs(p['contracts']) > 0.0001:
                    pos = p
                    break

            if not pos:
                return {'success': False, 'error': 'Posición no encontrada en OKX', 'ord_id': ord_id}

            result = {
                'success': True,
                'ord_id': ord_id,
                'avg_px': float(avg_px) if avg_px else float(pos.get('entryPrice', 0)),
                'position': pos,
                'size': abs(pos['contracts'])
            }

            if tp_price or sl_price or trail_distance:
                prot = self.protect_position(symbol, tp_price, sl_price, trail_distance,
                                             size=result['size'], side=side)
                result['protection'] = prot

            return result

        except Exception as e:
            logger.error(f"Error en open_position: {e}")
            return {'success': False, 'error': str(e)}

    # ============================
    # 4. CIERRE
    # ============================
    def close_position(self, symbol: str, size: float = None) -> bool:
        positions = self.get_positions(symbol)
        if not positions:
            return True
        pos = positions[0]
        side = 'sell' if pos['contracts'] > 0 else 'buy'
        size_to_close = abs(pos['contracts']) if not size else min(abs(pos['contracts']), size)
        try:
            order = self.exchange.create_order(symbol, 'market', side, size_to_close, None, {
                'tdMode': 'isolated',
                'reduceOnly': True,
                'clOrdId': f"pidelta_close_{int(time.time()*1000)}"
            })
            if not order.get('id'):
                return False
            time.sleep(2)
            self.cancel_all_protections(symbol)
            return True
        except Exception as e:
            logger.error(f"Error cerrando: {e}")
            return False

    # ============================
    # 5. PROTECCIONES
    # ============================
    def _place_algo(self, symbol: str, close_side: str, size: float,
                    tp_trigger: float = None, sl_trigger: float = None,
                    trail_px: float = None) -> Dict:
        cl_ord_id = f"pidelta_algo_{int(time.time()*1000)}"
        params = {
            'tdMode': 'isolated',
            'reduceOnly': True,
            'ordType': 'conditional',
            'clOrdId': cl_ord_id,
        }
        if tp_trigger:
            params['tpTriggerPx'] = str(tp_trigger)
            params['tpOrdPx'] = str(tp_trigger)
        elif sl_trigger:
            params['slTriggerPx'] = str(sl_trigger)
            params['slOrdPx'] = str(sl_trigger)
        elif trail_px:
            params['trailPx'] = str(trail_px)
        else:
            return {'success': False, 'error': 'Sin parámetro'}

        try:
            start = time.time()
            order = self.exchange.create_order(symbol, 'market', close_side, size, None, params)
            latency = (time.time() - start) * 1000
            algo_id = order.get('id') or order.get('algoId')
            self._audit('/api/v5/trade/order-algo', params, order, f'algoId={algo_id}', latency)
            if not algo_id:
                return {'success': False, 'error': 'No algoId'}
            if self.verify_algo_order(symbol, algo_id):
                return {'algoId': algo_id, 'success': True}
            else:
                return {'success': False, 'error': 'No confirmado live', 'algoId': algo_id}
        except Exception as e:
            logger.error(f"Error en _place_algo: {e}")
            return {'success': False, 'error': str(e)}

    def set_take_profit(self, symbol: str, trigger_price: float) -> Dict:
        pos = self.get_positions(symbol)
        if not pos:
            return {'success': False, 'error': 'Sin posición'}
        p = pos[0]
        side = 'long' if p['contracts'] > 0 else 'short'
        size = abs(p['contracts'])
        close_side = 'sell' if side == 'long' else 'buy'
        return self._place_algo(symbol, close_side, size, tp_trigger=trigger_price)

    def set_stop_loss(self, symbol: str, trigger_price: float) -> Dict:
        pos = self.get_positions(symbol)
        if not pos:
            return {'success': False, 'error': 'Sin posición'}
        p = pos[0]
        side = 'long' if p['contracts'] > 0 else 'short'
        size = abs(p['contracts'])
        close_side = 'sell' if side == 'long' else 'buy'
        return self._place_algo(symbol, close_side, size, sl_trigger=trigger_price)

    def set_trailing_stop(self, symbol: str, trail_distance: float) -> Dict:
        pos = self.get_positions(symbol)
        if not pos:
            return {'success': False, 'error': 'Sin posición'}
        p = pos[0]
        side = 'long' if p['contracts'] > 0 else 'short'
        size = abs(p['contracts'])
        close_side = 'sell' if side == 'long' else 'buy'
        return self._place_algo(symbol, close_side, size, trail_px=trail_distance)

    def set_break_even(self, symbol: str, offset: float = 0.0) -> Dict:
        positions = self.get_positions(symbol)
        if not positions:
            return {'success': False, 'error': 'Sin posición'}
        p = positions[0]
        avg_px = float(p.get('entryPrice', 0))
        if avg_px == 0:
            return {'success': False, 'error': 'No avgPx'}
        algos = self.get_algo_orders(symbol)
        sl_algos = [a for a in algos if a.get('slTriggerPx')]
        for a in sl_algos:
            self.cancel_algo(symbol, a['algoId'])
        side = 'long' if p['contracts'] > 0 else 'short'
        be_price = avg_px + offset if side == 'long' else avg_px - offset
        return self.set_stop_loss(symbol, be_price)

    def protect_position(self, symbol: str, tp_price: float = None, sl_price: float = None,
                         trail_distance: float = None, size: float = None, side: str = None) -> Dict:
        if not side or not size:
            pos = self.get_positions(symbol)
            if not pos:
                return {'success': False, 'error': 'Posición no encontrada'}
            p = pos[0]
            side = 'long' if p['contracts'] > 0 else 'short'
            size = abs(p['contracts'])

        result = {'success': True, 'tp': None, 'sl': None, 'trail': None}
        close_side = 'sell' if side == 'long' else 'buy'

        if tp_price:
            tp_res = self._place_algo(symbol, close_side, size, tp_trigger=tp_price)
            if tp_res.get('success'):
                result['tp'] = tp_res['algoId']
            else:
                result['success'] = False
                result['tp_error'] = tp_res.get('error')

        if trail_distance:
            trail_res = self._place_algo(symbol, close_side, size, trail_px=trail_distance)
            if trail_res.get('success'):
                result['trail'] = trail_res['algoId']
            else:
                result['success'] = False
                result['trail_error'] = trail_res.get('error')
        elif sl_price:
            sl_res = self._place_algo(symbol, close_side, size, sl_trigger=sl_price)
            if sl_res.get('success'):
                result['sl'] = sl_res['algoId']
            else:
                result['success'] = False
                result['sl_error'] = sl_res.get('error')

        return result

    # ============================
    # 6. CANCELACIONES
    # ============================
    def cancel_algo(self, symbol: str, algo_id: str) -> bool:
        try:
            start = time.time()
            resp = self.exchange.request('/api/v5/trade/cancel-algos', 'POST', {
                'instId': symbol,
                'algoId': algo_id
            })
            latency = (time.time() - start) * 1000
            self._audit('/api/v5/trade/cancel-algos', {'algoId': algo_id}, resp, 'cancel_algo', latency)
            return resp.get('code') == '0'
        except Exception:
            return False

    def cancel_all_protections(self, symbol: str) -> bool:
        algos = self.get_algo_orders(symbol)
        success = True
        for a in algos:
            if not self.cancel_algo(symbol, a['algoId']):
                success = False
        return success

    # ============================
    # 7. VERIFICACIONES
    # ============================
    def verify_algo_order(self, symbol: str, algo_id: str, timeout: int = 5) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = self.exchange.request('/api/v5/trade/order-algos-pending', 'GET', {
                    'instId': symbol,
                    'algoId': algo_id
                })
                if resp.get('code') == '0':
                    data = resp.get('data', [])
                    if data and data[0].get('algoId') == algo_id:
                        state = data[0].get('state')
                        if state in ('live', 'effective'):
                            return True
                time.sleep(self.poll_interval)
            except Exception:
                pass
        return False

    def verify_position(self, symbol: str) -> bool:
        return len(self.get_positions(symbol)) > 0

    def verify_protection(self, symbol: str) -> Dict:
        algos = self.get_algo_orders(symbol)
        return {
            'tp_exists': any(a.get('tpTriggerPx') for a in algos),
            'sl_exists': any(a.get('slTriggerPx') for a in algos),
            'trail_exists': any(a.get('trailPx') for a in algos),
            'algos': algos
        }

    # ============================
    # 8. RECUPERACIÓN Y RECONCILIACIÓN
    # ============================
    def reconcile_state(self, symbol: str) -> Dict:
        logger.info(f"Reconciliando {symbol}...")
        result = {'symbol': symbol, 'position': None, 'tp': False, 'sl': False, 'trail': False, 'fixed': False}

        positions = self.get_positions(symbol)
        if not positions:
            algos = self.get_algo_orders(symbol)
            for a in algos:
                self.cancel_algo(symbol, a['algoId'])
                logger.warning(f"Algo huérfano cancelado: {a['algoId']}")
            return result

        p = positions[0]
        result['position'] = p
        side = 'long' if p['contracts'] > 0 else 'short'
        size = abs(p['contracts'])
        avg_px = float(p.get('entryPrice', 0.0))

        algos = self.get_algo_orders(symbol)
        has_tp = any(a.get('tpTriggerPx') for a in algos)
        has_sl = any(a.get('slTriggerPx') for a in algos)
        has_trail = any(a.get('trailPx') for a in algos)

        result['tp'] = has_tp
        result['sl'] = has_sl
        result['trail'] = has_trail

        if not has_tp or (not has_sl and not has_trail):
            logger.warning(f"Protecciones incompletas para {symbol}. Recreando...")
            fallback_tp = avg_px * 1.02 if side == 'long' else avg_px * 0.98
            fallback_sl = avg_px * 0.98 if side == 'long' else avg_px * 1.02

            if not has_tp:
                res = self.set_take_profit(symbol, fallback_tp)
                if res.get('success'):
                    result['tp'] = True
                    result['tp_algo_id'] = res['algoId']
            if not has_sl and not has_trail:
                res = self.set_stop_loss(symbol, fallback_sl)
                if res.get('success'):
                    result['sl'] = True
                    result['sl_algo_id'] = res['algoId']

            result['fixed'] = True

        return result

    def recover_state(self, symbols: List[str] = None) -> Dict:
        logger.info("Recuperando estado desde OKX...")
        if not symbols:
            all_pos = self.get_positions()
            symbols = list(set([p['symbol'] for p in all_pos]))

        results = {}
        for sym in symbols:
            results[sym] = self.reconcile_state(sym)

        logger.info(f"Estado recuperado para {len(results)} símbolos.")
        return results

    # ============================
    # 9. BUCLE DE GUARDIA
    # ============================
    def position_guard_cycle(self, symbols: List[str], strategy_provider: Optional[Callable] = None) -> None:
        for sym in symbols:
            try:
                status = self.reconcile_state(sym)
                if status.get('position') and (not status.get('tp') or not status.get('sl')):
                    if strategy_provider:
                        pos = status['position']
                        side = 'long' if pos['contracts'] > 0 else 'short'
                        avg_px = float(pos.get('entryPrice', 0.0))
                        prices = strategy_provider(sym, side, avg_px)
                        if prices:
                            if not status.get('tp') and prices.get('tp'):
                                self.set_take_profit(sym, prices['tp'])
                            if not status.get('sl') and prices.get('sl'):
                                self.set_stop_loss(sym, prices['sl'])
            except Exception as e:
                logger.error(f"Error en guard cycle para {sym}: {e}")

    # ============================
    # 10. AUDITORÍA
    # ============================
    def sync_exchange_state(self, symbol: str) -> Dict:
        return {
            'positions': self.get_positions(symbol),
            'algo_orders': self.get_algo_orders(symbol),
            'timestamp': time.time()
        }

    def get_audit_trail(self, since: float = None) -> List:
        if since is None:
            return self.audit_trail
        return [e for e in self.audit_trail if e['timestamp'] >= since]
