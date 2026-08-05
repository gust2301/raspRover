"""Emission locale des commandes roues vers le noeud d'odometrie ROS 2."""

from __future__ import annotations

import json
import logging
import socket
import time

log = logging.getLogger(__name__)


class OdometryCommandPublisher:
    """Publie sans blocage les consignes gauche/droite sur un socket UDP local."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7667) -> None:
        self._address = (host, int(port))
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def publish(self, left: float, right: float) -> None:
        payload = json.dumps(
            {"left": float(left), "right": float(right), "timestamp": time.time()},
            separators=(",", ":"),
        ).encode("ascii")
        try:
            self._socket.sendto(payload, self._address)
        except OSError as exc:
            # L'odometrie ne doit jamais interrompre le controle des moteurs.
            log.debug("Publication odometrie impossible: %s", exc)

    def close(self) -> None:
        self._socket.close()
