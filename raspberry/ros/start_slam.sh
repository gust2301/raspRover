#!/usr/bin/env bash
set -eo pipefail

# Les scripts d'environnement ROS 2 lisent certaines variables optionnelles
# avant de les initialiser et ne sont donc pas compatibles avec `set -u`.
source /opt/ros/jazzy/setup.bash
set -u

cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Nettoie les auxiliaires orphelins d'un lancement précédent interrompu.
pkill -f '[c]ommand_odometry.py' 2>/dev/null || true
pkill -f '[e]ncoder_odometry.py' 2>/dev/null || true
pkill -f '[m]ap_writer.py' 2>/dev/null || true
pkill -f '[p]ose_writer.py' 2>/dev/null || true
rm -f /tmp/current_map.json /tmp/current_pose.json /tmp/nav2_status.json \
  /tmp/active_map_name /tmp/encoder_odometry_status.json

python3 /opt/rasprover/encoder_odometry.py --ros-args \
  -p udp_port:="${RASPROVER_ODOMETRY_UDP_PORT:-7667}" \
  -p wheel_separation_m:="${RASPROVER_WHEEL_SEPARATION_M:-0.33}" \
  -p counterclockwise_wheel_separation_m:="${RASPROVER_CCW_WHEEL_SEPARATION_M:-0.26}" \
  -p clockwise_wheel_separation_m:="${RASPROVER_CW_WHEEL_SEPARATION_M:-0.44}" \
  -p left_encoder_sign:="${RASPROVER_LEFT_ENCODER_SIGN:-1.0}" \
  -p right_encoder_sign:="${RASPROVER_RIGHT_ENCODER_SIGN:-1.0}" \
  -p laser_x_m:="${RASPROVER_LASER_X_M:-0.0}" \
  -p laser_y_m:="${RASPROVER_LASER_Y_M:-0.0}" \
  -p laser_z_m:="${RASPROVER_LASER_Z_M:-0.30}" \
  -p laser_yaw_deg:="${RASPROVER_LASER_YAW_DEG:-0.0}" &
ODOM_PID=$!

python3 /opt/rasprover/map_writer.py &
MAP_WRITER_PID=$!

python3 /opt/rasprover/pose_writer.py &
POSE_WRITER_PID=$!

ros2 run slam_toolbox async_slam_toolbox_node --ros-args \
  --params-file /opt/rasprover/slam_toolbox.yaml &
SLAM_PID=$!

# async_slam_toolbox_node est un noeud lifecycle. Lancé directement (sans le
# launch ROS officiel), il faut explicitement le configurer puis l'activer.
SLAM_DISCOVERED=false
for _attempt in $(seq 1 30); do
  if ros2 lifecycle get /slam_toolbox >/dev/null 2>&1; then
    SLAM_DISCOVERED=true
    break
  fi
  if ! kill -0 "${SLAM_PID}" 2>/dev/null; then
    echo "slam_toolbox s'est arrêté avant son activation" >&2
    exit 1
  fi
  sleep 0.2
done

if [ "${SLAM_DISCOVERED}" != "true" ]; then
  echo "slam_toolbox lifecycle introuvable après 6 secondes" >&2
  exit 1
fi

ros2 lifecycle set /slam_toolbox configure
ros2 lifecycle set /slam_toolbox activate
echo "slam_toolbox configuré et actif"

wait -n "${ODOM_PID}" "${MAP_WRITER_PID}" "${POSE_WRITER_PID}" "${SLAM_PID}"
