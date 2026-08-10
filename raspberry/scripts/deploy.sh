#!/usr/bin/env bash
# Pull the latest code and restart only what changed.
# Usage (on the Pi): bash ~/raspRover/raspberry/scripts/deploy.sh [branch]
set -euo pipefail

CURRENT_USER="$(logname 2>/dev/null || whoami)"
REPO_DIR="/home/${CURRENT_USER}/raspRover"
RASPBERRY_DIR="${REPO_DIR}/raspberry"
VENV="${RASPBERRY_DIR}/.venv"

echo "==> Mise à jour du code..."
BRANCH="${1:-$(git -C "${REPO_DIR}" branch --show-current)}"
if [ -n "$(git -C "${REPO_DIR}" status --porcelain)" ]; then
  echo "Le dépôt contient des modifications locales. Déploiement annulé." >&2
  exit 1
fi
BEFORE=$(git -C "${REPO_DIR}" rev-parse HEAD)
git -C "${REPO_DIR}" fetch origin "${BRANCH}"
if git -C "${REPO_DIR}" show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git -C "${REPO_DIR}" switch "${BRANCH}"
else
  git -C "${REPO_DIR}" switch --track -c "${BRANCH}" "origin/${BRANCH}"
fi
git -C "${REPO_DIR}" pull --ff-only origin "${BRANCH}"
AFTER=$(git -C "${REPO_DIR}" rev-parse HEAD)

echo "==> Mise à jour des dépendances Python..."
"${VENV}/bin/pip" install -r "${RASPBERRY_DIR}/requirements.txt" -q

if ! /usr/bin/python3 -c 'import cv2, numpy' 2>/dev/null; then
  echo "==> OpenCV système absent — installation pour le tracking humain..."
  sudo apt-get update
  sudo apt-get install -y python3-opencv python3-numpy
fi

# Détecte les changements qui exigent une reconstruction de l'image ROS.
LIDAR_SERVICE_CHANGED=false
ROS_IMAGE_CHANGED=false
if [ "${BEFORE}" != "${AFTER}" ]; then
  if git -C "${REPO_DIR}" diff --name-only "${BEFORE}" "${AFTER}" | grep -q "ros2-lidar.service"; then
    LIDAR_SERVICE_CHANGED=true
  fi
  if git -C "${REPO_DIR}" diff --name-only "${BEFORE}" "${AFTER}" \
    | grep -Eq '^raspberry/(Dockerfile\.lidar|map_writer\.py|ros/)'; then
    ROS_IMAGE_CHANGED=true
  fi
fi

if [ "${ROS_IMAGE_CHANGED}" = "true" ]; then
  echo "==> Fichiers ROS/SLAM modifiés — reconstruction de l'image..."
  docker build -t ros2-lidar "${RASPBERRY_DIR}" -f "${RASPBERRY_DIR}/Dockerfile.lidar"
  echo "  OK"
fi

# Toujours redémarre l'API Python
echo "==> Redémarrage rasprover-control..."
sudo systemctl restart rasprover-control.service
echo "  OK"

# Redémarre le lidar uniquement si son .service a changé
if [ "${LIDAR_SERVICE_CHANGED}" = "true" ]; then
  echo "==> ros2-lidar.service modifié — mise à jour et redémarrage..."
  sed "s/^User=.*/User=${CURRENT_USER}/" "${RASPBERRY_DIR}/ros2-lidar.service" \
    | sudo tee /etc/systemd/system/ros2-lidar.service > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl restart ros2-lidar.service
  echo "  OK"
elif [ "${ROS_IMAGE_CHANGED}" = "true" ]; then
  echo "==> Image ROS modifiée — redémarrage ros2-lidar..."
  sudo systemctl restart ros2-lidar.service
  echo "  OK"
else
  echo "==> ros2-lidar inchangé — ROS non redémarré."
fi

echo ""
echo "==> Déploiement terminé."
