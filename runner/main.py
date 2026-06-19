#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py - Punto de entrada del bot.
Orquesta el engine, la estrategia y la telemetría.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# Añadir directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.exchange_engine import ExchangeEngine
from strategy.strategy import generate_signal

load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('BotRunner')

# ======================== TELEMETRÍA ========================

class Telemetry:
    """Sistema de logging JSON para CI y auditoría."""

    @staticmethod
    def log(event_type: str, data: dict, log_file: str = 'logs/execution.jsonl'):
        entry = {
            'timestamp': time.time(),
            'datetime': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'data': data
        }
        # Escribir a stdout para CI
        print(json.dumps(entry))

        # Escribir a archivo
        try:
            os.makedirs('logs', exist_ok=True)
            with open(log_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            logger.debug(f"No se pudo escribir log: {e}")

    @staticmethod
    def log_state(engine, symbol: str, phase: str):
        """Log del estado actual del sistema."""
        positions = engine.fetch_positions(symbol)
        balance = engine.fetch_balance('USDT')
        Telemetry.log(f'state_{phase}', {
            'symbol': symbol,
            'positions': positions,
            'balance_usdt': balance,
            'position_count': len(positions)
        })

# ======================== BOT RUNNER ========================

def main():
    # Credenciales
    api_key = os.getenv('OKX_API_KEY')
    secret_key = os.getenv('OKX_SECRET_KEY')
    passphrase = os.getenv('OKX_PASSPHRASE')

    if not all([api_key, secret_key, passphrase]):
        logger.error("❌ Faltan credenciales. Configura OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE")
        sys.exit(1)

    # Configuración
    symbol = os.getenv('SYMBOL', 'BTC-USDT-SWAP')
    max_cycles = int(os.getenv('MAX_CYCLES', '0'))  # 0 = infinito
    cycle_interval = int(os.getenv('CYCLE_INTERVAL', '5'))

    # CI mode: limitar ciclos si no se especifica
    if os.getenv('CI') == 'true' and max_cycles == 0:
        max_cycles = 2
        logger.info("🔁 Modo CI: limitado a 2 ciclos")

    # Inicializar engine
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

                Telemetry.log_state(engine, symbol, 'pre_tick')

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
                    logger.info(f"📈 Ejecutando BUY {size} contratos")
                    result = engine.create_market_order(symbol, 'buy', size)
                    Telemetry.log('order', {'action': 'buy', 'result': result})

                    if result.get('success'):
                        tp = signal.get('tp')
                        sl = signal.get('sl')
                        if tp and sl:
                            logger.info(f"🔒 Colocando TP={tp}, SL={sl}")
                            engine.set_tp_sl(symbol, tp, sl)

                elif action == 'sell':
                    size = signal.get('size', 1.0)
                    logger.info(f"📉 Ejecutando SELL {size} contratos")
                    result = engine.create_market_order(symbol, 'sell', size)
                    Telemetry.log('order', {'action': 'sell', 'result': result})

                elif action == 'hold':
                    logger.info("⏸️ Manteniendo posición actual")

                elif action == 'close':
                    logger.info("🔚 Cerrando posición")
                    engine.close_position(symbol)

                else:
                    logger.warning(f"⚠️ Acción desconocida: {action}")

                # 4. Estado post-ejecución
                Telemetry.log_state(engine, symbol, 'post_tick')

                # 5. Esperar
                if max_cycles > 0 and loop >= max_cycles:
                    break
                time.sleep(cycle_interval)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"❌ Error en ciclo {loop}: {e}")
                Telemetry.log('error', {'message': str(e), 'cycle': loop})
                time.sleep(cycle_interval)

    except KeyboardInterrupt:
        logger.info("🛑 Interrupción manual")

    # Cierre
    logger.info(f"🏁 Bot finalizado después de {loop} ciclos")
    Telemetry.log('bot_end', {'total_cycles': loop})
    sys.exit(0)

if __name__ == '__main__':
    main()
