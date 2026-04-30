"""Daemon systemd minimal pour maintenir la liaison controle ouverte."""

from __future__ import annotations

import argparse
import logging
import pathlib
import signal
import threading

import yaml

from modules.control import ESP32Link, MotorController, PanTiltController

CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"
log = logging.getLogger(__name__)


def load_config(path: pathlib.Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    cfg = load_config()
    ctrl_cfg = cfg.get("control", {})
    parser = argparse.ArgumentParser(description="Service de controle persistant RaspRover")
    parser.add_argument("--config", type=pathlib.Path, default=CONFIG_PATH)
    parser.add_argument("--port", default=ctrl_cfg.get("serial_port", "/dev/ttyAMA0"))
    parser.add_argument("--baudrate", type=int, default=ctrl_cfg.get("baudrate", 115200))
    parser.add_argument("--timeout", type=float, default=ctrl_cfg.get("timeout_s", 1.0))
    parser.add_argument("--feedback-interval", type=float, default=5.0)
    parser.add_argument("--skip-feedback", action="store_true")
    parser.add_argument("--skip-center", action="store_true")
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


def install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle_signal(signum: int, _frame) -> None:
        log.info("Signal %s recu, extinction du service", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    configure_logging(cfg, verbose=args.verbose)

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    ctrl_cfg = cfg.get("control", {})
    port = args.port or ctrl_cfg.get("serial_port", "/dev/ttyAMA0")
    baudrate = args.baudrate or ctrl_cfg.get("baudrate", 115200)
    timeout_s = args.timeout or ctrl_cfg.get("timeout_s", 1.0)

    with ESP32Link(port=port, baudrate=baudrate, timeout_s=timeout_s) as link:
        motors = MotorController(
            link,
            max_speed=ctrl_cfg.get("motor_max_speed", 0.5),
            default_speed=ctrl_cfg.get("motor_default_speed", 0.35),
        )
        pantilt = PanTiltController(
            link,
            pan_range=(
                ctrl_cfg.get("pantilt", {}).get("pan_min_deg", -90),
                ctrl_cfg.get("pantilt", {}).get("pan_max_deg", 90),
            ),
            tilt_range=(
                ctrl_cfg.get("pantilt", {}).get("tilt_min_deg", -45),
                ctrl_cfg.get("pantilt", {}).get("tilt_max_deg", 60),
            ),
            speed=ctrl_cfg.get("pantilt", {}).get("servo_speed", 600),
            accel=ctrl_cfg.get("pantilt", {}).get("servo_accel", 50),
        )

        try:
            log.info("Liaison ESP32 ouverte sur %s @ %s", port, baudrate)
            motors.stop()
            log.info("Moteurs verifies a l'arret")

            if not args.skip_center:
                pantilt.center()
                log.info("Pan-Tilt recentre")

            while not stop_event.is_set():
                if not args.skip_feedback:
                    try:
                        feedback = link.request_feedback(timeout_s=timeout_s, command_type=126)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Feedback indisponible: %s", exc)
                    else:
                        log.debug("Feedback ESP32: %s", feedback)
                stop_event.wait(max(0.1, args.feedback_interval))
        finally:
            try:
                motors.shutdown()
            finally:
                log.info("Service de controle arrete proprement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
