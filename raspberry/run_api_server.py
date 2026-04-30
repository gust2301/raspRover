"""Point d'entrée — lance le serveur API RaspRover avec uvicorn."""

from __future__ import annotations

import argparse
import logging
import pathlib

import yaml

CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def parse_args() -> argparse.Namespace:
    cfg = _load_config().get("api", {})
    parser = argparse.ArgumentParser(description="Serveur API RaspRover")
    parser.add_argument("--host", default=cfg.get("host", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=cfg.get("port", 8080))
    parser.add_argument("--reload", action="store_true", help="Rechargement auto (dev)")
    parser.add_argument("--log-level", default="info")
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    logging.basicConfig(level=args.log_level.upper())

    uvicorn.run(
        "modules.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
