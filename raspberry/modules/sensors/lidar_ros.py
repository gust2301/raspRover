"""ROS2 RPLIDAR bridge via `docker exec` subprocess.

Subscribes to the /scan topic published by the ros2-lidar Docker container
(sensor_msgs/msg/LaserScan) and exposes a 360° point cloud as a dict.
Compatible snapshot interface with RPLidarA1 so the rest of the stack can
use whichever source is available.
"""

from __future__ import annotations

import logging
import math
import subprocess
import threading
import time
from typing import Any

import yaml

log = logging.getLogger(__name__)

_TOPIC = "/scan"
_DEFAULT_CONTAINER = "ros2-lidar"
# Down-sample to at most this many points for the broadcast payload.
_MAX_BROADCAST_POINTS = 360


def _container_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


class ROS2LidarBridge:
    """Background subscriber to ROS2 /scan via docker exec.

    Usage (mirrors RPLidarA1 interface):
        bridge = ROS2LidarBridge()
        bridge.start()
        snap = bridge.snapshot  # dict
        bridge.stop()
    """

    def __init__(self, container: str = _DEFAULT_CONTAINER) -> None:
        self._container = container
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = _empty_snapshot("non démarré")
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ros2-lidar-bridge"
        )
        self._thread.start()
        log.info("ROS2LidarBridge démarré (container=%s)", self._container)

    def stop(self) -> None:
        self._stop_event.set()
        _kill_proc(self._proc)
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("ROS2LidarBridge arrêté")

    @property
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    # ── background thread ─────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not _container_running(self._container):
                self._set(connected=False, error=f"conteneur '{self._container}' non actif")
                self._stop_event.wait(5.0)
                continue
            try:
                self._stream()
            except Exception as exc:  # noqa: BLE001
                log.warning("ROS2LidarBridge erreur : %s", exc)
                self._set(connected=False, error=str(exc))
                self._stop_event.wait(3.0)

    def _stream(self) -> None:
        cmd = ["docker", "exec", self._container, "ros2", "topic", "echo", _TOPIC]
        log.info("ROS2LidarBridge: écoute %s sur %s", _TOPIC, self._container)
        self._proc = subprocess.Popen(  # type: ignore[assignment]
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        buf: list[str] = []
        try:
            for line in self._proc.stdout:  # type: ignore[union-attr]
                if self._stop_event.is_set():
                    break
                stripped = line.rstrip("\n")
                if stripped == "---":
                    if buf:
                        self._parse("\n".join(buf))
                        buf = []
                else:
                    buf.append(stripped)
        finally:
            _kill_proc(self._proc)
            self._proc = None

    # ── parsing ───────────────────────────────────────────────────────────────

    def _parse(self, yaml_text: str) -> None:
        try:
            msg: dict = yaml.safe_load(yaml_text)
            if not isinstance(msg, dict) or "ranges" not in msg:
                return

            angle_min: float = float(msg.get("angle_min", -math.pi))
            angle_inc: float = float(msg.get("angle_increment", 0.01))
            range_min: float = float(msg.get("range_min", 0.15))
            range_max: float = float(msg.get("range_max", 12.0))
            raw_ranges: list = msg.get("ranges", [])

            points: list[dict[str, float]] = []
            for i, r in enumerate(raw_ranges):
                try:
                    dist_m = float(r)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(dist_m) or dist_m < range_min or dist_m > range_max:
                    continue
                angle_rad = angle_min + i * angle_inc
                angle_deg = math.degrees(angle_rad) % 360.0
                points.append(
                    {
                        "angle_deg": round(angle_deg, 2),
                        "distance_m": round(dist_m, 3),
                        "distance_cm": round(dist_m * 100.0, 1),
                    }
                )

            with self._lock:
                self._latest = {
                    "connected": True,
                    "points": points,
                    "angle_min_rad": angle_min,
                    "angle_max_rad": float(msg.get("angle_max", math.pi)),
                    "range_min_m": range_min,
                    "range_max_m": range_max,
                    "error": None,
                    "updated_at": time.time(),
                }
            log.debug("ROS2LidarBridge: %d points valides", len(points))

        except Exception as exc:  # noqa: BLE001
            log.warning("ROS2LidarBridge parse: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set(self, *, connected: bool, error: str | None = None) -> None:
        with self._lock:
            self._latest = {**self._latest, "connected": connected, "error": error}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _empty_snapshot(error: str) -> dict[str, Any]:
    return {
        "connected": False,
        "points": [],
        "angle_min_rad": -math.pi,
        "angle_max_rad": math.pi,
        "range_min_m": 0.0,
        "range_max_m": 12.0,
        "error": error,
        "updated_at": None,
    }


def _kill_proc(proc: subprocess.Popen | None) -> None:  # type: ignore[type-arg]
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass
