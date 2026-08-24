from __future__ import annotations

import asyncio
import time

from modules.control.follow_me import FollowMeController
from modules.sensors.lidar import LidarSnapshot
from modules.sensors.oak_d_lite import OakTarget


class FakeMotors:
    def __init__(self) -> None:
        self.commands: list[tuple] = []

    def drive(self, left: float, right: float) -> None:
        self.commands.append(("drive", left, right))

    def arc(self, speed: float, steering: float) -> None:
        self.commands.append(("arc", speed, steering))

    def stop(self) -> None:
        self.commands.append(("stop",))


class FakeOak:
    person_target: OakTarget | None = None
    depth_zones = {"left": False, "center": False, "right": False}


class FakeLidar:
    snapshot = LidarSnapshot(connected=True)


def _target(*, x_mm: int = 0, z_mm: int = 1800) -> OakTarget:
    return OakTarget("person", 0.9, 0.5, 0.5, x_mm, 0, z_mm)


def _controller(pose_provider=lambda: None):
    motors = FakeMotors()
    oak = FakeOak()
    lidar = FakeLidar()
    controller = FollowMeController(motors, oak, lidar, pose_provider)
    return controller, motors, oak, lidar


def test_follow_me_advances_towards_distant_centered_person():
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(z_mm=2000)

    asyncio.run(controller._step())

    assert motors.commands[-1][0] == "arc"
    assert motors.commands[-1][1] >= 0.14
    assert controller.to_dict()["follow_me_state"] == "following"


def test_follow_me_turns_towards_person_without_reversing():
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(x_mm=700, z_mm=1400)

    asyncio.run(controller._step())

    assert motors.commands[-1][0] == "drive"
    assert motors.commands[-1][1] > 0.0
    assert motors.commands[-1][2] < 0.0
    assert controller.to_dict()["follow_me_state"] == "turning_right"


def test_follow_me_stops_immediately_when_person_is_lost():
    controller, motors, _oak, _lidar = _controller()

    asyncio.run(controller._step())

    assert motors.commands[-1] == ("stop",)
    assert controller.to_dict()["follow_me_state"] == "waiting_person"


def test_follow_me_lidar_obstacle_has_priority():
    controller, motors, oak, lidar = _controller()
    oak.person_target = _target(z_mm=2000)
    lidar.snapshot = LidarSnapshot(connected=True, front_distance_cm=20.0)

    asyncio.run(controller._step())

    assert motors.commands[-1] == ("stop",)
    assert controller.to_dict()["follow_me_state"] == "obstacle"


def test_follow_me_creeps_forward_while_turning_moderately():
    """A moderately misaligned but still-far person must not freeze translation:
    the rover should keep closing distance while pivoting towards them."""
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(x_mm=728, z_mm=2000)  # ~20°, 2.0 m away

    asyncio.run(controller._step())

    command = motors.commands[-1]
    assert command[0] == "drive"
    left, right = command[1], command[2]
    assert left > 0.3  # correction franche sur la roue extérieure
    assert right > 0.0  # les deux roues avancent : virage fluide, pas de pivot saccadé
    assert left > right
    assert controller.to_dict()["follow_me_state"] == "turning_right"


def test_follow_me_pivots_in_place_beyond_pivot_threshold():
    """Near the edge of the camera's field of view, forward creep must stay
    off entirely so the rover doesn't arc away from (and lose) the person."""
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(x_mm=1788, z_mm=1500)  # ~50°, 1.5 m away

    asyncio.run(controller._step())

    command = motors.commands[-1]
    assert command[0] == "drive"
    assert command[1] == -command[2]  # pure pivot: no forward component


def test_follow_me_brief_loss_searches_last_bearing_without_advancing():
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(x_mm=700, z_mm=1400)
    asyncio.run(controller._step())

    oak.person_target = None
    asyncio.run(controller._step())

    command = motors.commands[-1]
    assert command[0] == "drive"
    assert command[1] == -command[2]
    assert controller.to_dict()["follow_me_state"] == "reacquiring"


def test_follow_me_stops_after_target_loss_grace_period():
    controller, motors, oak, _lidar = _controller()
    oak.person_target = _target(x_mm=700, z_mm=1400)
    asyncio.run(controller._step())
    controller._last_target_ts -= controller.target_loss_grace_s + 0.1

    oak.person_target = None
    asyncio.run(controller._step())

    assert motors.commands[-1] == ("stop",)
    assert controller.to_dict()["follow_me_state"] == "waiting_person"


def test_follow_me_records_spaced_slam_poses():
    poses = iter(
        [
            {"x": 0.0, "y": 0.0, "yaw": 0.0, "updated_at": time.time()},
            {"x": 0.1, "y": 0.0, "yaw": 0.0, "updated_at": time.time()},
            {"x": 0.4, "y": 0.0, "yaw": 0.0, "updated_at": time.time()},
        ]
    )
    controller, _motors, _oak, _lidar = _controller(lambda: next(poses))

    controller._record_pose()
    controller._record_pose()
    controller._record_pose()

    assert controller.to_dict()["follow_me_trail_count"] == 2
