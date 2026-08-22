from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def test_ros_setup_is_sourced_before_nounset_is_enabled():
    script = (Path(__file__).parents[1] / "ros" / "start_slam.sh").read_text()

    lines = script.splitlines()
    source_position = lines.index("source /opt/ros/jazzy/setup.bash")
    nounset_position = lines.index("set -u")

    assert source_position < nounset_position


def test_slam_toolbox_lifecycle_is_configured_and_activated():
    script = (Path(__file__).parents[1] / "ros" / "start_slam.sh").read_text()

    launch_position = script.index("async_slam_toolbox_node")
    configure_position = script.index("ros2 lifecycle set /slam_toolbox configure")
    activate_position = script.index("ros2 lifecycle set /slam_toolbox activate")

    assert launch_position < configure_position < activate_position


def test_lidar_service_mounts_persistent_map_volume():
    service = (Path(__file__).parents[1] / "ros2-lidar.service").read_text()

    assert "--volume=rasprover-maps:/maps" in service
    assert "FASTRTPS_DEFAULT_PROFILES_FILE=/opt/rasprover/fastdds_udp_only.xml" in service
    assert "FASTDDS_DEFAULT_PROFILES_FILE=/opt/rasprover/fastdds_udp_only.xml" in service


def test_fastdds_profile_disables_shm_and_keeps_udp_transport():
    profile = Path(__file__).parents[1] / "ros" / "fastdds_udp_only.xml"
    root = ET.parse(profile).getroot()
    xml = ET.tostring(root, encoding="unicode")

    assert "UDPv4" in xml
    assert "<ns0:useBuiltinTransports>false</ns0:useBuiltinTransports>" in xml
    assert "SHM" not in xml


def test_navigation_starts_nav2_with_selected_persistent_map():
    script = (Path(__file__).parents[1] / "ros" / "start_navigation.sh").read_text()

    assert 'MAP_YAML="${RASPROVER_MAP_YAML:' in script
    assert 'map:="${MAP_YAML}"' in script
    assert 'initial_pose_x:="${RASPROVER_INITIAL_POSE_X:-0.0}"' in script
    assert 'initial_pose_y:="${RASPROVER_INITIAL_POSE_Y:-0.0}"' in script
    assert 'initial_pose_yaw:="${RASPROVER_INITIAL_POSE_YAW:-0.0}"' in script
    assert "nav2_bringup bringup_launch.py" in script
    assert "nav2_bridge.py" in script
    assert "s/base_footprint/base_link/g" in script
    assert "RASPROVER_NAV2_ROBOT_RADIUS_M:-0.16" in script
    assert "RASPROVER_NAV2_INFLATION_RADIUS_M:-0.30" in script
    assert "RASPROVER_NAV2_SERVER_TIMEOUT_MS:-1000" in script
    assert "RASPROVER_NAV2_CONTROLLER_FREQUENCY_HZ:-10.0" in script
    assert "RASPROVER_NAV2_MODEL_DT_S:-0.1" in script
    assert "default_server_timeout:" in script
    assert "controller_frequency:" in script
    assert "model_dt:" in script
    assert "stop_on_failure:" in script
    assert "\\1 true" in script
    assert 'params_file:="${NAV2_PARAMS}"' in script
    assert "static_transform_publisher" not in script
    assert "pose_writer.py" in script
    assert 'basename "${MAP_YAML}" .yaml > /tmp/active_map_name' in script
    assert "pkill -f '[a]sync_slam_toolbox_node'" in script
    assert "Impossible d'arrêter slam_toolbox avant Nav2" in script
    assert "encoder_odometry.py" in script
    assert "command_odometry.py --ros-args" not in script


def test_slam_uses_physical_encoder_odometry():
    script = (Path(__file__).parents[1] / "ros" / "start_slam.sh").read_text()
    dockerfile = (Path(__file__).parents[1] / "Dockerfile.lidar").read_text()

    assert "encoder_odometry.py" in script
    assert "left_encoder_sign" in script
    assert "right_encoder_sign" in script
    assert "command_odometry.py --ros-args" not in script
    assert "modules/control/encoder_kinematics.py" in dockerfile


