"""Serveur FastAPI — contrôle RaspRover via REST et WebSocket."""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import math
import pathlib
import struct
import subprocess
import time
import zlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from modules.audio import AlertPlayer
from modules.control import ESP32Link, LightController, MotorController, PanTiltController
from modules.control.drive_mixer import DriveConfig, DriveMixer
from modules.control.exceptions import ControlError
from modules.control.motor_controller import Direction
from modules.control.patrol import PatrolController
from modules.control.tracker import TrackerController
from modules.sensors import RPLidarA1, UltrasonicSensor, VisionObstacleDetector
from modules.sensors.human_detector import HumanDetector
from modules.sensors.lidar import LidarPoint, LidarSnapshot
from modules.sensors.lidar_ros import ROS2LidarBridge

from .camera import (
    capture_photo,
    generate_frames,
    get_recording_state,
    register_frame_callback,
    start_standalone_vision_producer,
    start_video_recording,
    stop_standalone_vision_producer,
    stop_video_recording,
    unregister_frame_callback,
)
from .db import init_db, list_incidents, list_incidents_by_date, log_incident, update_media_key
from .media import get_r2_client

log = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config.yaml"

_link: ESP32Link | None = None
_motors: MotorController | None = None
_pantilt: PanTiltController | None = None
_lights: LightController | None = None
_mixer: DriveMixer = DriveMixer()
_alert: AlertPlayer = AlertPlayer()  # device configuré dans lifespan
_ultrasonic: UltrasonicSensor | None = None
_lidar: RPLidarA1 | None = None
_lidar_ros_adapter: _ROS2LidarAdapter | None = None
_lidar_ros: ROS2LidarBridge | None = None
_vision: VisionObstacleDetector | None = None
_patrol: PatrolController | None = None
_human_detector: HumanDetector | None = None
_tracker: TrackerController | None = None
_rover_name: str = "rasprover"
_manual_obstacle_override_until: float = 0.0
_slam_container: str = "ros2-lidar"   # SLAM runs inside the lidar container to share DDS


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


async def _auto_record_coro(mp4_path: str, incident_id: int) -> None:
    """Enregistre _AUTO_RECORD_DURATION secondes de vidéo puis upload vers R2."""
    from modules.control.patrol import _AUTO_RECORD_DURATION

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: start_video_recording(mp4_path))
    except RuntimeError as exc:
        log.warning("Auto-vidéo: impossible de démarrer (%s)", exc)
        return
    try:
        await asyncio.sleep(_AUTO_RECORD_DURATION)
    finally:
        mp4_out = await loop.run_in_executor(None, stop_video_recording)

    if not mp4_out:
        return

    r2 = get_r2_client()
    if r2 is None:
        pathlib.Path(mp4_out).unlink(missing_ok=True)
        return

    try:
        ts = pathlib.Path(mp4_out).stem.replace("auto_video_", "")
        date_str = ts[:10] if len(ts) >= 10 else datetime.datetime.utcnow().strftime("%Y-%m-%d")
        key = f"{_rover_name}/{date_str}/videos/auto_{ts}.mp4"
        with open(mp4_out, "rb") as f:
            data = f.read()
        await loop.run_in_executor(None, lambda: r2.upload_bytes(key, data, "video/mp4"))
        update_media_key(incident_id, key)
        log.info("Auto-vidéo uploadée : %s", key)
    except Exception as exc:
        log.warning("Auto-vidéo upload échoué : %s", exc)
    finally:
        pathlib.Path(mp4_out).unlink(missing_ok=True)


