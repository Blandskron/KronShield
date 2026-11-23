"""Regenerate or check the versioned OpenAPI contract without an IdP or database."""

import argparse
import json
from base64 import b64encode
from pathlib import Path
from unittest.mock import Mock

from adapters.api.app import build_app
from adapters.api.auth import RequestAuth
from application.documents import DocumentCipher


def specification() -> dict:
    access = RequestAuth(Mock(), "https://app.example")
    cipher = DocumentCipher(b64encode(bytes(32)).decode())
    return build_app(access, Mock(), cipher=cipher).openapi()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = Path(__file__).with_name("openapi-v1.json")
    generated = json.dumps(specification(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if destination.read_text(encoding="utf-8") != generated:
            raise SystemExit("OpenAPI v1 drift. Review the contract before regenerating it.")
    else:
        destination.write_text(generated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
