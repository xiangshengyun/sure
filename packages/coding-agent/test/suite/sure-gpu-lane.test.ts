import { describe, expect, it } from "vitest";
import { applyGpuLane } from "../../../../sure/runtime/gpu-lane.ts";

describe("applyGpuLane", () => {
	it("gives infer every card but the last, and the reserved lane the last", () => {
		const env: NodeJS.ProcessEnv = {};
		applyGpuLane(env, "infer", 8);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("0,1,2,3,4,5,6");
		applyGpuLane(env, "reserved", 8);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("7");
	});

	it("gives infer 0 to n-2 on a wider node, and still leaves n-1 alone", () => {
		const env: NodeJS.ProcessEnv = {};
		applyGpuLane(env, "infer", 16);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("0,1,2,3,4,5,6,7,8,9,10,11,12,13,14");
		applyGpuLane(env, "reserved", 16);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("15");
	});

	it("leaves a node with one GPU alone", () => {
		const env: NodeJS.ProcessEnv = {};
		applyGpuLane(env, "reserved", 1);
		expect(env.CUDA_VISIBLE_DEVICES).toBeUndefined();
	});

	it("keeps an allocation the caller already made", () => {
		const env: NodeJS.ProcessEnv = { CUDA_VISIBLE_DEVICES: "2,3" };
		applyGpuLane(env, "reserved", 8);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("2,3");
		expect(env.SURE_GPU_LANE_APPLIED).toBeUndefined();
	});

	it("moves the lane on the next run instead of inheriting the previous one", () => {
		const env: NodeJS.ProcessEnv = {};
		applyGpuLane(env, "infer", 8);
		applyGpuLane(env, "reserved", 8);
		expect(env.CUDA_VISIBLE_DEVICES).toBe("7");
	});
});
