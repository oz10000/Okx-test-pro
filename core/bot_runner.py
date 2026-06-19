import time
import logging
from typing import Optional, Callable
from engine.exchange_engine import ExchangeEngine
from strategies.base import StrategyBase
from .telemetry import Telemetry

logger = logging.getLogger(__name__)

class BotRunner:
    def __init__(self, engine: ExchangeEngine, strategy: StrategyBase,
                 symbol: str, telemetry: Telemetry,
                 cycle_interval: float = 5.0):
        self.engine = engine
        self.strategy = strategy
        self.symbol = symbol
        self.telemetry = telemetry
        self.cycle_interval = cycle_interval
        self._running = False

    def run(self, max_cycles: Optional[int] = None):
        """Run the main loop. If max_cycles is given, stop after that many."""
        self._running = True
        cycles = 0
        while self._running:
            try:
                self._cycle()
                cycles += 1
                if max_cycles and cycles >= max_cycles:
                    logger.info(f"Reached max cycles ({max_cycles}), stopping.")
                    break
                time.sleep(self.cycle_interval)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}")
                self.telemetry.log_error("cycle_error", str(e))
                time.sleep(self.cycle_interval)

    def _cycle(self):
        # 1. Sync state from exchange (reconcile)
        self.engine.reconcile_state(self.symbol)

        # 2. Get current state
        positions = self.engine.get_positions(self.symbol)
        algos = self.engine.get_algo_orders(self.symbol)

        # 3. Record telemetry
        self.telemetry.log_state("pre_tick", {
            'symbol': self.symbol,
            'positions': positions,
            'algo_orders': algos
        })

        # 4. Call strategy
        decision = self.strategy.on_tick(self.engine, self.symbol, self.telemetry)
        self.telemetry.log_decision(self.strategy.name(), decision)

        # 5. Execute decision
        action = decision.get('action')
        if action == 'open_long':
            size = decision.get('size', 1)
            tp = decision.get('tp_price')
            sl = decision.get('sl_price')
            trail = decision.get('trail_distance')
            result = self.engine.open_position(self.symbol, 'buy', size, tp, sl, trail)
            self.telemetry.log_order('open_long', result)
        elif action == 'open_short':
            size = decision.get('size', 1)
            tp = decision.get('tp_price')
            sl = decision.get('sl_price')
            trail = decision.get('trail_distance')
            result = self.engine.open_position(self.symbol, 'sell', size, tp, sl, trail)
            self.telemetry.log_order('open_short', result)
        elif action == 'close':
            result = self.engine.close_position(self.symbol)
            self.telemetry.log_order('close', result)
        # else hold

        # 6. Post-tick state
        self.telemetry.log_state("post_tick", {
            'symbol': self.symbol,
            'positions': self.engine.get_positions(self.symbol),
            'algo_orders': self.engine.get_algo_orders(self.symbol)
        })

    def stop(self):
        self._running = False
