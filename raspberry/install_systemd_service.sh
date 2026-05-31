#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(logname)"
PROJECT_DIR="${PROJECT_DIR:-/home/${CURRENT_USER}/raspRover/raspberry}"
RUN_USER="${RUN_USER:-${CURRENT_USER}}"
PYTHON_BIN="${PYTHON_BIN:-}"
PORT="${PORT:-8080}"

# ── rasprover-control ────────────────────────────────────────────────────────

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Dossier projet introuvable : ${PROJECT_DIR}" >&2
  exit 1
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
  elif [[ -x "${PROJECT_DIR}/../.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/../.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python introuvable : ${PYTHON_BIN}" >&2
  exit 1
fi

cat <<EOF | sudo tee /etc/systemd/system/rasprover-control.service > /dev/null
[Unit]
Description=RaspRover API server (FastAPI + WebSocket)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/run_api_server.py --port ${PORT}
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# ── ros2-lidar ───────────────────────────────────────────────────────────────

sudo cp "${SCRIPT_DIR}/ros2-lidar.service" /etc/systemd/system/ros2-lidar.service

# ── enable & start both ──────────────────────────────────────────────────────

sudo systemctl daemon-reload

for SVC in rasprover-control ros2-lidar; do
  sudo systemctl enable "${SVC}.service"
  sudo systemctl restart "${SVC}.service"
  echo "Service installe : ${SVC}.service"
  echo "  Statut : sudo systemctl status ${SVC}"
  echo "  Logs   : journalctl -u ${SVC} -f"
done

echo ""
echo "  API    : http://$(hostname -I | awk '{print $1}'):${PORT}/health"
echo "  HTTPS  : https://$(hostname -I | awk '{print $1}'):8443/health"
