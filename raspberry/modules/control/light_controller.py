"""Controle simple de l'eclairage pilote par l'ESP32."""

from __future__ import annotations

import logging

from .esp32_link import ESP32Link

log = logging.getLogger(__name__)

CMD_IO_PWM = 132


class LightController:
    """Pilote les sorties MOSFET IO4/IO5 du firmware Waveshare."""

    def __init__(self, link: ESP32Link, io4_default: int = 0, io5_default: int = 0) -> None:
        self._link = link
        self._io4 = self._clamp(io4_default)
        self._io5 = self._clamp(io5_default)

    def set_output(self, *, io4: int | None = None, io5: int | None = None) -> None:
        if io4 is not None:
            self._io4 = self._clamp(io4)
        if io5 is not None:
            self._io5 = self._clamp(io5)
        self._link.send({"T": CMD_IO_PWM, "IO4": self._io4, "IO5": self._io5})
        log.debug("light.set_output(IO4=%d, IO5=%d)", self._io4, self._io5)

    def set_camera_light(self, enabled: bool, level: int = 255) -> None:
        self.set_output(io5=level if enabled else 0)

    @property
    def state(self) -> dict[str, int | bool]:
        return {
            "io4": self._io4,
            "io5": self._io5,
            "camera_light": self._io5 > 0,
        }

    @staticmethod
    def _clamp(value: int) -> int:
        return max(0, min(255, int(value)))
