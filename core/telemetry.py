import json
import time
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

class Telemetry:
    """Central logging system for engine events, decisions, and errors."""

    def __init__(self, log_file: str = "telemetry.jsonl"):
        self.log_file = log_file
        self._entries = []

    def _log(self, event_type: str, data: Dict[str, Any]):
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            **data
        }
        # Always log to stdout (CI friendly)
        print(json.dumps(entry))
        # Also store in memory and optionally write to file
        self._entries.append(entry)
        if len(self._entries) > 1000:
            self._entries.pop(0)

    def log_state(self, phase: str, state: Dict):
        self._log("state", {"phase": phase, "state": state})

    def log_decision(self, strategy_name: str, decision: Dict):
        self._log("decision", {"strategy": strategy_name, "decision": decision})

    def log_order(self, action: str, result: Dict):
        self._log("order", {"action": action, "result": result})

    def log_error(self, error_type: str, message: str):
        self._log("error", {"error_type": error_type, "message": message})

    def log_engine_audit(self, audit_entry: Dict):
        # Forward from engine internal audit
        self._log("engine_audit", audit_entry)

    def get_entries(self):
        return self._entries
