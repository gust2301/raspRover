"""Client Cloudflare R2 via boto3 (S3-compatible)."""

from __future__ import annotations

import io
import logging
import pathlib

import yaml

log = logging.getLogger(__name__)

CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config.yaml"


def _load_r2_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("storage", {}).get("r2", {})


class R2Client:
    def __init__(self) -> None:
        cfg = _load_r2_config()
        endpoint = cfg.get("endpoint_url", "").strip()
        access_key = cfg.get("access_key_id", "").strip()
        secret_key = cfg.get("secret_access_key", "").strip()
        self._bucket = cfg.get("bucket_name", "rasprover-media")
        self._expiry = int(cfg.get("presigned_url_expiry_s", 3600))
        self._client = None

        if not all([endpoint, access_key, secret_key]):
            log.info("R2 non configuré — stockage désactivé")
            return

        try:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4"),
                region_name="auto",
            )
            log.info("R2Client initialisé (bucket=%s)", self._bucket)
        except Exception as exc:
            log.error("Impossible d'initialiser R2Client : %s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        assert self._client is not None
        self._client.upload_fileobj(
            io.BytesIO(data),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        log.info("R2 upload OK : %s (%d bytes)", key, len(data))

    def list_media(self, prefix: str = "") -> list[dict]:
        assert self._client is not None
        kwargs: dict = {"Bucket": self._bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        resp = self._client.list_objects_v2(**kwargs)
        items = []
        for obj in resp.get("Contents", []):
            key: str = obj["Key"]
            media_type = "photo" if key.endswith(".jpg") else "video"
            items.append(
                {
                    "key": key,
                    "url": self.presigned_url(key),
                    "type": media_type,
                    "size": obj["Size"],
                    "timestamp": obj["LastModified"].isoformat(),
                }
            )
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items

    def delete(self, key: str) -> None:
        assert self._client is not None
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def presigned_url(self, key: str) -> str:
        assert self._client is not None
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._expiry,
        )


_r2: R2Client | None = None


def get_r2_client() -> R2Client | None:
    global _r2
    if _r2 is None:
        _r2 = R2Client()
    return _r2 if _r2.available else None
