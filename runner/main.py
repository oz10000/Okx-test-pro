#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
runner/main.py - Orquestador principal del bot.
Ejecuta el ciclo de trading, sincroniza estado y llama a la estrategia.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

# Asegurar que el directorio raíz esté en el path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Crear directorio de logs si no existe
os.makedirs('logs', exist_ok=True)

from engine.exchange_engine import ExchangeEngine
from strategy.strategy import generate_signal

logger = logging.getLogger(__name__)

# ================================
# TELEMETRY (Logging JSON)
# ================================
class Telemetry:
    """Sistema de logging estructurado en JSON para auditoría y CI."""

    @staticmethod
    def log(event_type: str, data: Dict[str, Any]):
        """Registra un evento en stdout y en archivo."""
        entry = {
            'timestamp': time.time(),
            'datetime': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'data': data
        }
        # Salida a stdout (CI-friendly)
        print(json.dumps(entry))

        # Persistencia en archivo
        try:
            with open('logs/execution.jsonl', 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass  # Silencioso para no romper el flujo

# ================================
# FUNCIÓN PRINCIPAL
# ================================
def main():
    """Punto de entrada del runner."""
    # Configurar logging básico
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Credenciales desde variables de entorno
    api_key = os.getenv('OKX_API_KEY')
    secret_key = os.getenv('OKX_SECRET_KEY')
    passphrase = os.getenv('OKX_PASSPHRASE')

    if not all([api_key, secret_key, passphrase]):
        logger.error("❌ Faltan variables: OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE")
        sys.exit(1)

    # Configuración
    symbol = os.getenv('SYMBOL', 'BTC-USDT-SWAP')
    max_cycles = int(os.getenv('MAX_CYCLES', '0'))  # 0 = infinito
    cycle_interval = int(os.getenv('CYCLE_INTERVAL', '5'))

    # Modo CI: limitar ciclos si no se especifica
    if os.getenv('CI') == 'true' and max_cycles == 0:
        max_cycles = 2
        logger.info("🔁 Modo CI: limitado a 2 ciclos")

    # Inicializar engine (sandbox forzado para pruebas)
    engine = ExchangeEngine(sandbox=True)
    if not engine.connect():
        logger.error("❌ No se pudo conectar a OKX")
        sys.exit(1)

    logger.info(f"📊 Símbolo: {symbol}")
    logger.info(f"🔄 Ciclos: {'infinito' if max_cycles == 0 else max_cycles}")
    logger.info(f"⏱️  Intervalo: {cycle_interval}s")

    # Log inicial
    Telemetry.log('bot_start', {
        'symbol': symbol,
        'max_cycles': max_cycles,
        'sandbox': True
    })

    loop = 0
    try:
        while max_cycles == 0 or loop < max_cycles:
            loop += 1
            logger.info(f"--- Ciclo {loop} ---")

            try:
                # 1. Obtener estado actual
                positions = engine.fetch_positions(symbol)
                ticker = engine.fetch_ticker(symbol)
                balance = engine.fetch_balance('USDT')

                Telemetry.log('state_pre', {
                    'symbol': symbol,
                    'positions': positions,
                    'balance_usdt': balance,
                    'position_count': len(positions)
                })

                # 2. Generar señal
                context = {
                    'symbol': symbol,
                    'positions': positions,
                    'balance': balance,
                    'ticker_price': ticker.get('last', 0.0),
                    'timestamp': time.time()
                }
                signal = generate_signal(context)
                Telemetry.log('signal', signal)

                # 3. Ejecutar acción
                action = signal.get('action')

                if action == 'buy':
                    size = signal.get('size', 1.0)
                    tp = signal.get('tp')
                    sl = signal.get('sl')
                    logger.info(f"📈 Ejecutando BUY {size} contratos")
                    result = engine.create_market_order(symbol, 'buy', size)
                    Telemetry.log('order', {'action': 'buy', 'result': result})
                    if result.get('success') and tp and sl:
                        engine.set_tp_sl(symbol, tp, sl)
                        Telemetry.log('protection', {'tp': tp, 'sl': sl})

                elif action == 'sell':
                    size = signal.get('size', 1.0)
                    tp = signal.get('tp')
                    sl = signal.get('sl')
                    logger.info(f"📉 Ejecutando SELL {size} contratos")
                    result = engine.create_market_order(symbol, 'sell', size)
                    Telemetry.log('order', {'action': 'sell', 'result': result})
                    if result.get('success') and tp and sl:
                        engine.set_tp_sl(symbol, tp, sl)

                elif action == 'close':
                    logger.info("🔚 Cerrando posición")
                    engine.close_position(symbol)
                    Telemetry.log('close', {'symbol': symbol})

                elif action == 'hold':
                    logger.info("⏸️ Manteniendo posición")

                else:
                    logger.warning(f"⚠️ Acción desconocida: {action}")

                # 4. Reconciliar estado post-ejecución
                post_state = engine.reconcile_state(symbol)
                Telemetry.log('state_post', post_state)

                if max_cycles > 0 and loop >= max_cycles:
                    break
                time.sleep(cycle_interval)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"❌ Error en ciclo {loop}: {e}")
                Telemetry.log('error', {'message': str(e), 'cycle': loop})
                # Reconciliar tras error para mantener consistencia
                engine.reconcile_state(symbol)
                time.sleep(cycle_interval)

    except KeyboardInterrupt:
        logger.info("🛑 Interrupción manual")

    logger.info(f"🏁 Bot finalizado después de {loop} ciclos")
    Telemetry.log('bot_end', {'total_cycles': loop})
    sys.exit(0)

if __name__ == "__main__":
    main()
