"""Relay drivers for the valve motor (open / close direction)."""

from __future__ import annotations

import logging
import threading
import time

from .config import RelayConfig

log = logging.getLogger(__name__)

UP = "up"
DOWN = "down"


class RelayError(Exception):
    pass


class I2CRelay:
    """The I²C relay board: writing 0xFF to a register energises that relay, 0x00 releases it."""

    def __init__(self, cfg: RelayConfig):
        self.cfg = cfg
        try:
            from smbus2 import SMBus  # type: ignore
        except ImportError:
            from smbus import SMBus  # type: ignore  # apt: python3-smbus
        self._bus = SMBus(cfg.i2c_bus)
        self._lock = threading.Lock()
        self._registers = {UP: cfg.register_up, DOWN: cfg.register_down}

    def _write(self, register: int, value: int) -> None:
        last_error = None
        for _ in range(max(1, self.cfg.write_retries)):
            try:
                self._bus.write_byte_data(self.cfg.address, register, value)
                return
            except OSError as e:
                last_error = e
                time.sleep(0.05)
        raise RelayError(f"I2C write to register {register} failed: {last_error}")

    def energize(self, direction: str) -> None:
        with self._lock:
            other = DOWN if direction == UP else UP
            self._write(self._registers[other], 0x00)
            self._write(self._registers[direction], 0xFF)

    def all_off(self) -> None:
        """Release both relays. Tries both even if the first write fails."""
        with self._lock:
            errors = []
            for register in (self.cfg.register_up, self.cfg.register_down):
                try:
                    self._write(register, 0x00)
                except RelayError as e:
                    errors.append(str(e))
            if errors:
                raise RelayError("; ".join(errors))


class FakeRelay:
    """In-memory relay used by the simulator and tests."""

    def __init__(self):
        self.active = None
        self.history = []

    def energize(self, direction: str) -> None:
        self.active = direction
        self.history.append(direction)

    def all_off(self) -> None:
        self.active = None
        self.history.append("off")
