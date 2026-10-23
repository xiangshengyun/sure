import { spawnSync } from "node:child_process";

export type GpuLane = "infer" | "reserved";

function gpuCount(): number {
	const probe = spawnSync("nvidia-smi", ["--query-gpu=index", "--format=csv,noheader"], {
		encoding: "utf-8",
		timeout: 10_000,
	});
	if (probe.error || probe.status !== 0) {
		return 0;
	}
	return probe.stdout.split("\n").filter((line) => line.trim()).length;
}

/**
 * Give this run one GPU lane so a concurrent run of another skill cannot land
 * on the same cards.
 *
 * `sure_infer` takes every card but the last (0 to n-2); `sure_trans` and
 * `sure_onboard` take the last one (n-1). On an eight-GPU node that is 0-6 and 7.
 * The lane is exported as CUDA_VISIBLE_DEVICES, which the worker planner, the
 * local Python launcher and model children all read, so it is the whole
 * allocation they see.
 *
 * An allocation that is already set wins, and a single-GPU node has nothing to
 * split, so both are left alone. The value written here is remembered in
 * SURE_GPU_LANE_APPLIED: the harness process outlives one run, and the next
 * skill must be able to move the lane rather than inherit the previous one.
 */
export function applyGpuLane(env: NodeJS.ProcessEnv, lane: GpuLane, count: number = gpuCount()): void {
	const current = env.CUDA_VISIBLE_DEVICES;
	if (current !== undefined && current !== env.SURE_GPU_LANE_APPLIED) {
		return;
	}
	if (count < 2) {
		return;
	}
	const devices = lane === "infer" ? Array.from({ length: count - 1 }, (_, index) => index) : [count - 1];
	const value = devices.join(",");
	env.CUDA_VISIBLE_DEVICES = value;
	env.SURE_GPU_LANE_APPLIED = value;
}
