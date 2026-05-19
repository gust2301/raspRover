"""RPLIDAR A1 USB service.

Reads the 360 degree scan stream in a background thread and exposes a compact
snapshot suitable for obstacle avoidance and the web UI.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

try:
    import serial  # type: ignore[import-not-found]
    import serial.tools.list_ports  # type: ignore[import-not-found]

    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False
    log.warning("pyserial absent - RPLidarA1 indisponible")


_SYNC_BYTE = 0xA5
_CMD_STOP = 0x25
_CMD_SCAN = 0x20
_CMD_RESET = 0x40
_DESCRIPTOR_LEN = 7
_DESCRIPTOR_TIMEOUT_S = 2.0
_FIRST_MEASUREMENT_TIMEOUT_S = 2.0
_MAX_POINTS = 1440


@dataclass(frozen=True)
class LidarPoint:
    angle_deg: float
    distance_mm: float
    quality: int


@dataclass(frozen=True)
class LidarSnapshot:
    connected: bool = False
    port: str | None = None
    points: tuple[LidarPoint, ...] = ()
    front_distance_cm: float | None = None
    left_distance_cm: float | None = None
    right_distance_cm: float | None = None
    obstacle_front: bool = False
    updated_at: float | None = None
    error: str | None = "non demarre"


def _angle_delta(angle: float, center: float) -> float:
    return ((angle - center + 180.0) % 360.0) - 180.0


def _auto_detect_port() -> str | None:
    if not _SERIAL_AVAILABLE:
        return None

    scored: list[tuple[int, str]] = []
    for info in serial.tools.list_ports.comports():
        text = " ".join(
            str(value or "")
            for value in (info.device, info.description, info.manufacturer, info.product)
        ).lower()
        score = 0
        if "rplidar" in text or "slamtec" in text:
            score += 100
        if "cp210" in text or "silicon labs" in text:
            score += 50
        if "usb" in info.device.lower() or "acm" in info.device.lower():
            score += 10
        if score:
            scored.append((score, info.device))

    if scored:
        scored.sort(reverse=True)
        port = scored[0][1]
        log.info("RPLIDAR detecte via comports : %s", port)
        return port

    for port in ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"):
        try:
            s = serial.Serial(port, timeout=0.1)
            s.close()
            log.info("Port serie candidat RPLIDAR : %s", port)
            return port
        except (serial.SerialException, OSError):
            continue
    return None


class RPLidarA1:
    """Minimal RPLIDAR A1 driver using the standard serial scan protocol."""

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 115200,
        obstacle_threshold_cm: float = 70.0,
        front_fov_deg: float = 50.0,
        min_quality: int = 5,
        max_distance_mm: float = 6000.0,
        motor_dtr: bool = False,
        motor_start_delay_s: float = 0.8,
    ) -> None:
        self.port = port
        self.baudrate = int(baudrate)
        self.obstacle_threshold_cm = float(obstacle_threshold_cm)
        self.front_fov_deg = float(front_fov_deg)
        self.min_quality = int(min_quality)
        self.max_distance_mm = float(max_distance_mm)
        self.motor_dtr = bool(motor_dtr)
        self.motor_start_delay_s = float(motor_start_delay_s)

        self._lock = threading.Lock()
        self._latest = LidarSnapshot(error="non demarre")
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._serial: object | None = None
        self._resolved_port: str | None = None
        self._active_motor_dtr = self.motor_dtr

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="rplidar-a1")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._stop_scan()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._close_serial()
        log.info("RPLidarA1 arrete")

    @property
    def snapshot(self) -> LidarSnapshot:
        with self._lock:
            return self._latest

    def to_dict(self) -> dict:
        snap = self.snapshot
        points = [
            {"angle": round(p.angle_deg, 1), "distance_cm": round(p.distance_mm / 10.0, 1)}
            for p in snap.points
            if abs(_angle_delta(p.angle_deg, 0.0)) <= 90.0
        ]
        if len(points) > 180:
            step = max(1, len(points) // 180)
            points = points[::step]
        return {
            "lidar_connected": snap.connected,
            "lidar_port": snap.port,
            "lidar_error": snap.error,
            "lidar_points": points,
            "lidar_front_cm": snap.front_distance_cm,
            "lidar_left_cm": snap.left_distance_cm,
            "lidar_right_cm": snap.right_distance_cm,
            "lidar_obstacle_front": snap.obstacle_front,
            "lidar_updated_at": snap.updated_at,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._open_serial()
                scan_started = False
                for motor_dtr in self._motor_dtr_attempts():
                    self._active_motor_dtr = motor_dtr
                    self._set_motor_dtr(motor_dtr)
                    self._start_scan()
                    try:
                        self._read_scan_loop()
                    except TimeoutError:
                        self._stop_scan()
                        log.warning(
                            "RPLIDAR: aucune mesure avec DTR=%s, essai suivant",
                            motor_dtr,
                        )
                        continue
                    scan_started = True
                    break
                if not scan_started:
                    raise TimeoutError("timeout lecture scan apres essais DTR")
            except Exception as exc:  # noqa: BLE001
                log.warning("RPLIDAR deconnecte ou indisponible : %s", exc)
                self._set_snapshot(
                    LidarSnapshot(
                        connected=False,
                        port=self._resolved_port,
                        error=str(exc),
                        updated_at=time.time(),
                    )
                )
                self._close_serial()
                self._stop_event.wait(2.0)

    def _open_serial(self) -> None:
        if not _SERIAL_AVAILABLE:
            raise RuntimeError("pyserial absent")
        port = self.port or _auto_detect_port()
        if not port:
            raise RuntimeError("aucun port RPLIDAR detecte")
        self._resolved_port = port
        self._serial = serial.Serial(port, self.baudrate, timeout=1.0)
        self._set_motor_dtr(self.motor_dtr)
        self._serial.reset_input_buffer()  # type: ignore[union-attr]
        self._serial.reset_output_buffer()  # type: ignore[union-attr]
        log.info("RPLIDAR connecte sur %s (%d baud)", port, self.baudrate)

    def _motor_dtr_attempts(self) -> tuple[bool, ...]:
        return (self.motor_dtr, not self.motor_dtr)

    def _set_motor_dtr(self, value: bool) -> None:
        if self._serial is None:
            return
        try:
            self._serial.setDTR(value)  # type: ignore[union-attr]
            log.info("RPLIDAR moteur: DTR=%s", value)
            time.sleep(self.motor_start_delay_s)
        except Exception as exc:  # noqa: BLE001
            log.debug("RPLIDAR: setDTR(%s) ignore (%s)", value, exc)

    def _close_serial(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        self._serial = None

    def _send_command(self, cmd: int) -> None:
        if self._serial is None:
            return
        self._serial.write(bytes([_SYNC_BYTE, cmd]))  # type: ignore[union-attr]
        self._serial.flush()  # type: ignore[union-attr]

    def _start_scan(self) -> None:
        assert self._serial is not None
        self._send_command(_CMD_STOP)
        time.sleep(0.05)
        try:
            self._serial.reset_input_buffer()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        self._send_command(_CMD_SCAN)
        descriptor = self._read_scan_descriptor()
        log.debug("RPLIDAR scan descriptor: %s", descriptor.hex(" "))

    def _read_scan_descriptor(self) -> bytes:
        assert self._serial is not None
        deadline = time.monotonic() + _DESCRIPTOR_TIMEOUT_S
        window = bytearray()

        while time.monotonic() < deadline and not self._stop_event.is_set():
            chunk = self._serial.read(1)  # type: ignore[union-attr]
            if not chunk:
                continue
            window.extend(chunk)
            if len(window) > _DESCRIPTOR_LEN:
                del window[:-_DESCRIPTOR_LEN]
            if len(window) >= 2 and window[-2:] == b"\xa5\x5a":
                rest = self._serial.read(_DESCRIPTOR_LEN - 2)  # type: ignore[union-attr]
                descriptor = bytes(window[-2:] + rest)
                if len(descriptor) == _DESCRIPTOR_LEN:
                    return descriptor
                break

        tail = bytes(window).hex(" ") or "vide"
        raise RuntimeError(f"descripteur scan RPLIDAR invalide (tail={tail})")

    def _stop_scan(self) -> None:
        try:
            self._send_command(_CMD_STOP)
        except Exception:  # noqa: BLE001
            pass

    def _read_scan_loop(self) -> None:
        assert self._serial is not None
        current: list[LidarPoint] = []
        last_publish = 0.0
        first_measurement_deadline = time.monotonic() + _FIRST_MEASUREMENT_TIMEOUT_S

        while not self._stop_event.is_set():
            raw = self._serial.read(5)  # type: ignore[union-attr]
            if len(raw) != 5:
                if not current and time.monotonic() >= first_measurement_deadline:
                    raise TimeoutError(
                        f"timeout lecture scan (aucune mesure, DTR={self._active_motor_dtr})"
                    )
                continue
            point, new_scan = self._parse_measurement(raw)
            if point is None:
                continue

            if new_scan and len(current) >= 20:
                self._publish(current)
                current = []
                last_publish = time.monotonic()

            current.append(point)
            if len(current) > _MAX_POINTS or time.monotonic() - last_publish > 0.4:
                self._publish(current)
                current = []
                last_publish = time.monotonic()

    def _parse_measurement(self, raw: bytes) -> tuple[LidarPoint | None, bool]:
        b0, b1, b2, b3, b4 = raw
        start = bool(b0 & 0x01)
        inverted_start = bool(b0 & 0x02)
        if start == inverted_start or not (b1 & 0x01):
            return None, False
        quality = b0 >> 2
        angle_deg = (((b2 << 7) | (b1 >> 1)) / 64.0) % 360.0
        distance_mm = ((b4 << 8) | b3) / 4.0
        if quality < self.min_quality or distance_mm <= 0 or distance_mm > self.max_distance_mm:
            return None, start
        return LidarPoint(angle_deg=angle_deg, distance_mm=distance_mm, quality=quality), start

    def _publish(self, points: list[LidarPoint]) -> None:
        if not points:
            return
        front = self._sector_min(points, 0.0, self.front_fov_deg)
        left = self._sector_min(points, 315.0, 60.0)
        right = self._sector_min(points, 45.0, 60.0)
        snap = LidarSnapshot(
            connected=True,
            port=self._resolved_port,
            points=tuple(points),
            front_distance_cm=front,
            left_distance_cm=left,
            right_distance_cm=right,
            obstacle_front=front is not None and front < self.obstacle_threshold_cm,
            updated_at=time.time(),
            error=None,
        )
        self._set_snapshot(snap)

    def _sector_min(
        self,
        points: list[LidarPoint],
        center_deg: float,
        width_deg: float,
    ) -> float | None:
        half = width_deg / 2.0
        distances = [
            p.distance_mm / 10.0
            for p in points
            if abs(_angle_delta(p.angle_deg, center_deg)) <= half
        ]
        return min(distances) if distances else None

    def _set_snapshot(self, snapshot: LidarSnapshot) -> None:
        with self._lock:
            self._latest = snapshot
