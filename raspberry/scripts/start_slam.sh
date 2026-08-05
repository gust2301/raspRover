#!/usr/bin/env bash
# Launch SLAM toolbox in a Docker container (foreground).
# Requires the ros2-lidar image to be built first (install_all.sh).
# Usage: bash ~/raspRover/raspberry/scripts/start_slam.sh
set -euo pipefail

CONTAINER_NAME="ros2-lidar"

echo "==> Démarrage SLAM toolbox (slam_toolbox online_async)..."
echo "    Ctrl+C pour arrêter."
echo ""

if ! docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -qx true; then
  echo "Le container ros2-lidar doit etre actif (service ros2-lidar)." >&2
  exit 1
fi

docker exec "${CONTAINER_NAME}" /opt/rasprover/start_slam.sh
