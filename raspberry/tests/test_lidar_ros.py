from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

from modules.sensors.lidar_ros import _kill_proc, _kill_remote_scan_processes


def test_kill_proc_waits_for_child_to_avoid_zombie() -> None:
    process = Mock()

    _kill_proc(process)

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=2.0)


def test_kill_proc_escalates_when_child_ignores_terminate() -> None:
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("docker", 2.0), 0]

    _kill_proc(process)

    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2


@patch("modules.sensors.lidar_ros.subprocess.run")
def test_remote_cleanup_targets_only_scan_echo(run: Mock) -> None:
    _kill_remote_scan_processes()

    command = run.call_args.args[0]
    assert command[:4] == ["docker", "exec", "ros2-lidar", "pkill"]
    assert command[-1] == "[r]os2 topic echo /scan"
