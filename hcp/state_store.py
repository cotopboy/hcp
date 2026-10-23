"""Persistent runtime state (mode, target temperature, valve position, night saver).

Stored as JSON and written atomically (temp file + fsync + rename) so a power
cut never leaves a half-written file.  On first start the files of the old
controller (``settings/*.txt``) are migrated if present.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODES = (MODE_OFF, MODE_AUTO, MODE_MANUAL)


@dataclass
class State:
    mode: str = MODE_AUTO
    target_temperature: int = 50
    valve_position: int = 0        # pulses above the end stop (absolute)
    valve_calibrated: bool = False
    valve_zero_offset: int = -1    # pulses from the end stop to flow start; -1 = not measured yet
    night_saver: bool = False      # heating off during the night window (config night_saver)


class StateStore:
    def __init__(self, path: str, default_target: int, legacy_dir: str = ""):
        self.path = path
        self._lock = threading.Lock()
        self.state = self._load(default_target, legacy_dir)

    def _load(self, default_target: int, legacy_dir: str) -> State:
        state = State(target_temperature=default_target)
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
                defaults = State()
                bad_valve = False
                for key, value in data.items():
                    expected = type(getattr(defaults, key, None))
                    if hasattr(state, key) and type(value) is expected:
                        setattr(state, key, value)
                    elif hasattr(state, key):
                        log.error("ignoring invalid %s=%r in state file", key, value)
                        bad_valve = bad_valve or key.startswith("valve_")
                if bad_valve:
                    state.valve_calibrated = False
            except (OSError, ValueError) as e:
                log.error("state file %s unreadable (%s); using defaults, valve uncalibrated", self.path, e)
                state = State(target_temperature=default_target)
        elif legacy_dir and os.path.isdir(legacy_dir):
            state = self._migrate_legacy(state, legacy_dir)
        if state.mode not in MODES:
            log.error("invalid mode %r in state file, using auto", state.mode)
            state.mode = MODE_AUTO
        if not isinstance(state.target_temperature, int):
            state.target_temperature = default_target
        return state

    @staticmethod
    def _migrate_legacy(state: State, legacy_dir: str) -> State:
        log.info("migrating settings from old controller in %s", legacy_dir)
        state.mode = MODE_AUTO if os.path.exists(os.path.join(legacy_dir, "heating_active.txt")) else MODE_OFF
        try:
            with open(os.path.join(legacy_dir, "target_temperature.txt")) as f:
                state.target_temperature = int(f.read().strip())
        except (OSError, ValueError):
            pass
        # The old position counter drifted; the valve is recalibrated on startup instead.
        return state

    def update(self, **changes) -> State:
        with self._lock:
            for key, value in changes.items():
                if not hasattr(self.state, key):
                    raise AttributeError(key)
                setattr(self.state, key, value)
            self._write()
            return State(**asdict(self.state))

    def snapshot(self) -> State:
        with self._lock:
            return State(**asdict(self.state))

    def _write(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self.state), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
