"""
Détection de personnes par HOG+SVM (OpenCV built-in, zéro téléchargement).

Retourne la cible principale : position normalisée (cx, cy) dans [0,1] et
le poids de confiance HOG. Dégradé si OpenCV absent : person_detected = False.
"""

from __future__ import annotations

import logging
import pathlib
import queue
import sys
import threading
import time

log = logging.getLogger(__name__)

# Les paquets caméra/OpenCV de Raspberry Pi OS vivent hors du venv.
_SYSTEM_SITE = "/usr/lib/python3/dist-packages"
if pathlib.Path(_SYSTEM_SITE).exists() and _SYSTEM_SITE not in sys.path:
    sys.path.append(_SYSTEM_SITE)

try:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    log.warning("OpenCV absent — HumanDetector désactivé (person_detected=False)")

_DETECT_WIDTH = 320
_DETECT_HEIGHT = 240
_HOG_WIN_STRIDE = (8, 8)
_HOG_PADDING = (4, 4)
_HOG_SCALE = 1.05
_MIN_WEIGHT = -0.3  # seuil de confiance HOG (valeurs > 0 = haute confiance)
_TARGET_STALE_S = 1.5


class HumanDetector:
    """
    Détecte les personnes via HOG+SVM (cv2.HOGDescriptor_getDefaultPeopleDetector).

    Propriétés thread-safe :
        best_target : tuple[float, float, float] | None
            (cx, cy, weight) normalisé [0,1] pour cx/cy, ou None si aucune personne.
        person_detected : bool
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._best_target: tuple[float, float, float] | None = None
        self._last_update_ts: float = 0.0
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hog: cv2.HOGDescriptor | None = None  # type: ignore[name-defined]
        self._external_target: tuple[float, float, float] | None = None
        self._external_update_ts: float = 0.0

    # ------------------------------------------------------------------
    # Propriétés thread-safe
    # ------------------------------------------------------------------

    @property
    def best_target(self) -> tuple[float, float, float] | None:
        """(cx, cy, weight) normalisé, ou None si pas de personne."""
        with self._lock:
            if time.monotonic() - self._external_update_ts <= _TARGET_STALE_S:
                return self._external_target
            if time.monotonic() - self._last_update_ts > _TARGET_STALE_S:
                return None
            return self._best_target

    def update_external_target(self, target: tuple[float, float, float] | None) -> None:
        """Prefer a fresh accelerator-provided target (for example OAK-D)."""
        with self._lock:
            self._external_target = target
            self._external_update_ts = time.monotonic()

    @property
    def person_detected(self) -> bool:
        return self.best_target is not None

    @property
    def last_update_ts(self) -> float:
        with self._lock:
            return self._last_update_ts

    def to_dict(self) -> dict:
        target = self.best_target
        if target:
            cx, cy, weight = target
            return {
                "tracking_person_detected": True,
                "tracking_cx": round(cx, 3),
                "tracking_cy": round(cy, 3),
                "tracking_confidence": round(weight, 3),
                "tracking_detector_available": _CV2_AVAILABLE,
                "tracking_source": (
                    "oak"
                    if time.monotonic() - self._external_update_ts <= _TARGET_STALE_S
                    else "hog"
                ),
            }
        return {
            "tracking_person_detected": False,
            "tracking_cx": None,
            "tracking_cy": None,
            "tracking_confidence": 0.0,
            "tracking_detector_available": _CV2_AVAILABLE,
            "tracking_source": None,
        }

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _CV2_AVAILABLE:
            log.info("HumanDetector démarré en mode dégradé (cv2 absent)")
            return
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="human-detector")
        self._thread.start()
        log.info("HumanDetector démarré (HOG+SVM, résolution=%dx%d)", _DETECT_WIDTH, _DETECT_HEIGHT)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("HumanDetector arrêté")

    # ------------------------------------------------------------------
    # Callback caméra
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

            target = self._detect(jpeg)
            with self._lock:
                self._best_target = target
                self._last_update_ts = time.monotonic()

    def _detect(self, jpeg_bytes: bytes) -> tuple[float, float, float] | None:
        """Décode le JPEG, détecte les personnes, retourne la meilleure cible."""
        try:
            arr = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
            if arr is None:
                return None

            small = cv2.resize(arr, (_DETECT_WIDTH, _DETECT_HEIGHT))
            boxes, weights = self._hog.detectMultiScale(  # type: ignore[union-attr]
                small,
                winStride=_HOG_WIN_STRIDE,
                padding=_HOG_PADDING,
                scale=_HOG_SCALE,
            )

            if len(boxes) == 0:
                return None

            best_idx = int(np.argmax(weights))
            if float(weights[best_idx]) < _MIN_WEIGHT:
                return None

            x, y, w, h = boxes[best_idx]
            cx = (x + w / 2.0) / _DETECT_WIDTH
            cy = (y + h / 2.0) / _DETECT_HEIGHT
            return (cx, cy, float(weights[best_idx]))

        except Exception as exc:  # noqa: BLE001
            log.debug("HumanDetector._detect error: %s", exc)
            return None
