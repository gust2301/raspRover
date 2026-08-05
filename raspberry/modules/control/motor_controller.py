"""
API haut niveau de pilotage des moteurs 4WD en direction différentielle.

Le RaspRover Waveshare utilise un contrôle différentiel (skid steering) : deux
valeurs de vitesse, une pour le côté gauche, une pour le côté droit, chacune
dans l'intervalle ``[-1.0, 1.0]``. En pratique, Waveshare recommande de rester
sous 0.5 pour préserver les motoréducteurs.

Ce module expose des verbes métier lisibles (``forward``, ``backward``,
``rotate_left``, ``rotate_right``, ``stop``, ``drive``) et délègue l'envoi au
:class:`ESP32Link`.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable

from .esp32_link import CMD_SPEED_CTRL, ESP32Link
from .exceptions import InvalidParameterError

log = logging.getLogger(__name__)


class Direction(str, enum.Enum):
    FORWARD = "forward"
    BACKWARD = "backward"
    LEFT = "left"
    RIGHT = "right"
    STOP = "stop"


class MotorController:
    """
    Contrôle haut niveau des 4 moteurs du RaspRover.

    Parameters
    ----------
    link : ESP32Link
        Liaison série ouverte vers l'ESP32.
    max_speed : float
        Vitesse maximale autorisée en valeur absolue (0.0 – 1.0).
        Les commandes sont clampées à cet intervalle.
    default_speed : float
        Vitesse utilisée si on appelle ``forward()`` sans argument.
    watchdog_s : float | None
        Si défini, le dernier ordre est automatiquement ré-émis ou stoppé si
        aucune nouvelle commande n'arrive. Utile pour le téléopéré : si le
        WebSocket de l'interface web coupe, le robot s'arrête tout seul.
    """

    def __init__(
        self,
        link: ESP32Link,
        max_speed: float = 0.5,
        default_speed: float = 0.35,
        watchdog_s: float | None = 1.0,
        command_observer: Callable[[float, float], None] | None = None,
    ) -> None:
        if not (0.0 < max_speed <= 1.0):
            raise InvalidParameterError(f"max_speed doit être dans ]0, 1], reçu {max_speed}")
        if not (0.0 <= default_speed <= max_speed):
            raise InvalidParameterError(
                f"default_speed ({default_speed}) doit être dans [0, {max_speed}]"
            )
        self._link = link
        self.max_speed = max_speed
        self.default_speed = default_speed
        self.watchdog_s = watchdog_s
        self._command_observer = command_observer

        self._last_cmd_ts = 0.0
        self._last_cmd: tuple[float, float] = (0.0, 0.0)
        self._stop_event = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        if watchdog_s:
            self._start_watchdog()

    # -- Watchdog ------------------------------------------------------------

    def _start_watchdog(self) -> None:
        def loop() -> None:
            while not self._stop_event.is_set():
                time.sleep(0.1)
                if self._last_cmd == (0.0, 0.0):
                    continue
                assert self.watchdog_s is not None
                if time.time() - self._last_cmd_ts > self.watchdog_s:
                    log.warning(
                        "Watchdog déclenché (> %.2fs sans commande) : arrêt auto",
                        self.watchdog_s,
                    )
                    self.stop()

        self._watchdog_thread = threading.Thread(target=loop, name="MotorWatchdog", daemon=True)
        self._watchdog_thread.start()

    def shutdown(self) -> None:
        """À appeler avant de quitter : stoppe le watchdog et les moteurs."""
        self._stop_event.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=1.0)
        try:
            self.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Impossible d'envoyer stop() pendant shutdown: %s", exc)

    # -- API publique --------------------------------------------------------

    def drive(self, left: float, right: float) -> None:
        """
        Pilotage brut des deux côtés.

        ``left`` et ``right`` sont dans ``[-1.0, 1.0]`` ; clampés à ``max_speed``.
        Valeurs positives = avance, négatives = recul.
        """
        left = self._clamp(left)
        right = self._clamp(right)
        self._link.send({"T": CMD_SPEED_CTRL, "L": left, "R": right})
        self._notify_observer(left, right)
        self._last_cmd = (left, right)
        self._last_cmd_ts = time.time()
        log.debug("drive(L=%.2f, R=%.2f)", left, right)

    def forward(self, speed: float | None = None) -> None:
        """Avance en ligne droite."""
        v = self.default_speed if speed is None else speed
        self.drive(v, v)

    def backward(self, speed: float | None = None) -> None:
        """Recule en ligne droite."""
        v = self.default_speed if speed is None else speed
        self.drive(-v, -v)

    def rotate_left(self, speed: float | None = None) -> None:
        """Rotation sur place vers la gauche (R positif, L négatif)."""
        v = self.default_speed if speed is None else speed
        self.drive(-v, v)

    def rotate_right(self, speed: float | None = None) -> None:
        """Rotation sur place vers la droite."""
        v = self.default_speed if speed is None else speed
        self.drive(v, -v)

    def arc(self, speed: float, steering: float) -> None:
        """
        Déplacement avec courbure.

        speed    : vitesse linéaire [-1, 1]
        steering : angle de direction [-1, 1] (négatif = gauche, positif = droite)
        """
        left = self._clamp(speed + steering * abs(speed))
        right = self._clamp(speed - steering * abs(speed))
        self.drive(left, right)

    def stop(self) -> None:
        """Arrête immédiatement les 4 moteurs."""
        self._link.send({"T": CMD_SPEED_CTRL, "L": 0.0, "R": 0.0})
        self._notify_observer(0.0, 0.0)
        self._last_cmd = (0.0, 0.0)
        self._last_cmd_ts = time.time()
        log.debug("stop()")

    def from_direction(self, direction: Direction, speed: float | None = None) -> None:
        """Facilité : dispatch selon un enum Direction (utile pour l'API Web)."""
        mapping = {
            Direction.FORWARD: self.forward,
            Direction.BACKWARD: self.backward,
            Direction.LEFT: self.rotate_left,
            Direction.RIGHT: self.rotate_right,
            Direction.STOP: lambda _=None: self.stop(),
        }
        mapping[direction](speed) if direction is not Direction.STOP else self.stop()

    # -- Utilitaires ---------------------------------------------------------

    def _clamp(self, v: float) -> float:
        if v != v:  # NaN
            raise InvalidParameterError("Vitesse NaN")
        return max(-self.max_speed, min(self.max_speed, float(v)))

    def _notify_observer(self, left: float, right: float) -> None:
        if self._command_observer is None:
            return
        try:
            self._command_observer(left, right)
        except Exception as exc:  # noqa: BLE001
            log.warning("Observateur de commande moteur indisponible: %s", exc)

    @property
    def last_command(self) -> tuple[float, float]:
        """Dernière commande (L, R) envoyée."""
        return self._last_cmd
