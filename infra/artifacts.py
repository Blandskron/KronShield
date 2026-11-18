"""Publish complete report files under generated names."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


def publish_report(content: str, extension: str) -> Path:
    if extension not in {"html", "json"}:
        raise ValueError("Unsupported report extension")
    directory = Path.cwd().resolve() / "results"
    directory.mkdir(exist_ok=True)
    if directory.resolve(strict=True) != directory:
        raise ValueError("The results directory must be a local directory in the workspace")

    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=directory, prefix=".report-", delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        for _ in range(8):
            name = f"report-{uuid4().hex}.{extension}"
            try:
                # Publish the complete inode without replacing a name another
                # process already owns, including symbolic links.
                os.link(temporary, directory / name)
            except FileExistsError:
                continue
            return Path("results") / name
        raise FileExistsError("Could not allocate a unique report name")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
