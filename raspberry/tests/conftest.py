"""
Fixtures pytest partagees.

La fixture `emulator` demarre un `FakeESP32Server` sur un port libre choisi par
l'OS et l'arrete proprement apres le test. Les tests peuvent ensuite se
connecter au serveur virtuel avec :

    ESP32Link(port=emulator["url"])
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest

from tools.fake_esp32 import FakeESP32Server, RobotState, physics_loop


@pytest.fixture
def emulator() -> Iterator[dict]:
    """Demarre fake_esp32 sur un port libre, fournit son URL pyserial."""
    state = RobotState()
    # Port 0 -> l'OS en choisit un de libre. Indispensable pour que plusieurs
    # tests puissent tourner en parallele ou en sequence sans conflit.
    srv = FakeESP32Server(("127.0.0.1", 0), state)
    port = srv.server_address[1]
    stop_physics = threading.Event()

    tcp_thread = threading.Thread(target=srv.serve_forever, name="test-emu-tcp", daemon=True)
    phys_thread = threading.Thread(
        target=physics_loop, args=(state, stop_physics), name="test-emu-phys", daemon=True
    )
    tcp_thread.start()
    phys_thread.start()

    # Petit delai pour s'assurer que le socket ecoute.
    time.sleep(0.05)

    try:
        yield {
            "url": f"socket://127.0.0.1:{port}",
            "host": "127.0.0.1",
            "port": port,
            "state": state,
        }
    finally:
        stop_physics.set()
        srv.stopping.set()
        srv.shutdown()
        srv.server_close()