async def _auto_photo_coro(incident_id: int) -> None:
    """Capture une photo de la personne détectée et l'upload vers R2."""
    loop = asyncio.get_running_loop()
    try:
        jpeg_bytes = await loop.run_in_executor(None, capture_photo)
    except Exception as exc:
        log.warning("Auto-photo: capture échouée : %s", exc)
        return

    r2 = get_r2_client()
    if r2 is None:
        return

    now = datetime.datetime.utcnow()
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    key = f"{_rover_name}/{now.strftime('%Y-%m-%d')}/photos/human_{ts}.jpg"

    try:
        await loop.run_in_executor(None, lambda: r2.upload_bytes(key, jpeg_bytes, "image/jpeg"))
        update_media_key(incident_id, key)
        log.info("Auto-photo humaine uploadée : %s", key)
    except Exception as exc:
        log.warning("Auto-photo: upload échoué : %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global \
        _link, \
        _motors, \
        _pantilt, \
        _lights, \
        _ultrasonic, \
        _lidar, \
        _lidar_ros, \
        _lidar_ros_adapter, \
        _vision, \
        _patrol, \
        _human_detector, \
        _tracker, \
        _rover_name

    global _mixer
    cfg = _load_config()
    _rover_name = cfg.get("rover", {}).get("name", "rasprover")
    init_db()
    _mixer = DriveMixer(DriveConfig.from_dict(cfg.get("drive", {})))
    ctrl = cfg.get("control", {})
    esp32_required = bool(ctrl.get("esp32_required", False))
    port = ctrl.get("serial_port", "/dev/ttyAMA0")
    baudrate = ctrl.get("baudrate", 115200)
    timeout_s = ctrl.get("timeout_s", 1.0)
    pt_cfg = ctrl.get("pantilt", {})

    _link = ESP32Link(port=port, baudrate=baudrate, timeout_s=timeout_s)
    try:
        _link.open()
        _motors = MotorController(
            _link,
            max_speed=ctrl.get("motor_max_speed", 0.5),
            default_speed=ctrl.get("motor_default_speed", 0.35),
        )
        _pantilt = PanTiltController(
            _link,
            pan_range=(pt_cfg.get("pan_min_deg", -90), pt_cfg.get("pan_max_deg", 90)),
            tilt_range=(pt_cfg.get("tilt_min_deg", -45), pt_cfg.get("tilt_max_deg", 60)),
            speed=pt_cfg.get("servo_speed", 600),
            accel=pt_cfg.get("servo_accel", 50),
        )
        _lights = LightController(_link)
        log.info("ESP32 connecte - port=%s", port)
    except Exception as exc:  # noqa: BLE001
        _motors = None
        _pantilt = None
        _lights = None
        msg = f"ESP32 indisponible sur {port}: {exc}"
        if esp32_required:
            log.error("%s (control.esp32_required=true)", msg)
            raise
        log.warning("%s - demarrage continue en mode degrade", msg)

    audio_cfg = cfg.get("audio", {})
    _alert.device = audio_cfg.get("device") or None
    log.info("Audio device : %s", _alert.device or "default")

    # Capteur ultrason — via Arduino Uno (USB série)
    sensor_cfg = cfg.get("sensors", {}).get("ultrasonic", {})
    if sensor_cfg.get("enabled", False):
        _ultrasonic = UltrasonicSensor(
            port=sensor_cfg.get("port") or None,
            baudrate=int(sensor_cfg.get("baudrate", 9600)),
            obstacle_threshold_cm=float(sensor_cfg.get("obstacle_threshold_cm", 20.0)),
        )
        _ultrasonic.start()
        log.info("HC-SR04 (Arduino) démarré")
    else:
        log.info("Capteur ultrason désactivé (sensors.ultrasonic.enabled: false)")

    lidar_cfg = cfg.get("sensors", {}).get("lidar", {})
    if lidar_cfg.get("enabled", False):
        _lidar = RPLidarA1(
            port=lidar_cfg.get("port") or None,
            baudrate=int(lidar_cfg.get("baudrate", 115200)),
            obstacle_threshold_cm=float(lidar_cfg.get("obstacle_threshold_cm", 45.0)),
            front_fov_deg=float(lidar_cfg.get("front_fov_deg", 55.0)),
            min_quality=int(lidar_cfg.get("min_quality", 5)),
            max_distance_mm=float(lidar_cfg.get("max_distance_mm", 6000.0)),
            motor_dtr=bool(lidar_cfg.get("motor_dtr", False)),
            motor_start_delay_s=float(lidar_cfg.get("motor_start_delay_s", 0.8)),
            lidar_angle_offset_deg=float(
                lidar_cfg.get(
                    "lidar_angle_offset_deg",
                    lidar_cfg.get("angle_offset_deg", 0.0),
                )
            ),
            invert_angles=bool(lidar_cfg.get("lidar_invert_angles", False)),
        )
        _lidar.start()
        log.info("RPLIDAR A1 demarre (USB, port=%s)", lidar_cfg.get("port") or "auto")
    else:
        log.info("RPLIDAR desactive (sensors.lidar.enabled: false)")

    # Détecteur vision (OpenCV) — complément au HC-SR04
    vision_cfg = cfg.get("sensors", {}).get("vision", {})
    if vision_cfg.get("enabled", True):
        _vision = VisionObstacleDetector(
            edge_threshold=float(vision_cfg.get("edge_threshold", 0.08)),
            history=int(vision_cfg.get("history", 3)),
            uniform_std_max=float(vision_cfg.get("uniform_std_max", 18.0)),
        )
        _vision.start()
        register_frame_callback(_vision.push_frame)
        start_standalone_vision_producer()
        log.info("VisionObstacleDetector démarré")
    else:
        log.info("Détecteur vision désactivé (sensors.vision.enabled: false)")

    # Détecteur humain (HOG+SVM) + contrôleur de tracking
    _human_detector = HumanDetector()
    _human_detector.start()
    register_frame_callback(_human_detector.push_frame)
    log.info("HumanDetector démarré")

    # ROS2 LIDAR bridge — démarré avant la patrouille pour que l'adapter soit disponible
    _lidar_ros = ROS2LidarBridge()
    _lidar_ros.start()
    ros2_cfg = cfg.get("sensors", {}).get("ros2_lidar", {})
    _lidar_ros_adapter = _ROS2LidarAdapter(
        _lidar_ros,
        obstacle_cm=float(
            ros2_cfg.get("obstacle_threshold_cm", lidar_cfg.get("obstacle_threshold_cm", 45.0))
        ),
        angle_offset_deg=float(ros2_cfg.get("angle_offset_deg", 140.0)),
    )
    log.info("ROS2LidarBridge démarré")

    # Contrôleur de patrouille
    patrol_cfg = cfg.get("patrol", {})
    _patrol = PatrolController(
        motors=_motors,
        ultrasonic=_ultrasonic,
        lidar=_lidar or _lidar_ros_adapter,
        vision=_vision,
        pantilt=_pantilt,
        human_detector=_human_detector,
        navigation_mode=str(patrol_cfg.get("navigation_mode", "LIDAR_ONLY")),
        speed=float(patrol_cfg.get("speed", 0.3)),
        obstacle_cm=float(patrol_cfg.get("obstacle_cm", 40.0)),
        step_duration=float(patrol_cfg.get("step_duration", 0.7)),
        scan_with_pantilt=bool(patrol_cfg.get("scan_with_pantilt", False)),
        stuck_timeout=float(patrol_cfg.get("stuck_timeout", 3.5)),
        lidar_stop_cm=float(patrol_cfg.get("lidar_stop_cm", 32.0)),
        lidar_warning_cm=float(patrol_cfg.get("lidar_warning_cm", 65.0)),
        lidar_safe_cm=float(patrol_cfg.get("lidar_safe_cm", 110.0)),
        turn_clearance_cm=float(patrol_cfg.get("turn_clearance_cm", 55.0)),
        rear_clearance_cm=float(patrol_cfg.get("rear_clearance_cm", 50.0)),
        min_decision_duration_ms=int(patrol_cfg.get("min_decision_duration_ms", 1200)),
        patrol_forward_speed=float(
            patrol_cfg.get("patrol_forward_speed", patrol_cfg.get("speed", 0.3))
        ),
        patrol_turn_speed=float(patrol_cfg.get("patrol_turn_speed", 0.42)),
        scan_zone_min_points=int(patrol_cfg.get("scan_zone_min_points", 2)),
        on_incident=log_incident,
        on_auto_record=_auto_record_coro,
        on_capture_photo=_auto_photo_coro,
    )

    _tracker = (
        TrackerController(
            _pantilt,
            _human_detector,
            on_incident=log_incident,
            on_auto_record=_auto_record_coro,
        )
        if _pantilt
        else None
    )

    if _motors:
        _motors.stop()
    if _pantilt:
        _pantilt.center()
    if _lights:
        _lights.set_camera_light(False)
    log.info(
        "RaspRover API demarree - esp32=%s lidar=%s ros2=%s",
        bool(_motors),
        bool(_lidar),
        bool(_lidar_ros),
    )

    broadcast_task = asyncio.create_task(_lidar_scan_broadcast())

    yield

    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass

    if _patrol and _patrol.active:
        loop = asyncio.get_event_loop()
        await _patrol.stop(loop)
    if _tracker and _tracker.active:
        _tracker.stop()
    if get_recording_state()["is_recording"]:
        stop_video_recording()
    if _human_detector:
        unregister_frame_callback(_human_detector.push_frame)
        _human_detector.stop()
    if _vision:
        stop_standalone_vision_producer()
        unregister_frame_callback(_vision.push_frame)
        _vision.stop()
    if _ultrasonic:
        _ultrasonic.stop()
    if _lidar:
        _lidar.stop()
    if _lidar_ros:
        _lidar_ros.stop()
    if _motors:
        _motors.shutdown()
    if _link:
        _link.close()
    _alert.close()
    log.info("RaspRover API arrêtée proprement")


def _compute_battery_pct(voltage: float) -> int:
    """
    Convertit la tension 3S LiPo en pourcentage (0-100).
    Plage : 9.6 V (vide, 3.2 V/cell) → 12.6 V (plein, 4.2 V/cell).
    """
    pct = (voltage - 9.6) / (12.6 - 9.6) * 100.0
    return max(0, min(100, round(pct)))


def _enrich_feedback(feedback: dict) -> dict:
    """
    Enrichit le dict brut de l'ESP32 :
      - Le firmware Waveshare envoie la tension sous 'v' en centivolts
        (ex: v=1134 → 11.34 V). Le JS officiel Waveshare fait data['v']/100.
        On divise par 100 pour obtenir des volts réels.
      - Mappe vers 'voltage' (lisible) et calcule 'battery' (%)
      - Mappe L/R → speed_l/speed_r pour cohérence avec le frontend
    """
    result = dict(feedback)
    # Tension : champ 'v' en centivolts (firmware Waveshare), ou 'voltage' (simulateur)
    raw_v = result.get("v") if result.get("v") is not None else result.get("voltage")
    if raw_v is not None:
        try:
            raw = float(raw_v)
            # Le firmware envoie en centivolts (ex: 1134 = 11.34 V).
            # Si la valeur > 30, c'est forcément des centivolts.
            v = raw / 100.0 if raw > 30 else raw
            result["voltage"] = round(v, 2)
            result["battery"] = _compute_battery_pct(v)
        except (TypeError, ValueError):
            pass
    if "L" in result and "speed_l" not in result:
        result["speed_l"] = result["L"]
    if "R" in result and "speed_r" not in result:
        result["speed_r"] = result["R"]
    return result


def _ros2_zone_min_cm(points: list[dict], center_deg: float, half_width: float) -> float | None:
    dists = [
        p["distance_cm"]
        for p in points
        if abs(((p["angle_deg"] - center_deg + 180.0) % 360.0) - 180.0) <= half_width
    ]
    return min(dists) if dists else None


def _ros2_zone_name(corrected_deg: float) -> str:
    a = corrected_deg % 360.0
    if a <= 45 or a >= 315:
        return "front"
    if 45 < a <= 135:
        return "right"
    if 135 < a <= 225:
        return "rear"
    return "left"


class _ROS2LidarAdapter:
    """Wraps ROS2LidarBridge to expose the same snapshot/to_dict interface as RPLidarA1."""

    def __init__(
        self, bridge: ROS2LidarBridge, obstacle_cm: float = 45.0, angle_offset_deg: float = 0.0
    ) -> None:
        self._bridge = bridge
        self._obstacle_cm = obstacle_cm
        self._angle_offset_deg = angle_offset_deg % 360.0

    def set_angle_offset(self, angle_offset_deg: float) -> None:
        self._angle_offset_deg = float(angle_offset_deg) % 360.0

    def calibration_to_dict(self) -> dict:
        snap = self.snapshot
        raw = self._bridge.snapshot.get("points", [])
        debug = [
            {
                "raw_angle": round(p["angle_deg"], 1),
                "corrected_angle": round(self._correct(p["angle_deg"]), 1),
                "zone": _ros2_zone_name(self._correct(p["angle_deg"])),
                "distance_cm": round(p["distance_cm"], 1),
            }
            for p in sorted(raw, key=lambda x: x["distance_cm"])[:24]
        ]
        return {
            "angle_offset_deg": self._angle_offset_deg,
            "invert_angles": False,
            "connected": snap.connected,
            "port": "ros2",
            "error": snap.error if not snap.connected else None,
            "zones": {
                "front": snap.front_distance_cm,
                "right": snap.right_distance_cm,
                "rear": snap.rear_distance_cm,
                "left": snap.left_distance_cm,
            },
            "debug_points": debug,
        }

    def _correct(self, angle_deg: float) -> float:
        return (angle_deg + self._angle_offset_deg) % 360.0

    @property
    def snapshot(self) -> LidarSnapshot:
        snap = self._bridge.snapshot
        if not snap.get("connected"):
            return LidarSnapshot(connected=False, error=snap.get("error") or "ROS2 hors ligne")
        raw = snap.get("points", [])
        points = tuple(
            LidarPoint(
                angle_deg=self._correct(p["angle_deg"]),
                distance_mm=p["distance_m"] * 1000.0,
                quality=15,
            )
            for p in raw
        )
        corrected = [
            {"angle_deg": self._correct(p["angle_deg"]), "distance_cm": p["distance_cm"]}
            for p in raw
        ]
        front_cm = _ros2_zone_min_cm(corrected, 0.0, 45.0)
        right_cm = _ros2_zone_min_cm(corrected, 90.0, 45.0)
        rear_cm = _ros2_zone_min_cm(corrected, 180.0, 45.0)
        left_cm = _ros2_zone_min_cm(corrected, 270.0, 45.0)
        return LidarSnapshot(
            connected=True,
            points=points,
            front_distance_cm=front_cm,
            right_distance_cm=right_cm,
            rear_distance_cm=rear_cm,
            left_distance_cm=left_cm,
            obstacle_front=front_cm is not None and front_cm < self._obstacle_cm,
        )

    def to_dict(self) -> dict:
        snap = self.snapshot
        pts = snap.points
        front_pts = [
            {"angle": round(p.angle_deg, 1), "distance_cm": round(p.distance_mm / 10.0, 1)}
            for p in pts
            if abs(((p.angle_deg + 180.0) % 360.0) - 180.0) <= 90.0
        ]
        if len(front_pts) > 180:
            step = max(1, len(front_pts) // 180)
            front_pts = front_pts[::step]
        return {
            "lidar_connected": snap.connected,
            "lidar_port": "ros2",
            "lidar_error": snap.error if not snap.connected else None,
            "lidar_points": front_pts,
            "lidar_front_cm": snap.front_distance_cm,
            "lidar_left_cm": snap.left_distance_cm,
            "lidar_right_cm": snap.right_distance_cm,
            "lidar_rear_cm": snap.rear_distance_cm,
            "lidar_obstacle_front": snap.obstacle_front,
            "lidar_updated_at": self._bridge.snapshot.get("updated_at"),
            "lidar_angle_offset_deg": self._angle_offset_deg,
            "lidar_invert_angles": False,
        }


def _obstacle_front() -> bool:
    """
    Obstacle devant pour la sécurité anti-collision (pilotage manuel).

    Le LIDAR est prioritaire. L'ultrason reste en fallback si le capteur est
    explicitement active. La vision n'est pas utilisée ici pour éviter les faux
    positifs sur le sol, les reflets ou les zones latérales.
    """
    if time.monotonic() < _manual_obstacle_override_until:
        return False
    if _lidar:
        snap = _lidar.snapshot
        if snap.connected and snap.obstacle_front:
            return True
    elif _lidar_ros_adapter:
        snap = _lidar_ros_adapter.snapshot
        if snap.connected and snap.obstacle_front:
            return True
    return _ultrasonic.reading.front.obstacle if _ultrasonic else False


def _system_status() -> dict:
    pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
    light_state = _lights.state if _lights else {"camera_light": False}
    patrol_data = _patrol.to_dict() if _patrol else {"patrol_active": False, "patrol_state": "idle"}
    tracker_data = _tracker.to_dict() if _tracker else {"tracker_active": False}
    human_data = _human_detector.to_dict() if _human_detector else {}
    distance_data = _ultrasonic.to_dict() if _ultrasonic else {}
    vision_data = _vision.to_dict() if _vision else {}
    if _lidar:
        lidar_data = _lidar.to_dict()
    elif _lidar_ros_adapter:
        lidar_data = _lidar_ros_adapter.to_dict()
    else:
        lidar_data = {"lidar_connected": False}
    return {
        "esp32_connected": bool(_link and _link.is_open),
        "control_available": _motors is not None,
        "pan": pan,
        "tilt": tilt,
        **light_state,
        **distance_data,
        **vision_data,
        **lidar_data,
        **patrol_data,
        **tracker_data,
        **human_data,
    }


app = FastAPI(title="RaspRover Control API", version="1.0.0", lifespan=lifespan)

# CORS : autorise le front Vercel + réseau local
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # dev local
        "http://localhost:4173",  # vite preview
        "https://*.vercel.app",  # production Vercel
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "robot": "rasprover"}


@app.get("/stream")
async def video_stream() -> StreamingResponse:
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# REST — Moteurs
# ---------------------------------------------------------------------------


@app.post("/api/motors/move")
async def motors_move(body: dict[str, Any]) -> dict:
    if _motors is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    direction_str = body.get("direction", "forward")
    speed = body.get("speed")
    speed_f = float(speed) if speed is not None else None
    try:
        direction = Direction(direction_str)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"ok": False, "error": f"direction inconnue: {direction_str}"}
        )

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: _motors.from_direction(direction, speed_f))  # type: ignore[union-attr]
        return {"ok": True}
    except ControlError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.post("/api/motors/stop")
