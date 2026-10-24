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
        self.fixture_audio = self.candidate / "fixture" / "asr" / "sample.wav"
        self.fixture_audio.parent.mkdir(parents=True)
        self.fixture_audio.write_bytes(b"RIFF")
        (self.candidate / "artifacts").mkdir()
        (self.candidate / "artifacts" / "fixture_manifest.json").write_text(
            json.dumps(
                {
                    "model_dir": str(self.candidate),
                    "staged_dir": str(self.fixture_audio.parent),
                    "samples": [
                        {
                            "audio_path": str(self.fixture_audio),
                            "audio_roles": {"audio_path": str(self.fixture_audio)},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
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

    def config(self, *, working_dir: str = "/workspace/model", model_dir: str = "/workspace/model", extra_env: str = "") -> None:
        (self.candidate / "config.yaml").write_text(
            "server:\n"
            "  command: [python, server.py]\n"
            "  protocol: mcp\n"
            f"  working_dir: {working_dir}\n"
            "  env:\n"
            f"    SURE_MODEL_DIR: {model_dir}\n"
            f"{extra_env}"
            "tools:\n"
            "  - name: predict\n"
            "    input_schema:\n"
            "      type: object\n"
            "      properties:\n"
            "        audio_path: {type: string}\n",
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

    def test_rejects_pythonpath_that_reaches_the_bundle_by_another_root(self) -> None:
        self.config(extra_env="    PYTHONPATH: /model/src\n")
        with self.assertRaisesRegex(approval_core.ApprovalError, "PYTHONPATH.*root deployment does not mount"):
            approval_core.verify_server_contract(self.candidate, "container", self.binding)

    def test_allows_image_provided_and_mount_spelled_pythonpath(self) -> None:
        self.config(extra_env="    PYTHONPATH: /usr/local/lib/python3.11/site-packages:/workspace/model/src\n")
        evidence = approval_core.verify_server_contract(self.candidate, "container", self.binding)
        self.assertEqual(evidence["status"], "passed")

    def test_a_config_declaring_no_python_path_is_not_an_error(self) -> None:
        # Most bundles declare no PYTHONPATH at all; reading the key as a given
        # raised KeyError here and broke every container approval.
        self.config()
        evidence = approval_core.verify_server_contract(self.candidate, "container", self.binding)
        self.assertEqual(evidence["status"], "passed")

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
        self.assertIn("--gpus", observed)
        self.assertIn("/workspace/model", observed)
        # The smoke calls the tool: list-only would skip the weight load.
        self.assertNotIn("--list-only", observed)
        arguments = json.loads(observed[observed.index("--arguments-json") + 1])
        self.assertEqual(arguments, {"audio_path": "/workspace/model/fixture/asr/sample.wav"})

    def test_refuses_a_required_input_the_fixture_cannot_supply(self) -> None:
        (self.candidate / "config.yaml").write_text(
            "server:\n  command: [python, server.py]\n  protocol: mcp\n"
            "  working_dir: /workspace/model\ntools:\n"
            "  - name: predict\n    input_schema:\n      type: object\n      required: [audio_path, text]\n"
            "      properties:\n        audio_path: {type: string}\n        text: {type: string}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(approval_core.ApprovalError, "required tool input"):
            approval_core._verify_container_server(self.candidate, self.binding)

    def test_synthesizes_required_output_paths_and_sends_every_filled_input(self) -> None:
        # Inference makes its own scratch path for every output a tool declares,
        # so no bundle records one; and a two-input tool (SE) must receive both
        # inputs, not just the first the fixture happens to fill.
        reference = self.fixture_audio.parent / "reference.wav"
        reference.write_bytes(b"RIFF")
        (self.candidate / "artifacts" / "fixture_manifest.json").write_text(
            json.dumps(
                {
                    "model_dir": str(self.candidate),
                    "samples": [
                        {
                            "audio_path": str(self.fixture_audio),
                            "audio_roles": {
                                "audio_path": str(self.fixture_audio),
                                "reference_audio": str(reference),
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.candidate / "config.yaml").write_text(
            "server:\n  command: [python, server.py]\n  protocol: mcp\n"
            "  working_dir: /workspace/model\ntools:\n"
            "  - name: enhance\n    input_schema:\n      type: object\n"
            "      required: [audio_path, reference_audio, output_path]\n"
            "      properties:\n        audio_path: {type: string}\n"
            "        reference_audio: {type: string}\n        output_path: {type: string}\n",
            encoding="utf-8",
        )
        observed: list[str] = []

        def run(command: list[str], **kwargs: object) -> mock.Mock:
            observed.extend(command)
            output_mount = next(value for value in command if value.endswith(",dst=/sure-approve-output"))
            output_dir = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-output"))
            (output_dir / "server_contract_smoke.json").write_text(
                json.dumps({"status": "passed", "steps": {"tools_list": {"ok": True}}}), encoding="utf-8"
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(approval_core.subprocess, "run", side_effect=run):
            evidence = approval_core._verify_container_server(self.candidate, self.binding)
        arguments = json.loads(observed[observed.index("--arguments-json") + 1])
        self.assertEqual(
            arguments,
            {
                "audio_path": "/workspace/model/fixture/asr/sample.wav",
                "reference_audio": "/workspace/model/fixture/asr/reference.wav",
                "output_path": "/sure-approve-output/smoke_output_path.wav",
            },
        )
        self.assertNotIn("--list-only", observed)
        self.assertTrue(evidence["called_tool"])

    def test_falls_back_to_list_only_when_no_fixture_can_drive_the_tool(self) -> None:
        (self.candidate / "config.yaml").write_text(
            "server:\n  command: [python, server.py]\n  protocol: mcp\n"
            "  working_dir: /workspace/model\ntools:\n"
            "  - name: predict\n    input_schema:\n      type: object\n      properties:\n"
            "        text: {type: string}\n",
            encoding="utf-8",
        )
        observed: list[str] = []

        def run(command: list[str], **kwargs: object) -> mock.Mock:
            observed.extend(command)
            output_mount = next(value for value in command if value.endswith(",dst=/sure-approve-output"))
            output_dir = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-output"))
            (output_dir / "server_contract_smoke.json").write_text(
                json.dumps({"status": "passed", "steps": {"tools_list": {"ok": True}}}), encoding="utf-8"
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(approval_core.subprocess, "run", side_effect=run):
            evidence = approval_core._verify_container_server(self.candidate, self.binding)
        self.assertIn("--list-only", observed)
        self.assertFalse(evidence["called_tool"])

    def test_output_suffix_follows_the_sample_audio_not_the_first_fillable_field(self) -> None:
        # An SE/TTS bundle can fill a `.mp3` prompt first while the model writes
        # a `.wav`; the synthesized output name must follow the sample's own
        # audio, which is what the bundle says its media type is.
        prompt = self.fixture_audio.parent / "prompt.mp3"
        prompt.write_bytes(b"ID3")
        (self.candidate / "artifacts" / "fixture_manifest.json").write_text(
            json.dumps(
                {
                    "model_dir": str(self.candidate),
                    "samples": [
                        {
                            "audio_path": str(self.fixture_audio),
                            "audio_roles": {"prompt_audio": str(prompt)},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.candidate / "config.yaml").write_text(
            "server:\n  command: [python, server.py]\n  protocol: mcp\n"
            "  working_dir: /workspace/model\ntools:\n"
            "  - name: synth\n    input_schema:\n      type: object\n"
            "      required: [prompt_audio, output_path]\n"
            "      properties:\n        prompt_audio: {type: string}\n        output_path: {type: string}\n",
            encoding="utf-8",
        )
        observed: list[str] = []

        def run(command: list[str], **kwargs: object) -> mock.Mock:
            observed.extend(command)
            output_mount = next(value for value in command if value.endswith(",dst=/sure-approve-output"))
            output_dir = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/sure-approve-output"))
            (output_dir / "server_contract_smoke.json").write_text(
                json.dumps({"status": "passed", "steps": {"tools_list": {"ok": True}}}), encoding="utf-8"
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(approval_core.subprocess, "run", side_effect=run):
            approval_core._verify_container_server(self.candidate, self.binding)
        arguments = json.loads(observed[observed.index("--arguments-json") + 1])
        self.assertEqual(arguments["output_path"], "/sure-approve-output/smoke_output_path.wav")

    def test_unrecognised_path_argument_names_the_output_convention(self) -> None:
        # `save_path` is an output by intent but not by name; the refusal has to
        # tell a producer the name to use, not send them hunting for a fixture.
        (self.candidate / "config.yaml").write_text(
            "server:\n  command: [python, server.py]\n  protocol: mcp\n"
            "  working_dir: /workspace/model\ntools:\n"
            "  - name: predict\n    input_schema:\n      type: object\n"
            "      required: [audio_path, save_path]\n"
            "      properties:\n        audio_path: {type: string}\n        save_path: {type: string}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(approval_core.ApprovalError, "declare it as output_path"):
            approval_core._verify_container_server(self.candidate, self.binding)

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
