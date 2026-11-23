#!/usr/bin/env python3
"""Tests for the source datasets a selection manifest references.

Stage four of docs/spec/referenced-dataset-mounting-plan.md: the input resolver reads
and validates the manifests, and the container launcher turns the resolved list into
read-only mounts at the canonical paths the manifest samples use.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import resolve_eval_input
import test_deployment_binding as container_fixtures
import test_harness_runtime_contract as harness_contract
from container_execution import build_local_container_command, container_path
from referenced_datasets import (
    ReferencedDatasetError,
    collect_referenced_datasets,
    selection_manifest_path,
)
from sure_eval.datasets import source_resolver


class ReferencedDatasetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pool = self.root / "datasets"
        self.pool.mkdir()
        self.compose = self.pool / "MASC-compose"
        self.referenced = self.pool / "MASC-test_clean"
        self.other = self.pool / "other_clean"
        for path in (self.compose, self.referenced, self.other):
            path.mkdir()
        env = patch.dict(os.environ, {"SURE_DATASET_SOURCE_ROOT": ""})
        env.start()
        self.addCleanup(env.stop)
        roots = patch.object(source_resolver, "DEFAULT_SOURCE_ROOTS", {"default": str(self.pool)})
        roots.start()
        self.addCleanup(roots.stop)

    def manifest(self, rows: list[dict], *, root: Path | None = None, version: str = "v1.0.0") -> Path:
        path = selection_manifest_path(str(root or self.compose), version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def dataset(self, name: str = "compose", **overrides: str) -> dict:
        detail = {
            "name": name,
            "source_root": str(self.compose),
            "version_id": "v1.0.0",
        }
        detail.update(overrides)
        return detail

    def test_one_reference_resolves_to_the_declared_and_host_paths(self) -> None:
        self.manifest(
            [
                {
                    "sample_id": "0",
                    "source_ds_id": "ds_audio",
                    "source_dataset_root": str(self.referenced),
                    "source_version": "v1.0.0",
                    "raw_data_name": "example.wav",
                }
            ]
        )
        references, reports = collect_referenced_datasets([self.dataset()])

        self.assertEqual(len(references), 1)
        reference = references[0]
        self.assertEqual(reference["source_dataset_root"], str(self.referenced))
        self.assertEqual(reference["host_root"], str(self.referenced.resolve()))
        self.assertEqual(reference["source_root_key"], "default")
        self.assertEqual(reference["source_ds_ids"], ["ds_audio"])
        self.assertEqual(reference["source_versions"], ["v1.0.0"])
        self.assertEqual(reference["referenced_by"], ["compose"])
        self.assertEqual(reports["compose"]["status"], "resolved")
        self.assertEqual(reports["compose"]["references"], 1)
        self.assertEqual(reports["compose"]["rows"], 1)

    def test_two_datasets_referencing_one_source_mount_it_once(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}])
        second = self.pool / "VCTK-compose"
        second.mkdir()
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}], root=second)

        references, _ = collect_referenced_datasets(
            [self.dataset(), self.dataset("second", source_root=str(second))]
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["referenced_by"], ["compose", "second"])
        self.assertEqual(len(references[0]["manifests"]), 2)

    def test_one_dataset_referencing_two_sources_yields_two_references(self) -> None:
        self.manifest(
            [
                {"sample_id": "0", "source_dataset_root": str(self.other)},
                {"sample_id": "1", "source_dataset_root": str(self.referenced)},
            ]
        )
        references, reports = collect_referenced_datasets([self.dataset()])

        self.assertEqual(
            [reference["source_dataset_root"] for reference in references],
            sorted([str(self.other), str(self.referenced)]),
        )
        self.assertEqual(reports["compose"]["references"], 2)

    def test_a_reference_outside_the_allowed_roots_is_rejected(self) -> None:
        outside = self.root / "elsewhere"
        outside.mkdir()
        manifest = self.manifest([{"sample_id": "0", "source_dataset_root": str(outside)}])

        with self.assertRaisesRegex(ReferencedDatasetError, "outside the configured allowed_source_roots"):
            collect_referenced_datasets([self.dataset()])
        self.assertTrue(manifest.is_file())

    def test_a_reference_that_does_not_exist_is_rejected(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.pool / "missing")}])

        with self.assertRaisesRegex(ReferencedDatasetError, "not an existing directory"):
            collect_referenced_datasets([self.dataset()])

    def test_a_relative_reference_is_rejected(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": "ds_pool/MASC-test_clean"}])

        with self.assertRaisesRegex(ReferencedDatasetError, "must be an absolute path"):
            collect_referenced_datasets([self.dataset()])

    def test_a_manifest_recording_the_field_on_some_rows_only_is_rejected(self) -> None:
        self.manifest(
            [
                {"sample_id": "0", "source_dataset_root": str(self.referenced)},
                {"sample_id": "1"},
            ]
        )

        with self.assertRaisesRegex(ReferencedDatasetError, "on every row or on none"):
            collect_referenced_datasets([self.dataset()])

    def test_a_manifest_without_the_field_records_no_reference(self) -> None:
        self.manifest([{"sample_id": "0", "raw_data_name": "example.wav"}])
        references, reports = collect_referenced_datasets([self.dataset()])

        self.assertEqual(references, [])
        self.assertEqual(reports["compose"]["status"], "no_reference_field")
        self.assertEqual(reports["compose"]["references"], 0)

    def test_an_absent_manifest_records_no_reference(self) -> None:
        references, reports = collect_referenced_datasets([self.dataset()])

        self.assertEqual(references, [])
        self.assertEqual(reports["compose"]["status"], "absent")
        self.assertNotIn("references", reports["compose"])

    def test_an_unreadable_manifest_is_reported_as_a_resolution_error(self) -> None:
        manifest = self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}])
        real_open = Path.open

        def deny(path: Path, *args, **kwargs):
            if path == manifest:
                raise PermissionError(13, "Permission denied")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", deny):
            with self.assertRaisesRegex(ReferencedDatasetError, "cannot be read"):
                collect_referenced_datasets([self.dataset()])

    def test_a_temporary_version_directory_is_not_read(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}], version="TEMP_VERSION")
        references, reports = collect_referenced_datasets([self.dataset(version_id="v9.9.9")])

        self.assertEqual(references, [])
        self.assertEqual(reports["compose"]["status"], "absent")

    def test_a_dataset_without_a_source_root_is_left_alone(self) -> None:
        detail = {"name": "csv", "jsonl_path": "/tmp/csv.jsonl", "task": "ASR", "language": "EN"}
        references, reports = collect_referenced_datasets([detail])

        self.assertEqual(references, [])
        self.assertEqual(reports, {})
        self.assertNotIn("selection_manifest", detail)


class ReferencedDatasetMountTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = container_fixtures.DeploymentBindingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.binding = container_fixtures.load_deployment_binding(fixture.model, "demo")
        self.referenced = fixture.root / "datasets" / "MASC-test_clean"
        self.referenced.mkdir(parents=True)

    def _command(self, references: list[dict] | None = None, datasets: list[dict] | None = None):
        runtime = {
            "run_dir": str(self.fixture.output),
            "harness_runtime": self.fixture._runtime_binding(),
            "dataset_projection": {"host_root": str(self.fixture.projection)},
        }
        if references is not None:
            runtime["referenced_datasets"] = references
        return build_local_container_command(
            surface={"env": {}},
            eval_input={
                "model": {"deployment_binding": self.binding},
                "runtime": runtime,
                "datasets": datasets or [],
            },
            control_run_dir=self.fixture.control,
            entrypoint=self.fixture.entrypoint,
            repo_root=self.fixture.repo,
            device_request="cpu",
        )

    def _reference(self, canonical: Path | None = None, host: Path | None = None) -> dict:
        canonical = canonical or self.referenced
        return {
            "source_dataset_root": str(canonical),
            "host_root": str((host or canonical).resolve()),
        }

    def test_every_reference_is_mounted_read_only_at_its_canonical_path(self) -> None:
        command, metadata = self._command([self._reference()])

        spec = f"type=bind,src={self.referenced.resolve()},dst={container_path(str(self.referenced))},readonly"
        self.assertIn(spec, command)
        self.assertEqual(
            metadata["referenced_dataset_mounts"],
            [
                {
                    "source": str(self.referenced.resolve()),
                    "target": container_path(str(self.referenced)),
                    "read_only": True,
                }
            ],
        )

    def test_a_plain_dataset_run_declares_no_referenced_mounts(self) -> None:
        command, metadata = self._command()

        self.assertEqual(metadata["referenced_dataset_mounts"], [])
        self.assertNotIn(str(self.referenced.resolve()), " ".join(command))

    def test_a_reference_already_mounted_as_a_dataset_root_is_not_duplicated(self) -> None:
        command, _ = self._command(
            [self._reference()],
            datasets=[{"source_root": str(self.referenced), "jsonl_path": str(self.referenced / "x.jsonl")}],
        )

        target = container_path(str(self.referenced))
        self.assertEqual(sum(1 for part in command if part.endswith(f"dst={target},readonly")), 1)

    def test_two_references_at_one_target_are_rejected(self) -> None:
        other = self.fixture.root / "datasets" / "other"
        other.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "conflicting container mount target"):
            self._command([self._reference(), self._reference(host=other)])

    def test_a_reference_whose_host_root_is_gone_is_rejected(self) -> None:
        self.referenced.rmdir()
        with self.assertRaisesRegex(ValueError, "not an existing directory"):
            self._command([self._reference()])

    def test_a_malformed_reference_entry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a list"):
            self._command({"source_dataset_root": str(self.referenced)})
        with self.assertRaisesRegex(ValueError, "need host_root and source_dataset_root"):
            self._command([{"source_dataset_root": str(self.referenced)}])


class EvalInputIntegrationTests(unittest.TestCase):
    """The resolver writes both artifacts, and the container launch consumes them."""

    def setUp(self) -> None:
        fixture = harness_contract.HarnessRuntimeContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = Path(fixture.temp.name).resolve()
        self.pool = self.root / "datasets"
        self.compose = self.pool / "MASC-compose"
        self.referenced = self.pool / "MASC-test_clean"
        for path in (self.compose, self.referenced):
            path.mkdir(parents=True)
        self.jsonl = fixture.projection / "sure_benchmark" / "jsonl" / "ds.jsonl"
        self.record()
        patches = [
            mock.patch.dict(
                os.environ,
                {
                    "SURE_SITE_POLICY": str(fixture.site_policy),
                    "SURE_DATASET_SOURCE_ROOT": "",
                },
            ),
            mock.patch.object(source_resolver, "DEFAULT_SOURCE_ROOTS", {"default": str(self.pool)}),
            mock.patch.object(
                resolve_eval_input, "load_harness_runtime", return_value=fixture._runtime_binding()
            ),
            mock.patch.object(
                resolve_eval_input, "_resolve_model", return_value=fixture._approved_model_resolution()
            ),
        ]
        for started in patches:
            started.start()
            self.addCleanup(started.stop)

    def record(self) -> None:
        """The projection row is where the resolver reads a dataset's source identity."""
        row = {
            "task": "ASR",
            "language": "en",
            "metadata": {
                "source_dataset_name": "MASC-compose",
                "source_dataset_root": str(self.compose),
                "version_id": "v1.0.0",
            },
        }
        self.jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")

    def manifest(self, rows: list[dict]) -> Path:
        path = selection_manifest_path(str(self.compose), "v1.0.0")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_build_payload_records_the_manifest_and_the_runtime_references(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}])

        payload = resolve_eval_input.build_payload(self.fixture._args())

        manifest_report = payload["datasets"][0]["selection_manifest"]
        self.assertEqual(manifest_report["status"], "resolved")
        self.assertEqual(manifest_report["references"], 1)
        references = payload["runtime"]["referenced_datasets"]
        self.assertEqual([item["source_dataset_root"] for item in references], [str(self.referenced)])
        self.assertEqual(references[0]["referenced_by"], ["ds"])

        command, metadata = build_local_container_command(
            surface={"env": {}},
            eval_input=payload,
            control_run_dir=self.fixture.control,
            entrypoint=self.fixture.entrypoint,
            repo_root=self.fixture.repo,
            device_request="cpu",
        )

        target = container_path(str(self.referenced))
        self.assertIn(f"type=bind,src={self.referenced.resolve()},dst={target},readonly", command)
        self.assertEqual(
            metadata["referenced_dataset_mounts"],
            [{"source": str(self.referenced.resolve()), "target": target, "read_only": True}],
        )

    def test_the_written_eval_input_carries_both_fields(self) -> None:
        self.manifest([{"sample_id": "0", "source_dataset_root": str(self.referenced)}])
        output = self.root / "eval_input_resolved.json"
        argv = [
            "resolve_eval_input.py",
            "--model",
            "demo",
            "--datasets",
            "ds",
            "--device",
            "cpu",
            "--evaluation-engine-root",
            str(self.root / "no-engine"),
            "--output",
            str(output),
        ]

        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            code = resolve_eval_input.main()

        self.assertEqual(code, 0)
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["datasets"][0]["selection_manifest"]["status"], "resolved")
        self.assertEqual(
            [item["source_dataset_root"] for item in written["runtime"]["referenced_datasets"]],
            [str(self.referenced)],
        )

    def test_a_reference_outside_the_allowed_roots_exits_2(self) -> None:
        outside = self.root / "elsewhere"
        outside.mkdir()
        self.manifest([{"sample_id": "0", "source_dataset_root": str(outside)}])
        argv = [
            "resolve_eval_input.py",
            "--model",
            "demo",
            "--datasets",
            "ds",
            "--device",
            "cpu",
            "--evaluation-engine-root",
            str(self.root / "no-engine"),
            "--output-dir",
            str(self.fixture.output),
        ]

        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
            code = resolve_eval_input.main()

        self.assertEqual(code, 2)
        self.assertIn("allowed_source_roots", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()