async def motors_stop() -> dict:
    if _motors is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _motors.stop)
    return {"ok": True}


# ---------------------------------------------------------------------------
# REST — Pan-Tilt
# ---------------------------------------------------------------------------


@app.post("/api/pantilt")
async def pantilt_goto(body: dict[str, Any]) -> dict:
    if _pantilt is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    pan = body.get("pan")
    tilt = body.get("tilt")
    pan_f = float(pan) if pan is not None else None
    tilt_f = float(tilt) if tilt is not None else None
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: _pantilt.goto(pan_f, tilt_f))  # type: ignore[union-attr]
        return {"ok": True, "pan": _pantilt.position[0], "tilt": _pantilt.position[1]}
    except ControlError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.post("/api/pantilt/center")
async def pantilt_center() -> dict:
    if _pantilt is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _pantilt.center)
    return {"ok": True}


# ---------------------------------------------------------------------------
# REST â€” Eclairage
# ---------------------------------------------------------------------------


@app.post("/api/lights/camera")
async def camera_light(body: dict[str, Any]) -> dict:
    if _lights is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    enabled = bool(body.get("enabled", False))
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda enabled=enabled: _lights.set_camera_light(enabled))
    return {"ok": True, **_lights.state}


# ---------------------------------------------------------------------------
# REST — Capteur ultrason
# ---------------------------------------------------------------------------


