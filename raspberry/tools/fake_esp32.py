"""
Émulateur du firmware ESP32 Waveshare UGV — pour tester sans matériel.

Expose un serveur TCP qui "parle" le même protocole JSON-line que l'ESP32 réel.
Votre code client se connecte avec :

    ESP32Link(port="socket://localhost:9999")

L'émulateur :
- Parse les commandes entrantes (T=0 stop, T=1 speed, T=133 pan-tilt, T=126/130 feedback)
- Maintient un état robot (vitesses, angles, position virtuelle 2D, batterie)
- Intègre la position dans le temps avec un modèle différentiel simple
- Renvoie un JSON de feedback quand on le lui demande (T=126)
- Affiche en direct l'état dans la console, ASCII map optionnel

Usage
-----
Terminal 1 (émulateur) :
    python3 -m tools.fake_esp32
    python3 -m tools.fake_esp32 --port 9999 --viz

Terminal 2 (votre code) :
    python3 -m tests.test_control --port socket://localhost:9999
    python3 main.py                # après avoir mis ce port dans config.yaml

Ça marche sous Windows, macOS et Linux, sans driver virtuel.
"""

from __future__ import annotations

import argparse
import json
import math
import socketserver
import threading
import time
from dataclasses import dataclass, field

# --- Paramètres physiques du modèle ------------------------------------------

MAX_SPEED_M_S = 0.65  # Waveshare RaspRover max linear speed
WHEELBASE_M = 0.18  # approx. distance entre roues gauche/droite
PHYSICS_DT = 0.05  # pas d'intégration (50 ms)
BATTERY_CAPACITY_WH = 120  # 3S × 3200 mAh × 12.6 V ≈ 120 Wh
IDLE_POWER_W = 5  # conso quand à l'arrêt (ESP32 + servos statiques)
MOTOR_POWER_W = 30  # conso nominale moteurs à pleine vitesse


@dataclass
class RobotState:
    """État instantané du robot virtuel."""

    L: float = 0.0  # consigne côté gauche  [-1, 1]
    R: float = 0.0  # consigne côté droit   [-1, 1]
    pan_deg: float = 0.0
    tilt_deg: float = 0.0
    x: float = 0.0  # position en mètres
    y: float = 0.0
    heading_rad: float = 0.0  # cap (0 = +x)
    left_distance_m: float = 0.0
    right_distance_m: float = 0.0
    main_type: int = 2
    module_type: int = 2
    voltage: float = 12.6  # batterie 3S pleine
    uptime_s: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def step(self, dt: float) -> None:
        """Intègre un pas de physique différentielle + consommation batterie."""
        with self._lock:
            v_l = self.L * MAX_SPEED_M_S
            v_r = self.R * MAX_SPEED_M_S
            v = 0.5 * (v_l + v_r)
            omega = (v_r - v_l) / WHEELBASE_M
            self.left_distance_m += v_l * dt
            self.right_distance_m += v_r * dt
            self.x += v * math.cos(self.heading_rad) * dt
            self.y += v * math.sin(self.heading_rad) * dt
            self.heading_rad = (self.heading_rad + omega * dt + math.pi) % (2 * math.pi) - math.pi

            # Décharge batterie proportionnelle à l'activité moteur.
            power_w = IDLE_POWER_W + (abs(self.L) + abs(self.R)) * MOTOR_POWER_W
            # Wh consommés pendant dt (dt est en secondes).
            wh = power_w * dt / 3600.0
            pct_drop = wh / BATTERY_CAPACITY_WH
            self.voltage = max(9.5, self.voltage - 3.1 * pct_drop)
            self.uptime_s += dt

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "T": 1001,
                "x": round(self.x, 3),
                "y": round(self.y, 3),
                "yaw": round(math.degrees(self.heading_rad), 1),
                "L": round(self.L * MAX_SPEED_M_S, 4),
                "R": round(self.R * MAX_SPEED_M_S, 4),
                "odl": int(self.left_distance_m * 100),
                "odr": int(self.right_distance_m * 100),
                # Champ 'v' : centivolts comme le firmware Waveshare réel
                # Le JS officiel fait data['v']/100 → 1260 = 12.60 V
                "v": round(self.voltage * 100),
                "uptime": round(self.uptime_s, 1),
                **(
                    {"pan": round(self.pan_deg, 1), "tilt": round(self.tilt_deg, 1)}
                    if self.module_type == 2
                    else {}
                ),
            }


