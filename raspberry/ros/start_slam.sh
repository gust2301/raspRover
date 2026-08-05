#!/usr/bin/env bash
set -euo pipefail

source /opt/ros/jazzy/setup.bash

cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python3 /opt/rasprover/command_odometry.py --ros-args \
  -p max_linear_speed_m_s:="${RASPROVER_MAX_SPEED_M_S:-0.65}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.18}" \
  -p laser_x_m:="${RASPROVER_LASER_X_M:-0.0}" \
  -p laser_y_m:="${RASPROVER_LASER_Y_M:-0.0}" \
  -p laser_yaw_deg:="${RASPROVER_LASER_YAW_DEG:-140.0}" &
ODOM_PID=$!

python3 /opt/rasprover/map_writer.py &
MAP_WRITER_PID=$!

ros2 run slam_toolbox async_slam_toolbox_node --ros-args \
  --params-file /opt/rasprover/slam_toolbox.yaml &
SLAM_PID=$!

wait -n "${ODOM_PID}" "${MAP_WRITER_PID}" "${SLAM_PID}"
