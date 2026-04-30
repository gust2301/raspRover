"""
Module Contrôle du RaspRover.

Fournit une API Python haut niveau pour piloter :
- Les moteurs 4WD (déplacement différentiel)
- Le module Pan-Tilt ST3215

via l'ESP32 embarqué (firmware Waveshare UGV) en JSON sur UART.

Exemple minimal
---------------
>>> from modules.control import ESP32Link, MotorController, PanTiltController
>>> link = ESP32Link(port="/dev/ttyAMA0", baudrate=115200)
>>> link.open()
>>> motors = MotorController(link, max_speed=0.5)
>>> pantilt = PanTiltController(link)
>>> motors.forward(speed=0.3)
>>> pantilt.goto(pan_deg=30, tilt_deg=-15)
>>> motors.stop()
>>> link.close()
"""

from .esp32_link import ESP32Link
from .exceptions import (
    ControlError,
    ESP32TimeoutError,
    InvalidParameterError,
    LinkNotOpenError,
)
from .light_controller import LightController
from .motor_controller import Direction, MotorController
from .pantilt_controller import PanTiltController

__all__ = [
    "ESP32Link",
    "MotorController",
    "Direction",
    "PanTiltController",
    "LightController",
    "ControlError",
    "LinkNotOpenError",
    "InvalidParameterError",
    "ESP32TimeoutError",
]