def test_nav2_bridge_waits_for_amcl_and_uses_latest_tf_timestamp():
    bridge = (Path(__file__).parents[1] / "ros" / "nav2_bridge.py").read_text()

    assert "get_subscription_count()" in bridge
    assert 'create_client(GetState, "/amcl/get_state")' in bridge
    assert "State.PRIMARY_STATE_ACTIVE" in bridge
    assert "message.header.stamp = self.get_clock().now().to_msg()" not in bridge
    assert 'self._status["heartbeat_at"] = time.time()' in bridge
    assert 'getattr(wrapped_result.result, "error_msg", "")' in bridge


def test_nav2_initial_pose_uses_configurable_standard_deviation():
    bridge = (Path(__file__).parents[1] / "ros" / "nav2_bridge.py").read_text()
    launcher = (Path(__file__).parents[1] / "ros" / "start_navigation.sh").read_text()
    server = (Path(__file__).parents[1] / "modules" / "api" / "server.py").read_text()

    assert 'self._initial_pose["position_stddev_m"] ** 2' in bridge
    assert 'self._initial_pose["yaw_stddev_rad"] ** 2' in bridge
    assert "RASPROVER_INITIAL_POSE_POSITION_STDDEV_M" in launcher
    assert 'trusted_initial_pose = initial_pose_source in {"request", "home"}' in server
    assert '"position_stddev_m": 0.15 if trusted_initial_pose else 0.5' in server


def test_pose_writer_exposes_amcl_localization_quality():
    writer = (Path(__file__).parents[1] / "ros" / "pose_writer.py").read_text()

    assert '"/amcl_pose"' in writer
    assert 'payload["position_stddev_m"]' in writer
    assert 'payload["yaw_stddev_rad"]' in writer


def test_route_validator_uses_planner_without_sending_navigation_goals():
    validator = (Path(__file__).parents[1] / "ros" / "nav2_route_validator.py").read_text()

    assert "ComputePathToPose" in validator
    assert 'ActionClient(self, ComputePathToPose, "/compute_path_to_pose")' in validator
    assert "FollowWaypoints" not in validator
    assert "Twist" not in validator


def test_api_detects_composed_nav2_container():
    server = (Path(__file__).parents[1] / "modules" / "api" / "server.py").read_text()

    assert '"pgrep", "-f", "[n]av2_container"' in server
    assert '"pgrep", "-f", "bt_navigator"' not in server
    assert 'bridge_status.get("action_server_ready")' in server
    assert 'bridge_status.get("heartbeat_at", bridge_status.get("updated_at", 0.0))' in server
    assert "_nav2_motors.set_initial_pose(pose_values)" in server
    assert "for attempt in range(120):" in server
    assert "_navigation_launcher_running" in server
    assert "def _nav2_ready()" in server
    assert "navigation_ready" in server
    assert "_process_log_summary(error)" in server
    assert '@app.post("/api/automotive/routes/validate")' in server
    assert "_validate_automotive_poses(" in server
    assert '"position actuelle"' in server
    assert "INSPECTION_POSITION_TOLERANCE_M" in server
    assert "_wait_for_stable_inspection_pose(waypoint)" in server
    assert 'waypoint["_capture_pan"] = float(waypoint.get("pan", 0.0))' in server
    assert '@app.delete("/api/slam/maps/{map_name}")' in server
    assert '@app.post("/api/automotive/points/capture")' in server
    assert "def _slam_topic_publishers()" in server
    assert 'publishers["/scan"] == 0' in server


def test_navigation_uses_precise_inspection_goal_and_progress_tolerances():
    launcher = (Path(__file__).parents[1] / "ros" / "start_navigation.sh").read_text()
    server = (Path(__file__).parents[1] / "modules" / "api" / "server.py").read_text()

    assert "RASPROVER_NAV2_GOAL_XY_TOLERANCE_M:-0.05" in launcher
    assert "RASPROVER_NAV2_GOAL_YAW_TOLERANCE_RAD:-0.05236" in launcher
    assert "RASPROVER_NAV2_PROGRESS_RADIUS_M:-0.05" in launcher
    assert "RASPROVER_NAV2_PROGRESS_ALLOWANCE_S:-15.0" in launcher
    assert "RASPROVER_NAV2_GOAL_XY_TOLERANCE_M" in server
    assert "RASPROVER_NAV2_PROGRESS_RADIUS_M" in server
