"""Pure depth-zone processing shared by the isolated OAK worker and tests."""

from __future__ import annotations

from typing import Any

import numpy as np


def depth_zones(
    depth: np.ndarray,
    args: Any,
    excluded_rois: list[tuple[float, float, float, float]] | None = None,
) -> tuple[dict[str, bool], dict[str, float | None]]:
    height, width = depth.shape
    roi_top = int(height * args.depth_roi_top)
    roi_bottom = int(height * args.depth_roi_bottom)
    roi = depth[roi_top:roi_bottom, :]
    allowed = np.ones(roi.shape, dtype=bool)
    # Une personne suivie n'est pas un obstacle à contourner : masquer
    # seulement sa boîte dans le calcul de profondeur évite que ses jambes
    # bloquent le rover, sans désactiver les autres obstacles de la scène.
    for xmin, ymin, xmax, ymax in excluded_rois or []:
        x0 = max(0, min(width, int(xmin * width)))
        x1 = max(0, min(width, int(np.ceil(xmax * width))))
        y0 = max(roi_top, min(roi_bottom, int(ymin * height)))
        y1 = max(roi_top, min(roi_bottom, int(np.ceil(ymax * height))))
        if x1 > x0 and y1 > y0:
            allowed[y0 - roi_top : y1 - roi_top, x0:x1] = False
    third = width // 3
    areas = {
        "left": (roi[:, :third], allowed[:, :third]),
        "center": (roi[:, third : 2 * third], allowed[:, third : 2 * third]),
        "right": (roi[:, 2 * third :], allowed[:, 2 * third :]),
    }
    zones: dict[str, bool] = {}
    distances: dict[str, float | None] = {}
    for name, (area, area_allowed) in areas.items():
        valid = area[(area >= 100) & (area <= 8000) & area_allowed]
        if valid.size < args.min_valid_pixels:
            zones[name] = False
            distances[name] = None
            continue
        distance_mm = float(np.percentile(valid, 8))
        zones[name] = distance_mm <= args.obstacle_distance_mm
        distances[name] = round(distance_mm / 10.0, 1)
    return zones, distances
