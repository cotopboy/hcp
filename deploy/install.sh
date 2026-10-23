#!/usr/bin/env bash
# One-time setup on the Raspberry Pi (Raspberry Pi OS Bookworm). Safe to run again.
# Usage, from the install directory:  sudo ./deploy/install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "run with sudo: sudo $0" >&2
  exit 1
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-pi}"
echo "==> install dir: $DIR, service user: $RUN_USER"

echo "==> packages"
MISSING=()
for pkg in python3 python3-smbus i2c-tools avahi-daemon; do
  dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg")
done
if (( ${#MISSING[@]} )); then
  # A broken third-party apt source must not stop the install; try with what is cached.
  apt-get update -qq || echo "   warning: apt-get update failed, continuing with cached package lists"
  apt-get install -y -qq "${MISSING[@]}"
else
  echo "   all required packages already installed"
fi

echo "==> enable I2C and 1-Wire (takes effect after reboot)"
NEED_REBOOT=0
if command -v raspi-config >/dev/null; then
  if [[ "$(raspi-config nonint get_i2c)" != "0" ]]; then raspi-config nonint do_i2c 0; NEED_REBOOT=1; fi
  if [[ "$(raspi-config nonint get_onewire)" != "0" ]]; then raspi-config nonint do_onewire 0; NEED_REBOOT=1; fi
else
  echo "   raspi-config not found: enable dtparam=i2c_arm=on and dtoverlay=w1-gpio in /boot/firmware/config.txt yourself"
fi
usermod -aG i2c,gpio "$RUN_USER" || true

echo "==> config"
if [[ ! -f "$DIR/config.json" ]]; then
  cp "$DIR/config.example.json" "$DIR/config.json"
  chown "$RUN_USER": "$DIR/config.json"
  echo "   created config.json from the example — check the sensor IDs!"
fi
mkdir -p "$DIR/data"
PORT=$(cd "$DIR" && python3 -c 'from hcp.config import load_config; print(load_config().http.port)')
chown -R "$RUN_USER": "$DIR/data"

if pgrep -f hcpmain.py >/dev/null; then
  echo "!! the old controller (hcpmain.py) is running. Stop it and remove its autostart"
  echo "   (crontab -e / /etc/rc.local / screen) — two controllers must never drive the valve."
  exit 1
fi

echo "==> systemd service"
sed -e "s|@USER@|$RUN_USER|" -e "s|@DIR@|$DIR|" "$DIR/deploy/hcp.service" > /etc/systemd/system/hcp.service
systemctl daemon-reload
systemctl enable hcp.service

echo "==> Bonjour advertisement"
sed -e "s|<port>8080</port>|<port>$PORT</port>|" "$DIR/deploy/hcp-avahi.service" > /etc/avahi/services/hcp.service
systemctl enable --now avahi-daemon
systemctl reload avahi-daemon || true

if [[ $NEED_REBOOT == 1 ]]; then
  echo "==> I2C / 1-Wire were just enabled: reboot now (sudo reboot); the service starts automatically."
else
  systemctl restart hcp.service
  sleep 3
  systemctl --no-pager status hcp.service | head -5
  echo "==> done. Test:  curl http://$(hostname).local:$PORT/api/status"
fi
