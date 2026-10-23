#!/usr/bin/env bash
# Deploy from a Mac/Linux machine to the Raspberry Pi over SSH.
#   ./scripts/deploy.sh [user@host] [remote dir]
# Defaults: $HCP_TARGET or pi@hcp.local, $HCP_DIR or hcp (relative to the remote home).
# config.json and data/ on the Pi are never overwritten.
set -euo pipefail

TARGET="${1:-${HCP_TARGET:-pi@hcp.local}}"
REMOTE_DIR="${2:-${HCP_DIR:-hcp}}"
cd "$(dirname "$0")/.."

echo "==> running tests"
python3 -m unittest discover -s tests -t . >/dev/null 2>&1 || { echo "tests failed, not deploying" >&2; exit 1; }

echo "==> uploading to $TARGET:$REMOTE_DIR"
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='__pycache__' -czf - hcp deploy scripts config.example.json README.md docs \
  | ssh "$TARGET" "mkdir -p '$REMOTE_DIR' && rm -rf '$REMOTE_DIR/hcp' && tar -xzf - -C '$REMOTE_DIR'"

if ssh "$TARGET" "systemctl list-unit-files hcp.service >/dev/null 2>&1"; then
  echo "==> restarting service"
  ssh -t "$TARGET" "sudo systemctl restart hcp && sleep 3 && systemctl --no-pager status hcp | head -5"
else
  echo "==> first deployment: finish setup on the Pi with"
  echo "    ssh -t $TARGET 'cd $REMOTE_DIR && sudo ./deploy/install.sh'"
fi
