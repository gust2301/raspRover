"""
Détection d'obstacles par vision (OpenCV) — 3 zones : gauche / centre / droite.

Algorithme par zone :
  A) Canny         : obstacles texturés (câbles, chaises, boîtes…)
  B) Surface lisse : murs blancs/portes/meubles (faible écart-type)

Chaque zone (gauche/centre/droite) est analysée indépendamment.
Le robot sait ainsi de quel côté esquiver.

Dégradé si OpenCV absent : obstacle = False partout.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

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
    log.warning("OpenCV absent — VisionObstacleDetector désactivé (obstacle=False)")


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_PROCESS_WIDTH = 320  # largeur de traitement
_PROCESS_HEIGHT = 240  # hauteur de traitement
_ROI_TOP_PCT = 0.58  # on analyse les 42 % inférieurs (un peu plus de contexte)
_ROI_SIDE_PCT = 0.04  # exclusion latérale minimale (évite le châssis)

_EDGE_LOW = 30
_EDGE_HIGH = 90
_BLUR_KERNEL = (5, 5)

# Méthode B — surface uniforme
_UNIFORM_STD_MAX = 28.0  # écart-type max → surface lisse
_UNIFORM_MEAN_MIN = 130  # luminosité min (filtre sol sombre)
_UNIFORM_BANDS = 3
_UNIFORM_BAND_THRESH = 2


# ---------------------------------------------------------------------------
# Structure de résultat par zone
# ---------------------------------------------------------------------------


class _ZoneResult:
    __slots__ = ("obstacle", "confidence", "method")

    def __init__(
        self,
        obstacle: bool = False,
        confidence: float = 0.0,
        method: str = "none",
    ) -> None:
        self.obstacle = obstacle
        self.confidence = confidence
        self.method = method

    def __repr__(self) -> str:
        return f"Zone(obs={self.obstacle} conf={self.confidence:.2f} m={self.method})"


_CLEAR_ZONE = _ZoneResult()


# ---------------------------------------------------------------------------
# Détecteur
# ---------------------------------------------------------------------------


class VisionObstacleDetector:
    """
    Détecte les obstacles via la caméra en 3 zones (gauche / centre / droite).

    La zone centrale correspond au chemin direct.
    Les zones latérales permettent l'évitement directionnel.

    Parameters
    ----------
    edge_threshold : float
        Densité Canny (0-1) déclenchant "obstacle texturé".
    history : int
        Frames pour le vote majoritaire (lissage temporel).
    uniform_std_max : float
        Écart-type max pour détecter une surface lisse.
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
        self._zone_left = _CLEAR_ZONE
        self._zone_center = _CLEAR_ZONE
        self._zone_right = _CLEAR_ZONE
        self._last_update_ts: float = 0.0

        # Vote majoritaire par zone
        self._votes_left: list[bool] = []
        self._votes_center: list[bool] = []
        self._votes_right: list[bool] = []

        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Propriétés thread-safe
    # ------------------------------------------------------------------

    @property
    def obstacle(self) -> bool:
        """True si au moins une zone détecte un obstacle."""
        with self._lock:
            return (
                self._zone_left.obstacle or self._zone_center.obstacle or self._zone_right.obstacle
            )

    @property
    def zones(self) -> dict[str, bool]:
        """Résultat par zone : {"left": bool, "center": bool, "right": bool}."""
        with self._lock:
            return {
                "left": self._zone_left.obstacle,
                "center": self._zone_center.obstacle,
                "right": self._zone_right.obstacle,
            }

    @property
    def last_update_ts(self) -> float:
        """Timestamp (monotonic) de la dernière analyse."""
        with self._lock:
            return self._last_update_ts

    def to_dict(self) -> dict:
        with self._lock:
            any_obs = (
                self._zone_left.obstacle or self._zone_center.obstacle or self._zone_right.obstacle
            )
            best_conf = max(
                self._zone_left.confidence,
                self._zone_center.confidence,
                self._zone_right.confidence,
            )
            # Méthode principale = zone avec la plus haute confiance
            best_method = "none"
            for z in (self._zone_left, self._zone_center, self._zone_right):
                if z.obstacle and z.confidence >= best_conf:
                    best_method = z.method
            return {
                "vision_obstacle": any_obs,
                "vision_left": self._zone_left.obstacle,
                "vision_center": self._zone_center.obstacle,
                "vision_right": self._zone_right.obstacle,
                "vision_confidence": round(best_conf, 3),
                "vision_available": _CV2_AVAILABLE,
                "vision_method": best_method,
            }

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _CV2_AVAILABLE:
            log.info("VisionObstacleDetector démarré en mode dégradé (cv2 absent)")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="vision-detector")
        self._thread.start()
        log.info(
            "VisionObstacleDetector démarré — seuil=%.2f std_max=%.1f hist=%d",
            self._threshold,
            self._uniform_std_max,
            self._history,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("VisionObstacleDetector arrêté")

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------

    def push_frame(self, jpeg_bytes: bytes) -> None:
        """Appelé depuis le thread caméra avec les bytes JPEG d'une frame."""
        if not _CV2_AVAILABLE:
            return
        try:
            self._queue.put_nowait(jpeg_bytes)
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                jpeg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            left, center, right = self._analyse_zones(jpeg)

            # Vote majoritaire par zone
            def _vote(votes: list[bool], new_val: bool) -> bool:
                votes.append(new_val)
                if len(votes) > self._history:
                    votes.pop(0)
                return sum(votes) > len(votes) / 2

            with self._lock:
                smoothed_left = _vote(self._votes_left, left.obstacle)
                smoothed_center = _vote(self._votes_center, center.obstacle)
                smoothed_right = _vote(self._votes_right, right.obstacle)
                self._zone_left = _ZoneResult(smoothed_left, left.confidence, left.method)
                self._zone_center = _ZoneResult(smoothed_center, center.confidence, center.method)
                self._zone_right = _ZoneResult(smoothed_right, right.confidence, right.method)
                self._last_update_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Analyse d'une frame en 3 zones
    # ------------------------------------------------------------------

    def _analyse_zones(self, jpeg_bytes: bytes) -> tuple[_ZoneResult, _ZoneResult, _ZoneResult]:
        """Décode et analyse les 3 zones. Retourne (left, center, right)."""
        try:
            arr = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
            if arr is None:
                return _CLEAR_ZONE, _CLEAR_ZONE, _CLEAR_ZONE

            small = cv2.resize(arr, (_PROCESS_WIDTH, _PROCESS_HEIGHT))
            h, w = small.shape
            y_start = int(h * _ROI_TOP_PCT)
            x_start = int(w * _ROI_SIDE_PCT)
            x_end = w - x_start

            roi = small[y_start:, x_start:x_end]
            roi_w = roi.shape[1]

            # Découpe en 3 zones égales (gauche / centre / droite)
            z_left = roi[:, : roi_w // 3]
            z_center = roi[:, roi_w // 3 : 2 * roi_w // 3]
            z_right = roi[:, 2 * roi_w // 3 :]

            return (
                self._analyse_zone(z_left),
                self._analyse_zone(z_center),
                self._analyse_zone(z_right),
            )

        except Exception as exc:  # noqa: BLE001
            log.debug("Vision zones error: %s", exc)
            return _CLEAR_ZONE, _CLEAR_ZONE, _CLEAR_ZONE

    def _analyse_zone(self, zone: np.ndarray) -> _ZoneResult:
        """
        Analyse une zone ROI.

        Méthode A — Canny (obstacles texturés)
        Méthode B — Surface uniforme (murs lisses)
        """
        # Méthode A : Canny
        blurred = cv2.GaussianBlur(zone, _BLUR_KERNEL, 0)
        edges = cv2.Canny(blurred, _EDGE_LOW, _EDGE_HIGH)
        density = float(np.count_nonzero(edges)) / max(edges.size, 1)

        if density > self._threshold:
            return _ZoneResult(True, density, "canny")

        # Méthode B : surface uniforme
        roi_h, _roi_w = zone.shape
        band_h = max(1, roi_h // _UNIFORM_BANDS)
        uniform_count = 0

        for i in range(_UNIFORM_BANDS):
            y0 = i * band_h
            y1 = y0 + band_h if i < _UNIFORM_BANDS - 1 else roi_h
            band = zone[y0:y1, :]
            std = float(np.std(band))
            mean = float(np.mean(band))
            if std < self._uniform_std_max and mean >= _UNIFORM_MEAN_MIN:
                uniform_count += 1

        if uniform_count >= _UNIFORM_BAND_THRESH:
            confidence = uniform_count / _UNIFORM_BANDS
            return _ZoneResult(True, confidence, "uniform")

        return _ZoneResult(False, density, "none")
