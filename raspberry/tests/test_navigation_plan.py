from modules.navigation_plan import add_return_home


def test_patrol_appends_starting_pose_as_final_waypoint():
    route, added = add_return_home(
        [{"x": 2.0, "y": 1.0, "yaw": 0.0}],
        {"x": 0.2, "y": -0.1, "yaw": 1.2},
    )

    assert added is True
    assert route[-1] == {"x": 0.2, "y": -0.1, "yaw": 1.2}


def test_patrol_does_not_duplicate_home_when_last_point_is_already_close():
    original = [{"x": 0.1, "y": 0.1, "yaw": 0.0}]

    route, added = add_return_home(original, {"x": 0.0, "y": 0.0, "yaw": 1.2})

    assert added is False
    assert route == original


def test_return_home_can_be_disabled():
    original = [{"x": 2.0, "y": 1.0, "yaw": 0.0}]

    route, added = add_return_home(original, {"x": 0.0, "y": 0.0}, enabled=False)

    assert added is False
    assert route == original