# --- Gestion de la connexion client ------------------------------------------


class ESP32Handler(socketserver.StreamRequestHandler):
    """Une connexion TCP = un "ESP32" pour un client."""

    def handle(self) -> None:
        server: FakeESP32Server = self.server  # type: ignore[assignment]
        state: RobotState = server.state
        addr = self.client_address
        print(f"[SIM] + client connecté {addr}")
        rx_buf = b""
        try:
            # Non bloquant pour pouvoir fermer proprement à l'arrêt.
            self.request.settimeout(0.5)
            while not server.stopping.is_set():
                try:
                    chunk = self.request.recv(1024)
                except TimeoutError:
                    continue
                if not chunk:
                    break
                rx_buf += chunk
                while b"\n" in rx_buf:
                    line, rx_buf = rx_buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    self._process_line(line, state)
        except OSError as exc:
            print(f"[SIM] ! erreur socket {addr}: {exc}")
        finally:
            print(f"[SIM] - client déconnecté {addr}")

    def _process_line(self, line: bytes, state: RobotState) -> None:
        try:
            cmd = json.loads(line.decode("ascii", errors="replace"))
        except json.JSONDecodeError:
            print(f"[SIM] ? ligne non-JSON : {line!r}")
            return

        t = cmd.get("T")
        if t == 0:
            with state._lock:
                state.L = 0.0
                state.R = 0.0
            print("[SIM] CMD T=0  EMERGENCY STOP")
        elif t == 1:
            L = float(cmd.get("L", 0.0))
            R = float(cmd.get("R", 0.0))
            with state._lock:
                state.L = max(-1.0, min(1.0, L))
                state.R = max(-1.0, min(1.0, R))
            print(f"[SIM] CMD T=1  SPEED    L={state.L:+.2f}  R={state.R:+.2f}")
        elif t == 133:
            with state._lock:
                state.pan_deg = float(cmd.get("X", state.pan_deg))
                state.tilt_deg = float(cmd.get("Y", state.tilt_deg))
            print(
                f"[SIM] CMD T=133 PANTILT  pan={state.pan_deg:+.1f}°  tilt={state.tilt_deg:+.1f}°"
            )
        elif t in (126, 130):
            snap = state.snapshot()
            data = (json.dumps(snap, separators=(",", ":")) + "\n").encode("ascii")
            self.request.sendall(data)
            print(f"[SIM] CMD T={t} FEEDBACK → sent {snap}")
        elif t == 900:
            with state._lock:
                state.main_type = int(cmd.get("main", state.main_type))
                state.module_type = int(cmd.get("module", state.module_type))
            print(f"[SIM] CMD T=900 PLATFORM main={state.main_type} module={state.module_type}")
        else:
            print(f"[SIM] ? commande inconnue T={t}: {cmd}")


class FakeESP32Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], state: RobotState) -> None:
        super().__init__(addr, ESP32Handler)
        self.state = state
        self.stopping = threading.Event()


# --- Boucles annexes (physique, affichage, ASCII map) ------------------------


def physics_loop(state: RobotState, stop: threading.Event) -> None:
    """Intègre la physique à cadence fixe tant que le serveur tourne."""
    next_t = time.monotonic()
    while not stop.is_set():
        state.step(PHYSICS_DT)
        next_t += PHYSICS_DT
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_t = time.monotonic()


