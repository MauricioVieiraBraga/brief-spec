from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from briefspec.config import briefspec_home
from briefspec.models import Runtime, SessionState


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.chmod(0o700)


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    _private_dir(path.parent)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _session_key(runtime: Runtime, session_id: str) -> str:
    raw = f"{runtime.value}\0{session_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def session_path(runtime: Runtime, session_id: str) -> Path:
    return briefspec_home() / "sessions" / _session_key(runtime, session_id) / "state.json"


@contextmanager
def session_lock(runtime: Runtime, session_id: str, timeout: float = 1.5) -> Iterator[None]:
    lock_dir = briefspec_home() / "locks"
    _private_dir(lock_dir)
    lock_path = lock_dir / f"{_session_key(runtime, session_id)}.lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring session lock: {lock_path.name}") from None
            time.sleep(0.025)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def load_session(runtime: Runtime, session_id: str, now: datetime) -> SessionState:
    path = session_path(runtime, session_id)
    if not path.exists():
        return SessionState.new(runtime, session_id, now)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state root is not an object")
        return SessionState.from_dict(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        quarantine = path.with_name(f"state.corrupt.{int(time.time())}.json")
        with suppress(OSError):
            path.replace(quarantine)
        return SessionState.new(runtime, session_id, now)


def save_session(state: SessionState) -> None:
    content = json.dumps(state.to_dict(), indent=2, sort_keys=True).encode() + b"\n"
    atomic_write(session_path(Runtime(state.runtime), state.session_id), content)


def list_sessions() -> list[dict[str, Any]]:
    root = briefspec_home() / "sessions"
    results: list[dict[str, Any]] = []
    if not root.exists():
        return results
    for path in sorted(root.glob("*/state.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                results.append(value)
        except (OSError, json.JSONDecodeError):
            continue
    return results


def reset_session(runtime: Runtime, session_id: str) -> bool:
    path = session_path(runtime, session_id)
    if not path.exists():
        return False
    path.unlink()
    with suppress(OSError):
        path.parent.rmdir()
    return True


def prune_sessions(days: int, dry_run: bool = False, now: datetime | None = None) -> list[Path]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    removed: list[Path] = []
    root = briefspec_home() / "sessions"
    if not root.exists():
        return removed
    for path in root.glob("*/state.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(str(value["updated_at"]))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            updated = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if updated < cutoff:
            removed.append(path)
            if not dry_run:
                path.unlink(missing_ok=True)
                with suppress(OSError):
                    path.parent.rmdir()
    return removed
