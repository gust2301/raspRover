"""Cinématique différentielle pure pour l'odométrie encodeur."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class WheelSample:
    left_speed_m_s: float
    right_speed_m_s: float
    left_distance_m: float
    right_distance_m: float
    timestamp: float
    sequence: int


class EncoderIntegrator:
    """Intègre les vitesses encodeur et les recale sur leur cumul physique."""

    def __init__(
        self,
        wheel_separation_m: float,
        left_sign: float = 1.0,
        right_sign: float = 1.0,
    ) -> None:
        if wheel_separation_m <= 0:
            raise ValueError("wheel_separation_m doit être positif")
        self.wheel_separation_m = wheel_separation_m
        self.left_sign = 1.0 if left_sign >= 0 else -1.0
        self.right_sign = 1.0 if right_sign >= 0 else -1.0
        self.x = self.y = self.yaw = 0.0
        self.linear = self.angular = 0.0
        self._first: WheelSample | None = None
        self._previous: WheelSample | None = None
        self._integrated_left = 0.0
        self._integrated_right = 0.0

    def update(self, sample: WheelSample) -> bool:
        if self._first is None:
            self._first = self._previous = sample
            return False
        assert self._previous is not None
        dt = sample.timestamp - self._previous.timestamp
        if dt <= 0.0 or dt > 0.5 or sample.sequence <= self._previous.sequence:
            self._previous = sample
            self.linear = self.angular = 0.0
            return False

        vl = sample.left_speed_m_s * self.left_sign
        vr = sample.right_speed_m_s * self.right_sign
        previous_vl = self._previous.left_speed_m_s * self.left_sign
        previous_vr = self._previous.right_speed_m_s * self.right_sign
        predicted_left = 0.5 * (previous_vl + vl) * dt
        predicted_right = 0.5 * (previous_vr + vr) * dt

        first = self._first
        measured_left_total = (sample.left_distance_m - first.left_distance_m) * self.left_sign
        measured_right_total = (sample.right_distance_m - first.right_distance_m) * self.right_sign
        left_error = measured_left_total - (self._integrated_left + predicted_left)
        right_error = measured_right_total - (self._integrated_right + predicted_right)
        correction_limit = 0.003
        dl = predicted_left + max(-correction_limit, min(correction_limit, left_error * 0.25))
        dr = predicted_right + max(-correction_limit, min(correction_limit, right_error * 0.25))

        if abs(left_error) > 0.30 or abs(right_error) > 0.30:
            self._first = sample
            self._integrated_left = self._integrated_right = 0.0
            self._previous = sample
            self.linear = self.angular = 0.0
            return False

        self._integrated_left += dl
        self._integrated_right += dr
        distance = 0.5 * (dl + dr)
        heading_delta = (dr - dl) / self.wheel_separation_m
        middle_yaw = self.yaw + 0.5 * heading_delta
        self.x += distance * math.cos(middle_yaw)
        self.y += distance * math.sin(middle_yaw)
        self.yaw = math.atan2(
            math.sin(self.yaw + heading_delta), math.cos(self.yaw + heading_delta)
        )
        self.linear = distance / dt
        self.angular = heading_delta / dt
        self._previous = sample
        return True
