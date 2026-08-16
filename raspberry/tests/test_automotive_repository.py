import pathlib

from modules.automotive.repository import AutomotiveRepository


def _waypoints() -> list[dict]:
    return [
        {"zone": "front", "x": 1.0, "y": 2.0, "yaw": 0.2, "pan": 0.0, "tilt": -5.0},
        {"zone": "rear", "x": 3.0, "y": 4.0, "yaw": 3.1, "pan": 10.0, "tilt": 2.0},
    ]


def test_route_and_waypoints_are_persisted_in_order(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()

    route = repository.create_route("Place A", "parking", _waypoints())

    assert route["name"] == "Place A"
    assert [point["zone"] for point in route["waypoints"]] == ["front", "rear"]
    assert repository.list_routes("parking")[0]["waypoint_count"] == 2
    assert repository.list_routes("other") == []


def test_inspection_links_vehicle_route_and_spatial_capture(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()
    route = repository.create_route("Place A", "parking", _waypoints())
    vehicle = repository.upsert_vehicle("AA-123-AA", "SUV")
    inspection = repository.create_inspection(vehicle["id"], route["id"])

    capture = repository.add_capture(
        inspection["id"],
        route["waypoints"][0],
        "/tmp/photo.jpg",
        {"x": 1.1, "y": 2.1, "yaw": 0.25},
    )
    repository.update_inspection(inspection["id"], "completed", completed=True)
    stored = repository.get_inspection(inspection["id"])

    assert stored["status"] == "completed"
    assert stored["registration"] == "AA-123-AA"
    assert stored["captures"][0]["id"] == capture["id"]
    assert stored["captures"][0]["pose"]["x"] == 1.1


def test_capture_persists_compensated_camera_pan(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()
    route = repository.create_route("Place A", "parking", _waypoints())
    vehicle = repository.upsert_vehicle("AA-123-AA")
    inspection = repository.create_inspection(vehicle["id"], route["id"])
    waypoint = route["waypoints"][0]
    waypoint["_capture_pan"] = -17.5

    capture = repository.add_capture(
        inspection["id"], waypoint, "/tmp/photo.jpg", {"x": 1.0, "y": 2.0}
    )

    assert capture["pan"] == -17.5


def test_vehicle_is_reused_by_registration(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()

    first = repository.upsert_vehicle("AA-123-AA", "Berline")
    second = repository.upsert_vehicle("AA-123-AA", "SUV")

    assert second["id"] == first["id"]
    assert second["label"] == "SUV"


def test_map_records_report_dependencies_and_are_deleted_together(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()
    route = repository.create_route("Place A", "parking", _waypoints())
    vehicle = repository.upsert_vehicle("AA-123-AA")
    inspection = repository.create_inspection(vehicle["id"], route["id"])
    repository.add_capture(inspection["id"], route["waypoints"][0], "/tmp/capture.jpg", {"x": 1.0})

    assert repository.map_dependencies("parking") == {
        "routes": 1,
        "inspections": 1,
        "captures": 1,
    }
    assert repository.delete_map_records("parking") == ["/tmp/capture.jpg"]
    assert repository.map_dependencies("parking") == {
        "routes": 0,
        "inspections": 0,
        "captures": 0,
    }
    assert repository.list_routes("parking") == []
