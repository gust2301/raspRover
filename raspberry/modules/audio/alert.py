"""
Lecteur d'alertes audio — génère un bip d'alarme sans dépendances externes.

Utilise uniquement la bibliothèque standard Python + ALSA (aplay) ou PulseAudio (paplay).
La génération de la tonalité est faite en mémoire avec `wave` et `struct`.
"""

from __future__ import annotations

import io
import logging
import math
import shutil
import struct
import subprocess
import tempfile
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


def _detect_player() -> str | None:
    """Retourne la première commande audio disponible sur le système."""
    for cmd in ("aplay", "paplay", "ffplay", "aplaymidi"):
        if shutil.which(cmd):
            log.info("Lecteur audio détecté : %s", cmd)
            return cmd
    return None


_PLAYER: str | None = _detect_player()


def _play_wav(wav_bytes: bytes, device: str | None = None) -> tuple[bool, str]:
    """
    Joue un WAV en mémoire. Retourne (succès, message_erreur).
    Écrit dans un fichier temporaire pour maximiser la compatibilité.
    device : device ALSA (ex: "plughw:1,0", "default") ou None pour la valeur par défaut.
    """
    if _PLAYER is None:
        return False, "Aucun lecteur audio trouvé (aplay / paplay / ffplay)"

    # On écrit dans un fichier tmp car paplay/ffplay ne lisent pas stdin facilement
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name

    try:
        if _PLAYER == "aplay":
            cmd = ["aplay", "-q"]
            if device:
                cmd += ["-D", device]
            cmd.append(tmp_path)
        elif _PLAYER == "paplay":
            cmd = ["paplay", tmp_path]
        elif _PLAYER == "ffplay":
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path]
        else:
            cmd = [_PLAYER, tmp_path]

        result = subprocess.run(
            cmd,
            timeout=10,
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            return False, f"{_PLAYER} a échoué (code {result.returncode}) : {err}"
        return True, ""
    except FileNotFoundError:
        return False, f"Commande {_PLAYER!r} introuvable"
    except subprocess.TimeoutExpired:
        return False, "Timeout lors de la lecture audio"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        import os

        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class AlertPlayer:
    """Joue une alarme sonore de façon non-bloquante."""

    def __init__(self, device: str | None = None) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.last_error: str | None = None
        self.device = device  # device ALSA, ex: "plughw:1,0" ou None pour défaut

    def play(self) -> None:
        """Déclenche l'alerte dans un thread séparé."""
        with self._lock:
            # Annule une lecture en cours
            if self._thread and self._thread.is_alive():
                self._stop_event.set()
                self._thread.join(timeout=1.0)

            self._stop_event.clear()
            self.last_error = None
            device = self.device

            def _run() -> None:
                ok, err = _play_wav(_ALERT_WAV, device=device)
                if not ok:
                    self.last_error = err
                    log.error("Alerte audio échouée : %s", err)
                else:
                    log.info("Alerte audio jouée avec succès (device=%s)", device or "default")

            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        self.stop()

    @property
    def player_available(self) -> bool:
        return _PLAYER is not None

    @property
    def player_name(self) -> str | None:
        return _PLAYER
