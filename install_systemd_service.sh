#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="rasprover-control.service"
PROJECT_DIR="${PROJECT_DIR:-/home/ws/urgvrpi}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
RUN_USER="${RUN_USER:-ws}"
PYTHON_BIN="${PYTHON_BIN:-}"
PORT="${PORT:-/dev/ttyAMA0}"
EXTRA_ARGS="${EXTRA_ARGS:---skip-feedback}"

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Project directory not found: ${PROJECT_DIR}" >&2
  exit 1
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

cat <<EOF | sudo tee "${SERVICE_PATH}" > /dev/null
[Unit]
Description=RaspRover control backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/run_control_service.py --port ${PORT} ${EXTRA_ARGS}
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "Service installed: ${SERVICE_NAME}"
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
