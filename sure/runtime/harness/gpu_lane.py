#!/usr/bin/env python3
"""The GPU lane a run was given, and the Docker --gpus value that keeps to it.

The skill pre-start hook exports the lane as CUDA_VISIBLE_DEVICES. Docker does
not honour that variable for `--gpus all`, so a command this run builds or a
gate executes narrows `all` to the lane before it starts.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

_GPUS_ALL_RE = re.compile(r"--gpus(=|\s+)all\b")


def lane_devices(env: Mapping[str, str] | None = None) -> list[str]:
    """The devices this run may use, or [] when it has no lane (or CPU only)."""
    raw = (os.environ if env is None else env).get("CUDA_VISIBLE_DEVICES")
    devices = [device.strip() for device in (raw or "").split(",") if device.strip()]
    return [] if not devices or "-1" in devices else devices


def gpus_argument(env: Mapping[str, str] | None = None) -> str:
    """`--gpus` value for a command this run builds itself; `all` without a lane."""
    devices = lane_devices(env)
    return f"device={','.join(devices)}" if devices else "all"


def restrict_docker_gpus(command, env: Mapping[str, str] | None = None):
    """Rewrite an authored `--gpus all` to the lane, so a request cannot widen it.

    An explicit device list is left as authored: it already names cards.
    """
    devices = lane_devices(env)
    if not devices:
        return command
    value = f"device={','.join(devices)}"
    if isinstance(command, str):
        return _GPUS_ALL_RE.sub(lambda match: f"--gpus{match.group(1)}{value}", command)
    if not isinstance(command, list):
        return command
    rewritten = list(command)
    for index, token in enumerate(rewritten):
        if token == "--gpus" and index + 1 < len(rewritten) and rewritten[index + 1] == "all":
            rewritten[index + 1] = value
        elif token == "--gpus=all":
            rewritten[index] = f"--gpus={value}"
    return rewritten