@app.get("/api/distance")
async def get_distance() -> dict:
    """Distance mesurée par le HC-SR04. Rafraîchie toutes les 200 ms."""
    if _ultrasonic is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Capteur ultrason non activé (sensors.ultrasonic.enabled: false)"},
        )
    return _ultrasonic.to_dict()


@app.get("/api/vision")
async def get_vision() -> dict:
    """État de la détection vision (OpenCV). Rafraîchi à ~5 fps."""
    if _vision is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Détecteur vision non activé (sensors.vision.enabled: false)"},
        )
    return _vision.to_dict()


@app.get("/api/lidar")
async def get_lidar() -> dict:
    """Etat du LIDAR (RPLidar série ou ROS2) et points du scan avant."""
    if _lidar is not None:
        return _lidar.to_dict()
    if _lidar_ros_adapter is not None:
        return _lidar_ros_adapter.to_dict()
    return JSONResponse(status_code=503, content={"error": "Aucun LIDAR actif"})


def _persist_lidar_calibration(angle_offset_deg: float, invert_angles: bool) -> None:
    cfg = _load_config()
    sensors = cfg.setdefault("sensors", {})
    if _lidar is not None:
        lidar_cfg = sensors.setdefault("lidar", {})
        lidar_cfg["lidar_angle_offset_deg"] = float(angle_offset_deg) % 360.0
        lidar_cfg["lidar_invert_angles"] = bool(invert_angles)
    else:
        ros2_cfg = sensors.setdefault("ros2_lidar", {})
        ros2_cfg["angle_offset_deg"] = float(angle_offset_deg) % 360.0
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


