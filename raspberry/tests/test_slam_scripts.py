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
    assert "sed 's/base_footprint/base_link/g'" in script
    assert 'params_file:="${NAV2_PARAMS}"' in script
    assert "static_transform_publisher" not in script
    assert "pose_writer.py" in script
    assert 'basename "${MAP_YAML}" .yaml > /tmp/active_map_name' in script
    assert "pkill -f '[a]sync_slam_toolbox_node'" in script
    assert "Impossible d'arrêter slam_toolbox avant Nav2" in script
