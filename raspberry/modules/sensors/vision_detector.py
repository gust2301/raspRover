"""
Détection d'obstacles par vision (OpenCV) — complément au HC-SR04.

Algorithme dual :
  1. Reçoit les frames JPEG de la caméra via callback.
  2. Décode + redimensionne à 320×240.
  3. Analyse le bas du cadre (ROI : bottom 40 %) — là où le robot va aller.
  4. Méthode A — Canny : densité d'arêtes élevée = obstacle texturé
     (chaises, câbles, boîtes, personnes…).
  5. Méthode B — Surface uniforme : ROI à faible écart-type = obstacle lisse
     (murs blancs, portes, meubles…) que Canny rate complètement.
  6. Expose `obstacle` (bool), `confidence` (0.0–1.0) et `method` thread-safe.

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
_ROI_TOP_PCT = 0.60  # on analyse les 40 % inférieurs de l'image
_ROI_SIDE_PCT = 0.05  # on exclut 5 % sur chaque côté seulement (élargi vs 10 %)
_EDGE_LOW = 30  # seuil bas Canny
_EDGE_HIGH = 90  # seuil haut Canny
_BLUR_KERNEL = (5, 5)  # noyau de flou gaussien

# Méthode B : surface uniforme (mur blanc/lisse)
# Si l'écart-type du ROI est < _UNIFORM_STD_MAX → surface lisse = obstacle potentiel
# On split le ROI en 3 bandes horizontales et on analyse chacune séparément
# pour éviter les faux positifs (sol qui peut être partiellement uniforme).
_UNIFORM_STD_MAX = 28.0  # écart-type max pour considérer une surface uniforme
_UNIFORM_BANDS = 3  # nombre de bandes horizontales analysées
_UNIFORM_BAND_THRESH = 2  # nombre de bandes uniformes pour déclencher obstacle
# Luminosité minimale pour le critère uniforme (évite de confondre mur blanc et sol sombre)
_UNIFORM_MEAN_MIN = 130  # mean >= 130 → surface suffisamment claire


# ---------------------------------------------------------------------------
# Détecteur
# ---------------------------------------------------------------------------


class VisionObstacleDetector:
    """
    Détecte les obstacles via la caméra (OpenCV).

    Combine deux méthodes complémentaires :
    - Canny (arêtes) : obstacles texturés — chaises, câbles, boîtes, personnes
    - Écart-type (uniformité) : obstacles lisses — murs blancs, meubles, portes

    Parameters
    ----------
    edge_threshold : float
        Densité d'arêtes (0–1) au-delà de laquelle un obstacle est signalé.
        Par défaut 0.08 (8 % des pixels du ROI sont des arêtes).
    history : int
        Nombre de frames à agréger pour le vote majoritaire (lissage temporel).
    uniform_std_max : float
        Écart-type max (0-255) pour qu'une bande soit considérée uniforme.
        Réduire pour éviter les faux positifs sur sol texturé.
    """

    def __init__(
        self,
        edge_threshold: float = 0.08,
        history: int = 3,
        uniform_std_max: float = _UNIFORM_STD_MAX,
    ) -> None:
        self._threshold = edge_threshold
        self._history = history
        self._uniform_std_max = uniform_std_max

        self._lock = threading.Lock()
        self._obstacle = False
        self._confidence = 0.0
        self._method = "none"  # "canny" | "uniform" | "none"
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
                "vision_method": self._method,
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
            "VisionObstacleDetector démarré (seuil=%.2f, historique=%d, std_max=%.1f)",
            self._threshold,
            self._history,
            self._uniform_std_max,
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

            obstacle, confidence, method = self._analyse(jpeg)

            # Vote majoritaire sur les N dernières frames (lissage)
            self._votes.append(obstacle)
            if len(self._votes) > self._history:
                self._votes.pop(0)
            smoothed = sum(self._votes) > len(self._votes) / 2

            with self._lock:
                self._obstacle = smoothed
                self._confidence = confidence
                self._method = method if smoothed else "none"

    # ------------------------------------------------------------------
    # Analyse d'une frame — méthode principale
    # ------------------------------------------------------------------

    def _analyse(self, jpeg_bytes: bytes) -> tuple[bool, float, str]:
        """
        Retourne (obstacle, confiance, méthode).

        Deux méthodes complémentaires :
        A) Canny  — détecte les obstacles texturés (arêtes)
        B) Uniforme — détecte les surfaces lisses (murs/meubles sans texture)
        """
        try:
            arr = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
            if arr is None:
                return False, 0.0, "none"

            # Redimensionner pour la vitesse
            small = cv2.resize(arr, (_PROCESS_WIDTH, _PROCESS_HEIGHT))

            h, w = small.shape
            y_start = int(h * _ROI_TOP_PCT)
            x_start = int(w * _ROI_SIDE_PCT)
            x_end = w - x_start

            roi = small[y_start:, x_start:x_end]

            # ----------------------------------------------------------
            # Méthode A : Canny (obstacles texturés)
            # ----------------------------------------------------------
            blurred = cv2.GaussianBlur(roi, _BLUR_KERNEL, 0)
            edges = cv2.Canny(blurred, _EDGE_LOW, _EDGE_HIGH)
            density = float(np.count_nonzero(edges)) / max(edges.size, 1)

            if density > self._threshold:
                return True, density, "canny"

            # ----------------------------------------------------------
            # Méthode B : surface uniforme (murs lisses, meubles)
            # Divise le ROI en bandes horizontales et compte les bandes
            # ayant un faible écart-type (surface homogène).
            # Évite les faux positifs sur un sol partiellement uniforme.
            # ----------------------------------------------------------
            roi_h, roi_w = roi.shape
            band_h = max(1, roi_h // _UNIFORM_BANDS)
            uniform_count = 0

            for i in range(_UNIFORM_BANDS):
                y0 = i * band_h
                y1 = y0 + band_h if i < _UNIFORM_BANDS - 1 else roi_h
                band = roi[y0:y1, :]
                std = float(np.std(band))
                mean = float(np.mean(band))
                # Surface uniforme ET suffisamment claire (évite sol sombre)
                if std < self._uniform_std_max and mean >= _UNIFORM_MEAN_MIN:
                    uniform_count += 1

            if uniform_count >= _UNIFORM_BAND_THRESH:
                # Confiance proportionnelle : plus de bandes uniformes = plus sûr
                confidence = uniform_count / _UNIFORM_BANDS
                log.debug(
                    "Vision [uniform] obstacle=True bands=%d/%d",
                    uniform_count,
                    _UNIFORM_BANDS,
                )
                return True, confidence, "uniform"

            log.debug(
                "Vision clear — canny=%.3f uniform_bands=%d/%d",
                density,
                uniform_count,
                _UNIFORM_BANDS,
            )
            return False, density, "none"

        except Exception as exc:  # noqa: BLE001
            log.debug("Vision analyse error: %s", exc)
            return False, 0.0, "none"
