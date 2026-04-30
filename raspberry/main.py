"""Point d'entree du RaspRover pour le smoke test de la phase 1."""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import yaml

from modules.control import ESP32Link, MotorController, PanTiltController

CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"
log = logging.getLogger(__name__)


def load_config(path: pathlib.Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test du module controle RaspRover")
    parser.add_argument("--config", type=pathlib.Path, default=CONFIG_PATH)
    parser.add_argument("--port", help="Override du port serie ou socket://")
    parser.add_argument("--baudrate", type=int, help="Override du baudrate")
    parser.add_argument("--timeout", type=float, help="Override du timeout en secondes")
    parser.add_argument("--skip-feedback", action="store_true", help="Ne pas demander le feedback")
    parser.add_argument("--skip-center", action="store_true", help="Ne pas recentrer la camera")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def configure_logging(cfg: dict, verbose: bool = False) -> None:
    logging_cfg = cfg.get("logging", {})
    level_name = str(logging_cfg.get("level", "INFO")).upper()
    level = logging.DEBUG if verbose else getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = logging_cfg.get("file")
    if log_file:
        log_path = pathlib.Path(log_file)
        if not log_path.is_absolute():
            log_path = pathlib.Path(__file__).parent / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    configure_logging(cfg, verbose=args.verbose)

    ctrl_cfg = cfg["control"]
    port = args.port or ctrl_cfg["serial_port"]
    baudrate = args.baudrate or ctrl_cfg["baudrate"]
    timeout_s = args.timeout or ctrl_cfg["timeout_s"]

    with ESP32Link(port=port, baudrate=baudrate, timeout_s=timeout_s) as link:
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

        log.info("Liaison ESP32 ouverte sur %s @ %s", port, baudrate)
        if not args.skip_center:
            pantilt.center()
            log.info("Pan-Tilt recentre")
        motors.stop()
        log.info("Moteurs verifies a l'arret")

        if not args.skip_feedback:
            try:
                feedback = link.request_feedback()
            except Exception as exc:  # noqa: BLE001
                log.warning("Feedback indisponible: %s", exc)
            else:
                log.info("Feedback ESP32: %s", feedback)

        log.info("Smoke test phase 1 termine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
