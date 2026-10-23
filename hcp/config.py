"""Configuration.

All tunables live here with the values the original controller used.  A JSON
file (default: ``config.json`` next to the package, see ``config.example.json``)
can override any subset of them; unknown keys are rejected so typos are noticed.

Valve positions are counted in relay pulses (``valve.pulse_seconds`` each)
relative to the zero point, where water just starts to flow.  The zero point
lies ``zero_offset`` pulses above the mechanical end stop; it is measured with
the zero-point calibration in the app and stored in data/state.json
(``default_zero_offset`` is used until then).  This is the scale of the
original controller, which treated fully closed as -25.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict

# Sensor roles, in the column order used by the CSV log.
MAIN_INLET = "mainInlet"
MAIN_RETURN = "mainReturn"
HEATING_INLET = "heatingInlet"
HEATING_RETURN = "heatingReturn"
WATER_INLET = "waterInlet"
SENSOR_ROLES = (MAIN_INLET, MAIN_RETURN, HEATING_INLET, HEATING_RETURN, WATER_INLET)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigError(ValueError):
    pass


@dataclass
class HttpConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class SensorConfig:
    # DS18B20 1-Wire IDs (see /sys/bus/w1/devices/28-*). Replace after swapping a sensor.
    ids: Dict[str, str] = field(default_factory=lambda: {
        MAIN_INLET: "28-3ce1d458c862",
        MAIN_RETURN: "28-3ce1e380b738",
        HEATING_INLET: "28-3ce1e380d089",
        HEATING_RETURN: "28-3ce1e3802805",
        WATER_INLET: "28-3ce1e380cd60",
    })
    w1_dir: str = "/sys/bus/w1/devices"
    read_interval_seconds: float = 10.0
    # A reading older than this is treated as missing.
    stale_after_seconds: float = 60.0
    crc_retries: int = 3
    # Plausible range for water temperatures; anything outside is a sensor fault.
    min_valid: float = -20.0
    max_valid: float = 110.0


@dataclass
class RelayConfig:
    i2c_bus: int = 1
    address: int = 0x10
    register_up: int = 1      # relay that opens the valve
    register_down: int = 2    # relay that closes the valve
    write_retries: int = 3


@dataclass
class ValveConfig:
    pulse_seconds: float = 0.5
    # Pulses needed to travel from fully closed to fully open (turndown.sh used 60 s = 120 pulses).
    full_stroke_pulses: int = 120
    # Extra pulses driven when closing fully, so the counter is re-zeroed at the end stop.
    close_overtravel_pulses: int = 20
    # Pause between switching directions so both relays are never energised together.
    direction_change_pause_seconds: float = 0.5
    # Pulses from the end stop to where water starts to flow, until calibrated in the app.
    default_zero_offset: int = 25
    ready_position: int = 9    # opened to this when auto mode starts
    auto_min: int = 10         # auto control never closes below this
    auto_max: int = 41         # auto control never opens above this
    reduced_position: int = 0  # used for overheat / no consumption
    calibrate_on_startup: bool = True
    # An unfinished zero-point calibration is cancelled after this long.
    zero_calibration_timeout_minutes: float = 30.0


@dataclass
class ControlConfig:
    default_target: int = 50
    target_min: int = 30
    target_max: int = 75
    # Main return is kept inside [target, target + upper_band].
    upper_band: int = 10
    heating_inlet_min: float = 30.0
    inlet_plus_return_low: float = 70.0
    inlet_plus_return_high: float = 95.0
    interval_seconds: float = 15.0
    wait_after_up_seconds: float = 60.0
    wait_after_down_seconds: float = 30.0


@dataclass
class MonitorConfig:
    interval_seconds: float = 15.0
    trend_samples: int = 5
    no_consumption_main_return_above: float = 65.0
    no_consumption_delta_below: float = 3.0
    no_consumption_clear_main_return_below: float = 60.0
    no_consumption_clear_delta_above: float = 5.0
    heating_getting_hot_above: float = 55.0
    heating_too_hot_above: float = 65.0
    heating_ok_below: float = 45.0
    water_tank_delta_above: float = 10.0
    water_tank_main_inlet_above: float = 70.0
    water_tank_water_inlet_above: float = 60.0
    water_tank_timeout_minutes: float = 90.0
    # Natural end, checked only after the minimum duration: the tank no longer takes heat
    # (main inlet - main return below this), or the water inlet keeps falling by this much.
    water_tank_min_minutes: float = 5.0
    water_tank_end_delta_below: float = 5.0
    water_tank_end_drop: float = 2.0


@dataclass
class NightSaverConfig:
    # Heating is switched off between these local times ("HH:MM") while the night saver
    # is enabled in the app.  A window may cross midnight (e.g. "22:00" to "06:00").
    start: str = "00:30"
    end: str = "06:30"


def parse_hhmm(text: str) -> int:
    """'06:30' -> minutes after midnight."""
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
    except (AttributeError, ValueError):
        raise ConfigError(f"time must look like HH:MM, got {text!r}")
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ConfigError(f"time must look like HH:MM, got {text!r}")
    return h * 60 + m


@dataclass
class MqttConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = "home/hcp"


@dataclass
class Config:
    data_dir: str = os.path.join(PROJECT_DIR, "data")
    history_hours: float = 48.0
    simulate: bool = False
    http: HttpConfig = field(default_factory=HttpConfig)
    sensors: SensorConfig = field(default_factory=SensorConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    valve: ValveConfig = field(default_factory=ValveConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    night_saver: NightSaverConfig = field(default_factory=NightSaverConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)

    @property
    def log_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    @property
    def state_file(self) -> str:
        return os.path.join(self.data_dir, "state.json")

    def validate(self) -> None:
        v, c = self.valve, self.control
        if not 0 <= v.reduced_position <= v.ready_position <= v.auto_min < v.auto_max:
            raise ConfigError(
                "valve positions must satisfy 0 <= reduced_position <= ready_position <= auto_min < auto_max")
        if not 0 <= v.default_zero_offset <= v.full_stroke_pulses - v.auto_max:
            raise ConfigError("valve.default_zero_offset + valve.auto_max must not exceed full_stroke_pulses")
        if v.zero_calibration_timeout_minutes <= 0:
            raise ConfigError("valve.zero_calibration_timeout_minutes must be positive")
        if min(v.pulse_seconds, v.close_overtravel_pulses, v.direction_change_pause_seconds,
               c.wait_after_up_seconds, c.wait_after_down_seconds, c.upper_band) < 0:
            raise ConfigError("valve / control timings must not be negative")
        if min(c.interval_seconds, self.monitor.interval_seconds, self.sensors.read_interval_seconds,
               self.sensors.stale_after_seconds) <= 0:
            raise ConfigError("intervals must be positive")
        if not c.target_min <= c.default_target <= c.target_max:
            raise ConfigError("control.default_target must be within [target_min, target_max]")
        missing = set(SENSOR_ROLES) - set(self.sensors.ids)
        if missing:
            raise ConfigError(f"sensors.ids is missing roles: {sorted(missing)}")
        if parse_hhmm(self.night_saver.start) == parse_hhmm(self.night_saver.end):
            raise ConfigError("night_saver.start and night_saver.end must differ")
        if self.monitor.trend_samples < 2:
            raise ConfigError("monitor.trend_samples must be at least 2")


def _merge(obj: Any, overrides: Dict[str, Any], path: str) -> None:
    fields = {f.name: f for f in dataclasses.fields(obj)}
    for key, value in overrides.items():
        if key.startswith("_"):  # allow "_comment" keys in JSON
            continue
        if key not in fields:
            raise ConfigError(f"unknown config key: {path}{key}")
        current = getattr(obj, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key} must be an object")
            _merge(current, value, f"{path}{key}.")
        elif key == "ids":
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                raise ConfigError(f"{path}{key} must map sensor roles to ID strings")
            current.update(value)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{path}{key} must be true or false")
            setattr(obj, key, value)
        elif isinstance(current, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigError(f"{path}{key} must be a finite number")
            if isinstance(current, int):
                if value != int(value):
                    raise ConfigError(f"{path}{key} must be a whole number")
                value = int(value)
            setattr(obj, key, type(current)(value))
        else:
            if not isinstance(value, type(current)):
                raise ConfigError(f"{path}{key} has the wrong type")
            setattr(obj, key, value)


def load_config(path: str | None = None) -> Config:
    """Load defaults, then overrides from ``path`` (or ``$HCP_CONFIG`` / ``config.json``)."""
    cfg = Config()
    path = path or os.environ.get("HCP_CONFIG") or os.path.join(PROJECT_DIR, "config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ConfigError(f"{path}: {e}") from e
        _merge(cfg, data, "")
        if not os.path.isabs(cfg.data_dir):
            cfg.data_dir = os.path.join(os.path.dirname(os.path.abspath(path)), cfg.data_dir)
    cfg.validate()
    return cfg
