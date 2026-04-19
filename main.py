"""
Point d'entrée du RaspRover (stub).

Pour l'instant, ce fichier se contente de charger la configuration et d'ouvrir
la liaison ESP32 en mode interactif. Les autres modules (vidéo, perception,
surveillance, API) seront montés ici au fur et à mesure du développement.
"""

from __future__ import annotations

import logging
import pathlib
import sys

import yaml

from modules.control import ESP32Link, MotorController, PanTiltController


CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"


def load_config(path: pathlib.Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"].upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctrl_cfg = cfg["control"]

    with ESP32Link(
        port=ctrl_cfg["serial_port"],
        baudrate=ctrl_cfg["baudrate"],
        timeout_s=ctrl_cfg["timeout_s"],
    ) as link:
        motors = MotorController(
            link,
            max_speed=ctrl_cfg["motor_max_speed"],
            default_speed=ctrl_cfg["motor_default_speed"],
        )
        pantilt = PanTiltController(
            link,
            pan_range=(
                ctrl_cfg["pantilt"]["pan_min_deg"],
                ctrl_cfg["pantilt"]["pan_max_deg"],
            ),
            tilt_range=(
                ctrl_cfg["pantilt"]["tilt_min_deg"],
                ctrl_cfg["pantilt"]["tilt_max_deg"],
            ),
            speed=ctrl_cfg["pantilt"]["servo_speed"],
            accel=ctrl_cfg["pantilt"]["servo_accel"],
        )

        logging.info("RaspRover prêt. (Ajouter les modules vidéo/API ici.)")
        # Démo : on centre la caméra puis on fait un petit mouvement de test.
        pantilt.center()
        motors.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
