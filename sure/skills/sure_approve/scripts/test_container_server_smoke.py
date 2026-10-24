#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import approval_core


class ContainerServerSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.candidate = Path(temporary.name) / "model"
        self.candidate.mkdir()
        self.binding = {
            "runtime_kind": "container",
            "target_image_ref": "registry.example/model@sha256:" + "a" * 64,
            "container": {
                "model_mount": {"target": "/workspace/model"},
                "working_dir": "/workspace/model",
                "python_executable": "/usr/local/bin/python",
                "server_command": ["python", "server.py"],
                "gpu_required": True,
            },
        }

    def config(self, *, working_dir: str = "/workspace/model", model_dir: str = "/workspace/model") -> None:
        (self.candidate / "config.yaml").write_text(
            "server:\n"
            "  command: [python, server.py]\n"
            "  protocol: mcp\n"
            f"  working_dir: {working_dir}\n"
            "  env:\n"
            f"    SURE_MODEL_DIR: {model_dir}\n"
            "tools:\n"
            "  - name: predict\n"
            "    input_schema:\n"
            "      type: object\n"
            "      properties:\n"
            "        text: {type: string}\n",
            encoding="utf-8",
        )

    def test_rejects_server_working_dir_from_onboard_container(self) -> None:
        self.config(working_dir="/model", model_dir="/model")
        with self.assertRaisesRegex(approval_core.ApprovalError, "server.working_dir.*approved container"):
            approval_core.verify_server_contract(self.candidate, "container", self.binding)

    def test_rejects_declared_model_dir_outside_mount(self) -> None:
        self.config(model_dir="/model")
        with self.assertRaisesRegex(approval_core.ApprovalError, "server.env.SURE_MODEL_DIR.*approved model mount"):
            approval_core.verify_server_contract(self.candidate, "container", self.binding)

    def test_smokes_server_under_approved_read_only_mount(self) -> None:
        self.config()
        observed: list[str] = []

        def run(command: list[str], **kwargs: object) -> mock.Mock:
            observed.extend(command)
            output_mount = next(value for value in command if value.endswith(",dst=/sure-approve-output"))
            output_dir = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-output"))
            runner_mount = next(value for value in command if value.endswith(",dst=/sure-approve-repo,readonly"))
            runner_dir = Path(runner_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-repo,readonly"))
            self.assertTrue((runner_dir / "sure/skills/sure_onboard/scripts/run_server_smoke.py").is_file())
            self.assertFalse((runner_dir / "sure/skills/sure_approve/scripts/approval_core.py").exists())
            (output_dir / "server_contract_smoke.json").write_text(
                json.dumps({"status": "passed", "steps": {"tools_list": {"ok": True}}}), encoding="utf-8"
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(approval_core.subprocess, "run", side_effect=run):
            evidence = approval_core._verify_container_server(self.candidate, self.binding)
        self.assertEqual(evidence["status"], "passed")
        self.assertIn(f"type=bind,src={self.candidate},dst=/workspace/model,readonly", observed)
        self.assertIn("--list-only", observed)
        self.assertIn("--gpus", observed)
        self.assertIn("/workspace/model", observed)

    def test_reports_server_stderr_when_startup_fails(self) -> None:
        self.config()

        def run(command: list[str], **kwargs: object) -> mock.Mock:
            output_mount = next(value for value in command if value.endswith(",dst=/sure-approve-output"))
            output_dir = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-output"))
            (output_dir / "server_contract_smoke.json").write_text(
                json.dumps({"status": "failed", "error": "initialize failed", "server_stderr_tail": ["pretrained_models directory missing"]}),
                encoding="utf-8",
            )
            return mock.Mock(returncode=1, stdout="", stderr="")

        with mock.patch.object(approval_core.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(approval_core.ApprovalError, "pretrained_models directory missing"):
                approval_core._verify_container_server(self.candidate, self.binding)


if __name__ == "__main__":
    unittest.main()
