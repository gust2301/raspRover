"""
REPL interactif pour tester le Module Contrôle sur matériel réel.

Usage (depuis la Pi 5, à la racine du dépôt) :

    python3 -m tests.test_control                       # /dev/ttyAMA0 par défaut
    python3 -m tests.test_control --port /dev/ttyUSB0   # si ESP32 connecté en USB
    python3 -m tests.test_control --dry-run             # sans matériel, juste pour voir les trames

Commandes du REPL :
    f [spd]   avance (spd optionnel, ex: f 0.3)
    b [spd]   recule
    l [spd]   rotation gauche
    r [spd]   rotation droite
    s         stop
    p <pan> <tilt>   orienter la caméra (ex: p 30 -15)
    c         recentrer la caméra
    ?         état courant
    q         quitter (stop + close)
"""

from __future__ import annotations

import argparse
import logging
import shlex
import sys
from typing import Optional

# Permet de lancer le script en autonome aussi bien qu'avec -m
if __package__ is None or __package__ == "":  # pragma: no cover
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.control import (  # noqa: E402
    ESP32Link,
    MotorController,
    PanTiltController,
)


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
        print(f"[DRY-RUN] TX → {json.dumps(payload, separators=(',', ':'))}")

    def emergency_stop(self) -> None:
        self.send({"T": 0})
        self.send({"T": 1, "L": 0.0, "R": 0.0})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test interactif du Module Contrôle")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Port série de l'ESP32")
    p.add_argument("--baudrate", type=int, default=115200)
    p.add_argument("--max-speed", type=float, default=0.4)
    p.add_argument("--dry-run", action="store_true", help="Ne pas ouvrir le port série")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


HELP = """
Commandes disponibles :
  f [speed]         avance         (défaut : vitesse par défaut)
  b [speed]         recule
  l [speed]         rotation gauche
  r [speed]         rotation droite
  s                 stop
  p <pan> <tilt>    orienter la caméra (degrés)
  c                 recentrer la caméra
  ?                 afficher l'état
  h                 cette aide
  q                 quitter
"""


def run_repl(motors: MotorController, pantilt: PanTiltController) -> None:
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
            elif cmd in ("h", "help", "?help"):
                print(HELP)
            elif cmd == "?":
                L, R = motors.last_command
                pan, tilt = pantilt.position
                print(f"  moteurs : L={L:+.2f}  R={R:+.2f}")
                print(f"  caméra  : pan={pan:+.1f}°  tilt={tilt:+.1f}°")
            elif cmd == "f":
                motors.forward(_opt_float(args, 0))
            elif cmd == "b":
                motors.backward(_opt_float(args, 0))
            elif cmd == "l":
                motors.rotate_left(_opt_float(args, 0))
            elif cmd == "r":
                motors.rotate_right(_opt_float(args, 0))
            elif cmd == "s":
                motors.stop()
            elif cmd == "c":
                pantilt.center()
            elif cmd == "p":
                if len(args) != 2:
                    print("Usage : p <pan> <tilt>  (ex : p 30 -15)")
                    continue
                pantilt.goto(pan_deg=float(args[0]), tilt_deg=float(args[1]))
            else:
                print(f"Commande inconnue : {cmd!r} (tape 'h' pour l'aide)")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERREUR] {exc}")


def _opt_float(args: list[str], idx: int) -> Optional[float]:
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
        link = DryRunLink()  # type: ignore[assignment]
    else:
        link = ESP32Link(port=args.port, baudrate=args.baudrate)
        link.open()

    motors = MotorController(link, max_speed=args.max_speed)  # type: ignore[arg-type]
    pantilt = PanTiltController(link)  # type: ignore[arg-type]

    try:
        run_repl(motors, pantilt)
    finally:
        motors.shutdown()
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
