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
  bash -c "source /opt/ros/jazzy/setup.bash && ros2 run tf2_ros static_transform_publisher --frame-id odom --child-frame-id laser & python3 /opt/map_writer.py & sleep 2 && ros2 run slam_toolbox async_slam_toolbox_node --ros-args -p base_frame:=laser -p odom_frame:=odom -p scan_topic:=/scan -p use_lifecycle_manager:=false -p use_sim_time:=false"
