"""SQLite persistence for learned vehicle-inspection routes and executions."""

from __future__ import annotations

import json
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone

DEFAULT_DB_PATH = pathlib.Path.home() / ".rasprover" / "incidents.db"


def _now() -> str:
    # timezone.utc keeps the developer fallback Python 3.9 compatible.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017


class AutomotiveRepository:
    """Small repository kept separate from the legacy incident data helpers."""

    def __init__(self, path: pathlib.Path = DEFAULT_DB_PATH) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inspection_routes (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    map_name    TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inspection_waypoints (
                    id          TEXT PRIMARY KEY,
                    route_id    TEXT NOT NULL REFERENCES inspection_routes(id) ON DELETE CASCADE,
                    sequence    INTEGER NOT NULL,
                    zone        TEXT NOT NULL,
                    x           REAL NOT NULL,
                    y           REAL NOT NULL,
                    yaw         REAL NOT NULL,
                    pan         REAL NOT NULL DEFAULT 0,
                    tilt        REAL NOT NULL DEFAULT 0,
                    UNIQUE(route_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS vehicles (
                    id            TEXT PRIMARY KEY,
                    registration  TEXT NOT NULL UNIQUE,
                    label         TEXT,
                    created_at    TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vehicle_inspections (
                    id                TEXT PRIMARY KEY,
                    vehicle_id        TEXT NOT NULL REFERENCES vehicles(id),
                    route_id          TEXT NOT NULL REFERENCES inspection_routes(id),
                    status            TEXT NOT NULL,
                    current_waypoint  INTEGER,
                    error             TEXT,
                    started_at        TEXT NOT NULL,
                    completed_at      TEXT
                );
                CREATE TABLE IF NOT EXISTS inspection_captures (
                    id             TEXT PRIMARY KEY,
                    inspection_id  TEXT NOT NULL REFERENCES vehicle_inspections(id) ON DELETE CASCADE,
                    waypoint_id    TEXT NOT NULL REFERENCES inspection_waypoints(id),
                    zone           TEXT NOT NULL,
                    captured_at    TEXT NOT NULL,
                    media_path     TEXT NOT NULL,
                    pose_json      TEXT,
                    pan            REAL NOT NULL,
                    tilt           REAL NOT NULL
                );
                """
            )

    def create_route(self, name: str, map_name: str, waypoints: list[dict]) -> dict:
        route_id = str(uuid.uuid4())
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO inspection_routes (id, name, map_name, created_at) VALUES (?, ?, ?, ?)",
                (route_id, name, map_name, created_at),
            )
            for sequence, waypoint in enumerate(waypoints):
                connection.execute(
                    """
                    INSERT INTO inspection_waypoints
                        (id, route_id, sequence, zone, x, y, yaw, pan, tilt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        route_id,
                        sequence,
                        waypoint["zone"],
                        waypoint["x"],
                        waypoint["y"],
                        waypoint["yaw"],
                        waypoint["pan"],
                        waypoint["tilt"],
                    ),
                )
        return self.get_route(route_id)

    def list_routes(self, map_name: str | None = None) -> list[dict]:
        query = "SELECT * FROM inspection_routes"
        values: tuple = ()
        if map_name:
            query += " WHERE map_name = ?"
            values = (map_name,)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            routes = [dict(row) for row in connection.execute(query, values).fetchall()]
            for route in routes:
                route["waypoint_count"] = connection.execute(
                    "SELECT COUNT(*) FROM inspection_waypoints WHERE route_id = ?",
                    (route["id"],),
                ).fetchone()[0]
        return routes

    def get_route(self, route_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM inspection_routes WHERE id = ?", (route_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Parcours introuvable")
            route = dict(row)
            route["waypoints"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM inspection_waypoints WHERE route_id = ? ORDER BY sequence",
                    (route_id,),
                ).fetchall()
            ]
        return route

    def upsert_vehicle(self, registration: str, label: str | None = None) -> dict:
        vehicle_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO vehicles (id, registration, label, created_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(registration) DO UPDATE SET label = excluded.label
                """,
                (vehicle_id, registration, label, _now()),
            )
            row = connection.execute(
                "SELECT * FROM vehicles WHERE registration = ?", (registration,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def create_inspection(self, vehicle_id: str, route_id: str) -> dict:
        inspection_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO vehicle_inspections
                    (id, vehicle_id, route_id, status, started_at)
                VALUES (?, ?, ?, 'starting', ?)
                """,
                (inspection_id, vehicle_id, route_id, _now()),
            )
        return self.get_inspection(inspection_id)

    def update_inspection(
        self,
        inspection_id: str,
        status: str,
        *,
        current_waypoint: int | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE vehicle_inspections
                SET status = ?, current_waypoint = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, current_waypoint, error, _now() if completed else None, inspection_id),
            )

    def add_capture(
        self,
        inspection_id: str,
        waypoint: dict,
        media_path: str,
        pose: dict | None,
    ) -> dict:
        capture_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO inspection_captures
                    (id, inspection_id, waypoint_id, zone, captured_at, media_path,
                     pose_json, pan, tilt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    inspection_id,
                    waypoint["id"],
                    waypoint["zone"],
                    _now(),
                    media_path,
                    json.dumps(pose) if pose else None,
                    waypoint["pan"],
                    waypoint["tilt"],
                ),
            )
        return self.get_capture(capture_id)

    def get_capture(self, capture_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM inspection_captures WHERE id = ?", (capture_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Capture introuvable")
        capture = dict(row)
        pose_json = capture.pop("pose_json")
        capture["pose"] = json.loads(pose_json) if pose_json else None
        return capture

    def get_inspection(self, inspection_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT i.*, v.registration, v.label, r.name AS route_name, r.map_name
                FROM vehicle_inspections i
                JOIN vehicles v ON v.id = i.vehicle_id
                JOIN inspection_routes r ON r.id = i.route_id
                WHERE i.id = ?
                """,
                (inspection_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Inspection introuvable")
            inspection = dict(row)
            captures = connection.execute(
                "SELECT id FROM inspection_captures WHERE inspection_id = ? ORDER BY captured_at",
                (inspection_id,),
            ).fetchall()
        inspection["captures"] = [self.get_capture(item["id"]) for item in captures]
        return inspection

    def list_inspections(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.*, v.registration, v.label, r.name AS route_name, r.map_name,
                       COUNT(c.id) AS capture_count
                FROM vehicle_inspections i
                JOIN vehicles v ON v.id = i.vehicle_id
                JOIN inspection_routes r ON r.id = i.route_id
                LEFT JOIN inspection_captures c ON c.inspection_id = i.id
                GROUP BY i.id
                ORDER BY i.started_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
