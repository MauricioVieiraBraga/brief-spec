from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from briefspec.delivery import (
    CORE_FORMATS,
    canonical_sha256,
    load_delivery,
    render_core,
    render_html,
    render_spoken_text,
    sha256_bytes,
    validate_delivery,
)
from briefspec.models import VerificationLevel
from briefspec.renderers import available_renderers

_LEVEL_ORDER = {
    VerificationLevel.STRUCTURAL: 0,
    VerificationLevel.RESOLVED: 1,
    VerificationLevel.RENDERED: 2,
    VerificationLevel.DELIVERED: 3,
}
_HTML_HASH = re.compile(r'<meta name="(?:brief-spec|briefspec)-sha256" content="([0-9a-f]{64})">')
_HTML_CANONICAL = re.compile(r"<pre>(.*?)</pre>", re.DOTALL)
_SOURCE_LOCATION = re.compile(r"^(?P<path>.+):(?P<line>\d+)(?::(?P<column>\d+))?$")


def _check(checks: list[dict[str, Any]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def _inside(path: Path, workspace: Path) -> bool:
    try:
        path.relative_to(workspace)
    except ValueError:
        return False
    return True


def _source_path(locator: str) -> Path:
    """Accept the common path:line[:column] evidence locator without losing file identity."""
    candidate = Path(locator).expanduser()
    match = _SOURCE_LOCATION.fullmatch(locator)
    if match and not candidate.exists():
        return Path(match.group("path")).expanduser()
    return candidate


def _delivery_from_target(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    try:
        delivery, warnings = load_delivery(path.read_text(encoding="utf-8"), source_path=path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _check(checks, "structure", "FAIL", str(exc))
        return None, checks
    validation = validate_delivery(delivery)
    _check(
        checks,
        "structure",
        "PASS" if validation.valid else "FAIL",
        "canonical delivery is valid" if validation.valid else "; ".join(validation.errors),
    )
    for warning in (*warnings, *validation.warnings):
        _check(checks, "quality warning", "WARN", warning)
    return delivery, checks


def _verify_html(path: Path, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _check(checks, "HTML readability", "FAIL", str(exc))
        return None
    required_csp = ("default-src 'none'", "base-uri 'none'", "form-action 'none'")
    if (
        "Content-Security-Policy" not in content
        or not all(directive in content for directive in required_csp)
        or "<main" not in content
        or "<h1" not in content
    ):
        _check(checks, "HTML semantics", "FAIL", "CSP or semantic landmarks are missing")
        return None
    if re.search(r'<(?:script|link)\b[^>]*(?:src|href)=["\']https?://', content, re.I):
        _check(checks, "HTML offline", "FAIL", "external script or stylesheet reference found")
    else:
        _check(checks, "HTML offline", "PASS", "no external script or stylesheet references")
    hash_match = _HTML_HASH.search(content)
    canonical_match = _HTML_CANONICAL.search(content)
    if hash_match is None or canonical_match is None:
        _check(checks, "HTML integrity", "FAIL", "embedded canonical JSON or hash is missing")
        return None
    try:
        delivery = json.loads(html.unescape(canonical_match.group(1)))
    except json.JSONDecodeError as exc:
        _check(checks, "HTML integrity", "FAIL", f"embedded canonical JSON is invalid: {exc}")
        return None
    actual = canonical_sha256(delivery)
    declared = hash_match.group(1)
    _check(
        checks,
        "HTML integrity",
        "PASS" if actual == declared else "FAIL",
        f"canonical sha256 {actual}",
    )
    return delivery


def _verify_bundle(
    path: Path,
    checks: list[dict[str, Any]],
    *,
    rendered: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    delivery: dict[str, Any] | None = None
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "manifest.json" not in names:
                raise ValueError("manifest.json is missing")
            manifest = json.loads(archive.read("manifest.json"))
            expected_names = sorted(item["path"] for item in manifest.get("files", []))
            actual_names = sorted(name for name in names if name != "manifest.json")
            if expected_names != actual_names:
                raise ValueError("bundle contents do not match manifest")
            for item in manifest.get("files", []):
                content = archive.read(item["path"])
                if len(content) != item["size_bytes"]:
                    raise ValueError(f"size mismatch: {item['path']}")
                if sha256_bytes(content) != item["sha256"]:
                    raise ValueError(f"hash mismatch: {item['path']}")
            if "brief.json" in names:
                candidate = json.loads(archive.read("brief.json"))
                validation = validate_delivery(candidate)
                if not validation.valid:
                    raise ValueError(
                        "canonical delivery is invalid: " + "; ".join(validation.errors)
                    )
                if canonical_sha256(candidate) != manifest.get("canonical_sha256"):
                    raise ValueError("canonical delivery hash does not match manifest")
                delivery = candidate
                for output_format, (filename, _) in CORE_FORMATS.items():
                    if filename in names and archive.read(filename) != render_core(
                        delivery, output_format
                    ):
                        raise ValueError(
                            f"{filename} is not the deterministic rendering of brief.json"
                        )
            if rendered and "brief.html" in names:
                rendered_html = archive.read("brief.html").decode("utf-8")
                if not all(
                    directive in rendered_html
                    for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'")
                ):
                    raise ValueError("HTML content security policy is not restrictive")
                declared = _HTML_HASH.search(rendered_html)
                embedded = _HTML_CANONICAL.search(rendered_html)
                if declared is None or embedded is None:
                    raise ValueError("HTML canonical payload or hash is missing")
                html_delivery = json.loads(html.unescape(embedded.group(1)))
                if canonical_sha256(html_delivery) != declared.group(1):
                    raise ValueError("HTML canonical hash mismatch")
                if delivery is not None and html_delivery != delivery:
                    raise ValueError("HTML and JSON canonical deliveries differ")
                if re.search(
                    r'<(?:script|link)\b[^>]*(?:src|href)=["\']https?://',
                    rendered_html,
                    re.I,
                ):
                    raise ValueError("HTML contains an external script or stylesheet")
            if rendered:
                installed = available_renderers()
                for member, renderer_name in (("brief.pdf", "pdf"), ("brief.mp3", "audio")):
                    if member in names and renderer_name not in installed:
                        raise ValueError(f"{renderer_name} renderer is required to verify {member}")
                with tempfile.TemporaryDirectory(prefix="briefspec-bundle-verify-") as temporary:
                    root = Path(temporary)
                    for name, renderer in installed.items():
                        member = renderer.filename
                        if member not in names:
                            continue
                        artifact = root / member
                        artifact.write_bytes(archive.read(member))
                        result = renderer.verify(artifact)
                        if result.get("status") != "PASS":
                            raise ValueError(
                                f"{name} verification failed: {result.get('detail', 'unknown')}"
                            )
                        record = next(
                            item for item in manifest["files"] if item.get("path") == member
                        )
                        metadata = record.get("metadata", {})
                        if name == "pdf":
                            expected = sha256_bytes(render_html(delivery).encode("utf-8"))
                            if metadata.get("source_html_sha256") != expected:
                                raise ValueError("PDF source HTML hash does not match brief.json")
                            if metadata.get("visual_sha256") != result.get("visual_sha256"):
                                raise ValueError("PDF rendered-page hash does not match manifest")
                        if name == "audio":
                            expected = sha256_bytes(
                                render_spoken_text(delivery).strip().encode("utf-8")
                            )
                            if metadata.get("source_script_sha256") != expected:
                                raise ValueError(
                                    "audio source Script hash does not match brief.json"
                                )
                            if metadata.get("ai_generated") is not True:
                                raise ValueError("audio AI-generated disclosure is missing")
    except (
        OSError,
        KeyError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        _check(checks, "bundle manifest", "FAIL", str(exc))
        return None, None
    _check(checks, "bundle manifest", "PASS", f"verified {len(expected_names)} file(s)")
    return manifest, delivery


def _resolve_delivery(
    delivery: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    workspace: Path,
    offline: bool,
    allow_outside_workspace: bool,
) -> None:
    evidence = delivery.get("brief", {}).get("proof", [])
    references = [item for item in evidence if isinstance(item, dict)]
    references.extend(item for item in delivery.get("provenance", []) if isinstance(item, dict))
    references.extend(item for item in delivery.get("artifacts", []) if isinstance(item, dict))
    now = datetime.now(UTC)
    for index, item in enumerate(references, start=1):
        locator = str(item.get("locator", ""))
        inferred_kind = "url" if locator.startswith(("https://", "http://")) else "observation"
        kind = str(item.get("kind") or ("artifact" if "artifact_id" in item else inferred_kind))
        expires_at = item.get("expires_at")
        if expires_at:
            try:
                expired = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) < now
            except ValueError:
                _check(checks, f"reference {index}", "FAIL", "invalid expiry timestamp")
                continue
            if expired:
                _check(checks, f"reference {index}", "FAIL", f"expired artifact: {locator}")
                continue
        if kind in {"file", "artifact"}:
            candidate = _source_path(locator)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            resolved = candidate.resolve(strict=False)
            if not allow_outside_workspace and not _inside(resolved, workspace):
                _check(checks, f"reference {index}", "FAIL", f"path escapes workspace: {locator}")
                continue
            if not resolved.is_file():
                _check(checks, f"reference {index}", "FAIL", f"file not found: {locator}")
                continue
            declared = item.get("sha256")
            actual = sha256_bytes(resolved.read_bytes())
            if declared and declared != actual:
                _check(checks, f"reference {index}", "FAIL", f"hash mismatch: {locator}")
            else:
                _check(checks, f"reference {index}", "PASS", f"file resolved: {locator}")
        elif kind == "commit":
            result = subprocess.run(
                ["git", "cat-file", "-e", f"{locator}^{{commit}}"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            _check(
                checks,
                f"reference {index}",
                "PASS" if result.returncode == 0 else "FAIL",
                f"commit {'resolved' if result.returncode == 0 else 'missing'}: {locator}",
            )
        elif kind == "url":
            if item.get("access") == "private":
                _check(
                    checks,
                    f"reference {index}",
                    "WARN",
                    f"private URL requires authorized access; unresolved: {locator}",
                )
                continue
            if offline:
                _check(checks, f"reference {index}", "WARN", f"offline; URL unresolved: {locator}")
                continue
            try:
                request = urllib.request.Request(locator, method="HEAD")
                with urllib.request.urlopen(request, timeout=10) as response:
                    status = int(response.status)
                if status >= 400:
                    raise urllib.error.HTTPError(locator, status, "unavailable", {}, None)
            except (OSError, ValueError, urllib.error.URLError) as exc:
                _check(checks, f"reference {index}", "FAIL", f"URL unresolved: {exc}")
            else:
                _check(checks, f"reference {index}", "PASS", f"URL resolved: {locator}")
        elif kind == "command":
            _check(checks, f"reference {index}", "WARN", "command evidence is never executed")
        else:
            _check(checks, f"reference {index}", "WARN", f"unresolved {kind}: {locator}")


def _verify_receipt(path: Path, checks: list[dict[str, Any]]) -> None:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("kind") not in {
            "brief-spec-delivery-receipt",
            "briefspec-delivery-receipt",
        }:
            raise ValueError("not a Brief-Spec delivery receipt")
        if receipt.get("status") != "delivered" or not receipt.get("delivered_at"):
            raise ValueError("receipt is not delivered")
        locator = receipt["destination"]["locator"]
        destination = Path(locator)
        if not destination.is_file():
            raise ValueError(f"delivered file is missing: {destination}")
        actual = sha256_bytes(destination.read_bytes())
        if actual != receipt.get("content_sha256"):
            raise ValueError("delivered content hash does not match receipt")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _check(checks, "delivery receipt", "FAIL", str(exc))
        return
    _check(checks, "delivery receipt", "PASS", f"delivered content verified: {destination}")


def verify_bundle_integrity(target: Path) -> dict[str, Any]:
    """Verify a bundle's manifest and deterministic renderings without resolving sources."""
    checks: list[dict[str, Any]] = []
    _verify_bundle(target.resolve(), checks, rendered=True)
    status = "FAIL" if any(item["status"] == "FAIL" for item in checks) else "PASS"
    return {"target": str(target.resolve()), "status": status, "checks": checks}


def verify_target(
    target: Path,
    *,
    level: VerificationLevel = VerificationLevel.STRUCTURAL,
    workspace: Path | None = None,
    offline: bool = False,
    allow_outside_workspace: bool = False,
) -> dict[str, Any]:
    target = target.resolve()
    workspace = (workspace or Path.cwd()).resolve()
    checks: list[dict[str, Any]] = []
    delivery: dict[str, Any] | None = None
    suffix = target.suffix.lower()
    if not target.is_file():
        _check(checks, "target", "FAIL", f"file does not exist: {target}")
    elif target.name.endswith(".receipt.json"):
        _verify_receipt(target, checks)
    elif suffix == ".zip":
        _, delivery = _verify_bundle(
            target,
            checks,
            rendered=_LEVEL_ORDER[level] >= _LEVEL_ORDER[VerificationLevel.RENDERED],
        )
    elif suffix == ".html":
        delivery = _verify_html(target, checks)
    elif suffix in {".pdf", ".mp3"}:
        renderer_name = "pdf" if suffix == ".pdf" else "audio"
        renderer = available_renderers().get(renderer_name)
        if renderer is None:
            _check(checks, "renderer", "FAIL", f"{renderer_name} renderer is not installed")
        else:
            result = renderer.verify(target)
            _check(
                checks,
                f"{renderer_name} render",
                str(result.get("status", "FAIL")),
                str(result.get("detail", "renderer returned no detail")),
            )
    else:
        delivery, parsed_checks = _delivery_from_target(target)
        checks.extend(parsed_checks)

    if delivery is not None and _LEVEL_ORDER[level] >= _LEVEL_ORDER[VerificationLevel.RESOLVED]:
        _resolve_delivery(
            delivery,
            checks,
            workspace=workspace,
            offline=offline,
            allow_outside_workspace=allow_outside_workspace,
        )
    if level is VerificationLevel.DELIVERED and not target.name.endswith(".receipt.json"):
        receipt = target.with_suffix(target.suffix + ".receipt.json")
        if receipt.is_file():
            _verify_receipt(receipt, checks)
        else:
            _check(checks, "delivery receipt", "FAIL", f"receipt not found: {receipt}")
    status = (
        "FAIL"
        if any(item["status"] == "FAIL" for item in checks)
        else ("WARN" if any(item["status"] == "WARN" for item in checks) else "PASS")
    )
    return {
        "target": str(target),
        "level": level.value,
        "status": status,
        "checks": checks,
    }
