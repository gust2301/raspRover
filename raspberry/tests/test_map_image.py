import pytest

from modules.map_image import occupancy_grid_pixels


def test_occupancy_grid_rows_are_flipped_for_png_coordinates():
    # ROS row 0 is the bottom row: [free, occupied].
    pixels = occupancy_grid_pixels([0, 100, -1, 0], width=2, height=2)

    assert list(pixels) == [128, 255, 255, 55]


def test_occupancy_grid_rejects_invalid_dimensions():
    with pytest.raises(ValueError, match="OccupancyGrid invalide"):
        occupancy_grid_pixels([0], width=2, height=1)
