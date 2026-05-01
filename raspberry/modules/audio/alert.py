"""
Lecteur d'alertes audio — génère un bip d'alarme sans dépendances externes.

Utilise uniquement la bibliothèque standard Python + ALSA (aplay) ou PulseAudio (paplay).
La génération de la tonalité est faite en mémoire avec `wave` et `struct`.

Détection automatique du device USB : si aucun device n'est configuré, le module
cherche la première carte ALSA de type "USB" et l'utilise (évite les sorties HDMI).
"""

from __future__ import annotations

import io
import logging
import math
import os
import re
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
    for cmd in ("aplay", "paplay", "ffplay"):
        if shutil.which(cmd):
            log.info("Lecteur audio détecté : %s", cmd)
            return cmd
    return None


def _auto_detect_usb_device() -> str | None:
    """
    Détecte automatiquement la première carte ALSA USB (évite HDMI).
    Lit /proc/asound/cards et retourne "plughw:<n>,0" pour la première
    carte dont le nom contient "USB" ou "usb".
    Retourne None si aucune carte USB trouvée.
    """
    cards_path = "/proc/asound/cards"
    if not os.path.exists(cards_path):
        return None
    try:
        content = open(cards_path).read()
        # Format: " 3 [Device         ]: USB_PnP_Audio - USB PnP Audio Device"
        for line in content.splitlines():
            m = re.match(r"^\s*(\d+)\s+\[", line)
            if m and "usb" in line.lower():
                card_num = m.group(1)
                device = f"plughw:{card_num},0"
                log.info("Carte USB détectée automatiquement : card %s → %s", card_num, device)
                return device
    except OSError:
        pass
    return None


_PLAYER: str | None = _detect_player()
# Device auto-détecté au démarrage (overridable par config.yaml)
_AUTO_USB_DEVICE: str | None = _auto_detect_usb_device()


def _play_wav(wav_bytes: bytes, device: str | None = None) -> tuple[bool, str]:
    """
    Joue un WAV en mémoire. Retourne (succès, message_erreur).
    Écrit dans un fichier temporaire pour maximiser la compatibilité.
    device : device ALSA (ex: "plughw:3,0") ou None → utilise _AUTO_USB_DEVICE.
    """
    if _PLAYER is None:
        return False, "Aucun lecteur audio trouvé (aplay / paplay / ffplay)"

    # Si pas de device explicite, on prend l'USB auto-détecté
    resolved_device = device or _AUTO_USB_DEVICE

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name

    try:
        if _PLAYER == "aplay":
            cmd = ["aplay", "-q"]
            if resolved_device:
                cmd += ["-D", resolved_device]
            cmd.append(tmp_path)
        elif _PLAYER == "paplay":
            cmd = ["paplay", tmp_path]
        elif _PLAYER == "ffplay":
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path]
        else:
            cmd = [_PLAYER, tmp_path]

        result = subprocess.run(cmd, timeout=10, capture_output=True)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            return False, f"{_PLAYER} ({resolved_device or 'default'}) a échoué : {err}"
        return True, ""
    except FileNotFoundError:
        return False, f"Commande {_PLAYER!r} introuvable"
    except subprocess.TimeoutExpired:
        return False, "Timeout lors de la lecture audio"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
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
        # device explicite depuis config.yaml (prioritaire sur auto-détection)
        self.device = device

    def play(self) -> None:
        """Déclenche l'alerte dans un thread séparé."""
        with self._lock:
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
                    resolved = device or _AUTO_USB_DEVICE or "default"
                    log.info("Alerte audio jouée avec succès (device=%s)", resolved)

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

    @property
    def resolved_device(self) -> str:
        return self.device or _AUTO_USB_DEVICE or "default (HDMI)"
