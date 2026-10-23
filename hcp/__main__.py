"""Entry point: ``python3 -m hcp [--config FILE] [--simulate] [--port N]``."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import __version__
from .api import ApiServer
from .config import PROJECT_DIR, SENSOR_ROLES, ConfigError, load_config
from .controller import Controller
from .history import CsvLogger, EventLog, History
from .relay import FakeRelay, I2CRelay
from .sensors import DS18B20Source, SensorService
from .state_store import StateStore
from .valve import Valve

log = logging.getLogger("hcp")


def setup_logging(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(os.path.join(log_dir, "hcp.log"), maxBytes=5 * 1024 * 1024,
                                       backupCount=5, encoding="utf-8")
    console = logging.StreamHandler()  # ends up in journald under systemd
    for handler in (file_handler, console):
        handler.setFormatter(fmt)
        root.addHandler(handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hcp", description="Heating valve controller")
    parser.add_argument("--config", help="config JSON (default: $HCP_CONFIG or ./config.json)")
    parser.add_argument("--simulate", action="store_true", help="fake sensors and relay, for development")
    parser.add_argument("--port", type=int, help="override http.port")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    cfg.simulate = cfg.simulate or args.simulate
    if args.port is not None:
        cfg.http.port = args.port
    if cfg.simulate and not args.config:
        cfg.data_dir = os.path.join(PROJECT_DIR, "data-sim")
        cfg.valve.pulse_seconds = 0.1  # faster valve so calibration does not take a minute

    setup_logging(cfg.log_dir)
    log.info("HCP %s starting (simulate=%s, data=%s)", __version__, cfg.simulate, cfg.data_dir)

    store = StateStore(cfg.state_file, cfg.control.default_target,
                       legacy_dir=os.path.join(PROJECT_DIR, "settings"))
    state = store.snapshot()
    stop = threading.Event()

    relay = FakeRelay() if cfg.simulate else I2CRelay(cfg.relay)
    valve = Valve(relay, cfg.valve, state.valve_position, state.valve_calibrated,
                  persist=lambda pos, cal: store.update(valve_position=pos, valve_calibrated=cal),
                  stop_event=stop)
    # Never start with a relay left energised by a crash.
    relay.all_off()

    if cfg.simulate:
        from .simulator import SimulatedPlant
        source = SimulatedPlant(cfg.sensors.ids, lambda: valve.position, cfg.valve.full_stroke_pulses)
    else:
        source = DS18B20Source(cfg.sensors)

    events = EventLog()
    history = History(cfg.history_hours, cfg.sensors.read_interval_seconds)
    history.load_csv(cfg.log_dir)
    csv_logger = CsvLogger(cfg.log_dir)
    sensors = SensorService(cfg.sensors, source)
    controller = Controller(cfg, sensors, valve, store, events)

    mqtt = None
    if cfg.mqtt.enabled:
        try:
            from .mqtt import MqttPublisher
            mqtt = MqttPublisher(cfg.mqtt)
        except Exception:
            log.exception("MQTT disabled: could not start publisher")

    def record(readings):
        now = dt.datetime.fromtimestamp(readings.taken_at)
        temps = {r: readings.get(r, readings.taken_at, cfg.sensors.stale_after_seconds) for r in SENSOR_ROLES}
        mode, position = controller.mode, valve.position
        csv_logger.write(now, temps, position, mode)
        history.add({"t": readings.taken_at, **temps, "valve": position, "mode": mode})
        log.info("  ".join(f"{r}={'--' if temps[r] is None else f'{temps[r]:.1f}'}" for r in SENSOR_ROLES)
                 + f"  valve={position}")
        if mqtt:
            try:
                mqtt.publish(temps, position, mode)
            except Exception:
                log.warning("MQTT publish failed", exc_info=True)

    sensors.listeners.append(record)
    sensors.read_once()

    try:
        api = ApiServer(cfg.http.host, cfg.http.port, controller, history, events)
    except OSError as e:
        log.critical("cannot listen on port %d: %s", cfg.http.port, e)
        relay.all_off()
        return 1

    def shutdown(signum, frame):
        log.info("signal %d received, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    sensors.start()
    controller.start()
    api.start()
    events.add("start", f"controller started ({controller.mode} mode)")

    stop.wait()
    api.stop()
    controller.stop()
    sensors.stop()
    csv_logger.close()
    if mqtt:
        mqtt.close()
    log.info("stopped, relays off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
