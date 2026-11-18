"""S3 object storage (RustFS locally; any S3-compatible store works) via boto3. Images live here; events only
carry their keys (claim-check pattern)."""

from __future__ import annotations

import boto3
from botocore.config import Config

from ekyc.messaging.settings import Settings, load_settings


def s3_client(settings: Settings | None = None, public: bool = False):
    """public=True: a client for presigning links that a BROWSER opens (S3_PUBLIC_ENDPOINT). Presigning needs no
    connection; the endpoint is part of the signed URL, so it must be the address the browser can reach."""
    s = settings or load_settings()
    endpoint = (s.s3_public_endpoint or s.s3_endpoint) if public else s.s3_endpoint
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=s.s3_access_key,
                        aws_secret_access_key=s.s3_secret_key, region_name=s.s3_region,
                        # path-style URLs (http://host:9000/bucket/key): local stores have no per-bucket DNS names;
                        # boto3's own retries are kept low because the worker has its own retry + DLQ logic
                        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2, "mode": "standard"},
                                      connect_timeout=5, read_timeout=30))


def upload_bytes(client, bucket: str, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def download_bytes(client, bucket: str, key: str) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()
