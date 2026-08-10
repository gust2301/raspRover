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
    assert "stop_on_failure:" in script
    assert "\\1 true" in script
    assert 'params_file:="${NAV2_PARAMS}"' in script
    assert "static_transform_publisher" not in script
    assert "pose_writer.py" in script
    assert 'basename "${MAP_YAML}" .yaml > /tmp/active_map_name' in script
    assert "pkill -f '[a]sync_slam_toolbox_node'" in script
    assert "Impossible d'arrêter slam_toolbox avant Nav2" in script


def test_nav2_bridge_waits_for_amcl_and_uses_latest_tf_timestamp():
    bridge = (Path(__file__).parents[1] / "ros" / "nav2_bridge.py").read_text()

    assert "get_subscription_count()" in bridge
    assert 'create_client(GetState, "/amcl/get_state")' in bridge
    assert "State.PRIMARY_STATE_ACTIVE" in bridge
    assert "message.header.stamp = self.get_clock().now().to_msg()" not in bridge


def test_api_detects_composed_nav2_container():
    server = (Path(__file__).parents[1] / "modules" / "api" / "server.py").read_text()

    assert '"pgrep", "-f", "[n]av2_container"' in server
    assert '"pgrep", "-f", "bt_navigator"' not in server
    assert 'bridge_status.get("action_server_ready")' in server
    assert "_nav2_motors.set_initial_pose(pose_values)" in server
