"""Serveur FastAPI — contrôle RaspRover via REST et WebSocket."""

from __future__ import annotations

import asyncio
import datetime
import logging
import pathlib
import time
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
from modules.sensors import UltrasonicSensor, VisionObstacleDetector
from modules.sensors.human_detector import HumanDetector

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
from .db import init_db, list_incidents, log_incident, update_media_key
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
_vision: VisionObstacleDetector | None = None
_patrol: PatrolController | None = None
_human_detector: HumanDetector | None = None
_tracker: TrackerController | None = None
_rover_name: str = "rasprover"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global \
        _link, \
        _motors, \
        _pantilt, \
        _lights, \
        _ultrasonic, \
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
    port = ctrl.get("serial_port", "/dev/ttyAMA0")
    baudrate = ctrl.get("baudrate", 115200)
    timeout_s = ctrl.get("timeout_s", 1.0)
    pt_cfg = ctrl.get("pantilt", {})

    _link = ESP32Link(port=port, baudrate=baudrate, timeout_s=timeout_s)
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

    # Contrôleur de patrouille
    patrol_cfg = cfg.get("patrol", {})
    _patrol = PatrolController(
        motors=_motors,
        ultrasonic=_ultrasonic,
        vision=_vision,
        pantilt=_pantilt,
        speed=float(patrol_cfg.get("speed", 0.3)),
        obstacle_cm=float(patrol_cfg.get("obstacle_cm", 40.0)),
        step_duration=float(patrol_cfg.get("step_duration", 0.7)),
        scan_with_pantilt=bool(patrol_cfg.get("scan_with_pantilt", False)),
        stuck_timeout=float(patrol_cfg.get("stuck_timeout", 3.5)),
        on_incident=log_incident,
        on_auto_record=_auto_record_coro,
    )

    _tracker = TrackerController(
        _pantilt,
        _human_detector,
        on_incident=log_incident,
        on_auto_record=_auto_record_coro,
    )

    _motors.stop()
    _pantilt.center()
    _lights.set_camera_light(False)
    log.info("RaspRover API démarrée — port=%s", port)

    yield

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


def _obstacle_front() -> bool:
    """
    Obstacle devant pour la sécurité anti-collision (pilotage manuel).

    On se base uniquement sur l'ultrason : fiable, seuil calibré (obstacle_threshold_cm).
    La vision n'est PAS utilisée ici — trop de faux positifs (sol, reflets, zones G/D)
    qui bloqueraient l'avance à tort. La vision est gérée dans la logique de patrouille.
    """
    return _ultrasonic.reading.front.obstacle if _ultrasonic else False


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
    if _link is None:
        return JSONResponse(status_code=503, content={"error": "not ready"})
    loop = asyncio.get_running_loop()
    try:
        # T=130 (chassis feedback) → tension réelle + vitesses L/R
        feedback = await loop.run_in_executor(
            None,
            lambda: _link.request_feedback(timeout_s=1.0, command_type=130),  # type: ignore[union-attr]
        )
        pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
        light_state = _lights.state if _lights else {"camera_light": False}
        return {**_enrich_feedback(feedback), "pan": pan, "tilt": tilt, **light_state}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"error": str(exc)})


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


_manager = _ConnectionManager()


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

            elif msg_type == "status":
                if _link is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                try:
                    # T=130 (chassis feedback) → tension réelle + vitesses L/R
                    feedback = await loop.run_in_executor(
                        None,
                        lambda: _link.request_feedback(timeout_s=1.0, command_type=130),  # type: ignore[union-attr]
                    )
                    pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
                    light_state = _lights.state if _lights else {"camera_light": False}
                    distance_data = _ultrasonic.to_dict() if _ultrasonic else {}
                    vision_data = _vision.to_dict() if _vision else {}
                    patrol_data = (
                        _patrol.to_dict()
                        if _patrol
                        else {"patrol_active": False, "patrol_state": "idle"}
                    )
                    tracker_data = _tracker.to_dict() if _tracker else {"tracker_active": False}
                    human_data = _human_detector.to_dict() if _human_detector else {}
                    await ws.send_json(
                        {
                            "type": "status",
                            **_enrich_feedback(feedback),
                            "pan": pan,
                            "tilt": tilt,
                            **light_state,
                            **distance_data,
                            **vision_data,
                            **patrol_data,
                            **tracker_data,
                            **human_data,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    await ws.send_json({"type": "error", "message": str(exc)})

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
async def get_incidents(days: int = 7) -> list:
    """Retourne les incidents des N derniers jours (défaut 7)."""
    loop = asyncio.get_running_loop()
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
