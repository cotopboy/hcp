#!/usr/bin/env bash
# Hardware bring-up only: pulse one relay directly over I2C.
# Stop the service first (sudo systemctl stop hcp) — this bypasses the position counter,
# so run a calibration from the app afterwards.
#   ./scripts/relay_test.sh up|down [seconds]
set -euo pipefail
ADDR=0x10
case "${1:-}" in
  up) REG=0x01 ;;
  down) REG=0x02 ;;
  *) echo "usage: $0 up|down [seconds]" >&2; exit 1 ;;
esac
SECONDS_ON="${2:-1}"
if systemctl is-active --quiet hcp 2>/dev/null; then
  echo "hcp service is running; stop it first: sudo systemctl stop hcp" >&2
  exit 1
fi
trap 'i2cset -y 1 $ADDR 0x01 0x00; i2cset -y 1 $ADDR 0x02 0x00' EXIT
i2cset -y 1 $ADDR 0x01 0x00
i2cset -y 1 $ADDR 0x02 0x00
echo "relay $1 on for ${SECONDS_ON}s"
i2cset -y 1 $ADDR "$REG" 0xFF
sleep "$SECONDS_ON"
