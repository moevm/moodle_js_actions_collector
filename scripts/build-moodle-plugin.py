#!/usr/bin/env python3
"""Package the Moodle plugin and shared tracker using only the Python stdlib."""

from __future__ import annotations

import argparse
import logging
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "version.php",
    "settings.php",
    "db/hooks.php",
    "classes/hook_callbacks.php",
    "lang/en/local_actioncollector.php",
)


def collect_sources(project_root: Path) -> list[tuple[Path, str]]:
    plugin_root = project_root / "moodle/local/actioncollector"
    tracker = project_root / "stat_tracker/collector.js"
    for path in [tracker, *(plugin_root / name for name in REQUIRED_FILES)]:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular source file: {path}")

    sources: list[tuple[Path, str]] = []
    for path in sorted(plugin_root.rglob("*")):
        relative = path.relative_to(plugin_root)
        if any(part.startswith(".") or part in {"tests", "node_modules", "__pycache__"}
               for part in relative.parts):
            continue
        if relative.as_posix() in {"playground.php", "collector.js"}:
            continue
        if "Zone.Identifier" in path.name or path.suffix in {".zip", ".tar", ".gz", ".pyc"}:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks are not supported in plugin sources: {path}")
        if path.is_file():
            sources.append((path, f"actioncollector/{relative.as_posix()}"))
    sources.append((tracker, "actioncollector/collector.js"))
    return sources


def build_plugin(project_root: Path, output: Path) -> int:
    sources = collect_sources(project_root)
    if output.suffix.lower() != ".zip":
        raise ValueError("Output path must end in .zip")
    if output in {source.resolve() for source, _ in sources}:
        raise ValueError("Output must not replace a source file")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Build next to the destination, then publish atomically. A failed build
    # leaves any previously built archive intact.
    with TemporaryDirectory(prefix=".actioncollector-", dir=output.parent) as staging:
        archive_path = Path(staging) / "plugin.zip"
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for source, name in sources:
                info = ZipInfo(name)
                info.create_system = 3
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, source.read_bytes())
        with ZipFile(archive_path) as archive:
            damaged = archive.testzip()
            if damaged is not None:
                raise BadZipFile(f"Archive verification failed: {damaged}")
        os.replace(archive_path, output)
    return len(sources)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "dist/local_actioncollector.zip",
        help="Destination ZIP (default: dist/local_actioncollector.zip in the project)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        output = args.output.expanduser().resolve()
        count = build_plugin(PROJECT_ROOT, output)
    except (OSError, ValueError, BadZipFile) as error:
        LOGGER.error("Plugin build failed: %s", error)
        return 1
    LOGGER.info("Plugin ZIP: %s (%d files)", output, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
