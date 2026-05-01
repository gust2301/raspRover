"""
Mixage différentiel avec modes de pilotage.

Le DriveMixer traduit des entrées joystick (x, y) en commandes moteur (L, R).

Modes :
  driver  — perspective conducteur : y>0 avance, x>0 tourne à droite
  mirror  — face au robot : y>0 recule (robot s'éloigne), x>0 tourne à gauche
             Concrètement : inversion de x ET y avant le mixage.

Mixage différentiel :
  L = forward + turn
  R = forward - turn
  (clampés à [-max_speed, +max_speed])
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class ControlMode(str, enum.Enum):
    DRIVER = "driver"
    MIRROR = "mirror"


@dataclass
class DriveConfig:
    control_mode: ControlMode = ControlMode.DRIVER
    invert_x: bool = False
    invert_y: bool = False
    invert_left_motor: bool = False
    invert_right_motor: bool = False
    max_speed: float = 0.5

    @classmethod
    def from_dict(cls, cfg: dict) -> "DriveConfig":
        return cls(
            control_mode=ControlMode(cfg.get("control_mode", "driver")),
            invert_x=bool(cfg.get("invert_x", False)),
            invert_y=bool(cfg.get("invert_y", False)),
            invert_left_motor=bool(cfg.get("invert_left_motor", False)),
            invert_right_motor=bool(cfg.get("invert_right_motor", False)),
            max_speed=float(cfg.get("max_speed", 0.5)),
        )


class DriveMixer:
    """
    Convertit (x, y) joystick → (L, R) moteurs selon le mode de pilotage.

    Parameters
    ----------
    config : DriveConfig
        Configuration du mixeur.
    """

    def __init__(self, config: DriveConfig | None = None) -> None:
        self.config = config or DriveConfig()

    def mix(self, x: float, y: float) -> tuple[float, float]:
        """
        Calcule (left, right) depuis les entrées joystick normalisées.

        x : axe latéral  [-1, 1] — positif = droite depuis la perspective du mode
        y : axe longitud. [-1, 1] — positif = avancer depuis la perspective du mode

        Retourne (left, right) dans [-max_speed, +max_speed].
        """
        cfg = self.config

        if cfg.control_mode == ControlMode.MIRROR:
            x, y = -x, -y

        if cfg.invert_x:
            x = -x
        if cfg.invert_y:
            y = -y

        left = self._clamp(y + x, cfg.max_speed)
        right = self._clamp(y - x, cfg.max_speed)

        if cfg.invert_left_motor:
            left = -left
        if cfg.invert_right_motor:
            right = -right

        log.debug("mix(x=%.2f, y=%.2f) → L=%.2f R=%.2f [%s]", x, y, left, right, cfg.control_mode)
        return left, right

    @staticmethod
    def _clamp(v: float, limit: float) -> float:
        return max(-limit, min(limit, v))
