#!/usr/bin/env bash
# Pull the latest code and restart both services.
# Usage (on the Pi): bash ~/raspRover/raspberry/scripts/deploy.sh
set -euo pipefail

CURRENT_USER="$(logname)"
REPO_DIR="/home/${CURRENT_USER}/raspRover"
RASPBERRY_DIR="${REPO_DIR}/raspberry"
VENV="${RASPBERRY_DIR}/.venv"

echo "==> Mise à jour du code..."
git -C "${REPO_DIR}" pull origin master

echo "==> Mise à jour des dépendances Python..."
"${VENV}/bin/pip" install -r "${RASPBERRY_DIR}/requirements.txt" -q

echo "==> Mise à jour des services systemd..."
bash "${RASPBERRY_DIR}/install_systemd_service.sh"

echo "==> Statut rasprover-control..."
sudo systemctl status rasprover-control --no-pager -l | head -8

echo ""
echo "==> Déploiement terminé."
