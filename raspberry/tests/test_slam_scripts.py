from __future__ import annotations

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
