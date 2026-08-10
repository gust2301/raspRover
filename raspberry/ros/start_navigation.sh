#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
set -u

MAP_YAML="${RASPROVER_MAP_YAML:?RASPROVER_MAP_YAML manquant}"
if [[ "${MAP_YAML}" != /maps/*.yaml ]] || [ ! -f "${MAP_YAML}" ]; then
  echo "Carte Nav2 invalide ou absente: ${MAP_YAML}" >&2
  exit 1
fi

cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

pkill -f '[c]ommand_odometry.py' 2>/dev/null || true
pkill -f '[m]ap_writer.py' 2>/dev/null || true
pkill -f '[p]ose_writer.py' 2>/dev/null || true
pkill -f '[n]av2_bridge.py' 2>/dev/null || true
rm -f /tmp/current_map.json /tmp/current_pose.json /tmp/nav2_status.json
basename "${MAP_YAML}" .yaml > /tmp/active_map_name

python3 /opt/rasprover/command_odometry.py --ros-args \
  -p udp_port:="${RASPROVER_ODOMETRY_UDP_PORT:-7667}" \
  -p max_linear_speed_m_s:="${RASPROVER_MAX_SPEED_M_S:-0.65}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.18}" \
  -p laser_x_m:="${RASPROVER_LASER_X_M:-0.0}" \
  -p laser_y_m:="${RASPROVER_LASER_Y_M:-0.0}" \
  -p laser_yaw_deg:="${RASPROVER_LASER_YAW_DEG:-140.0}" &
ODOM_PID=$!

# The stock Jazzy parameters use base_footprint for AMCL.
ros2 run tf2_ros static_transform_publisher \
  --x 0 --y 0 --z 0 --yaw 0 --pitch 0 --roll 0 \
  --frame-id base_link --child-frame-id base_footprint &
FOOTPRINT_PID=$!

python3 /opt/rasprover/map_writer.py &
MAP_WRITER_PID=$!
python3 /opt/rasprover/pose_writer.py &
POSE_WRITER_PID=$!
python3 /opt/rasprover/nav2_bridge.py --ros-args \
  -p motor_udp_port:="${RASPROVER_NAV2_MOTOR_UDP_PORT:-7668}" \
  -p command_udp_port:="${RASPROVER_NAV2_COMMAND_UDP_PORT:-7669}" \
  -p max_linear_speed_m_s:="${RASPROVER_MAX_SPEED_M_S:-0.65}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.18}" &
BRIDGE_PID=$!

ros2 launch nav2_bringup bringup_launch.py \
  map:="${MAP_YAML}" \
  use_sim_time:=false \
  autostart:=true &
NAV2_PID=$!

wait -n "${ODOM_PID}" "${FOOTPRINT_PID}" "${MAP_WRITER_PID}" \
  "${POSE_WRITER_PID}" "${BRIDGE_PID}" "${NAV2_PID}"
