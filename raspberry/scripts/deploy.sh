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

echo "==> Redémarrage rasprover-control..."
sudo systemctl restart rasprover-control
sudo systemctl status rasprover-control --no-pager -l | head -8

echo "==> Vérification ros2-lidar..."
if sudo systemctl is-active --quiet ros2-lidar; then
  sudo systemctl restart ros2-lidar
  echo "    ros2-lidar redémarré."
else
  echo "    ros2-lidar inactif — skippé."
fi

echo ""
echo "==> Déploiement terminé."
