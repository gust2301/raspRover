#!/usr/bin/env bash
# Launch SLAM toolbox in a Docker container (foreground).
# Requires the ros2-lidar image to be built first (install_all.sh).
# Usage: bash ~/raspRover/raspberry/scripts/start_slam.sh
set -euo pipefail

CONTAINER_NAME="ros2-slam"

# Clean up any existing container
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

echo "==> Démarrage SLAM toolbox (slam_toolbox online_async)..."
echo "    Ctrl+C pour arrêter."
echo ""

docker run --rm --name "${CONTAINER_NAME}" \
  --network=host \
  ros2-lidar \
  ros2 launch slam_toolbox online_async_launch.py
