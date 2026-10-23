"""JSON HTTP API for the phone app (see docs/API.md). Standard library only."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .controller import CommandError, Controller
from .history import EventLog, History

log = logging.getLogger(__name__)

MAX_BODY = 4096


class ApiServer:
    def __init__(self, host: str, port: int, controller: Controller, history: History, events: EventLog):
        handler = type("Handler", (_Handler,), {"controller": controller, "history": history, "events": events})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> None:
        self._thread.start()
        log.info("HTTP API listening on port %d", self.port)

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class _Handler(BaseHTTPRequestHandler):
    controller: Controller
    history: History
    events: EventLog
    server_version = f"hcp/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # route access log to debug level
        log.debug("%s %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------- helpers

    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self.close_connection = True  # the request body may be unread; don't reuse the connection
        self._send(status, {"error": message})

    def _body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._error(413 if length > MAX_BODY else 400, "invalid request body size")
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._error(400, "request body must be JSON")
            return None
        if not isinstance(data, dict):
            self._error(400, "request body must be a JSON object")
            return None
        return data

    @staticmethod
    def _query_number(query: dict, name: str, default: float, lo: float, hi: float) -> float:
        try:
            value = float(query.get(name, [default])[0])
        except ValueError:
            raise CommandError(400, f"{name} must be a number")
        return max(lo, min(hi, value))

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        route = (method, url.path.rstrip("/") or "/")
        handler = _ROUTES.get(route)
        if handler is None:
            known = {path for (_, path) in _ROUTES}
            self._error(405 if route[1] in known else 404, "not found" if route[1] not in known
                        else f"{method} not allowed")
            return
        try:
            handler(self, parse_qs(url.query))
        except CommandError as e:
            self._error(e.status, str(e))
        except Exception:
            log.exception("API error on %s %s", method, self.path)
            self._error(500, "internal error")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    # ------------------------------------------------------------- endpoints

    def get_health(self, query):
        self._send(200, {"ok": True, "version": __version__})

    def get_status(self, query):
        self._send(200, self.controller.status())

    def get_history(self, query):
        hours = self._query_number(query, "hours", 6, 0.1, self.history.hours)
        points = int(self._query_number(query, "max_points", 360, 10, 2000))
        self._send(200, {"hours": hours, "points": self.history.query(hours, points)})

    def get_events(self, query):
        limit = int(self._query_number(query, "limit", 50, 1, 200))
        self._send(200, {"events": self.events.recent(limit)})

    def put_mode(self, query):
        body = self._body()
        if body is None:
            return
        self.controller.set_mode(body.get("mode"))
        self._send(200, self.controller.status())

    def put_target(self, query):
        body = self._body()
        if body is None:
            return
        self.controller.set_target(body.get("temperature"))
        self._send(200, self.controller.status())

    def put_night_saver(self, query):
        body = self._body()
        if body is None:
            return
        self.controller.set_night_saver(body.get("enabled"))
        self._send(200, self.controller.status())

    def post_valve_move(self, query):
        body = self._body()
        if body is None:
            return
        self.controller.manual_move(steps=body.get("steps"), position=body.get("position"))
        self._send(202, self.controller.status())

    def post_valve_calibrate(self, query):
        if self._body() is None:
            return
        self.controller.request_calibration()
        self._send(202, self.controller.status())

    def post_zero_start(self, query):
        if self._body() is None:
            return
        self.controller.start_zero_calibration()
        self._send(202, self.controller.status())

    def post_zero_jog(self, query):
        body = self._body()
        if body is None:
            return
        self.controller.zero_jog(body.get("steps"))
        self._send(202, self.controller.status())

    def post_zero_set(self, query):
        if self._body() is None:
            return
        self.controller.finish_zero_calibration()
        self._send(202, self.controller.status())

    def post_zero_cancel(self, query):
        if self._body() is None:
            return
        self.controller.cancel_zero_calibration()
        self._send(202, self.controller.status())


_ROUTES = {
    ("GET", "/api/health"): _Handler.get_health,
    ("GET", "/api/status"): _Handler.get_status,
    ("GET", "/api/history"): _Handler.get_history,
    ("GET", "/api/events"): _Handler.get_events,
    ("PUT", "/api/mode"): _Handler.put_mode,
    ("PUT", "/api/target"): _Handler.put_target,
    ("PUT", "/api/night-saver"): _Handler.put_night_saver,
    ("POST", "/api/valve/move"): _Handler.post_valve_move,
    ("POST", "/api/valve/calibrate"): _Handler.post_valve_calibrate,
    ("POST", "/api/valve/zero/start"): _Handler.post_zero_start,
    ("POST", "/api/valve/zero/jog"): _Handler.post_zero_jog,
    ("POST", "/api/valve/zero/set"): _Handler.post_zero_set,
    ("POST", "/api/valve/zero/cancel"): _Handler.post_zero_cancel,
}
