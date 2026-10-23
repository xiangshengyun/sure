#!/usr/bin/env python3
from __future__ import annotations

import unittest

from gpu_lane import gpus_argument, lane_devices, restrict_docker_gpus


class GpuLaneTests(unittest.TestCase):
    def test_lane_devices_read_the_allocation(self) -> None:
        self.assertEqual(lane_devices({"CUDA_VISIBLE_DEVICES": "0,1,2"}), ["0", "1", "2"])
        self.assertEqual(lane_devices({"CUDA_VISIBLE_DEVICES": ""}), [])
        self.assertEqual(lane_devices({"CUDA_VISIBLE_DEVICES": "-1"}), [])
        self.assertEqual(lane_devices({}), [])

    def test_gpus_argument_keeps_all_without_a_lane(self) -> None:
        self.assertEqual(gpus_argument({"CUDA_VISIBLE_DEVICES": "7"}), "device=7")
        self.assertEqual(gpus_argument({"CUDA_VISIBLE_DEVICES": "0,1"}), "device=0,1")
        self.assertEqual(gpus_argument({}), "all")

    def test_restrict_rewrites_only_an_all_request(self) -> None:
        env = {"CUDA_VISIBLE_DEVICES": "7"}
        self.assertEqual(
            restrict_docker_gpus(["docker", "run", "--rm", "--gpus", "all", "image"], env),
            ["docker", "run", "--rm", "--gpus", "device=7", "image"],
        )
        self.assertEqual(
            restrict_docker_gpus("docker run --gpus=all image", env),
            "docker run --gpus=device=7 image",
        )
        authored = ["docker", "run", "--gpus", "device=2", "image"]
        self.assertEqual(restrict_docker_gpus(authored, env), authored)
        self.assertEqual(restrict_docker_gpus(["docker", "run", "image"], env), ["docker", "run", "image"])


if __name__ == "__main__":
    unittest.main()
