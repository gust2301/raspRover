"""Point d'entree - lance le serveur API RaspRover avec HTTP et proxy TLS optionnel."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import pathlib
import ssl
import subprocess
import tempfile
from typing import Any

import yaml

CONFIG_PATH = pathlib.Path(__file__).parent / "config.yaml"
DEFAULT_CERT_PATH = pathlib.Path("certs/rasprover.crt")
DEFAULT_KEY_PATH = pathlib.Path("certs/rasprover.key")
log = logging.getLogger(__name__)


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _resolve_path(path_str: str) -> pathlib.Path:
    path = pathlib.Path(path_str)
    if path.is_absolute():
        return path
    return CONFIG_PATH.parent / path


def _build_subject_alt_names(common_name: str, configured_sans: list[str]) -> list[str]:
    sans = list(configured_sans)
    if not sans:
        try:
            ipaddress.ip_address(common_name)
        except ValueError:
            sans.append(f"DNS:{common_name}")
        else:
            sans.append(f"IP:{common_name}")

        sans.extend(["DNS:localhost", "IP:127.0.0.1"])

    deduped: list[str] = []
    for san in sans:
        if san not in deduped:
            deduped.append(san)
    return deduped


def _generate_self_signed_certificate(
    cert_path: pathlib.Path,
    key_path: pathlib.Path,
    *,
    common_name: str,
    subject_alt_names: list[str],
) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    san_value = ", ".join(subject_alt_names)
    openssl_config = f"""
[req]
prompt = no
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = {common_name}

[v3_req]
subjectAltName = {san_value}
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
""".strip()

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".cnf", delete=False) as cfg_file:
        cfg_file.write(openssl_config)
        cfg_path = pathlib.Path(cfg_file.name)

    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-days",
                "3650",
                "-config",
                str(cfg_path),
                "-extensions",
                "v3_req",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("openssl est requis pour generer le certificat HTTPS") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "commande openssl echouee"
        raise RuntimeError(f"Generation du certificat HTTPS impossible: {stderr}") from exc
    finally:
        cfg_path.unlink(missing_ok=True)


def _ensure_tls_material(args: argparse.Namespace) -> tuple[pathlib.Path, pathlib.Path]:
    cert_path = _resolve_path(args.https_certfile)
    key_path = _resolve_path(args.https_keyfile)

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    if not args.https_auto_generate:
        raise RuntimeError(
            f"Certificat HTTPS manquant: {cert_path} / {key_path}. "
            "Fournissez-les ou activez la generation automatique."
        )

    subject_alt_names = _build_subject_alt_names(args.https_common_name, args.https_subject_alt_names)
    log.warning(
        "Generation d'un certificat auto-signe pour HTTPS (%s, SAN=%s). "
        "Il devra etre approuve sur les appareils clients.",
        args.https_common_name,
        ", ".join(subject_alt_names),
    )
    _generate_self_signed_certificate(
        cert_path,
        key_path,
        common_name=args.https_common_name,
        subject_alt_names=subject_alt_names,
    )
    return cert_path, key_path


async def _pipe_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, ssl.SSLError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_tls_proxy(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    target_host: str,
    target_port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(target_host, target_port)
    except OSError:
        client_writer.close()
        await client_writer.wait_closed()
        return

    tasks = [
        asyncio.create_task(_pipe_stream(client_reader, upstream_writer)),
        asyncio.create_task(_pipe_stream(upstream_reader, client_writer)),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.gather(*done, return_exceptions=True)


def parse_args() -> argparse.Namespace:
    cfg = _load_config()
    api_cfg = cfg.get("api", {})
    https_cfg = api_cfg.get("https", {})

    parser = argparse.ArgumentParser(description="Serveur API RaspRover")
    parser.add_argument("--host", default=api_cfg.get("host", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=api_cfg.get("port", 8080))
    parser.add_argument("--reload", action="store_true", help="Rechargement auto (dev)")
    parser.add_argument("--log-level", default=cfg.get("logging", {}).get("level", "info"))

    parser.add_argument(
        "--https-port",
        type=int,
        default=https_cfg.get("port", 8443),
        help="Port du proxy HTTPS/WSS",
    )
    parser.add_argument(
        "--disable-https",
        action="store_true",
        default=not https_cfg.get("enabled", True),
        help="Desactive le proxy HTTPS/WSS",
    )
    parser.add_argument(
        "--https-certfile",
        default=https_cfg.get("certfile", str(DEFAULT_CERT_PATH)),
        help="Chemin du certificat PEM",
    )
    parser.add_argument(
        "--https-keyfile",
        default=https_cfg.get("keyfile", str(DEFAULT_KEY_PATH)),
        help="Chemin de la cle privee PEM",
    )
    parser.add_argument(
        "--https-common-name",
        default=https_cfg.get("common_name", "localhost"),
        help="Common Name du certificat auto-signe",
    )
    parser.add_argument(
        "--https-san",
        action="append",
        dest="https_subject_alt_names",
        default=list(https_cfg.get("subject_alt_names", [])),
        help="Subject Alternative Name, ex: DNS:robot.local ou IP:192.168.1.121",
    )
    parser.add_argument(
        "--no-auto-generate-cert",
        action="store_true",
        default=not https_cfg.get("auto_generate", True),
        help="N'essaie pas de generer automatiquement un certificat auto-signe",
    )
    return parser.parse_args()


async def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn_config = uvicorn.Config(
        "modules.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    server = uvicorn.Server(uvicorn_config)

    if args.disable_https:
        await server.serve()
        return

    cert_path, key_path = _ensure_tls_material(args)

    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    tls_server = await asyncio.start_server(
        lambda reader, writer: _handle_tls_proxy(
            reader,
            writer,
            target_host="127.0.0.1",
            target_port=args.port,
        ),
        host=args.host,
        port=args.https_port,
        ssl=tls_context,
    )

    log.info("HTTPS/WSS actif sur %s:%s", args.host, args.https_port)

    async with tls_server:
        uvicorn_task = asyncio.create_task(server.serve())
        tls_task = asyncio.create_task(tls_server.serve_forever())
        done, pending = await asyncio.wait(
            [uvicorn_task, tls_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper())
    args.https_auto_generate = not args.no_auto_generate_cert
    asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
