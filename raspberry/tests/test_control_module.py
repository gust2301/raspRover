"""
Tests d'integration du module Controle contre l'emulateur ESP32.

Ces tests valident la chaine complete :
  ESP32Link --- socket --> FakeESP32Server --- state updates --> assertions

Ils ne necessitent aucun materiel physique.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from modules.control import (
    ESP32Link,
    ESP32TimeoutError,
    InvalidParameterError,
    MotorController,
    PanTiltController,
)

# --- ESP32Link : ouverture / fermeture / transport --------------------------


class TestESP32Link:
    def test_read_line_keeps_uart_fragments_until_newline(self):
        class FragmentedSerial:
            is_open = True
            timeout = 1.0

            def __init__(self):
                self.fragments = [b'{"T":', b'1001,"L":0', b',"R":0}\n']

            @property
            def in_waiting(self):
                return len(self.fragments[0]) if self.fragments else 0

            def read(self, _size):
                return self.fragments.pop(0) if self.fragments else b""

        link = ESP32Link()
        link._ser = FragmentedSerial()  # type: ignore[assignment]

        assert link.read_line(timeout_s=0.2) == '{"T":1001,"L":0,"R":0}'

    def test_open_close(self, emulator):
        link = ESP32Link(port=emulator["url"])
        assert not link.is_open
        link.open()
        assert link.is_open
        link.close()
        assert not link.is_open

    def test_context_manager(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            assert link.is_open
        assert not link.is_open

    def test_send_updates_stats(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            link.send({"T": 1, "L": 0.0, "R": 0.0})
            assert link.stats.commands_sent == 1
            assert link.stats.bytes_sent > 0

    def test_request_feedback_round_trip(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            fb = link.request_feedback(timeout_s=2.0)
        assert fb["T"] == 1001
        # Le firmware Waveshare envoie 'v' en centivolts (ex: 1260 = 12.60 V).
        # _enrich_feedback() dans server.py divise par 100 pour obtenir les vrais volts.
        assert 900 < fb["v"] <= 1260  # centivolts : 9.00 V → 12.60 V
        assert "x" in fb and "y" in fb and "yaw" in fb

    def test_configure_platform_enables_measured_pantilt_feedback(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            link.configure_platform(main_type=2, module_type=2)
            fb = link.request_feedback(timeout_s=1.0, command_type=130)
        assert "pan" in fb and "tilt" in fb

    def test_feedback_timeout_on_silent_server(self):
        """Un serveur TCP qui accepte mais ne repond jamais doit causer un timeout."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def accept_and_stay_silent():
            srv.settimeout(1.0)
            try:
                conn, _ = srv.accept()
                conn.settimeout(0.1)
                while not stop.is_set():
                    try:
                        conn.recv(1024)
                    except (TimeoutError, OSError):
                        pass
            except Exception:
                pass

        t = threading.Thread(target=accept_and_stay_silent, daemon=True)
        t.start()

        try:
            link = ESP32Link(port=f"socket://127.0.0.1:{port}", timeout_s=0.2)
            link.open()
            with pytest.raises(ESP32TimeoutError):
                link.request_feedback(timeout_s=0.3)
            link.close()
        finally:
            stop.set()
            srv.close()


# --- MotorController : pilotage moteurs --------------------------------------


