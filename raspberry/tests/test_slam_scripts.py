from __future__ import annotations

from pathlib import Path


def test_ros_setup_is_sourced_before_nounset_is_enabled():
    script = (Path(__file__).parents[1] / "ros" / "start_slam.sh").read_text()

    lines = script.splitlines()
    source_position = lines.index("source /opt/ros/jazzy/setup.bash")
    nounset_position = lines.index("set -u")

    assert source_position < nounset_position
