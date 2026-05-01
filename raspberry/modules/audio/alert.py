"""
Lecteur d'alertes audio — génère un bip d'alarme sans dépendances externes.

Utilise uniquement la bibliothèque standard Python + ALSA (aplay).
La génération de la tonalité est faite en mémoire avec `wave` et `struct`.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import subprocess
import threading
import wave

log = logging.getLogger(__name__)

_SAMPLE_RATE = 44100


def _build_alert_wav(
    freq_lo: float = 880.0,
    freq_hi: float = 1320.0,
    duration_s: float = 3.0,
    beeps: int = 3,
    volume: float = 0.85,
) -> bytes:
    """Génère un WAV mono en mémoire : alternance freq_lo / freq_hi."""
    n_total = int(_SAMPLE_RATE * duration_s)
    beep_len = n_total // (beeps * 2)
    samples = bytearray()

    for i in range(n_total):
        beep_phase = i // beep_len
        freq = freq_hi if beep_phase % 2 == 0 else freq_lo
        t = i / _SAMPLE_RATE
        val = int(volume * 32767 * math.sin(2 * math.pi * freq * t))
        val = max(-32768, min(32767, val))
        samples += struct.pack("<h", val)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(bytes(samples))
    return buf.getvalue()


_ALERT_WAV: bytes = _build_alert_wav()


class AlertPlayer:
    """Joue une alarme sonore de façon non-bloquante via aplay (ALSA)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def play(self) -> None:
        """Déclenche l'alerte. Si une alerte est déjà en cours, on l'interrompt."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
            try:
                self._proc = subprocess.Popen(
                    ["aplay", "-q", "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._proc.stdin.write(_ALERT_WAV)  # type: ignore[union-attr]
                self._proc.stdin.close()  # type: ignore[union-attr]
            except FileNotFoundError:
                log.warning("aplay introuvable — audio non disponible sur ce système")
            except Exception as exc:  # noqa: BLE001
                log.error("Erreur lecture audio : %s", exc)

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def close(self) -> None:
        self.stop()
