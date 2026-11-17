"""Connection settings for Kafka, S3 and MongoDB, read from .env (and the process environment, which wins).
The same .env file feeds docker-compose.yml, so the containers and the host services agree."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import dotenv_values

from ekyc import config


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str = "localhost:9094"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "kyc-uploads"
    s3_region: str = "us-east-1"
    mongo_host: str = "localhost:27017"
    mongo_user: str = "ekyc"
    mongo_password: str = ""
    mongo_db: str = "ekyc"
    ollama_host: str = "http://localhost:11434"

    @property
    def mongo_uri(self) -> str:
        return f"mongodb://{quote_plus(self.mongo_user)}:{quote_plus(self.mongo_password)}@{self.mongo_host}/?authSource=admin"


def load_settings(env_file: Path = config.PROJECT_ROOT / ".env") -> Settings:
    values = {**dotenv_values(env_file), **os.environ}

    def get(name: str, default: str) -> str:
        return values.get(name) or default

    d = Settings()
    return Settings(kafka_bootstrap=get("KAFKA_BOOTSTRAP", d.kafka_bootstrap), s3_endpoint=get("S3_ENDPOINT", d.s3_endpoint),
                    s3_access_key=get("S3_ACCESS_KEY", ""), s3_secret_key=get("S3_SECRET_KEY", ""),
                    s3_bucket=get("S3_BUCKET", d.s3_bucket), s3_region=get("S3_REGION", d.s3_region),
                    mongo_host=get("MONGO_HOST", d.mongo_host), mongo_user=get("MONGO_ROOT_USER", d.mongo_user),
                    mongo_password=get("MONGO_ROOT_PASSWORD", ""), mongo_db=get("MONGO_DB", d.mongo_db),
                    ollama_host=get("OLLAMA_HOST", d.ollama_host))
