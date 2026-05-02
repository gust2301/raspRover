"""
Détection d'obstacles par vision (OpenCV) — complément au HC-SR04.

Algorithme :
  1. Reçoit les frames JPEG de la caméra via callback.
  2. Décode + redimensionne à 320×240.
  3. Analyse le bas du cadre (ROI : bottom 35 %) — là où le robot va aller.
  4. Détection de contours (Canny) : densité d'arêtes élevée = obstacle.
  5. Expose `obstacle` (bool) et `confidence` (0.0–1.0) thread-safe.

Dégradé si OpenCV absent (CI, dev sans caméra) : obstacle = False.
"""

from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import OpenCV — optionnel
# ---------------------------------------------------------------------------

try:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    log.warning("OpenCV absent — VisionObstacleDetector en mode simulation (obstacle=False)")


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_PROCESS_WIDTH = 320  # largeur de traitement (redimensionné)
_PROCESS_HEIGHT = 240  # hauteur de traitement
_ROI_TOP_PCT = 0.62  # on analyse les 38 % inférieurs de l'image
_ROI_SIDE_PCT = 0.10  # on exclut 10 % sur chaque côté (évite le bord du chassis)
_EDGE_LOW = 30  # seuil bas Canny
_EDGE_HIGH = 90  # seuil haut Canny
_BLUR_KERNEL = (5, 5)  # noyau de flou gaussien


# ---------------------------------------------------------------------------
# Détecteur
# ---------------------------------------------------------------------------


class VisionObstacleDetector:
    """
    Détecte les obstacles via la caméra (OpenCV).

    Parameters
    ----------
    edge_threshold : float
        Densité d'arêtes (0–1) au-delà de laquelle un obstacle est signalé.
        Par défaut 0.08 (8 % des pixels du ROI sont des arêtes).
    history : int
        Nombre de frames à agréger pour le vote majoritaire (lissage temporel).
    """

    def __init__(
        self,
        edge_threshold: float = 0.08,
        history: int = 3,
    ) -> None:
        self._threshold = edge_threshold
        self._history = history

        self._lock = threading.Lock()
        self._obstacle = False
        self._confidence = 0.0
        self._votes: list[bool] = []

        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Propriétés thread-safe
    # ------------------------------------------------------------------

    @property
    def obstacle(self) -> bool:
        with self._lock:
            return self._obstacle

    @property
    def confidence(self) -> float:
        with self._lock:
            return self._confidence

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "vision_obstacle": self._obstacle,
                "vision_confidence": round(self._confidence, 3),
                "vision_available": _CV2_AVAILABLE,
            }

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _CV2_AVAILABLE:
            log.info("VisionObstacleDetector démarré en mode dégradé (pas de cv2)")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="vision-detector")
        self._thread.start()
        log.info(
            "VisionObstacleDetector démarré (seuil=%.2f, historique=%d)",
            self._threshold,
            self._history,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("VisionObstacleDetector arrêté")

    # ------------------------------------------------------------------
    # Callback appelé par camera.py
    # ------------------------------------------------------------------

    def push_frame(self, jpeg_bytes: bytes) -> None:
        """Appelé depuis le thread caméra avec les bytes JPEG d'une frame."""
        if not _CV2_AVAILABLE:
            return
        try:
            self._queue.put_nowait(jpeg_bytes)
        except queue.Full:
            pass  # On abandonne la frame si le worker n'est pas à jour

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                jpeg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            obstacle, confidence = self._analyse(jpeg)

            # Vote majoritaire sur les N dernières frames (lissage)
            self._votes.append(obstacle)
            if len(self._votes) > self._history:
                self._votes.pop(0)
            smoothed = sum(self._votes) > len(self._votes) / 2

            with self._lock:
                self._obstacle = smoothed
                self._confidence = confidence

    # ------------------------------------------------------------------
    # Analyse d'une frame
    # ------------------------------------------------------------------

    def _analyse(self, jpeg_bytes: bytes) -> tuple[bool, float]:
        """Retourne (obstacle, densité_arêtes)."""
        try:
            arr = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
            if arr is None:
                return False, 0.0

            # Redimensionner pour la vitesse
            small = cv2.resize(arr, (_PROCESS_WIDTH, _PROCESS_HEIGHT))

            h, w = small.shape
            y_start = int(h * _ROI_TOP_PCT)
            x_start = int(w * _ROI_SIDE_PCT)
            x_end = w - x_start

            roi = small[y_start:, x_start:x_end]

            # Flou gaussien puis Canny
            blurred = cv2.GaussianBlur(roi, _BLUR_KERNEL, 0)
            edges = cv2.Canny(blurred, _EDGE_LOW, _EDGE_HIGH)

            density = float(np.count_nonzero(edges)) / max(edges.size, 1)
            return density > self._threshold, density

        except Exception as exc:  # noqa: BLE001
            log.debug("Vision analyse error: %s", exc)
            return False, 0.0
