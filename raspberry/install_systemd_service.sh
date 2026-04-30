#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="rasprover-control.service"
PROJECT_DIR="${PROJECT_DIR:-/home/ws/raspRover/raspberry}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
RUN_USER="${RUN_USER:-ws}"
PYTHON_BIN="${PYTHON_BIN:-}"
PORT="${PORT:-8080}"

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Dossier projet introuvable : ${PROJECT_DIR}" >&2
  exit 1
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${PROJECT_DIR}/../.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/../.venv/bin/python"
  elif [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python introuvable : ${PYTHON_BIN}" >&2
  exit 1
fi

cat <<EOF | sudo tee "${SERVICE_PATH}" > /dev/null
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

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo ""
echo "Service installe : ${SERVICE_NAME}"
echo "  Statut : sudo systemctl status ${SERVICE_NAME}"
echo "  Logs   : journalctl -u ${SERVICE_NAME} -f"
echo "  API    : http://$(hostname -I | awk '{print $1}'):${PORT}/health"
echo "  HTTPS  : https://$(hostname -I | awk '{print $1}'):8443/health"
