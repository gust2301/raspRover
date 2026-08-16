"""Safe UDP boundary between the ROS 2 Nav2 container and motor control."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


def compensate_motor_deadzone(
    left: float, right: float, minimum_command: float
) -> tuple[float, float]:
    """Raise a non-zero wheel pair above the physical motor dead zone.

    Both sides are scaled by the same factor so Nav2's requested curvature is
    preserved. Exact zero remains zero and can always stop the rover.
    """
    magnitude = max(abs(left), abs(right))
    if magnitude <= 1e-6 or magnitude >= minimum_command:
        return left, right
    scale = minimum_command / magnitude
    return left * scale, right * scale


class Nav2MotorBridge:
    """Accept Nav2 wheel commands only while an API-authorized mission is active."""

    def __init__(
        self,
        drive: Callable[[float, float], None],
        stop: Callable[[], None],
        *,
        motor_port: int = 7668,
        command_port: int = 7669,
        timeout_s: float = 0.6,
        minimum_motor_command: float = 0.12,
    ) -> None:
        if not 0.0 <= minimum_motor_command <= 1.0:
            raise ValueError("minimum_motor_command doit être compris entre 0 et 1")
        self._drive = drive
        self._stop = stop
        self._motor_port = motor_port
        self._command_port = command_port
        self._timeout_s = timeout_s
        self._minimum_motor_command = minimum_motor_command
        self._enabled = False
        self._received_command = False
        self._closed = threading.Event()
        self._last_command = 0.0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("127.0.0.1", motor_port))
        self._socket.settimeout(0.1)
        self._thread = threading.Thread(target=self._run, name="Nav2MotorBridge", daemon=True)
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._last_command = time.monotonic()
        self._received_command = False
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._stop()

    def follow_waypoints(self, waypoints: list[dict[str, float]]) -> None:
        self.enable()
        self._send_command({"action": "follow_waypoints", "waypoints": waypoints})

    def go_to_pose(self, pose: dict[str, float], *, no_recovery: bool = False) -> None:
        """Navigate to one pose, optionally without autonomous recovery motions."""
        self.enable()
        self._send_command(
            {
                "action": "navigate_to_pose",
                "pose": pose,
                "no_recovery": no_recovery,
            }
        )

    def set_initial_pose(self, pose: dict[str, float]) -> None:
        """Send the localization seed repeatedly while the ROS bridge starts."""
        payload = {"action": "set_initial_pose", "pose": pose}
        for _attempt in range(3):
            self._send_command(payload)
            time.sleep(0.2)

    def cancel(self) -> None:
        self._send_command({"action": "cancel"})
        self.disable()

    def close(self) -> None:
        self.disable()
        self._closed.set()
        self._thread.join(timeout=1.0)
        self._socket.close()

    def _send_command(self, payload: dict) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(json.dumps(payload).encode(), ("127.0.0.1", self._command_port))

    def _run(self) -> None:
        stopped_for_timeout = False
        while not self._closed.is_set():
            try:
                raw, _ = self._socket.recvfrom(2048)
            except OSError as exc:
                if not isinstance(exc, socket.timeout):
                    return
                timed_out = time.monotonic() - self._last_command > self._timeout_s
                if self._enabled and self._received_command and timed_out:
                    if not stopped_for_timeout:
                        self._stop()
                        stopped_for_timeout = True
                    self._enabled = False
                continue

            if not self._enabled:
                continue
            try:
                command = json.loads(raw)
                left = max(-1.0, min(1.0, float(command["left"])))
                right = max(-1.0, min(1.0, float(command["right"])))
                left, right = compensate_motor_deadzone(
                    left, right, self._minimum_motor_command
                )
                mission_finished = bool(command.get("mission_finished", False))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                log.warning("Commande moteur Nav2 UDP invalide")
                continue
            self._last_command = time.monotonic()
            # Nav2 peut publier un zéro, puis rester silencieux pendant que le
            # planificateur prépare le premier trajet. Ne démarre le watchdog
            # qu'au premier mouvement réel, sinon la mission est désarmée avant
            # que sa première commande non nulle atteigne les moteurs.
            if abs(left) > 1e-6 or abs(right) > 1e-6:
                self._received_command = True
            stopped_for_timeout = False
            self._drive(left, right)
            if mission_finished:
                self.disable()