@app.get("/api/lidar/calibration")
async def get_lidar_calibration() -> dict:
    if _lidar is not None:
        return _lidar.calibration_to_dict()
    if _lidar_ros_adapter is not None:
        return _lidar_ros_adapter.calibration_to_dict()
    return JSONResponse(status_code=503, content={"error": "Aucun LIDAR actif"})


@app.post("/api/lidar/calibration")
async def set_lidar_calibration(body: dict[str, Any]) -> dict:
    if _lidar is not None:
        calibration = _lidar.set_calibration(
            angle_offset_deg=body.get("angle_offset_deg"),
            invert_angles=body.get("invert_angles"),
        )
        if bool(body.get("save", False)):
            _persist_lidar_calibration(
                calibration["angle_offset_deg"], calibration["invert_angles"]
            )
        return {"ok": True, **calibration}

    if _lidar_ros_adapter is not None:
        new_offset = float(body.get("angle_offset_deg", _lidar_ros_adapter._angle_offset_deg))
        _lidar_ros_adapter.set_angle_offset(new_offset)
        if bool(body.get("save", False)):
            _persist_lidar_calibration(new_offset, False)
        return {"ok": True, **_lidar_ros_adapter.calibration_to_dict()}

    return JSONResponse(status_code=503, content={"error": "Aucun LIDAR actif"})


@app.post("/api/lidar/calibrate/auto")
async def auto_calibrate_lidar() -> dict:
    """Pointe automatiquement l'avant du robot vers le cluster de points le plus proche.

    Place le robot face à un obstacle, puis appelle cet endpoint.
    L'offset est calculé pour que la direction des points les plus proches devienne l'avant (0°).
    """
    if _lidar_ros_adapter is None or _lidar_ros is None:
        return JSONResponse(status_code=503, content={"error": "ROS2 LIDAR non actif"})
    snap = _lidar_ros.snapshot
    if not snap.get("connected"):
        return JSONResponse(status_code=503, content={"error": "ROS2 LIDAR non connecté"})
    points = snap.get("points", [])
    if not points:
        return JSONResponse(status_code=503, content={"error": "Scan vide"})
    closest = sorted(points, key=lambda p: p["distance_cm"])[:15]
    angles = [p["angle_deg"] for p in closest]
    sin_sum = sum(math.sin(math.radians(a)) for a in angles)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles)
    mean_raw = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    new_offset = (360.0 - mean_raw) % 360.0
    _lidar_ros_adapter.set_angle_offset(new_offset)
    _persist_lidar_calibration(new_offset, False)
    return {
        "ok": True,
        "angle_offset_deg": round(new_offset, 1),
        **_lidar_ros_adapter.calibration_to_dict(),
    }


@app.get("/api/lidar/scan")
async def get_lidar_scan() -> dict:
    """Dernier scan 360° ROS2 (/scan topic via docker exec)."""
    if _lidar_ros is None:
        return JSONResponse(status_code=503, content={"error": "ROS2LidarBridge non démarré"})
    snap = _lidar_ros.snapshot
    if not snap.get("connected"):
        return JSONResponse(
            status_code=503,
            content={"error": snap.get("error", "ROS2 LIDAR non connecté"), "connected": False},
        )
    return snap


# ---------------------------------------------------------------------------
# REST — SLAM (slam_toolbox via Docker)
# ---------------------------------------------------------------------------


def _slam_running() -> bool:
    """True si async_slam_toolbox_node tourne dans le container lidar."""
    r = subprocess.run(
        ["docker", "exec", _slam_container, "pgrep", "-f", "async_slam_toolbox_node"],
        capture_output=True,
    )
    return r.returncode == 0


@app.get("/api/slam/status")
async def slam_status() -> dict:
    running = await asyncio.get_running_loop().run_in_executor(None, _slam_running)
    return {"running": running}


@app.post("/api/slam/start")
async def slam_start() -> dict:
    loop = asyncio.get_running_loop()
    if await loop.run_in_executor(None, _slam_running):
        return {"ok": True, "running": True, "message": "déjà en cours"}

    if not await loop.run_in_executor(None, lambda: _docker_running(_slam_container)):
        return JSONResponse(status_code=503, content={"ok": False, "error": "container ros2-lidar absent"})

    cmd = (
        "source /opt/ros/jazzy/setup.bash && "
        "ros2 run tf2_ros static_transform_publisher --frame-id odom --child-frame-id laser & "
        "python3 /opt/map_writer.py & "
        "ros2 run slam_toolbox async_slam_toolbox_node --ros-args "
        "-p base_frame:=laser -p odom_frame:=odom -p scan_topic:=/scan "
        "-p use_lifecycle_manager:=false -p use_sim_time:=false"
    )
    try:
        await loop.run_in_executor(
            None,
            lambda: subprocess.Popen(
                ["docker", "exec", "-d", _slam_container, "bash", "-c", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        )
        return {"ok": True, "running": True}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.post("/api/slam/stop")
async def slam_stop() -> dict:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["docker", "exec", _slam_container, "pkill", "-f", "async_slam_toolbox_node"],
                capture_output=True,
                timeout=10.0,
            ),
        )
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["docker", "exec", _slam_container, "pkill", "-f", "map_writer"],
                capture_output=True,
                timeout=5.0,
            ),
        )
        return {"ok": True, "running": False}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.get("/api/slam/map")
