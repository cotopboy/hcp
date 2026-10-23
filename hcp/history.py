"""Temperature history: daily CSV files on disk plus an in-memory ring buffer for the API."""

from __future__ import annotations

import csv
import datetime as dt
import glob
import logging
import os
import threading
from collections import deque
from typing import Deque, Dict, List, Optional

from .config import SENSOR_ROLES

log = logging.getLogger(__name__)

CSV_HEADER = ["Timestamp", "MainInlet", "MainReturn", "HeatingInlet", "HeatingReturn", "WaterInlet",
              "ValvePosition", "Mode"]
_FILE_PREFIX = "temperature_"


class CsvLogger:
    """Appends one row per sample to ``<log_dir>/temperature_YYYYMMDD.csv``; switches file at midnight."""

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        self._date: Optional[dt.date] = None
        self._file = None
        self._writer = None

    def write(self, when: dt.datetime, temps: Dict[str, Optional[float]], valve: int, mode: str) -> None:
        try:
            if when.date() != self._date:
                self._open(when.date())
            row = [when.strftime("%Y-%m-%d %H:%M:%S")]
            row += ["" if temps.get(r) is None else f"{temps[r]:.2f}" for r in SENSOR_ROLES]
            row += [valve, mode]
            self._writer.writerow(row)
            self._file.flush()
        except OSError:
            log.exception("could not write temperature CSV")
            self.close()

    def _open(self, date: dt.date) -> None:
        self.close()
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, f"{_FILE_PREFIX}{date:%Y%m%d}.csv")
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        if self._file.tell() == 0:
            self._writer.writerow(CSV_HEADER)
        self._date = date

    def close(self) -> None:
        if self._file:
            self._file.close()
        self._file = self._writer = None
        self._date = None


class History:
    """Thread-safe ring buffer of samples: ``{"t": epoch, <role>: °C|None, "valve": int, "mode": str}``."""

    def __init__(self, hours: float, sample_seconds: float):
        self.hours = hours
        self._samples: Deque[dict] = deque(maxlen=int(hours * 3600 / max(1.0, sample_seconds)) + 10)
        self._lock = threading.Lock()

    def add(self, sample: dict) -> None:
        with self._lock:
            self._samples.append(sample)

    def query(self, hours: float, max_points: int) -> List[dict]:
        since = dt.datetime.now().timestamp() - hours * 3600
        with self._lock:
            samples = [s for s in self._samples if s["t"] >= since]
        if max_points <= 0 or len(samples) <= max_points:
            return samples
        # Average into equal buckets so the client gets a bounded number of points.
        bucket = len(samples) / max_points
        out = []
        for i in range(max_points):
            chunk = samples[int(i * bucket):int((i + 1) * bucket)] or [samples[-1]]
            point = {"t": chunk[-1]["t"], "valve": chunk[-1]["valve"], "mode": chunk[-1]["mode"]}
            for role in SENSOR_ROLES:
                vals = [s[role] for s in chunk if s.get(role) is not None]
                point[role] = round(sum(vals) / len(vals), 2) if vals else None
            out.append(point)
        return out

    def load_csv(self, log_dir: str) -> None:
        """Seed the buffer from recent CSV files so history survives a restart."""
        since = dt.datetime.now() - dt.timedelta(hours=self.hours)
        files = sorted(glob.glob(os.path.join(log_dir, f"{_FILE_PREFIX}*.csv")))
        loaded = 0
        for path in files:
            day = os.path.basename(path)[len(_FILE_PREFIX):-4]
            try:
                if dt.datetime.strptime(day, "%Y%m%d").date() < since.date():
                    continue
                with open(path, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        when = dt.datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S")
                        if when < since:
                            continue
                        sample = {"t": when.timestamp(), "valve": int(row["ValvePosition"]), "mode": row["Mode"]}
                        for role, col in zip(SENSOR_ROLES, CSV_HEADER[1:6]):
                            sample[role] = float(row[col]) if row[col] else None
                        self.add(sample)
                        loaded += 1
            except (OSError, ValueError, KeyError) as e:
                log.warning("skipping history file %s: %s", path, e)
        if loaded:
            log.info("loaded %d history samples from CSV", loaded)


class EventLog:
    """The most recent controller events, shown in the app."""

    def __init__(self, size: int = 200):
        self._events: Deque[dict] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, kind: str, message: str, level: str = "info") -> None:
        with self._lock:
            self._events.append({"t": dt.datetime.now().timestamp(), "kind": kind,
                                 "level": level, "message": message})

    def recent(self, limit: int) -> List[dict]:
        with self._lock:
            return list(self._events)[-limit:][::-1]
