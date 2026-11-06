"""Resolve prediction artifacts that still name a container mount path.

A packager that runs inside a container writes absolute artifact paths below its
run mount (for example ``/sure-output/predictions/audio/...``). The published
bundle keeps those paths in the prediction files because the prediction text and
its structured projection are part of the prediction identity, and records the
mount-to-host mapping in ``artifact_path_localization.json`` instead.

Host-side validation and evaluation therefore translate a missing container path
through that evidence. Nothing here rewrites a bundle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCALIZATION_SCHEMA = "sure.eval.artifact_path_localization.v1"
RUNTIME_MANIFEST = "prediction_reuse_manifest.json"
MAPPING_FILENAME = "artifact_path_localization.json"
SEARCH_DEPTH = 3


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _mapping(bundle_root: Path) -> tuple[str, str] | None:
    evidence = _read_object(bundle_root / MAPPING_FILENAME)
    if evidence is None or evidence.get("schema") != LOCALIZATION_SCHEMA:
        return None
    container = str(evidence.get("container_run_dir") or "").strip()
    published = str(evidence.get("published_run_dir") or "").strip()
    if not container or not published:
        return None
    return (container.rstrip("/") or "/", published)


def _source_results_dir(bundle_root: Path) -> str | None:
    manifest = _read_object(bundle_root / RUNTIME_MANIFEST)
    if manifest is None:
        return None
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    for value in (source.get("source_results_dir"), manifest.get("source_results_dir")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def mappings(base_dir: Path | None) -> list[tuple[str, str]]:
    """Return container-to-host mappings visible from ``base_dir``."""
    if base_dir is None:
        return []
    found: list[tuple[str, str]] = []
    current: Path | None = Path(base_dir)
    for _ in range(SEARCH_DEPTH):
        if current is None:
            break
        candidates = [current]
        source_dir = _source_results_dir(current)
        if source_dir:
            candidates.append(Path(source_dir))
        for candidate in candidates:
            mapping = _mapping(candidate)
            if mapping is not None and mapping not in found:
                found.append(mapping)
        current = current.parent if current.parent != current else None
    return found


def primary_path(value: Any, base_dir: Path | None) -> Path:
    """Return the path as written, joined to ``base_dir`` when it is relative."""
    path = Path(str(value)).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def remapped_paths(value: Any, base_dir: Path | None) -> list[Path]:
    """Return the container-mount translations that apply to ``value``."""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        return []
    text = path.as_posix()
    translated: list[Path] = []
    for container, published in mappings(base_dir):
        if text != container and not text.startswith(f"{container}/"):
            continue
        if text != container:
            candidate = Path(published.rstrip("/") + text[len(container) :])
        else:
            candidate = Path(published)
        if candidate not in translated:
            translated.append(candidate)
    return translated


def resolve_existing(value: Any, base_dir: Path | None) -> Path | None:
    """Return the first existing candidate for ``value``, or ``None``."""
    for candidate in [primary_path(value, base_dir), *remapped_paths(value, base_dir)]:
        if candidate.exists():
            return candidate
    return None