async def slam_map() -> dict:
    """Retourne la carte SLAM courante en PNG base64."""
    loop = asyncio.get_running_loop()
    if not await loop.run_in_executor(None, _slam_running):
        return JSONResponse(status_code=503, content={"error": "SLAM non actif"})

    msg = await loop.run_in_executor(None, lambda: _read_ros2_map_once(_slam_container))
    if msg is None:
        return JSONResponse(status_code=503, content={"error": "Aucune carte disponible"})

    try:
        png_b64 = _occupancy_grid_to_png_b64(msg)
    except ValueError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    info = msg.get("info", {})
    origin = info.get("origin", {}).get("position", {})
    return {
        "ok": True,
        "image": png_b64,
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "resolution_m": info.get("resolution", 0.05),
        "origin_x": origin.get("x", 0.0),
        "origin_y": origin.get("y", 0.0),
    }


@app.post("/api/slam/save")
async def slam_save(body: dict[str, Any] | None = None) -> dict:
    """Demande au slam_toolbox de sauvegarder la carte courante."""
    loop = asyncio.get_running_loop()
    if not await loop.run_in_executor(None, _slam_running):
        return JSONResponse(status_code=503, content={"ok": False, "error": "SLAM non actif"})

    map_name = (body or {}).get("name", "/tmp/rasprover_map")
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [
                    "docker",
                    "exec",
                    _slam_container,
                    "bash",
                    "-c",
                    f"source /opt/ros/jazzy/setup.bash && ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap '{{name: {{data: \"{map_name}\"}}}}'",
                ],
                capture_output=True,
                text=True,
                timeout=15.0,
            ),
        )
        ok = result.returncode == 0
        return {"ok": ok, "map_name": map_name, "output": result.stdout.strip()}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# REST — Patrouille
# ---------------------------------------------------------------------------


@app.post("/api/patrol/start")
async def patrol_start() -> dict:
    """Démarre la patrouille autonome."""
    if _patrol is None or _motors is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    loop = asyncio.get_running_loop()
    await _patrol.start(loop)
    return {"ok": True, **_patrol.to_dict()}


@app.post("/api/patrol/stop")
async def patrol_stop() -> dict:
    """Arrête la patrouille autonome."""
    if _patrol is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not ready"})
    loop = asyncio.get_running_loop()
    await _patrol.stop(loop)
    return {"ok": True, **_patrol.to_dict()}


@app.get("/api/patrol/status")
async def patrol_status() -> dict:
    if _patrol is None:
        return {"patrol_active": False, "patrol_state": "idle"}
    return _patrol.to_dict()


# ---------------------------------------------------------------------------
# REST — Audio
# ---------------------------------------------------------------------------


@app.get("/api/audio/info")
async def audio_info() -> dict:
    """Diagnostic : indique quel lecteur audio est disponible."""
    return {
        "player": _alert.player_name,
        "device": _alert.resolved_device,
        "available": _alert.player_available,
        "last_error": _alert.last_error,
    }


@app.post("/api/audio/test")
async def audio_test() -> dict:
    """Déclenche une alerte audio de test (REST, pour diagnostic)."""
    if not _alert.player_available:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Aucun lecteur audio (aplay/paplay/ffplay)"},
        )
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _alert.play)
    await asyncio.sleep(0.3)
    err = _alert.last_error
    return {"ok": err is None, "player": _alert.player_name, "error": err}


# ---------------------------------------------------------------------------
# REST — Statut
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def get_status() -> dict:
    loop = asyncio.get_running_loop()
    base_status = _system_status()
    if _link is None or not _link.is_open:
        return {
            **base_status,
            "status_warning": "ESP32 indisponible - controle moteur/pantilt desactive",
        }
    try:
        # T=130 (chassis feedback) → tension réelle + vitesses L/R
        feedback = await loop.run_in_executor(
            None,
            lambda: _link.request_feedback(timeout_s=1.0, command_type=130),  # type: ignore[union-attr]
        )
        return {**base_status, **_enrich_feedback(feedback)}
    except Exception as exc:  # noqa: BLE001
        return {**base_status, "esp32_connected": False, "status_warning": str(exc)}


# ---------------------------------------------------------------------------
# WebSocket — contrôle temps-réel
# ---------------------------------------------------------------------------


