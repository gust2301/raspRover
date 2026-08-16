import json
import socket
import time

from modules.control.nav2 import Nav2MotorBridge, compensate_motor_deadzone


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_motor_deadzone_compensation_preserves_curvature_and_zero():
    left, right = compensate_motor_deadzone(0.006, 0.003, 0.12)

    assert left == 0.12
    assert right == 0.06
    assert compensate_motor_deadzone(0.0, 0.0, 0.12) == (0.0, 0.0)
    assert compensate_motor_deadzone(-0.2, 0.1, 0.12) == (-0.2, 0.1)


def test_nav2_bridge_applies_minimum_motor_command():
    commands: list[tuple[float, float]] = []
    motor_port = _free_udp_port()
    bridge = Nav2MotorBridge(
        lambda left, right: commands.append((left, right)),
        lambda: None,
        motor_port=motor_port,
        command_port=_free_udp_port(),
        minimum_motor_command=0.12,
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        bridge.enable()
        sender.sendto(b'{"left":0.006,"right":0.003}', ("127.0.0.1", motor_port))
        time.sleep(0.15)

        assert commands == [(0.12, 0.06)]
    finally:
        sender.close()
        bridge.close()


def test_nav2_motor_commands_require_explicit_authorization():
    commands: list[tuple[float, float]] = []
    stops: list[bool] = []
    motor_port = _free_udp_port()
    bridge = Nav2MotorBridge(
        lambda left, right: commands.append((left, right)),
        lambda: stops.append(True),
        motor_port=motor_port,
        command_port=_free_udp_port(),
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(json.dumps({"left": 0.4, "right": 0.2}).encode(), ("127.0.0.1", motor_port))
        time.sleep(0.15)
        assert commands == []

        bridge.enable()
        sender.sendto(json.dumps({"left": 4, "right": -2}).encode(), ("127.0.0.1", motor_port))
        time.sleep(0.15)
        assert commands == [(1.0, -1.0)]

        bridge.disable()
        assert stops
    finally:
        sender.close()
        bridge.close()


def test_nav2_motor_bridge_stops_after_command_timeout():
    stops: list[float] = []
    motor_port = _free_udp_port()
    bridge = Nav2MotorBridge(
        lambda _left, _right: None,
        lambda: stops.append(time.monotonic()),
        motor_port=motor_port,
        command_port=_free_udp_port(),
        timeout_s=0.1,
    )
    try:
        bridge.enable()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b'{"left":0.1,"right":0.1}', ("127.0.0.1", motor_port))
        sender.close()
        time.sleep(0.25)
        assert stops
        assert bridge.enabled is False
    finally:
        bridge.close()


def test_nav2_motor_bridge_waits_for_first_real_command_before_timeout():
    commands: list[tuple[float, float]] = []
    motor_port = _free_udp_port()
    bridge = Nav2MotorBridge(
        lambda left, right: commands.append((left, right)),
        lambda: None,
        motor_port=motor_port,
        command_port=_free_udp_port(),
        timeout_s=0.1,
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        bridge.enable()
        sender.sendto(b'{"left":0.0,"right":0.0}', ("127.0.0.1", motor_port))
        time.sleep(0.25)

        assert bridge.enabled is True

        sender.sendto(b'{"left":-0.2,"right":-0.2}', ("127.0.0.1", motor_port))
        time.sleep(0.15)
        assert (-0.2, -0.2) in commands
    finally:
        sender.close()
        bridge.close()


def test_nav2_motor_bridge_disables_when_ros_reports_mission_finished():
    commands: list[tuple[float, float]] = []
    motor_port = _free_udp_port()
    bridge = Nav2MotorBridge(
        lambda left, right: commands.append((left, right)),
        lambda: None,
        motor_port=motor_port,
        command_port=_free_udp_port(),
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        bridge.enable()
        sender.sendto(
            b'{"left":0.0,"right":0.0,"mission_finished":true}',
            ("127.0.0.1", motor_port),
        )
        time.sleep(0.15)

        assert commands == [(0.0, 0.0)]
        assert bridge.enabled is False
    finally:
        sender.close()
        bridge.close()


def test_nav2_motor_bridge_sends_initial_pose_to_ros_bridge():
    motor_port = _free_udp_port()
    command_port = _free_udp_port()
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", command_port))
    receiver.settimeout(1.0)
    bridge = Nav2MotorBridge(
        lambda _left, _right: None,
        lambda: None,
        motor_port=motor_port,
        command_port=command_port,
    )
    try:
        bridge.set_initial_pose({"x": 1.2, "y": -0.4, "yaw": 0.75})
        payload, _address = receiver.recvfrom(4096)
        assert json.loads(payload) == {
            "action": "set_initial_pose",
            "pose": {"x": 1.2, "y": -0.4, "yaw": 0.75},
        }
    finally:
        receiver.close()
        bridge.close()
