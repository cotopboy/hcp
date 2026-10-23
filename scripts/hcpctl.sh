#!/usr/bin/env bash
# Command-line control through the HTTP API (works on the Pi or any machine on the LAN).
#   HCP_URL=http://hcp.local:8080 ./scripts/hcpctl.sh status
#   ./scripts/hcpctl.sh mode auto|manual|off
#   ./scripts/hcpctl.sh target 52
#   ./scripts/hcpctl.sh move +5 | -5      (manual mode, pulses)
#   ./scripts/hcpctl.sh position 40       (manual mode, absolute)
#   ./scripts/hcpctl.sh calibrate
#   ./scripts/hcpctl.sh zero start|set|cancel   zero-point calibration
#   ./scripts/hcpctl.sh zero jog +5             (during zero-point calibration)
#   ./scripts/hcpctl.sh events
set -euo pipefail
URL="${HCP_URL:-http://localhost:8080}"
pretty() { python3 -m json.tool; }
case "${1:-status}" in
  status) curl -fsS "$URL/api/status" | pretty ;;
  events) curl -fsS "$URL/api/events?limit=30" | pretty ;;
  mode) curl -sS -X PUT "$URL/api/mode" -d "{\"mode\":\"$2\"}" | pretty ;;
  target) curl -sS -X PUT "$URL/api/target" -d "{\"temperature\":$2}" | pretty ;;
  move) curl -sS -X POST "$URL/api/valve/move" -d "{\"steps\":${2#+}}" | pretty ;;
  position) curl -sS -X POST "$URL/api/valve/move" -d "{\"position\":$2}" | pretty ;;
  calibrate) curl -sS -X POST "$URL/api/valve/calibrate" -d '{}' | pretty ;;
  zero)
    case "${2:-}" in
      start|set|cancel) curl -sS -X POST "$URL/api/valve/zero/$2" -d '{}' | pretty ;;
      jog) curl -sS -X POST "$URL/api/valve/zero/jog" -d "{\"steps\":${3#+}}" | pretty ;;
      *) echo "usage: $0 zero start|jog N|set|cancel" >&2; exit 1 ;;
    esac ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