class _ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        log.info("Client WebSocket connecté (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.remove(ws)
        log.info("Client WebSocket déconnecté (%d restants)", len(self._clients))

    async def broadcast(self, data: dict) -> None:
        if not self._clients:
            return
        msg = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_manager = _ConnectionManager()


async def _lidar_scan_broadcast() -> None:
    """Push 360° ROS2 scan to all WS clients at ~5 Hz."""
    while True:
        await asyncio.sleep(0.2)
        if not _lidar_ros or not _manager._clients:
            continue
        snap = _lidar_ros.snapshot
        if not snap.get("connected"):
            continue
        points = snap.get("points", [])
        # Down-sample: keep at most 360 points for the broadcast
        if len(points) > 360:
            step = max(1, len(points) // 360)
            points = points[::step]
        try:
            await _manager.broadcast(
                {
                    "type": "lidar_scan",
                    "connected": True,
                    "points": points,
                    "range_min_m": snap.get("range_min_m", 0.0),
                    "range_max_m": snap.get("range_max_m", 12.0),
                    "updated_at": snap.get("updated_at"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("lidar_scan broadcast: %s", exc)


# ---------------------------------------------------------------------------
# SLAM helpers
# ---------------------------------------------------------------------------


def _docker_running(name: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=3.0,
        ).stdout.strip()
        return out == "true"
    except Exception:  # noqa: BLE001
        return False


def _read_ros2_map_once(container: str = "ros2-slam") -> dict | None:
    """Read the latest map from the JSON file written by map_writer.py."""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "cat", "/tmp/current_map.json"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        msg = json.loads(result.stdout)
        if not isinstance(msg, dict) or "data" not in msg:
            return None
        return msg
    except Exception as exc:  # noqa: BLE001
        log.warning("_read_ros2_map_once: %s", exc)
        return None


def _occupancy_grid_to_png_b64(msg: dict) -> str:
    """Convert nav_msgs/OccupancyGrid to a base64-encoded grayscale PNG."""
    info = msg.get("info", {})
    width: int = int(info.get("width", 0))
    height: int = int(info.get("height", 0))
    raw: list[int] = msg.get("data", [])

    if width <= 0 or height <= 0 or len(raw) != width * height:
        raise ValueError(f"OccupancyGrid invalide: {width}×{height}, {len(raw)} points")

    pixels = bytearray(width * height)
    for i, v in enumerate(raw):
        if v == -1:
            pixels[i] = 128  # unknown → grey
        elif v == 0:
            pixels[i] = 255  # free → white
        else:
            pixels[i] = max(0, 255 - v * 2)  # occupied (100) → black

    # Minimal grayscale PNG encoder (stdlib only)
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))

    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # filter=None
        raw_rows.extend(pixels[y * width : (y + 1) * width])
    idat = chunk(b"IDAT", zlib.compress(bytes(raw_rows), 9))
    iend = chunk(b"IEND", b"")

    png_bytes = sig + ihdr + idat + iend
    return base64.b64encode(png_bytes).decode()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await _manager.connect(ws)
    loop = asyncio.get_running_loop()

    try:
        while True:
            data: dict = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "move":
                if _motors is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                # Patrouille active → ignore les commandes manuelles
                if _patrol and _patrol.active:
                    await ws.send_json(
                        {"type": "error", "message": "Patrouille active — arrête-la d'abord"}
                    )
                    continue
                try:
                    if "x" in data or "y" in data:
                        x = float(data.get("x", 0.0))
                        y = float(data.get("y", 0.0))
                        # Sécurité : bloque l'avance si obstacle devant (ultrason OU vision)
                        if y > 0.1 and _obstacle_front():
                            await loop.run_in_executor(None, _motors.stop)  # type: ignore[union-attr]
                            await ws.send_json(
                                {
                                    "type": "obstacle_blocked",
                                    "message": "Obstacle détecté à l'avant",
                                }
                            )
                            continue
                        left, right = _mixer.mix(x, y)
                        await loop.run_in_executor(
                            None,
                            lambda left=left, right=right: _motors.drive(left, right),  # type: ignore[union-attr]
                        )
                    else:
                        direction_str = data.get("direction", "forward")
                        speed = data.get("speed")
                        speed_f = float(speed) if speed is not None else None
                        direction = Direction(direction_str)
                        # Sécurité : bloque l'avance si obstacle devant (ultrason OU vision)
                        if direction == Direction.FORWARD and _obstacle_front():
                            await loop.run_in_executor(None, _motors.stop)  # type: ignore[union-attr]
                            await ws.send_json(
                                {
                                    "type": "obstacle_blocked",
                                    "message": "Obstacle détecté à l'avant",
                                }
                            )
                            continue
                        await loop.run_in_executor(
                            None,
                            lambda direction=direction, speed_f=speed_f: _motors.from_direction(
                                direction, speed_f
                            ),  # type: ignore[union-attr]
                        )
                except (ValueError, ControlError) as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})

            elif msg_type == "stop":
                if _motors:
                    await loop.run_in_executor(None, _motors.stop)

            elif msg_type == "obstacle_override":
                global _manual_obstacle_override_until
                seconds = max(1.0, min(10.0, float(data.get("seconds", 5.0))))
                _manual_obstacle_override_until = time.monotonic() + seconds
                log.warning("Obstacle manuel ignore pendant %.1fs", seconds)
                await ws.send_json(
                    {
                        "type": "obstacle_override_ack",
                        "seconds": seconds,
                    }
                )

            elif msg_type == "pantilt":
                if _pantilt is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                pan = data.get("pan")
                tilt = data.get("tilt")
                pan_f = float(pan) if pan is not None else None
                tilt_f = float(tilt) if tilt is not None else None
                try:
                    await loop.run_in_executor(
                        None,
                        lambda pan_f=pan_f, tilt_f=tilt_f: _pantilt.goto(pan_f, tilt_f),  # type: ignore[union-attr]
                    )
                    pos = _pantilt.position
                    await ws.send_json({"type": "pantilt_ack", "pan": pos[0], "tilt": pos[1]})
                except ControlError as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})

            elif msg_type == "light":
                if _lights is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                enabled = bool(data.get("enabled", False))
                await loop.run_in_executor(
                    None,
                    lambda enabled=enabled: _lights.set_camera_light(enabled),
                )
                await ws.send_json({"type": "light_ack", **_lights.state})

            elif msg_type == "alert":
                action = data.get("action", "play")
                if action == "stop":
                    _alert.stop()
                    await ws.send_json({"type": "alert_ack", "action": "stop", "ok": True})
                else:
                    if not _alert.player_available:
                        await ws.send_json(
                            {
                                "type": "alert_ack",
                                "action": "play",
                                "ok": False,
                                "error": "Aucun lecteur audio disponible sur le Pi (aplay/paplay introuvable)",
                            }
                        )
                    else:
                        await loop.run_in_executor(None, _alert.play)
                        # Laisse 200ms pour que l'erreur éventuelle remonte
                        await asyncio.sleep(0.2)
                        err = _alert.last_error
                        await ws.send_json(
                            {
                                "type": "alert_ack",
                                "action": "play",
                                "ok": err is None,
                                "player": _alert.player_name,
                                "error": err,
                            }
                        )

            elif msg_type == "patrol":
                if _patrol is None or _motors is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                action = data.get("action", "start")
                if action == "start":
                    if _tracker and _tracker.active:
                        _tracker.stop()
                    await _patrol.start(loop)
                else:
                    await _patrol.stop(loop)
                await ws.send_json({"type": "patrol_ack", **_patrol.to_dict()})

            elif msg_type == "tracker":
                if _tracker is None or _pantilt is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                action = data.get("action", "start")
                if action == "start":
                    if _patrol and _patrol.active:
                        await _patrol.stop(loop)
                    _tracker.start(loop)
                else:
                    _tracker.stop()
                tracker_data = _tracker.to_dict()
                human_data = _human_detector.to_dict() if _human_detector else {}
                await ws.send_json({"type": "tracker_ack", **tracker_data, **human_data})

            elif msg_type == "lidar_calibration":
                action = data.get("action")
                if _lidar is not None:
                    if action == "offset":
                        _lidar.adjust_angle_offset(float(data.get("delta_deg", 0.0)))
                    elif action == "invert":
                        _lidar.toggle_angle_inversion()
                    elif action == "set":
                        _lidar.set_calibration(
                            angle_offset_deg=data.get("angle_offset_deg"),
                            invert_angles=data.get("invert_angles"),
                        )
                elif _lidar_ros_adapter is not None:
                    if action == "offset":
                        new_offset = (
                            _lidar_ros_adapter._angle_offset_deg + float(data.get("delta_deg", 0.0))
                        ) % 360.0
                        _lidar_ros_adapter.set_angle_offset(new_offset)
                    elif action == "set":
                        _lidar_ros_adapter.set_angle_offset(
                            float(data.get("angle_offset_deg", 0.0))
                        )
                else:
                    await ws.send_json({"type": "error", "message": "lidar not ready"})
                    continue
                if action not in ("offset", "invert", "set"):
                    await ws.send_json(
                        {"type": "error", "message": f"action calibration inconnue: {action}"}
                    )
                    continue
                await ws.send_json({"type": "status", **_system_status()})

            elif msg_type == "status":
                base_status = _system_status()
                if _link is None or not _link.is_open:
                    await ws.send_json(
                        {
                            "type": "status",
                            **base_status,
                            "status_warning": "ESP32 indisponible - controle moteur/pantilt desactive",
                        }
                    )
                    continue
                try:
                    # T=130 (chassis feedback) → tension réelle + vitesses L/R
                    feedback = await loop.run_in_executor(
                        None,
                        lambda: _link.request_feedback(timeout_s=1.0, command_type=130),  # type: ignore[union-attr]
                    )
                    await ws.send_json(
                        {
                            "type": "status",
                            **base_status,
                            **_enrich_feedback(feedback),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    await ws.send_json(
                        {
                            "type": "status",
                            **base_status,
                            "esp32_connected": False,
                            "status_warning": str(exc),
                        }
                    )

    except WebSocketDisconnect:
        _manager.disconnect(ws)
        if _motors:
            try:
                await loop.run_in_executor(None, _motors.stop)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# REST — Média (photo / vidéo / galerie R2)
# ---------------------------------------------------------------------------


@app.post("/api/photo")
async def take_photo() -> dict:
    """Capture un JPEG et l'upload vers R2. Retourne key, url, size, timestamp."""
    loop = asyncio.get_running_loop()
    try:
        jpeg_bytes = await loop.run_in_executor(None, capture_photo)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    r2 = get_r2_client()
    if r2 is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Stockage R2 non configuré"},
        )

    now = datetime.datetime.utcnow()
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    key = f"{_rover_name}/{now.strftime('%Y-%m-%d')}/photos/photo_{ts}.jpg"

    try:
        await loop.run_in_executor(None, lambda: r2.upload_bytes(key, jpeg_bytes, "image/jpeg"))
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    url = await loop.run_in_executor(None, lambda: r2.presigned_url(key))
    return {"ok": True, "key": key, "url": url, "size": len(jpeg_bytes), "timestamp": ts}


@app.post("/api/video/start")
async def video_start() -> dict:
    """Démarre l'enregistrement vidéo vers /tmp/."""
    if get_recording_state()["is_recording"]:
        return JSONResponse(
            status_code=409, content={"ok": False, "error": "Déjà en cours d'enregistrement"}
        )

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    mp4_path = f"/tmp/video_{ts}.mp4"

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: start_video_recording(mp4_path))
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    return {"ok": True, "recording": True, "started_at": ts}


