from abc import ABC, abstractmethod
from typing import Dict, Any

class StrategyBase(ABC):
    """Abstract base class for all trading strategies."""

    @abstractmethod
    def on_tick(self, engine, symbol: str, telemetry) -> Dict[str, Any]:
        """
        Called every loop cycle.
        Should return a dict with decisions:
        {
            'action': 'open_long' | 'open_short' | 'close' | 'hold',
            'size': float,
            'tp_price': float (optional),
            'sl_price': float (optional),
            'trail_distance': float (optional)
        }
        """
        pass

    @abstractmethod
    def name(self) -> str:
        pass
