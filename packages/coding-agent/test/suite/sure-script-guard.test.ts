import { describe, expect, it } from "vitest";
import { invokedSkillScripts, isUnboundedFilesystemSearch } from "../../../../sure/runtime/script-guard.ts";

describe("invokedSkillScripts", () => {
	it("returns every script a compound command runs, not just the first", () => {
		expect(invokedSkillScripts("python3 scripts/allowed.py && python3 scripts/other.py")).toEqual([
			"scripts/allowed.py",
			"scripts/other.py",
		]);
	});

	it("ignores a script that is only being read", () => {
		expect(invokedSkillScripts("cat scripts/other.py")).toEqual([]);
		expect(invokedSkillScripts("grep -n def scripts/other.py")).toEqual([]);
	});

	it("still catches a run hidden behind a read", () => {
		expect(invokedSkillScripts("cat scripts/allowed.py; python3 scripts/other.py")).toEqual(["scripts/other.py"]);
	});

	it("returns nothing when no skill script is named", () => {
		expect(invokedSkillScripts("ls -la")).toEqual([]);
	});

	it("catches a backslash-spelled script path", () => {
		expect(invokedSkillScripts("python3 scripts\\run_infer.py")).toEqual(["scripts/run_infer.py"]);
	});

	it("honours a caller-supplied prefix", () => {
		expect(invokedSkillScripts("python3 sure_infer/scripts/run.py", "sure_infer/scripts")).toEqual([
			"sure_infer/scripts/run.py",
		]);
	});
});

describe("isUnboundedFilesystemSearch", () => {
	it("blocks root and mount-root searches", () => {
		expect(isUnboundedFilesystemSearch('find / -name "*.py"')).toBe(true);
		expect(isUnboundedFilesystemSearch('grep -r "speaker-verification" /')).toBe(true);
		expect(isUnboundedFilesystemSearch('rg -n "funasr" /mnt/lustre')).toBe(true);
	});

	it("blocks searches without an explicit rg path", () => {
		expect(isUnboundedFilesystemSearch('rg -n "speaker-verification"')).toBe(true);
	});

	it("allows bounded project-relative searches", () => {
		expect(isUnboundedFilesystemSearch('rg -n "speaker-verification" sure/runtime/evaluation')).toBe(false);
		expect(isUnboundedFilesystemSearch('find sure/handoffs -maxdepth 2 -name model_input.yaml')).toBe(false);
		expect(isUnboundedFilesystemSearch('grep -r "task_type" sure/runtime/evaluation')).toBe(false);
	});
});