def status_loop(state: RobotState, stop: threading.Event, interval: float = 2.0) -> None:
    """Affiche régulièrement la position + batterie (seulement si en mouvement)."""
    while not stop.is_set():
        if stop.wait(interval):
            break
        with state._lock:
            moving = abs(state.L) > 1e-3 or abs(state.R) > 1e-3
            snap = state.snapshot()
        if moving:
            print(
                f"[SIM] pos x={snap['x']:+.2f}m y={snap['y']:+.2f}m "
                f"yaw={snap['yaw']:+.1f}°  battery={snap['voltage']}V  "
                f"uptime={snap['uptime']:.0f}s"
            )


def viz_loop(state: RobotState, stop: threading.Event, interval: float = 0.5) -> None:
    """Mini ASCII map (30×15) du plan x/y, utile en headless."""
    W, H = 41, 21
    scale = 0.25  # 1 cellule = 25 cm
    while not stop.is_set():
        if stop.wait(interval):
            break
        with state._lock:
            snap = state.snapshot()
        cx, cy = W // 2, H // 2
        px = cx + int(round(snap["x"] / scale))
        py = cy - int(round(snap["y"] / scale))
        px = max(0, min(W - 1, px))
        py = max(0, min(H - 1, py))
        # Direction du rover → un des 8 caractères fléchés
        yaw = (snap["yaw"] + 360) % 360
        arrows = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]
        arrow = arrows[int(((yaw + 22.5) % 360) // 45)]
        rows = []
        for r in range(H):
            row = []
            for c in range(W):
                if r == py and c == px:
                    row.append(arrow)
                elif r == cy and c == cx:
                    row.append("+")
                elif r in (0, H - 1) or c in (0, W - 1):
                    row.append("·")
                else:
                    row.append(" ")
            rows.append("".join(row))
        # Efface la console (\x1b[2J\x1b[H) puis dessine.
        print("\x1b[2J\x1b[H" + "\n".join(rows))
        print(
            f"  pos ({snap['x']:+.2f}, {snap['y']:+.2f})  yaw={snap['yaw']:+.1f}°  "
            f"L={snap['L']:+.2f} R={snap['R']:+.2f}  "
            f"pan={snap['pan']:+.1f}° tilt={snap['tilt']:+.1f}°  "
            f"bat={snap['voltage']}V"
        )


# --- Entrée --------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Émulateur ESP32 Waveshare UGV")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=9999)
    p.add_argument(
        "--viz",
        action="store_true",
        help="Affiche une mini ASCII map temps-réel de la position du rover",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state = RobotState()
    stop = threading.Event()
    srv = FakeESP32Server((args.host, args.port), state)

    banner = (
        "\n"
        "═════════════════════════════════════════════════════════════\n"
        " Émulateur ESP32 Waveshare UGV  (firmware virtuel)          \n"
        "═════════════════════════════════════════════════════════════\n"
        f"  URL pyserial à utiliser côté client :\n"
        f"      socket://{args.host}:{args.port}\n\n"
        f"  Exemple :\n"
        f"      python3 -m tests.test_control --port socket://{args.host}:{args.port}\n\n"
        "  Ctrl+C pour arrêter.\n"
        "═════════════════════════════════════════════════════════════\n"
    )
    print(banner)

    threads = [
        threading.Thread(target=srv.serve_forever, name="tcp", daemon=True),
        threading.Thread(target=physics_loop, args=(state, stop), name="physics", daemon=True),
    ]
    if args.viz:
        threads.append(
            threading.Thread(target=viz_loop, args=(state, stop), name="viz", daemon=True)
        )
    else:
        threads.append(
            threading.Thread(target=status_loop, args=(state, stop), name="status", daemon=True)
        )
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SIM] Arrêt demandé, fermeture…")
    finally:
        stop.set()
        srv.stopping.set()
        srv.shutdown()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
