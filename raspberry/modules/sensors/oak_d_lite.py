"""OAK-D Lite RGB, spatial detections and short-range depth safety.

DepthAI is deliberately optional: importing the API server must still work on
development machines and on a rover where the camera is disconnected.
"""

from __future__ import annotations

import json
import logging
import pathlib
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OakTarget:
    label: str
    confidence: float
    cx: float
    cy: float
    x_mm: int
    y_mm: int
    z_mm: int


class OakDLiteSensor:
    """Background DepthAI pipeline with a fail-safe, read-only public state."""

    def __init__(
        self,
        *,
        model: str = "mobilenet-ssd",
        fps: int = 8,
        obstacle_distance_mm: int = 700,
        depth_roi_top: float = 0.45,
        depth_roi_bottom: float = 0.82,
        min_valid_pixels: int = 80,
        on_person: Callable[[tuple[float, float, float] | None], None] | None = None,
        on_depth: Callable[[dict[str, bool], dict[str, float | None]], None] | None = None,
    ) -> None:
        self.model = model
        self.fps = max(1, min(int(fps), 15))
        self.obstacle_distance_mm = max(150, int(obstacle_distance_mm))
        self.depth_roi_top = max(0.0, min(float(depth_roi_top), 0.9))
        self.depth_roi_bottom = max(self.depth_roi_top + 0.05, min(float(depth_roi_bottom), 1.0))
        self.min_valid_pixels = max(10, int(min_valid_pixels))
        self._on_person = on_person
        self._on_depth = on_depth
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._available = False
        self._connected = False
        self._usb_speed: str | None = None
        self._error: str | None = None
        self._detections: list[OakTarget] = []
        self._person_target: OakTarget | None = None
        self._person_update_ts = 0.0
        self._vehicle_target: OakTarget | None = None
        self._vehicle_update_ts = 0.0
        self._depth_zones = {"left": False, "center": False, "right": False}
        self._depth_cm: dict[str, float | None] = {
            "left": None,
            "center": None,
            "right": None,
        }
        self._last_update_ts = 0.0

    @property
    def vehicle_target(self) -> OakTarget | None:
        """Fresh spatial vehicle target, or ``None`` when it is lost."""
        with self._lock:
            if time.monotonic() - self._vehicle_update_ts > 0.75:
                return None
            return self._vehicle_target

    @property
    def person_target(self) -> OakTarget | None:
        """Fresh spatial person target, or ``None`` when it is lost."""
        with self._lock:
            if time.monotonic() - self._person_update_ts > 0.75:
                return None
            return self._person_target

    @property
    def depth_zones(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._depth_zones)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="oak-d-lite")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process and process.poll() is None:
            process.terminate()
        if self._thread:
            self._thread.join(timeout=4.0)
            self._thread = None
        self._publish_person(None)
        self._publish_depth(
            {"left": False, "center": False, "right": False},
            {"left": None, "center": None, "right": None},
        )

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "oak_available": self._available,
                "oak_connected": self._connected,
                "oak_usb_speed": self._usb_speed,
                "oak_error": self._error,
                "oak_depth_zones": dict(self._depth_zones),
                "oak_depth_cm": dict(self._depth_cm),
                "oak_detections": [target.__dict__ for target in self._detections],
                "oak_vehicle": self._vehicle_target.__dict__ if self._vehicle_target else None,
                "oak_last_update_age_s": (
                    round(time.monotonic() - self._last_update_ts, 2)
                    if self._last_update_ts
                    else None
                ),
            }

    def _run(self) -> None:
        raspberry_dir = pathlib.Path(__file__).resolve().parents[2]
        python = raspberry_dir / ".venv-oak" / "bin" / "python"
        worker = pathlib.Path(__file__).with_name("oak_worker.py")
        if not python.exists():
            self._set_error(f"Environnement OAK absent: {python}", available=False)
            return
        while not self._stop.is_set():
            try:
                command = [
                    str(python),
                    "-u",
                    str(worker),
                    "--model",
                    self.model,
                    "--fps",
                    str(self.fps),
                    "--obstacle-distance-mm",
                    str(self.obstacle_distance_mm),
                    "--depth-roi-top",
                    str(self.depth_roi_top),
                    "--depth-roi-bottom",
                    str(self.depth_roi_bottom),
                    "--min-valid-pixels",
                    str(self.min_valid_pixels),
                ]
                self._process = subprocess.Popen(  # noqa: S603
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self._process.stdout is not None
                for line in self._process.stdout:
                    if self._stop.is_set():
                        break
                    try:
                        self._handle_message(json.loads(line))
                    except json.JSONDecodeError:
                        log.debug("OAK worker: %s", line.rstrip())
                return_code = self._process.wait(timeout=3.0)
                if not self._stop.is_set():
                    raise RuntimeError(f"processus OAK arrêté (code {return_code})")
            except Exception as exc:  # noqa: BLE001
                self._set_error(str(exc), available=True)
                if not self._stop.wait(3.0):
                    log.warning("OAK-D Lite: nouvelle tentative après erreur: %s", exc)
            finally:
                self._process = None

    def _handle_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ready":
            with self._lock:
                self._available = True
                self._connected = True
                self._usb_speed = str(message.get("usb_speed") or "UNKNOWN")
                self._error = message.get("model_error")
            return
        if kind == "detections":
            targets = [OakTarget(**item) for item in message.get("items", [])]
            person = next((item for item in targets if item.label == "person"), None)
            vehicle = next(
                (
                    item
                    for item in targets
                    if item.label in {"car", "truck", "bus", "motorbike", "motorcycle"}
                ),
                None,
            )
            with self._lock:
                self._detections = targets
                self._person_target = person
                self._person_update_ts = time.monotonic()
                self._vehicle_target = vehicle
                self._vehicle_update_ts = time.monotonic()
                self._last_update_ts = time.monotonic()
            self._publish_person((person.cx, person.cy, person.confidence) if person else None)
            return
        if kind == "depth":
            zones = {name: bool(message["zones"].get(name)) for name in self._depth_zones}
            distances = {name: message["distances_cm"].get(name) for name in self._depth_cm}
            with self._lock:
                self._depth_zones = zones
                self._depth_cm = distances
                self._last_update_ts = time.monotonic()
            self._publish_depth(zones, distances)
            return
        if kind == "error":
            self._set_error(str(message.get("message", "Erreur OAK")), available=True)

    def _publish_person(self, target: tuple[float, float, float] | None) -> None:
        if self._on_person:
            self._on_person(target)

    def _publish_depth(self, zones: dict[str, bool], distances: dict[str, float | None]) -> None:
        if self._on_depth:
            self._on_depth(zones, distances)

    def _set_error(self, message: str, *, available: bool) -> None:
        with self._lock:
            self._available = available
            self._connected = False
            self._error = message[:500]
            self._detections = []
            self._person_target = None
            self._person_update_ts = 0.0
            self._vehicle_target = None
            self._vehicle_update_ts = 0.0
        self._publish_person(None)
        self._publish_depth(
            {"left": False, "center": False, "right": False},
            {"left": None, "center": None, "right": None},
        )
        log.error("OAK-D Lite indisponible: %s", message)