@app.post("/api/video/stop")
async def video_stop() -> dict:
    """Arrête l'enregistrement et upload le MP4 vers R2."""
    state = get_recording_state()
    if not state["is_recording"]:
        return JSONResponse(
            status_code=409, content={"ok": False, "error": "Aucun enregistrement en cours"}
        )

    started_at: float | None = state["started_at"]
    loop = asyncio.get_running_loop()

    mp4_path = await loop.run_in_executor(None, stop_video_recording)
    if not mp4_path:
        return JSONResponse(status_code=500, content={"ok": False, "error": "Fichier introuvable"})

    duration_s = round(time.time() - started_at, 1) if started_at else 0.0

    ts = Path(mp4_path).stem.replace("video_", "")
    date_str = ts[:10] if len(ts) >= 10 else datetime.datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{_rover_name}/{date_str}/videos/video_{ts}.mp4"

    r2 = get_r2_client()
    if r2 is None:
        Path(mp4_path).unlink(missing_ok=True)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Stockage R2 non configuré", "duration_s": duration_s},
        )

    try:
        with open(mp4_path, "rb") as f:
            data = f.read()
        content_type = "video/mp4" if mp4_path.endswith(".mp4") else "video/h264"
        await loop.run_in_executor(None, lambda: r2.upload_bytes(key, data, content_type))
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    finally:
        Path(mp4_path).unlink(missing_ok=True)

    url = await loop.run_in_executor(None, lambda: r2.presigned_url(key))
    return {"ok": True, "key": key, "url": url, "duration_s": duration_s}


@app.get("/api/media")
async def list_media() -> list | dict:
    """Liste les médias stockés dans R2 avec leurs presigned URLs."""
    r2 = get_r2_client()
    if r2 is None:
        return JSONResponse(status_code=503, content={"error": "Stockage R2 non configuré"})
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, lambda: r2.list_media(prefix=_rover_name))
    return items


@app.delete("/api/media/{key:path}")
async def delete_media(key: str) -> dict:
    """Supprime un média de R2."""
    r2 = get_r2_client()
    if r2 is None:
        return JSONResponse(
            status_code=503, content={"ok": False, "error": "Stockage R2 non configuré"}
        )
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: r2.delete(key))
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    return {"ok": True, "key": key}


@app.get("/api/incidents")
async def get_incidents(days: int = 7, date: str | None = None) -> list:
    """Retourne les incidents des N derniers jours ou d'une date précise (YYYY-MM-DD)."""
    loop = asyncio.get_running_loop()
    if date:
        incidents = await loop.run_in_executor(None, lambda: list_incidents_by_date(date))
    else:
        incidents = await loop.run_in_executor(None, lambda: list_incidents(days))
    r2 = get_r2_client()

    if r2 is None:
        return incidents

    # Génère les presigned URLs pour les médias liés
    def enrich(inc: dict) -> dict:
        if inc.get("media_key"):
            try:
                inc["media_url"] = r2.presigned_url(inc["media_key"])
            except Exception:
                inc["media_url"] = None
        return inc

    return await loop.run_in_executor(None, lambda: [enrich(i) for i in incidents])
