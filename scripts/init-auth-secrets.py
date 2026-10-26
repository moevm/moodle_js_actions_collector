#!/usr/bin/env python3
"""Initialize missing authentication secrets in .env without printing them."""

from __future__ import annotations

import argparse
import logging
import os
import re
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parents[1]
KEYS = ("COLLECTOR_AUTH_SECRET", "COLLECTOR_INGEST_KEY")
LOGGER = logging.getLogger(__name__)


def initialize(env_file: Path, example_file: Path) -> bool:
    existing = env_file.exists()
    original = (env_file if existing else example_file).read_bytes().decode("utf-8")
    lines = original.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in original else "\n"
    changed = not existing
    for key in KEYS:
        pattern = re.compile(rf"^\s*(?:export\s+)?{key}\s*=(.*)$")
        matches = [(i, match) for i, line in enumerate(lines) if (match := pattern.match(line.rstrip("\r\n")))]
        if len(matches) > 1:
            raise ValueError(f"Duplicate {key} definitions; keep one definition before retrying")
        if matches:
            index, match = matches[0]
            value = match[1].split("#", 1)[0].strip()
            if value not in {"", "''", '\"\"'}:
                continue
            lines[index] = f"{key}={secrets.token_urlsafe(32)}{newline}"
        else:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.append(f"{key}={secrets.token_urlsafe(32)}{newline}")
        changed = True
    if not changed:
        return False

    env_file.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile("wb", prefix=".collector-env-", dir=env_file.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write("".join(lines).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, env_file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        changed = initialize(args.env_file.resolve(), ROOT / ".env.example")
    except (OSError, ValueError, UnicodeError) as error:
        LOGGER.error("Could not initialize authentication settings: %s", error)
        return 1
    LOGGER.info("Authentication settings initialized." if changed else "Existing authentication settings preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
