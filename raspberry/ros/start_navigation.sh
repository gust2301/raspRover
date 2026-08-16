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
pkill -f '[e]ncoder_odometry.py' 2>/dev/null || true
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
rm -f /tmp/current_map.json /tmp/current_pose.json /tmp/nav2_status.json \
  /tmp/encoder_odometry_status.json
basename "${MAP_YAML}" .yaml > /tmp/active_map_name

python3 /opt/rasprover/encoder_odometry.py --ros-args \
  -p udp_port:="${RASPROVER_ODOMETRY_UDP_PORT:-7667}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.172}" \
  -p left_encoder_sign:="${RASPROVER_LEFT_ENCODER_SIGN:-1.0}" \
  -p right_encoder_sign:="${RASPROVER_RIGHT_ENCODER_SIGN:-1.0}" \
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
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.172}" \
  -p initial_pose_x:="${RASPROVER_INITIAL_POSE_X:-0.0}" \
  -p initial_pose_y:="${RASPROVER_INITIAL_POSE_Y:-0.0}" \
  -p initial_pose_yaw:="${RASPROVER_INITIAL_POSE_YAW:-0.0}" \
  -p initial_pose_position_stddev_m:="${RASPROVER_INITIAL_POSE_POSITION_STDDEV_M:-0.5}" \
  -p initial_pose_yaw_stddev_rad:="${RASPROVER_INITIAL_POSE_YAW_STDDEV_RAD:-0.261799}" &
BRIDGE_PID=$!

# Le rover publie odom -> base_link. Aligne tous les composants Nav2 sur ce
# frame au lieu d'ajouter un alias base_footprint qui perturbe AMCL.
NAV2_DEFAULT_PARAMS=/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml
NAV2_PARAMS=/tmp/rasprover_nav2_params.yaml
ROBOT_RADIUS="${RASPROVER_NAV2_ROBOT_RADIUS_M:-0.16}"
INFLATION_RADIUS="${RASPROVER_NAV2_INFLATION_RADIUS_M:-0.30}"
SERVER_TIMEOUT_MS="${RASPROVER_NAV2_SERVER_TIMEOUT_MS:-1000}"
CONTROLLER_FREQUENCY_HZ="${RASPROVER_NAV2_CONTROLLER_FREQUENCY_HZ:-10.0}"
MODEL_DT_S="${RASPROVER_NAV2_MODEL_DT_S:-0.1}"
GOAL_XY_TOLERANCE_M="${RASPROVER_NAV2_GOAL_XY_TOLERANCE_M:-0.05}"
GOAL_YAW_TOLERANCE_RAD="${RASPROVER_NAV2_GOAL_YAW_TOLERANCE_RAD:-0.05236}"
PROGRESS_RADIUS_M="${RASPROVER_NAV2_PROGRESS_RADIUS_M:-0.05}"
PROGRESS_ALLOWANCE_S="${RASPROVER_NAV2_PROGRESS_ALLOWANCE_S:-15.0}"
sed -E \
  -e 's/base_footprint/base_link/g' \
  -e "s/^([[:space:]]*robot_radius:).*/\\1 ${ROBOT_RADIUS}/" \
  -e "s/^([[:space:]]*inflation_radius:).*/\\1 ${INFLATION_RADIUS}/" \
  -e "s/^([[:space:]]*default_server_timeout:).*/\\1 ${SERVER_TIMEOUT_MS}/" \
  -e "0,/^([[:space:]]*controller_frequency:).*/s//\\1 ${CONTROLLER_FREQUENCY_HZ}/" \
  -e "s/^([[:space:]]*model_dt:).*/\\1 ${MODEL_DT_S}/" \
  -e "s/^([[:space:]]*xy_goal_tolerance:).*/\\1 ${GOAL_XY_TOLERANCE_M}/" \
  -e "s/^([[:space:]]*yaw_goal_tolerance:).*/\\1 ${GOAL_YAW_TOLERANCE_RAD}/" \
  -e "s/^([[:space:]]*required_movement_radius:).*/\\1 ${PROGRESS_RADIUS_M}/" \
  -e "s/^([[:space:]]*movement_time_allowance:).*/\\1 ${PROGRESS_ALLOWANCE_S}/" \
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
