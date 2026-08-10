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
  rm -f /tmp/rasprover_nav2_params.yaml
}
trap cleanup EXIT INT TERM

pkill -f '[c]ommand_odometry.py' 2>/dev/null || true
pkill -f '[m]ap_writer.py' 2>/dev/null || true
pkill -f '[p]ose_writer.py' 2>/dev/null || true
pkill -f '[n]av2_bridge.py' 2>/dev/null || true
pkill -f '[a]sync_slam_toolbox_node' 2>/dev/null || true

# Never let slam_toolbox and AMCL publish map -> odom at the same time.
for _attempt in $(seq 1 30); do
  if ! pgrep -f 'async_slam_toolbox_node' >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if pgrep -f 'async_slam_toolbox_node' >/dev/null 2>&1; then
  echo "Impossible d'arrêter slam_toolbox avant Nav2" >&2
  exit 1
fi
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

python3 /opt/rasprover/map_writer.py &
MAP_WRITER_PID=$!
python3 /opt/rasprover/pose_writer.py &
POSE_WRITER_PID=$!
python3 /opt/rasprover/nav2_bridge.py --ros-args \
  -p motor_udp_port:="${RASPROVER_NAV2_MOTOR_UDP_PORT:-7668}" \
  -p command_udp_port:="${RASPROVER_NAV2_COMMAND_UDP_PORT:-7669}" \
  -p max_linear_speed_m_s:="${RASPROVER_MAX_SPEED_M_S:-0.65}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.18}" \
  -p initial_pose_x:="${RASPROVER_INITIAL_POSE_X:-0.0}" \
  -p initial_pose_y:="${RASPROVER_INITIAL_POSE_Y:-0.0}" \
  -p initial_pose_yaw:="${RASPROVER_INITIAL_POSE_YAW:-0.0}" &
BRIDGE_PID=$!

# Le rover publie odom -> base_link. Aligne tous les composants Nav2 sur ce
# frame au lieu d'ajouter un alias base_footprint qui perturbe AMCL.
NAV2_DEFAULT_PARAMS=/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml
NAV2_PARAMS=/tmp/rasprover_nav2_params.yaml
ROBOT_RADIUS="${RASPROVER_NAV2_ROBOT_RADIUS_M:-0.16}"
INFLATION_RADIUS="${RASPROVER_NAV2_INFLATION_RADIUS_M:-0.30}"
sed -E \
  -e 's/base_footprint/base_link/g' \
  -e "s/^([[:space:]]*robot_radius:).*/\\1 ${ROBOT_RADIUS}/" \
  -e "s/^([[:space:]]*inflation_radius:).*/\\1 ${INFLATION_RADIUS}/" \
  -e 's/^([[:space:]]*stop_on_failure:).*/\1 true/' \
  "${NAV2_DEFAULT_PARAMS}" > "${NAV2_PARAMS}"

ros2 launch nav2_bringup bringup_launch.py \
  map:="${MAP_YAML}" \
  params_file:="${NAV2_PARAMS}" \
  use_sim_time:=false \
  autostart:=true &
NAV2_PID=$!

wait -n "${ODOM_PID}" "${MAP_WRITER_PID}" \
  "${POSE_WRITER_PID}" "${BRIDGE_PID}" "${NAV2_PID}"
