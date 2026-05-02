"""Serveur FastAPI — contrôle RaspRover via REST et WebSocket."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
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
from modules.sensors import UltrasonicSensor, VisionObstacleDetector

from .camera import (
    generate_frames,
    register_frame_callback,
    start_standalone_vision_producer,
    stop_standalone_vision_producer,
    unregister_frame_callback,
)

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


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _link, _motors, _pantilt, _lights, _ultrasonic, _vision, _patrol

    global _mixer
    cfg = _load_config()
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

    # Contrôleur de patrouille
    # La vision N'est PAS passée au patrol : trop de faux positifs (sol, reflets)
    # qui empêchent d'avancer. L'ultrason seul gère les obstacles en patrol.
    # La vision reste active pour l'affichage temps réel et la future détection latérale.
    patrol_cfg = cfg.get("patrol", {})
    _patrol = PatrolController(
        motors=_motors,
        ultrasonic=_ultrasonic,
        vision=None,
        pantilt=_pantilt,
        speed=float(patrol_cfg.get("speed", 0.3)),
        obstacle_cm=float(patrol_cfg.get("obstacle_cm", 40.0)),
        step_duration=float(patrol_cfg.get("step_duration", 0.7)),
        scan_with_pantilt=bool(patrol_cfg.get("scan_with_pantilt", False)),
        stuck_timeout=float(patrol_cfg.get("stuck_timeout", 3.5)),
    )

    _motors.stop()
    _pantilt.center()
    _lights.set_camera_light(False)
    log.info("RaspRover API démarrée — port=%s", port)

    yield

    if _patrol and _patrol.active:
        loop = asyncio.get_event_loop()
        await _patrol.stop(loop)
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
        feedback = await loop.run_in_executor(
            None,
            lambda: _link.request_feedback(timeout_s=1.0, command_type=126),  # type: ignore[union-attr]
        )
        pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
        light_state = _lights.state if _lights else {"camera_light": False}
        return {**feedback, "pan": pan, "tilt": tilt, **light_state}
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
                    await _patrol.start(loop)
                else:
                    await _patrol.stop(loop)
                await ws.send_json({"type": "patrol_ack", **_patrol.to_dict()})

            elif msg_type == "status":
                if _link is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                try:
                    feedback = await loop.run_in_executor(
                        None,
                        lambda: _link.request_feedback(timeout_s=1.0, command_type=126),  # type: ignore[union-attr]
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
                    await ws.send_json(
                        {
                            "type": "status",
                            **feedback,
                            "pan": pan,
                            "tilt": tilt,
                            **light_state,
                            **distance_data,
                            **vision_data,
                            **patrol_data,
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