class TestMotorController:
    def test_command_observer_receives_clamped_drive_and_stop(self, emulator):
        observed = []
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(
                link,
                max_speed=0.5,
                watchdog_s=None,
                command_observer=lambda left, right: observed.append((left, right)),
            )
            motors.drive(0.8, -0.7)
            motors.stop()
            assert observed == [(0.5, -0.5), (0.0, 0.0)]

    def test_forward_sets_both_sides_positive(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.4, watchdog_s=None)
            motors.forward(0.4)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == pytest.approx(0.4)
                assert emulator["state"].R == pytest.approx(0.4)
            motors.shutdown()

    def test_backward_sets_both_sides_negative(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.3, watchdog_s=None)
            motors.backward(0.3)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == pytest.approx(-0.3)
                assert emulator["state"].R == pytest.approx(-0.3)
            motors.shutdown()

    def test_rotate_left_opposes_sides(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.3, watchdog_s=None)
            motors.rotate_left(0.3)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == pytest.approx(-0.3)
                assert emulator["state"].R == pytest.approx(0.3)
            motors.shutdown()

    def test_stop_zeroes_everything(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.4, watchdog_s=None)
            motors.forward(0.4)
            time.sleep(0.05)
            motors.stop()
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == 0.0
                assert emulator["state"].R == 0.0
            motors.shutdown()

    def test_max_speed_clamps_commands(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.3, default_speed=0.2, watchdog_s=None)
            motors.drive(0.9, 0.9)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == pytest.approx(0.3)
                assert emulator["state"].R == pytest.approx(0.3)
            motors.shutdown()

    def test_invalid_max_speed_raises(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            with pytest.raises(InvalidParameterError):
                MotorController(link, max_speed=0.0, watchdog_s=None)
            with pytest.raises(InvalidParameterError):
                MotorController(link, max_speed=1.5, watchdog_s=None)

    def test_watchdog_auto_stops(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.3, watchdog_s=0.2)
            motors.forward(0.3)
            time.sleep(0.5)
            with emulator["state"]._lock:
                assert emulator["state"].L == 0.0
                assert emulator["state"].R == 0.0
            motors.shutdown()


# --- PanTiltController : servos ST3215 ---------------------------------------


class TestPanTiltController:
    def test_goto_updates_angles(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            pt = PanTiltController(link)
            pt.goto(pan_deg=45, tilt_deg=10)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].pan_deg == pytest.approx(45)
                assert emulator["state"].tilt_deg == pytest.approx(10)

    def test_clamps_out_of_range_pan(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            pt = PanTiltController(link, pan_range=(-30, 30))
            pt.goto(pan_deg=180, tilt_deg=0)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].pan_deg == pytest.approx(30)

    def test_center_sets_zero(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            pt = PanTiltController(link)
            pt.goto(pan_deg=45, tilt_deg=20)
            time.sleep(0.05)
            pt.center()
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].pan_deg == 0.0
                assert emulator["state"].tilt_deg == 0.0

    def test_nudge_is_relative(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            pt = PanTiltController(link)
            pt.goto(pan_deg=10, tilt_deg=0)
            time.sleep(0.05)
            pt.nudge(d_pan=5, d_tilt=2)
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].pan_deg == pytest.approx(15)
                assert emulator["state"].tilt_deg == pytest.approx(2)

    def test_wait_until_reached_uses_measured_feedback(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            pt = PanTiltController(link)
            pt.goto(pan_deg=12, tilt_deg=-4)
            feedback = link.request_feedback(timeout_s=1.0, command_type=130)
            pt.update_feedback(feedback)
            measured = pt.wait_until_reached(12, -4, timeout_s=0.2)
        assert measured == pytest.approx((12, -4))


# --- Integration end-to-end --------------------------------------------------


class TestIntegration:
    def test_drive_then_feedback_shows_movement(self, emulator):
        """Conduire 0.3s puis demander le feedback doit montrer une position non nulle."""
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.4, watchdog_s=None)
            motors.forward(0.4)
            time.sleep(0.3)
            motors.stop()
            fb = link.request_feedback(timeout_s=1.0)
            motors.shutdown()
        assert abs(fb["x"]) > 0.01, f"Le rover aurait du avancer, mais x={fb['x']}"

    def test_emergency_stop_zeroes_motors(self, emulator):
        with ESP32Link(port=emulator["url"]) as link:
            motors = MotorController(link, max_speed=0.5, default_speed=0.4, watchdog_s=None)
            motors.forward(0.4)
            time.sleep(0.05)
            link.emergency_stop()
            time.sleep(0.05)
            with emulator["state"]._lock:
                assert emulator["state"].L == 0.0
                assert emulator["state"].R == 0.0
            motors.shutdown()
