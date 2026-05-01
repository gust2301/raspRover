"""Tests unitaires pour DriveMixer."""

import pytest

from modules.control.drive_mixer import ControlMode, DriveConfig, DriveMixer


def mixer(mode: str = "driver", **kwargs) -> DriveMixer:
    cfg = DriveConfig(control_mode=ControlMode(mode), **kwargs)
    return DriveMixer(cfg)


class TestDriverMode:
    def test_forward(self):
        L, R = mixer().mix(x=0, y=0.5)
        assert L == pytest.approx(0.5)
        assert R == pytest.approx(0.5)

    def test_backward(self):
        L, R = mixer().mix(x=0, y=-0.5)
        assert L == pytest.approx(-0.5)
        assert R == pytest.approx(-0.5)

    def test_turn_right(self):
        L, R = mixer().mix(x=0.5, y=0)
        assert L == pytest.approx(0.5)
        assert R == pytest.approx(-0.5)

    def test_turn_left(self):
        L, R = mixer().mix(x=-0.5, y=0)
        assert L == pytest.approx(-0.5)
        assert R == pytest.approx(0.5)

    def test_arc_forward_right(self):
        L, R = mixer().mix(x=0.3, y=0.5)
        assert L == pytest.approx(0.5)
        assert R == pytest.approx(0.2)

    def test_stop(self):
        L, R = mixer().mix(x=0, y=0)
        assert L == 0.0
        assert R == 0.0


class TestMirrorMode:
    def test_forward_becomes_backward(self):
        """En mode miroir, y>0 (poussé vers le haut) = robot s'éloigne = backward."""
        L_d, R_d = mixer("driver").mix(x=0, y=0.5)
        L_m, R_m = mixer("mirror").mix(x=0, y=-0.5)
        assert L_m == pytest.approx(L_d)
        assert R_m == pytest.approx(R_d)

    def test_pull_toward_user_advances_robot(self):
        """Tirer joystick (y<0) en miroir = robot avance vers l'utilisateur."""
        L, R = mixer("mirror").mix(x=0, y=-0.5)
        assert L == pytest.approx(0.5)
        assert R == pytest.approx(0.5)

    def test_right_becomes_left(self):
        """En mode miroir, x>0 = tourne à gauche (miroir)."""
        L_mirror, R_mirror = mixer("mirror").mix(x=0.5, y=0)
        L_driver, R_driver = mixer("driver").mix(x=-0.5, y=0)
        assert L_mirror == pytest.approx(L_driver)
        assert R_mirror == pytest.approx(R_driver)

    def test_mirror_vs_driver_symmetry(self):
        """mirror(x, y) == driver(-x, -y) toujours."""
        cases = [(0.3, 0.4), (-0.2, 0.5), (0.0, -0.3), (0.5, 0.5)]
        for x, y in cases:
            Lm, Rm = mixer("mirror").mix(x, y)
            Ld, Rd = mixer("driver").mix(-x, -y)
            assert Lm == pytest.approx(Ld), f"L mismatch for ({x},{y})"
            assert Rm == pytest.approx(Rd), f"R mismatch for ({x},{y})"


class TestClamp:
    def test_max_speed_clamped(self):
        m = mixer(max_speed=0.5)
        L, R = m.mix(x=1.0, y=1.0)
        assert abs(L) <= 0.5
        assert abs(R) <= 0.5

    def test_custom_max_speed(self):
        m = mixer(max_speed=0.3)
        L, R = m.mix(x=0, y=1.0)
        assert L == pytest.approx(0.3)
        assert R == pytest.approx(0.3)


class TestInversions:
    def test_invert_x(self):
        L_normal, R_normal = mixer().mix(x=0.3, y=0)
        L_inv, R_inv = mixer(invert_x=True).mix(x=0.3, y=0)
        assert L_inv == pytest.approx(-L_normal)
        assert R_inv == pytest.approx(-R_normal)

    def test_invert_y(self):
        L_normal, R_normal = mixer().mix(x=0, y=0.4)
        L_inv, R_inv = mixer(invert_y=True).mix(x=0, y=0.4)
        assert L_inv == pytest.approx(-L_normal)
        assert R_inv == pytest.approx(-R_normal)

    def test_invert_motors(self):
        L, R = mixer(invert_left_motor=True, invert_right_motor=True).mix(x=0, y=0.5)
        assert L == pytest.approx(-0.5)
        assert R == pytest.approx(-0.5)


class TestFromDict:
    def test_defaults(self):
        cfg = DriveConfig.from_dict({})
        assert cfg.control_mode == ControlMode.DRIVER
        assert cfg.max_speed == 0.5
        assert not cfg.invert_x

    def test_mirror_from_dict(self):
        cfg = DriveConfig.from_dict({"control_mode": "mirror", "max_speed": 0.4})
        assert cfg.control_mode == ControlMode.MIRROR
        assert cfg.max_speed == 0.4
