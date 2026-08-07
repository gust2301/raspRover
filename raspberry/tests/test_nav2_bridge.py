import json
import socket
import time

from modules.control.nav2 import Nav2MotorBridge


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


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
