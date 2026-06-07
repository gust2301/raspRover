"""Endpoints réseau : statut Wi-Fi, scan et connexion via nmcli."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess

from fastapi import APIRouter
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/network", tags=["network"])

_IFACE = "wlan0"


def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _nmcli_status() -> dict:
    """Retourne connected, ssid, ipAddress via nmcli."""
    try:
        r = _run(
            [
                "nmcli",
                "-t",
                "-f",
                "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
                "dev",
                "show",
                _IFACE,
            ]
        )
        state_line = next(
            (line for line in r.stdout.splitlines() if line.startswith("GENERAL.STATE")), ""
        )
        conn_line = next(
            (line for line in r.stdout.splitlines() if line.startswith("GENERAL.CONNECTION")), ""
        )
        ip_line = next(
            (line for line in r.stdout.splitlines() if line.startswith("IP4.ADDRESS")), ""
        )

        connected = "100" in state_line
        ssid = conn_line.split(":", 1)[1].strip() if ":" in conn_line else None
        ip_raw = ip_line.split(":", 1)[1].strip() if ":" in ip_line else None
        ip_address = ip_raw.split("/")[0] if ip_raw else None

        return {"connected": connected, "ssid": ssid or None, "ipAddress": ip_address}
    except Exception as exc:
        log.warning("nmcli status failed: %s", exc)
        return {"connected": False, "ssid": None, "ipAddress": None}


def _nmcli_scan() -> list[dict]:
    """Retourne la liste des réseaux Wi-Fi détectés."""
    try:
        r = _run(
            [
                "nmcli",
                "--terse",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "dev",
                "wifi",
                "list",
                "--rescan",
                "yes",
            ],
            timeout=20.0,
        )
        networks: list[dict] = []
        seen: set[str] = set()
        for line in r.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            ssid, signal_str, security = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                signal = int(signal_str)
            except ValueError:
                signal = 0
            networks.append(
                {
                    "ssid": ssid,
                    "signal": signal,
                    "security": security if security and security != "--" else None,
                }
            )
        networks.sort(key=lambda n: n["signal"], reverse=True)
        return networks
    except Exception as exc:
        log.warning("nmcli scan failed: %s", exc)
        raise


def _nmcli_connect(ssid: str, password: str) -> dict:
    """Lance nmcli dev wifi connect et retourne le résultat."""
    try:
        r = _run(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
            timeout=30.0,
        )
        success = r.returncode == 0
        message = r.stdout.strip() or r.stderr.strip() or ("Connecté" if success else "Échec")
        new_ip: str | None = None
        if success:
            ip_r = _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", _IFACE])
            ip_line = next(
                (line for line in ip_r.stdout.splitlines() if line.startswith("IP4.ADDRESS")), ""
            )
            ip_raw = ip_line.split(":", 1)[1].strip() if ":" in ip_line else None
            new_ip = ip_raw.split("/")[0] if ip_raw else None
        return {"success": success, "message": message, "newIpAddress": new_ip}
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "Timeout — vérifiez le SSID et le mot de passe.",
            "newIpAddress": None,
        }
    except Exception as exc:
        log.warning("nmcli connect failed: %s", exc)
        return {"success": False, "message": str(exc), "newIpAddress": None}


@router.get("/status")
async def network_status() -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _nmcli_status)


@router.get("/wifi/scan")
async def wifi_scan() -> list | dict:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _nmcli_scan)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/wifi/connect")
async def wifi_connect(body: dict) -> dict:
    ssid: str | None = body.get("ssid")
    password: str | None = body.get("password")
    if not ssid:
        return JSONResponse(status_code=400, content={"error": "ssid requis"})
    if password is None:
        return JSONResponse(status_code=400, content={"error": "password requis"})
    # Reject obviously malicious chars (newline, semicolon) — nmcli takes args as list so shell injection is already avoided
    if re.search(r"[\r\n;`$|&]", ssid + password):
        return JSONResponse(
            status_code=400, content={"error": "Caractères non autorisés dans SSID ou mot de passe"}
        )
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _nmcli_connect(ssid, password))
    status_code = 200 if result["success"] else 502
    return JSONResponse(status_code=status_code, content=result)
