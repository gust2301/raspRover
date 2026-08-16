"""Alignement ICP 2D léger pour corriger le lacet de l'odométrie."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ScanMatch:
    yaw: float
    translation_x: float
    translation_y: float
    residual_m: float
    pairs: int


def scan_points(
    ranges: list[float] | tuple[float, ...],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    stride: int = 3,
) -> np.ndarray:
    """Convertit un LaserScan en points finis et sous-échantillonnés."""
    values = np.asarray(ranges, dtype=float)
    angles = angle_min + np.arange(values.size, dtype=float) * angle_increment
    valid = np.isfinite(values) & (values >= range_min) & (values <= range_max)
    values = values[valid][::stride]
    angles = angles[valid][::stride]
    return np.column_stack((values * np.cos(angles), values * np.sin(angles)))


def _rotation(yaw: float) -> np.ndarray:
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return np.array(((cosine, -sine), (sine, cosine)), dtype=float)


def match_scans(
    reference: np.ndarray,
    current: np.ndarray,
    initial_yaw: float,
    initial_translation: tuple[float, float],
    maximum_pair_distance_m: float = 0.35,
    iterations: int = 8,
) -> ScanMatch | None:
    """Estime la transformation ``current -> reference`` par ICP robuste."""
    if len(reference) < 40 or len(current) < 40:
        return None

    translation = np.asarray(initial_translation, dtype=float)
    # Le glissement peut rendre l'angle encodeur faux de plusieurs dizaines de
    # degrés. Une recherche grossière évite que l'ICP reste dans ce minimum
    # local, particulièrement dans un couloir aux parois parallèles.
    coarse_candidates = np.linspace(
        initial_yaw - math.radians(25.0),
        initial_yaw + math.radians(25.0),
        21,
    )
    coarse_scores: list[tuple[float, float]] = []
    for candidate in coarse_candidates:
        transformed = current @ _rotation(float(candidate)).T + translation
        squared = ((transformed[:, None, :] - reference[None, :, :]) ** 2).sum(axis=2)
        nearest = np.sqrt(squared.min(axis=1))
        coarse_scores.append((float(np.quantile(nearest, 0.6)), float(candidate)))
    _, coarse_yaw = min(coarse_scores)
    rotation = _rotation(coarse_yaw)
    pair_count = 0
    residual = math.inf

    for _ in range(iterations):
        transformed = current @ rotation.T + translation
        squared = ((transformed[:, None, :] - reference[None, :, :]) ** 2).sum(axis=2)
        indices = squared.argmin(axis=1)
        distances = np.sqrt(squared[np.arange(len(current)), indices])
        adaptive_gate = min(maximum_pair_distance_m, float(np.quantile(distances, 0.7)))
        selected = distances <= max(0.04, adaptive_gate)
        pair_count = int(selected.sum())
        if pair_count < 30:
            return None

        source = transformed[selected]
        target = reference[indices[selected]]
        source_center = source.mean(axis=0)
        target_center = target.mean(axis=0)
        covariance = (source - source_center).T @ (target - target_center)
        u_matrix, _, vt_matrix = np.linalg.svd(covariance)
        correction_rotation = vt_matrix.T @ u_matrix.T
        if np.linalg.det(correction_rotation) < 0:
            vt_matrix[-1, :] *= -1
            correction_rotation = vt_matrix.T @ u_matrix.T
        correction_translation = target_center - correction_rotation @ source_center
        rotation = correction_rotation @ rotation
        translation = correction_rotation @ translation + correction_translation
        residual = float(np.median(distances[selected]))

    return ScanMatch(
        yaw=math.atan2(rotation[1, 0], rotation[0, 0]),
        translation_x=float(translation[0]),
        translation_y=float(translation[1]),
        residual_m=residual,
        pairs=pair_count,
    )
