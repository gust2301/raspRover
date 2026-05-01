"""Tests pour UltrasonicSensor — s'exécutent sans GPIO réel (mode simulation)."""

from __future__ import annotations

import time

import pytest

from modules.sensors.ultrasonic import _GPIO_AVAILABLE, SensorReading, UltrasonicSensor

# ---------------------------------------------------------------------------
# SensorReading
# ---------------------------------------------------------------------------


def test_sensor_reading_immutable() -> None:
    r = SensorReading(distance_cm=45.0, obstacle=False, error=None)
    with pytest.raises((AttributeError, TypeError)):
        r.distance_cm = 10.0  # type: ignore[misc]


def test_sensor_reading_obstacle_flag() -> None:
    ok = SensorReading(distance_cm=15.0, obstacle=True, error=None)
    assert ok.obstacle is True
    clear = SensorReading(distance_cm=50.0, obstacle=False, error=None)
    assert clear.obstacle is False


def test_sensor_reading_error() -> None:
    r = SensorReading(distance_cm=None, obstacle=False, error="timeout")
    assert r.distance_cm is None
    assert r.error == "timeout"


# ---------------------------------------------------------------------------
# UltrasonicSensor (mode simulation sans GPIO)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_GPIO_AVAILABLE, reason="Test simulation uniquement (pas de GPIO réel)")
def test_sensor_start_stop_simulation() -> None:
    sensor = UltrasonicSensor(obstacle_threshold_cm=20.0, poll_interval_s=0.05)
    sensor.start()
    time.sleep(0.15)  # laisse 2-3 cycles se produire
    r = sensor.reading
    sensor.stop()

    # En simulation, distance_cm est toujours non-None
    assert r.distance_cm is not None
    assert r.error is None


@pytest.mark.skipif(_GPIO_AVAILABLE, reason="Test simulation uniquement (pas de GPIO réel)")
def test_sensor_obstacle_detection_simulation() -> None:
    """Le simulateur oscille entre ~20 et ~80 cm — vérifie juste que le flag est cohérent."""
    sensor = UltrasonicSensor(obstacle_threshold_cm=20.0, poll_interval_s=0.05)
    sensor.start()
    time.sleep(0.3)
    r = sensor.reading
    sensor.stop()

    assert r.distance_cm is not None
    assert r.obstacle == (r.distance_cm < 20.0)


@pytest.mark.skipif(_GPIO_AVAILABLE, reason="Test simulation uniquement (pas de GPIO réel)")
def test_sensor_to_dict() -> None:
    sensor = UltrasonicSensor(poll_interval_s=0.05)
    sensor.start()
    time.sleep(0.15)
    d = sensor.to_dict()
    sensor.stop()

    assert "distance_cm" in d
    assert "obstacle" in d
    assert "sensor_error" in d


@pytest.mark.skipif(_GPIO_AVAILABLE, reason="Test simulation uniquement (pas de GPIO réel)")
def test_sensor_context_manager() -> None:
    with UltrasonicSensor(poll_interval_s=0.05) as sensor:
        time.sleep(0.15)
        r = sensor.reading
    assert r.distance_cm is not None


@pytest.mark.skipif(_GPIO_AVAILABLE, reason="Test simulation uniquement (pas de GPIO réel)")
def test_sensor_threshold_configurable() -> None:
    """Avec un seuil très haut, tout est obstacle."""
    sensor = UltrasonicSensor(obstacle_threshold_cm=999.0, poll_interval_s=0.05)
    sensor.start()
    time.sleep(0.15)
    r = sensor.reading
    sensor.stop()
    assert r.obstacle is True
