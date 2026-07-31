from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

from briefspec.state import atomic_write

_SKIP_PARTS = {"__pycache__", "resources"}


def build_zipapp(destination: Path) -> str:
    """Build a deterministic, stdlib-only BriefSpec zipapp."""
    package_root = Path(__file__).resolve().parent
    files: list[tuple[Path, str]] = []
    for path in package_root.rglob("*"):
        if not path.is_file() or any(part in _SKIP_PARTS for part in path.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(package_root)
        files.append((path, f"briefspec/{relative.as_posix()}"))

    main = b"from briefspec.cli import main\nraise SystemExit(main())\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=".briefspec.",
        suffix=".pyz",
        dir=destination.parent,
    )
    os.close(descriptor)
    temp = Path(raw_temp)
    try:
        with zipfile.ZipFile(
            temp,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            main_info = zipfile.ZipInfo("__main__.py", date_time=(1980, 1, 1, 0, 0, 0))
            main_info.external_attr = 0o644 << 16
            archive.writestr(main_info, main)
            for source, archive_name in sorted(files, key=lambda item: item[1]):
                info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                archive.writestr(info, source.read_bytes())
        payload = temp.read_bytes()
        atomic_write(destination, payload, mode=0o700)
    finally:
        temp.unlink(missing_ok=True)
    return hashlib.sha256(destination.read_bytes()).hexdigest()
