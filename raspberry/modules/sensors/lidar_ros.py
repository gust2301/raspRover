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
_CONTAINER_NAME = "ros2-lidar"  # always use name, never ID
_MAX_BROADCAST_POINTS = 360


class ROS2LidarBridge:
    """Background subscriber to ROS2 /scan via docker exec.

    Usage (mirrors RPLidarA1 interface):
        bridge = ROS2LidarBridge()
        bridge.start()
        snap = bridge.snapshot  # dict
        bridge.stop()
    """

    def __init__(self) -> None:
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
        self._thread = threading.Thread(target=self._run, daemon=True, name="ros2-lidar-bridge")
        self._thread.start()
        log.info("ROS2LidarBridge démarré (container=%s)", _CONTAINER_NAME)

    def stop(self) -> None:
        self._stop_event.set()
        _kill_proc(self._proc)
        _kill_remote_scan_processes()
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
        # No pre-check: let docker exec itself signal failure.
        # This avoids silent permission errors from docker ps/inspect.
        while not self._stop_event.is_set():
            try:
                self._stream()
            except Exception as exc:  # noqa: BLE001
                log.warning("ROS2LidarBridge: %s — retry in 5s", exc)
                self._set(connected=False, error=str(exc))
                self._stop_event.wait(5.0)

    def _stream(self) -> None:
        # ``docker exec`` ne propage pas toujours la terminaison de son client
        # au processus créé dans le conteneur. Après un redémarrage de l'API,
        # les anciens ``ros2 topic echo`` restaient donc actifs et finissaient
        # par saturer Nav2. Il ne doit exister qu'un seul lecteur RaspRover.
        _kill_remote_scan_processes()
        cmd = [
            "docker",
            "exec",
            _CONTAINER_NAME,
            "bash",
            "-c",
            # ROS 2 tronque les longues séquences à 128 éléments par défaut.
            # Un LaserScan A1 contient ~720 distances : sans --full-length,
            # trois quarts du balayage 360° disparaissent avant le parsing.
            f"source /opt/ros/jazzy/setup.bash && ros2 topic echo {_TOPIC} --full-length",
        ]
        log.info("ROS2LidarBridge: docker exec %s ... ros2 topic echo %s", _CONTAINER_NAME, _TOPIC)
        self._proc = subprocess.Popen(  # type: ignore[assignment]
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Give the process a moment to either produce output or die immediately
        # (e.g. "No such container" or "permission denied").
        try:
            first_line = self._proc.stdout.readline()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"docker exec non lisible: {exc}") from exc

        if not first_line:
            stderr_out = self._proc.stderr.read(400).strip()  # type: ignore[union-attr]
            _kill_proc(self._proc)
            self._proc = None
            raise RuntimeError(
                stderr_out or f"docker exec {_CONTAINER_NAME} s'est arrêté immédiatement"
            )

        buf: list[str] = []
        # Re-seed the buffer with the first line we already consumed
        stripped = first_line.rstrip("\n")
        if stripped != "---":
            buf.append(stripped)

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
# module-level helpers
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
        return
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass


def _kill_remote_scan_processes() -> None:
    """Supprime les lecteurs /scan laissés dans le conteneur par docker exec."""
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                _CONTAINER_NAME,
                "pkill",
                "-f",
                "[r]os2 topic echo /scan",
            ],
            capture_output=True,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
