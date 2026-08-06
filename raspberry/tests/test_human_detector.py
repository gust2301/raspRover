from __future__ import annotations

import time

from modules.sensors.human_detector import _TARGET_STALE_S, HumanDetector


def test_stale_human_target_is_not_tracked_forever():
    detector = HumanDetector()
    with detector._lock:
        detector._best_target = (0.4, 0.5, 0.8)
        detector._last_update_ts = time.monotonic() - _TARGET_STALE_S - 0.1

    assert detector.best_target is None
    assert detector.person_detected is False
