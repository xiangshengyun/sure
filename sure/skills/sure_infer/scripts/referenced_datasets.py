#!/usr/bin/env python3
"""Resolve the source datasets that a requested dataset's selection manifest references.

/sure_infer mounts each requested dataset's own source root into the container. A
compose dataset's samples can read media that live in another site dataset, so the
manifest under ``<source_root>/extras/<version_id>/`` is read before the container
starts: every referenced dataset root is validated against the allowed source roots
and becomes one more read-only mount, while the canonical path recorded in the
manifest stays the path its samples use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Private on purpose: the allowed-root matching lives in one place. If that module
# renames or drops _match_source_root, this import breaks loudly instead of silently
# accepting roots the resolver would reject.
from sure_eval.datasets.source_resolver import _match_source_root, accepted_source_roots

MANIFEST_FIELD = "source_dataset_root"
MANIFEST_DIR = "extras"
MANIFEST_NAME = "selection_manifest.jsonl"


class ReferencedDatasetError(ValueError):
    """A selection manifest cannot be read, or declares a dataset that may not be mounted."""


def selection_manifest_path(source_root: str, version_id: str) -> Path:
    """The only manifest location read: ``<source_root>/extras/<version_id>/selection_manifest.jsonl``.

    Only the directory named after the resolved version is read; there is no fallback
    to ``extras/TEMP_VERSION``, so a missing file is reported rather than guessed at.
    """
    return Path(source_root) / MANIFEST_DIR / str(version_id) / MANIFEST_NAME


def _is_absolute(value: str) -> bool:
    # Manifests are written on POSIX, so a leading "/" is absolute even where the
    # launcher runs on Windows and Path("/x").is_absolute() says otherwise.
    return value.startswith("/") or Path(value).is_absolute()


def _read_manifest(manifest: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        handle = manifest.open("r", encoding="utf-8")
    except OSError as exc:
        raise ReferencedDatasetError(f"{manifest}: cannot be read ({exc})") from exc
    with handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReferencedDatasetError(f"{manifest}: line {line_no} is not valid JSON ({exc})") from exc
            if not isinstance(row, dict):
                raise ReferencedDatasetError(f"{manifest}: line {line_no} is not a JSON object")
            rows.append(row)
    return rows


def _validated_reference(declared: object, manifest: Path, allowed: dict[str, str]) -> tuple[str, str, str]:
    """Return the declared canonical root, its resolved host root, and the allowed root key."""
    value = str(declared or "").strip()
    if not value:
        raise ReferencedDatasetError(f"{manifest}: {MANIFEST_FIELD} is empty")
    if not _is_absolute(value):
        raise ReferencedDatasetError(f"{manifest}: {MANIFEST_FIELD} must be an absolute path, got {value!r}")
    resolved = Path(value).resolve()
    key, _ = _match_source_root(resolved, allowed)
    if key is None:
        listed = ", ".join(
            root if not name else f"{name}={root}" for name, root in sorted(allowed.items())
        )
        raise ReferencedDatasetError(
            f"{manifest}: {MANIFEST_FIELD} {value!r} is outside the configured allowed_source_roots "
            f"({listed or 'none'})"
        )
    if not resolved.is_dir():
        raise ReferencedDatasetError(
            f"{manifest}: referenced source dataset {value!r} is not an existing directory"
        )
    return value, str(resolved), key


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def collect_referenced_datasets(
    datasets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Read every requested dataset's selection manifest.

    Returns one deduplicated reference per canonical root, ordered by that root, and
    per dataset name what its manifest said. A dataset without a source root or a
    version has no manifest to read, so it gets no report and no mount.
    """
    allowed = accepted_source_roots()
    references: dict[tuple[str, str], dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    for item in datasets:
        name = str(item.get("name") or "")
        source_root = str(item.get("source_root") or "").strip()
        version_id = str(item.get("version_id") or "").strip()
        if not name or not source_root or not version_id:
            continue
        manifest = selection_manifest_path(source_root, version_id)
        report: dict[str, Any] = {"path": str(manifest), "requested_version": version_id, "status": "absent"}
        if manifest.is_file():
            rows = _read_manifest(manifest)
            declared = [str(row.get(MANIFEST_FIELD) or "").strip() for row in rows]
            recorded = [value for value in declared if value]
            if recorded and len(recorded) != len(declared):
                raise ReferencedDatasetError(
                    f"{manifest}: {len(declared) - len(recorded)} of {len(declared)} rows carry no "
                    f"{MANIFEST_FIELD}; a manifest records it on every row or on none"
                )
            report["rows"] = len(rows)
            # Many rows name the same dataset, and two spellings can resolve to the same
            # host root, so validate once per spelling and group the identity fields by
            # canonical root while the rows are read.
            resolved: dict[str, dict[str, Any]] = {}
            checked: dict[str, tuple[str, str, str]] = {}
            for row, value in zip(rows, declared):
                if not value:
                    continue
                if value not in checked:
                    checked[value] = _validated_reference(value, manifest, allowed)
                canonical, host_root, key = checked[value]
                group = resolved.get(canonical)
                if group is None:
                    group = {
                        "host_root": host_root,
                        "source_root_key": key,
                        "source_ds_ids": [],
                        "source_versions": [],
                    }
                    resolved[canonical] = group
                for field, target in (("source_ds_id", "source_ds_ids"), ("source_version", "source_versions")):
                    identity = str(row.get(field) or "").strip()
                    if identity:
                        _append_unique(group[target], identity)
            report["references"] = len(resolved)
            report["status"] = "resolved" if resolved else ("empty" if not rows else "no_reference_field")
            for canonical, group in resolved.items():
                entry = references.get((canonical, group["host_root"]))
                if entry is None:
                    entry = {
                        "source_dataset_root": canonical,
                        "host_root": group["host_root"],
                        "source_root_key": group["source_root_key"],
                        "source_ds_ids": [],
                        "source_versions": [],
                        "referenced_by": [],
                        "manifests": [],
                    }
                    references[(canonical, group["host_root"])] = entry
                for target in ("source_ds_ids", "source_versions"):
                    for identity in group[target]:
                        _append_unique(entry[target], identity)
                _append_unique(entry["referenced_by"], name)
                _append_unique(entry["manifests"], str(manifest))
        reports[name] = report
    ordered = sorted(references.values(), key=lambda entry: entry["source_dataset_root"])
    return ordered, reports