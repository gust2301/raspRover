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

from modules.control import ESP32Link, MotorController, PanTiltController
from modules.control.exceptions import ControlError
from modules.control.motor_controller import Direction
from .camera import generate_frames

log = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config.yaml"

_link: ESP32Link | None = None
_motors: MotorController | None = None
_pantilt: PanTiltController | None = None


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _link, _motors, _pantilt

    cfg = _load_config()
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

    _motors.stop()
    _pantilt.center()
    log.info("RaspRover API démarrée — port=%s", port)

    yield

    if _motors:
        _motors.shutdown()
    if _link:
        _link.close()
    log.info("RaspRover API arrêtée proprement")


app = FastAPI(title="RaspRover Control API", version="1.0.0", lifespan=lifespan)

# CORS : autorise le front Vercel + réseau local
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # dev local
        "http://localhost:4173",   # vite preview
        "https://*.vercel.app",    # production Vercel
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
        return JSONResponse(status_code=400, content={"ok": False, "error": f"direction inconnue: {direction_str}"})

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
# REST — Statut
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def get_status() -> dict:
    if _link is None:
        return JSONResponse(status_code=503, content={"error": "not ready"})
    loop = asyncio.get_running_loop()
    try:
        feedback = await loop.run_in_executor(
            None, lambda: _link.request_feedback(timeout_s=1.0, command_type=126)  # type: ignore[union-attr]
        )
        pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
        return {**feedback, "pan": pan, "tilt": tilt}
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
                direction_str = data.get("direction", "forward")
                speed = data.get("speed")
                speed_f = float(speed) if speed is not None else None
                try:
                    direction = Direction(direction_str)
                    await loop.run_in_executor(None, lambda: _motors.from_direction(direction, speed_f))  # type: ignore[union-attr]
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
                    await loop.run_in_executor(None, lambda: _pantilt.goto(pan_f, tilt_f))  # type: ignore[union-attr]
                    pos = _pantilt.position
                    await ws.send_json({"type": "pantilt_ack", "pan": pos[0], "tilt": pos[1]})
                except ControlError as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})

            elif msg_type == "status":
                if _link is None:
                    await ws.send_json({"type": "error", "message": "not ready"})
                    continue
                try:
                    feedback = await loop.run_in_executor(
                        None, lambda: _link.request_feedback(timeout_s=1.0, command_type=126)  # type: ignore[union-attr]
                    )
                    pan, tilt = _pantilt.position if _pantilt else (0.0, 0.0)
                    await ws.send_json({"type": "status", **feedback, "pan": pan, "tilt": tilt})
                except Exception as exc:  # noqa: BLE001
                    await ws.send_json({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        _manager.disconnect(ws)
        if _motors:
            try:
                await loop.run_in_executor(None, _motors.stop)
            except Exception:  # noqa: BLE001
                pass
