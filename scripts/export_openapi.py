"""Write the API's OpenAPI schema to a file without starting the server (Phase 8).

    .venv/bin/python scripts/export_openapi.py frontend/openapi.json

The frontend generates its TypeScript types from this file (cd frontend && npm run gen:api). The app is built with
placeholder dependencies: building the schema needs no MongoDB, S3 or Kafka.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

from ekyc import config


def main(out: str) -> None:
    os.environ["EKYC_API_NO_AUTOCREATE"] = "1"
    spec = importlib.util.spec_from_file_location("ekyc_api_app", config.PROJECT_ROOT / "services" / "api" / "app.py")
    api = importlib.util.module_from_spec(spec)
    sys.modules["ekyc_api_app"] = api
    spec.loader.exec_module(api)
    app = api.create_app(db=object(), s3=object(), producer=object(), seed={},
                         api_config=api.ApiConfig(jwt_secret="schema-export-only"))
    path = Path(out)
    path.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path} ({len(app.openapi()['paths'])} paths, {len(app.openapi()['components']['schemas'])} schemas)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
