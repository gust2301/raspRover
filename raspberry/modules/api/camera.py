"""Flux MJPEG pour la camera du rover."""

from __future__ import annotations

import importlib
import io
import logging
import pathlib
import sys
import threading
import time
from collections.abc import Callable, Iterator

import yaml

try:
    from picamera2 import Picamera2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - dev hors Raspberry Pi
    Picamera2 = None  # type: ignore[assignment]
    system_site = "/usr/lib/python3/dist-packages"
    if system_site not in sys.path and pathlib.Path(system_site).exists():
        sys.path.append(system_site)
        try:
            Picamera2 = importlib.import_module("picamera2").Picamera2  # type: ignore[attr-defined]
        except ImportError:
            Picamera2 = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - pillow n'est pas requise
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config.yaml"
BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
FRAME_DELAY_FALLBACK = 1 / 24
BLACK_JPEG_FRAME = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19"
    b"\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.3"
    b"44\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18\r\r\x182!\x1c!222222222222222222222222222222"
    b'22222222222222222222222222\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01"\x00\x02\x11\x01'
    b"\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
    b"\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03"
    b"\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
    b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*"
    b"456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95"
    b"\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9"
    b"\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3"
    b"\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01"
    b"\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
    b"\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00"
    b'\x01\x02w\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1'
    b"\xc1\t#3R\xf0\x15br\xd1\n\x16$4\xe1%\xf1\x17\x18\x19\x1a&'()*56789:CDEFGHIJSTUVWXYZcdefg"
    b"hijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2"
    b"\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6"
    b"\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea"
    b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00"
    b"\xf7\xfa(\xa2\x80?\xff\xd9"
)


def _load_camera_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            cfg = yaml.safe_load(file) or {}
            return cfg.get("camera", {})
    return {}


def _camera_settings() -> tuple[int, int, int]:
    cfg = _load_camera_config()
    width = int(cfg.get("width", 640))
    height = int(cfg.get("height", 480))
    framerate = max(1, int(cfg.get("framerate", 24)))
    return width, height, framerate


def _multipart_frame(frame_bytes: bytes) -> bytes:
    return BOUNDARY + frame_bytes + b"\r\n"


def _generate_test_frame(width: int, height: int) -> bytes:
    if Image is None or ImageDraw is None:
        return BLACK_JPEG_FRAME

    image = Image.new("RGB", (width, height), color="black")
    draw = ImageDraw.Draw(image)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    draw.text((24, 24), f"RaspRover test stream\n{timestamp}", fill="white")

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


_camera_instance: object | None = None
_camera_lock = threading.Lock()
_camera_clients = 0

# ---------------------------------------------------------------------------
# Partage de frames avec le détecteur vision
# ---------------------------------------------------------------------------

_frame_callbacks: list[Callable[[bytes], None]] = []
_frame_counter = 0
_VISION_SAMPLE_EVERY = 5  # 1 frame sur 5 envoyée au détecteur vision (~5fps à 24fps)


def register_frame_callback(cb: Callable[[bytes], None]) -> None:
    """Enregistre un callback appelé avec les bytes JPEG toutes les N frames."""
    _frame_callbacks.append(cb)


def unregister_frame_callback(cb: Callable[[bytes], None]) -> None:
    if cb in _frame_callbacks:
        _frame_callbacks.remove(cb)


def _get_camera(width: int, height: int, framerate: int) -> object:
    global _camera_instance
    assert Picamera2 is not None
    if _camera_instance is None:
        cam = Picamera2()
        config = cam.create_video_configuration(main={"size": (width, height)})
        cam.configure(config)
        cam.start()
        time.sleep(0.2)
        log.info("Camera singleton started (%sx%s @ %sfps)", width, height, framerate)
        _camera_instance = cam
    return _camera_instance


def _release_camera() -> None:
    global _camera_instance
    if _camera_instance is not None:
        try:
            _camera_instance.stop()  # type: ignore[union-attr]
            _camera_instance.close()  # type: ignore[union-attr]
        except Exception:
            pass
        _camera_instance = None
        log.info("Camera singleton released")


def _picamera_stream(width: int, height: int, framerate: int) -> Iterator[bytes]:
    global _camera_clients
    delay = 1 / framerate

    with _camera_lock:
        _camera_clients += 1
        try:
            camera = _get_camera(width, height, framerate)
        except Exception as exc:
            _camera_clients -= 1
            raise exc

    log.info("Camera stream client connected (total=%d)", _camera_clients)
    try:
        while True:
            try:
                buffer = io.BytesIO()
                camera.capture_file(buffer, format="jpeg")  # type: ignore[union-attr]
                frame_bytes = buffer.getvalue()
                yield _multipart_frame(frame_bytes)

                # Partage avec le détecteur vision (toutes les N frames)
                global _frame_counter
                _frame_counter += 1
                if _frame_callbacks and _frame_counter % _VISION_SAMPLE_EVERY == 0:
                    for cb in _frame_callbacks:
                        try:
                            cb(frame_bytes)
                        except Exception:  # noqa: BLE001
                            pass
            except GeneratorExit:
                raise
            except Exception as exc:
                log.warning("Frame capture error (skipping): %s", exc)
            time.sleep(delay)
    except GeneratorExit:
        log.info("Camera stream client disconnected")
        raise
    finally:
        with _camera_lock:
            _camera_clients -= 1
            log.info("Camera clients remaining: %d", _camera_clients)
            if _camera_clients == 0:
                _release_camera()


def _test_pattern_stream(width: int, height: int, framerate: int) -> Iterator[bytes]:
    delay = 1 / framerate if framerate > 0 else FRAME_DELAY_FALLBACK
    log.warning("picamera2 unavailable, serving generated test frames")

    try:
        while True:
            yield _multipart_frame(_generate_test_frame(width, height))
            time.sleep(delay)
    except GeneratorExit:
        log.info("Test stream client disconnected")
        raise


def generate_frames() -> Iterator[bytes]:
    """Yield multipart MJPEG frames for the /stream route."""

    width, height, framerate = _camera_settings()
    if Picamera2 is None:
        yield from _test_pattern_stream(width, height, framerate)
        return

    try:
        yield from _picamera_stream(width, height, framerate)
    except GeneratorExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("picamera2 stream failed, falling back to test frames: %s", exc)
        yield from _test_pattern_stream(width, height, framerate)
