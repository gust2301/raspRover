import asyncio
import pathlib

from modules.automotive.repository import AutomotiveRepository
from modules.automotive.service import InspectionRunner


def test_runner_navigates_and_captures_each_point_then_returns_home(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()
    waypoints = [
        {"zone": "front", "x": 1.0, "y": 2.0, "yaw": 0.0, "pan": 0.0, "tilt": 0.0},
        {"zone": "rear", "x": 2.0, "y": 2.0, "yaw": 3.14, "pan": 5.0, "tilt": -2.0},
    ]
    route = repository.create_route("Place A", "parking", waypoints)
    vehicle = repository.upsert_vehicle("TEST-001")
    events: list[str] = []

    async def navigate(point: dict) -> None:
        events.append(f"navigate:{point['zone']}")

    async def capture(inspection_id: str, point: dict) -> tuple[str, dict]:
        events.append(f"capture:{point['zone']}")
        return f"/tmp/{inspection_id}-{point['zone']}.jpg", {"x": point["x"]}

    async def home() -> None:
        events.append("home")

    async def cancel() -> None:
        events.append("cancel")

    async def scenario() -> dict:
        runner = InspectionRunner(repository, navigate, capture, home, cancel)
        inspection = runner.start(vehicle, route["id"])
        assert runner._task is not None
        await runner._task
        return repository.get_inspection(inspection["id"])

    inspection = asyncio.run(scenario())

    assert events == ["navigate:front", "capture:front", "navigate:rear", "capture:rear", "home"]
    assert inspection["status"] == "completed"
    assert [capture["zone"] for capture in inspection["captures"]] == ["front", "rear"]


def test_runner_records_navigation_failure(tmp_path: pathlib.Path):
    repository = AutomotiveRepository(tmp_path / "robot.db")
    repository.init()
    route = repository.create_route(
        "Place A",
        "parking",
        [{"zone": "front", "x": 1.0, "y": 2.0, "yaw": 0.0, "pan": 0.0, "tilt": 0.0}],
    )
    vehicle = repository.upsert_vehicle("TEST-002")
    cancelled: list[bool] = []

    async def fail(_point: dict) -> None:
        raise RuntimeError("point inaccessible")

    async def capture(_inspection_id: str, _point: dict) -> tuple[str, None]:
        raise AssertionError("capture should not run")

    async def home() -> None:
        raise AssertionError("home should not run")

    async def cancel() -> None:
        cancelled.append(True)

    async def scenario() -> dict:
        runner = InspectionRunner(repository, fail, capture, home, cancel)
        inspection = runner.start(vehicle, route["id"])
        assert runner._task is not None
        await runner._task
        return repository.get_inspection(inspection["id"])

    inspection = asyncio.run(scenario())

    assert cancelled == [True]
    assert inspection["status"] == "error"
    assert inspection["error"] == "point inaccessible"
