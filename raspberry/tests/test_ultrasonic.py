"""Tests pour UltrasonicSensor (Arduino série 2x HC-SR04) — sans matériel réel."""

from __future__ import annotations

import time

import pytest

from modules.sensors.ultrasonic import (
    _SERIAL_AVAILABLE,
    SensorReading,
    SingleReading,
    UltrasonicSensor,
)

# ---------------------------------------------------------------------------
# SingleReading
# ---------------------------------------------------------------------------


def test_single_reading_immutable() -> None:
    r = SingleReading(distance_cm=45.0, obstacle=False, ok=True)
    with pytest.raises((AttributeError, TypeError)):
        r.distance_cm = 10.0  # type: ignore[misc]


def test_single_reading_fields() -> None:
    r = SingleReading(distance_cm=15.0, obstacle=True, ok=True)
    assert r.distance_cm == 15.0
    assert r.obstacle is True
    assert r.ok is True


# ---------------------------------------------------------------------------
# SensorReading
# ---------------------------------------------------------------------------


def test_sensor_reading_immutable() -> None:
    r = SensorReading()
    with pytest.raises((AttributeError, TypeError)):
        r.front = SingleReading(10.0, True, True)  # type: ignore[misc]


def test_sensor_reading_obstacle_both_clear() -> None:
    r = SensorReading(
        front=SingleReading(50.0, False, True),
        rear=SingleReading(80.0, False, True),
    )
    assert r.obstacle is False


def test_sensor_reading_obstacle_front() -> None:
    r = SensorReading(
        front=SingleReading(15.0, True, True),
        rear=SingleReading(80.0, False, True),
    )
    assert r.obstacle is True


def test_sensor_reading_obstacle_rear() -> None:
    r = SensorReading(
        front=SingleReading(50.0, False, True),
        rear=SingleReading(10.0, True, True),
    )
    assert r.obstacle is True


def test_sensor_reading_distance_cm_min() -> None:
    """distance_cm retourne le minimum des deux capteurs."""
    r = SensorReading(
        front=SingleReading(30.0, False, True),
        rear=SingleReading(60.0, False, True),
    )
    assert r.distance_cm == 30.0


def test_sensor_reading_distance_cm_none_one_sensor() -> None:
    """Si un capteur est en timeout, l'autre est utilisé."""
    r = SensorReading(
        front=SingleReading(None, False, False),
        rear=SingleReading(45.0, False, True),
    )
    assert r.distance_cm == 45.0


def test_sensor_reading_distance_cm_both_none() -> None:
    r = SensorReading(
        front=SingleReading(None, False, False),
        rear=SingleReading(None, False, False),
    )
    assert r.distance_cm is None


def test_sensor_reading_error() -> None:
    r = SensorReading(error="port série non disponible")
    assert r.error == "port série non disponible"
    assert r.distance_cm is None


def test_sensor_reading_defaults() -> None:
    """SensorReading vide = aucun obstacle, aucune distance."""
    r = SensorReading()
    assert r.obstacle is False
    assert r.distance_cm is None
    assert r.error is None


# ---------------------------------------------------------------------------
# UltrasonicSensor en mode simulation (pyserial absent ou port None)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SERIAL_AVAILABLE, reason="Test simulation uniquement (pas de port réel)")
def test_sensor_start_stop_simulation() -> None:
    sensor = UltrasonicSensor(obstacle_threshold_cm=20.0)
    sensor.start()
    time.sleep(0.5)
    r = sensor.reading
    sensor.stop()

    assert isinstance(r, SensorReading)
    assert r.error is None
    assert r.front.distance_cm is not None
    assert r.rear.distance_cm is not None


@pytest.mark.skipif(_SERIAL_AVAILABLE, reason="Test simulation uniquement (pas de port réel)")
def test_sensor_obstacle_coherence() -> None:
    sensor = UltrasonicSensor(obstacle_threshold_cm=20.0)
    sensor.start()
    time.sleep(0.5)
    r = sensor.reading
    sensor.stop()

    # obstacle global = OR des deux capteurs
    assert r.obstacle == (r.front.obstacle or r.rear.obstacle)


@pytest.mark.skipif(_SERIAL_AVAILABLE, reason="Test simulation uniquement (pas de port réel)")
def test_sensor_to_dict() -> None:
    sensor = UltrasonicSensor()
    sensor.start()
    time.sleep(0.5)
    d = sensor.to_dict()
    sensor.stop()

    assert "distance_cm" in d
    assert "obstacle" in d
    assert "sensor_error" in d
    assert "front_cm" in d
    assert "rear_cm" in d
    assert "obstacle_front" in d
    assert "obstacle_rear" in d


@pytest.mark.skipif(_SERIAL_AVAILABLE, reason="Test simulation uniquement (pas de port réel)")
def test_sensor_context_manager() -> None:
    with UltrasonicSensor() as sensor:
        time.sleep(0.5)
        r = sensor.reading
    assert r.front.distance_cm is not None
    assert r.rear.distance_cm is not None


@pytest.mark.skipif(_SERIAL_AVAILABLE, reason="Test simulation uniquement (pas de port réel)")
def test_sensor_threshold_configurable() -> None:
    """Avec un seuil très haut, tout est obstacle."""
    sensor = UltrasonicSensor(obstacle_threshold_cm=999.0)
    sensor.start()
    time.sleep(0.5)
    r = sensor.reading
    sensor.stop()
    assert r.obstacle is True
    assert r.front.obstacle is True
    assert r.rear.obstacle is True
