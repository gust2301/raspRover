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
  bash -c "source /opt/ros/jazzy/setup.bash && printf 'slam_toolbox:\n  ros__parameters:\n    base_frame: laser\n    odom_frame: laser\n    map_frame: map\n    scan_topic: /scan\n    use_sim_time: false\n    provide_odom_frame: false\n' > /tmp/slam_params.yaml && ros2 launch slam_toolbox online_async_launch.py params_file:=/tmp/slam_params.yaml"
