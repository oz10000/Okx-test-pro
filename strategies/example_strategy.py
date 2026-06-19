from .base import StrategyBase

class ExampleStrategy(StrategyBase):
    """Simple strategy: if no position, open long with fixed TP/SL."""

    def name(self) -> str:
        return "ExampleStrategy"

    def on_tick(self, engine, symbol: str, telemetry):
        positions = engine.get_positions(symbol)
        if not positions:
            # Open a long with a fixed size (1 contract)
            return {
                'action': 'open_long',
                'size': 1,
                'tp_price': None,   # will be set in the runner using engine defaults
                'sl_price': None,
                'trail_distance': None
            }
        else:
            # Do nothing else (engine will maintain existing protections)
            return {'action': 'hold'}
