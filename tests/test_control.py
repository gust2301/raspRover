"""
REPL interactif pour tester le module controle sur materiel reel.

Usage:
    python3 -m tests.test_control
    python3 -m tests.test_control --port /dev/ttyUSB0
    python3 -m tests.test_control --dry-run
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import shlex
import sys

import yaml

# Permet de lancer le script en autonome aussi bien qu'avec -m
if __package__ is None or __package__ == "":  # pragma: no cover
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.control import (  # noqa: E402
    ESP32Link,
    ESP32TimeoutError,
    MotorController,
    PanTiltController,
)

CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / "config.yaml"


class DryRunLink:
    """Faux ESP32Link qui imprime les trames au lieu de les envoyer."""

    def __init__(self) -> None:
        self.is_open = True

    def open(self) -> None:  # pragma: no cover
        print("[DRY-RUN] open()")

    def close(self) -> None:
        print("[DRY-RUN] close()")

    def send(self, payload: dict) -> None:
        import json

        print(f"[DRY-RUN] TX -> {json.dumps(payload, separators=(',', ':'))}")

    def emergency_stop(self) -> None:
        self.send({"T": 0})
        self.send({"T": 1, "L": 0.0, "R": 0.0})

    def request_feedback(self, timeout_s: float | None = None) -> dict:
        return {"T": 1001, "dry_run": True, "timeout_s": timeout_s}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_config(path: pathlib.Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    cfg = load_config()
    ctrl_cfg = cfg.get("control", {})
    parser = argparse.ArgumentParser(description="Test interactif du module controle")
    parser.add_argument("--port", default=ctrl_cfg.get("serial_port", "/dev/ttyAMA0"))
    parser.add_argument("--baudrate", type=int, default=ctrl_cfg.get("baudrate", 115200))
    parser.add_argument("--max-speed", type=float, default=ctrl_cfg.get("motor_max_speed", 0.4))
    parser.add_argument("--timeout", type=float, default=ctrl_cfg.get("timeout_s", 1.0))
    parser.add_argument("--dry-run", action="store_true", help="Ne pas ouvrir le port serie")
    parser.add_argument(
        "--skip-feedback",
        action="store_true",
        help="Ne pas faire de ping feedback au demarrage",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


HELP = """
Commandes disponibles :
  f [speed]         avance
  b [speed]         recule
  l [speed]         rotation gauche
  r [speed]         rotation droite
  s                 stop
  p <pan> <tilt>    orienter la camera (degres)
  c                 recentrer la camera
  fb                demander le feedback ESP32
  ?                 afficher l'etat local
  h                 cette aide
  q                 quitter
"""


def run_repl(
    link: ESP32Link | DryRunLink, motors: MotorController, pantilt: PanTiltController
) -> None:
    print(HELP)
    while True:
        try:
            raw = input("rover> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"Erreur parsing : {exc}")
            continue
        cmd, *args = parts

        try:
            if cmd in ("q", "quit", "exit"):
                break
            if cmd in ("h", "help", "?help"):
                print(HELP)
                continue
            if cmd == "?":
                left, right = motors.last_command
                pan, tilt = pantilt.position
                print(f"  moteurs : L={left:+.2f}  R={right:+.2f}")
                print(f"  camera  : pan={pan:+.1f}deg  tilt={tilt:+.1f}deg")
                continue
            if cmd == "f":
                motors.forward(_opt_float(args, 0))
                continue
            if cmd == "b":
                motors.backward(_opt_float(args, 0))
                continue
            if cmd == "l":
                motors.rotate_left(_opt_float(args, 0))
                continue
            if cmd == "r":
                motors.rotate_right(_opt_float(args, 0))
                continue
            if cmd == "s":
                motors.stop()
                continue
            if cmd == "c":
                pantilt.center()
                continue
            if cmd == "fb":
                try:
                    feedback = link.request_feedback(timeout_s=1.5)
                except ESP32TimeoutError as exc:
                    print(f"Feedback timeout : {exc}")
                else:
                    print(f"  feedback: {feedback}")
                continue
            if cmd == "p":
                if len(args) != 2:
                    print("Usage : p <pan> <tilt>  (ex : p 30 -15)")
                    continue
                pantilt.goto(pan_deg=float(args[0]), tilt_deg=float(args[1]))
                continue
            print(f"Commande inconnue : {cmd!r} (tape 'h' pour l'aide)")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERREUR] {exc}")


def _opt_float(args: list[str], idx: int) -> float | None:
    try:
        return float(args[idx])
    except (IndexError, ValueError):
        return None


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.dry_run:
        link = DryRunLink()
    else:
        link = ESP32Link(port=args.port, baudrate=args.baudrate, timeout_s=args.timeout)
        link.open()

    motors = MotorController(link, max_speed=args.max_speed)  # type: ignore[arg-type]
    pantilt = PanTiltController(link)  # type: ignore[arg-type]

    try:
        print(f"Liaison ouverte sur {args.port} @ {args.baudrate}")
        print("Commande conseillee au demarrage: 'fb' puis 'c'")
        if not args.skip_feedback:
            try:
                feedback = link.request_feedback(timeout_s=args.timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] Feedback indisponible au demarrage: {exc}")
            else:
                print(f"[OK] Feedback initial: {feedback}")
        run_repl(link, motors, pantilt)
    finally:
        motors.shutdown()
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
