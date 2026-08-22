"""Helpers for rendering ROS occupancy grids in browser image coordinates."""

from __future__ import annotations


def occupancy_grid_pixels(raw: list[int], width: int, height: int) -> bytearray:
    """Convert an OccupancyGrid into top-to-bottom grayscale image pixels.

    ROS stores row zero at the map origin (bottom of the map), whereas PNG rows
    are displayed from top to bottom. Reversing the rows keeps browser overlays
    in the same map coordinate system as Nav2.
    """
    if width <= 0 or height <= 0 or len(raw) != width * height:
        raise ValueError(f"OccupancyGrid invalide: {width}×{height}, {len(raw)} points")

    pixels = bytearray(width * height)
    for image_y, grid_y in enumerate(reversed(range(height))):
        for x in range(width):
            value = raw[grid_y * width + x]
            index = image_y * width + x
            if value == -1:
                pixels[index] = 128
            elif value == 0:
                pixels[index] = 255
            else:
                pixels[index] = max(0, 255 - value * 2)
    return pixels
