"""Sequential automatic inspection runner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .repository import AutomotiveRepository

log = logging.getLogger(__name__)


class InspectionRunner:
    """Navigate, stop, frame the camera and capture at every learned point."""

    def __init__(
        self,
        repository: AutomotiveRepository,
        navigate: Callable[[dict], Awaitable[None]],
        capture: Callable[[str, dict], Awaitable[tuple[str, dict | None]]],
        return_home: Callable[[], Awaitable[None]],
        cancel_navigation: Callable[[], Awaitable[None]],
    ) -> None:
        self.repository = repository
        self._navigate = navigate
        self._capture = capture
        self._return_home = return_home
        self._cancel_navigation = cancel_navigation
        self._task: asyncio.Task | None = None
        self._inspection_id: str | None = None

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, vehicle: dict, route_id: str) -> dict:
        if self.active:
            raise RuntimeError("Une inspection est déjà en cours")
        route = self.repository.get_route(route_id)
        inspection = self.repository.create_inspection(vehicle["id"], route_id)
        self._inspection_id = inspection["id"]
        self._task = asyncio.create_task(self._run(inspection["id"], route))
        return inspection

    async def stop(self) -> None:
        inspection_id = self._inspection_id
        if self._task and not self._task.done():
            self._task.cancel()
            await self._cancel_navigation()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if inspection_id:
            self.repository.update_inspection(inspection_id, "cancelled", completed=True)

    async def _run(self, inspection_id: str, route: dict) -> None:
        try:
            for index, waypoint in enumerate(route["waypoints"]):
                self.repository.update_inspection(
                    inspection_id, "navigating", current_waypoint=index
                )
                await self._navigate(waypoint)
                self.repository.update_inspection(
                    inspection_id, "capturing", current_waypoint=index
                )
                media_path, pose = await self._capture(inspection_id, waypoint)
                self.repository.add_capture(inspection_id, waypoint, media_path, pose)

            self.repository.update_inspection(
                inspection_id, "returning_home", current_waypoint=len(route["waypoints"])
            )
            await self._return_home()
            self.repository.update_inspection(inspection_id, "completed", completed=True)
        except asyncio.CancelledError:
            self.repository.update_inspection(inspection_id, "cancelled", completed=True)
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Inspection automobile %s échouée", inspection_id)
            await self._cancel_navigation()
            self.repository.update_inspection(
                inspection_id, "error", error=str(exc), completed=True
            )
        finally:
            self._inspection_id = None
