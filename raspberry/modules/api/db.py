"""Journal SQLite des incidents — rétention configurable (défaut 7 jours)."""

from __future__ import annotations

import pathlib
import sqlite3
import threading
from datetime import datetime, timedelta

_DEFAULT_PATH = pathlib.Path.home() / ".rasprover" / "incidents.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def init_db(path: pathlib.Path = _DEFAULT_PATH) -> None:
    """Initialise la base et crée la table si absente. Nettoie les vieilles entrées."""
    global _conn
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,
            type      TEXT NOT NULL,
            severity  TEXT NOT NULL DEFAULT 'warning',
            details   TEXT,
            media_key TEXT
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS map_homes (
            map_name   TEXT PRIMARY KEY,
            x          REAL NOT NULL,
            y          REAL NOT NULL,
            yaw        REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    _conn.commit()
    cleanup_old()


def log_incident(
    type: str,
    severity: str = "warning",
    details: str | None = None,
    media_key: str | None = None,
) -> int:
    """Insère un incident. Retourne l'id généré."""
    if _conn is None:
        return -1
    ts = datetime.utcnow().isoformat(timespec="seconds")
    with _lock:
        cur = _conn.execute(
            "INSERT INTO incidents (ts, type, severity, details, media_key) VALUES (?,?,?,?,?)",
            (ts, type, severity, details, media_key),
        )
        _conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def update_media_key(incident_id: int, media_key: str) -> None:
    """Met à jour le lien média d'un incident après upload R2."""
    if _conn is None or incident_id < 0:
        return
    with _lock:
        _conn.execute(
            "UPDATE incidents SET media_key = ? WHERE id = ?",
            (media_key, incident_id),
        )
        _conn.commit()


def list_incidents(days: int = 7) -> list[dict]:
    """Retourne les incidents des N derniers jours, du plus récent au plus ancien."""
    if _conn is None:
        return []
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM incidents WHERE ts > ? ORDER BY ts DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_incidents_by_date(date_str: str) -> list[dict]:
    """Retourne les incidents d'une date précise (YYYY-MM-DD), du plus récent au plus ancien."""
    if _conn is None:
        return []
    date_from = f"{date_str}T00:00:00"
    date_to = f"{date_str}T23:59:59"
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM incidents WHERE ts >= ? AND ts <= ? ORDER BY ts DESC",
            (date_from, date_to),
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old(days: int = 7) -> int:
    """Supprime les incidents plus vieux que N jours. Retourne le nb de lignes supprimées."""
    if _conn is None:
        return 0
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
    with _lock:
        cur = _conn.execute("DELETE FROM incidents WHERE ts < ?", (cutoff,))
        _conn.commit()
        return cur.rowcount


def set_map_home(map_name: str, x: float, y: float, yaw: float) -> dict:
    """Create or replace the fixed home pose associated with a SLAM map."""
    if _conn is None:
        raise RuntimeError("Base SQLite non initialisée")
    updated_at = datetime.utcnow().isoformat(timespec="seconds")
    with _lock:
        _conn.execute(
            """
            INSERT INTO map_homes (map_name, x, y, yaw, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(map_name) DO UPDATE SET
                x = excluded.x,
                y = excluded.y,
                yaw = excluded.yaw,
                updated_at = excluded.updated_at
            """,
            (map_name, x, y, yaw, updated_at),
        )
        _conn.commit()
    return {"map_name": map_name, "x": x, "y": y, "yaw": yaw, "updated_at": updated_at}


def get_map_home(map_name: str) -> dict | None:
    """Return the fixed home pose for a map, if one was configured."""
    if _conn is None:
        return None
    with _lock:
        row = _conn.execute(
            "SELECT map_name, x, y, yaw, updated_at FROM map_homes WHERE map_name = ?",
            (map_name,),
        ).fetchone()
    return dict(row) if row else None


def delete_map_home(map_name: str) -> None:
    """Delete the home pose associated with a removed map."""
    if _conn is None:
        return
    with _lock:
        _conn.execute("DELETE FROM map_homes WHERE map_name = ?", (map_name,))
        _conn.commit()
