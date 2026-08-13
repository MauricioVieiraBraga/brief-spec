from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any, Protocol


class Renderer(Protocol):
    name: str
    media_type: str
    filename: str

    def capabilities(self) -> dict[str, Any]: ...

    def render(
        self,
        delivery: dict[str, Any],
        output: Path,
        options: dict[str, Any],
    ) -> dict[str, Any]: ...

    def verify(self, artifact: Path) -> dict[str, Any]: ...


def available_renderers() -> dict[str, Renderer]:
    discovered: dict[str, Renderer] = {}
    entry_points = metadata.entry_points()
    for group in ("briefspec.renderers", "brief_spec.renderers"):
        candidates = (
            entry_points.select(group=group)
            if hasattr(entry_points, "select")
            else entry_points.get(group, ())
        )
        for entry_point in candidates:
            factory = entry_point.load()
            renderer = factory() if isinstance(factory, type) else factory
            discovered[str(renderer.name)] = renderer
    return discovered


def render_with_plugin(
    name: str,
    delivery: dict[str, Any],
    output_dir: Path,
    *,
    force: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    renderer = available_renderers().get(name)
    if renderer is None:
        raise ValueError(
            f"Renderer {name!r} is not installed. Install the matching Brief-Spec renderer package."
        )
    output = output_dir / renderer.filename
    if output.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return renderer.render(delivery, output, options or {})


def renderer_capabilities() -> list[dict[str, Any]]:
    return [
        {"name": name, **renderer.capabilities()}
        for name, renderer in sorted(available_renderers().items())
    ]


def setup_renderers(*, dry_run: bool = False) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, renderer in sorted(available_renderers().items()):
        setup = getattr(renderer, "setup", None)
        if setup is None:
            results.append({"renderer": name, "status": "PASS", "detail": "no setup required"})
            continue
        result = setup(dry_run=dry_run)
        results.append({"renderer": name, **result})
    return results
