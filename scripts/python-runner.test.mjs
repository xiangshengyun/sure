import assert from "node:assert/strict";
import test from "node:test";
import { pythonInvocation } from "./python-runner.mjs";

// The resolution rule is the whole point of python-runner: the harness interpreter
// when the environment names one, uv with the probe dependencies otherwise. A caller
// that broke either half (a direct uv call in package.json, a swapped priority) used
// to leave no trace in any test.
function withEnv(values, fn) {
	const previous = new Map();
	for (const [name, value] of Object.entries(values)) {
		previous.set(name, process.env[name]);
		if (value === undefined) delete process.env[name];
		else process.env[name] = value;
	}
	try {
		return fn();
	} finally {
		for (const [name, value] of previous) {
			if (value === undefined) delete process.env[name];
			else process.env[name] = value;
		}
	}
}

test("prefers HARNESS_PYTHON_BIN over uv", () => {
	withEnv({ HARNESS_PYTHON_BIN: "/venv/bin/python", SURE_EVAL_HARNESS_PYTHON_BIN: undefined }, () => {
		const [command, args] = pythonInvocation(["-c", "print(1)"]);
		assert.equal(command, "/venv/bin/python");
		assert.deepEqual(args, ["-c", "print(1)"]);
	});
});

test("falls back to SURE_EVAL_HARNESS_PYTHON_BIN when HARNESS_PYTHON_BIN is unset", () => {
	withEnv({ HARNESS_PYTHON_BIN: undefined, SURE_EVAL_HARNESS_PYTHON_BIN: "C:/venv/Scripts/python.exe" }, () => {
		const [command] = pythonInvocation(["-c", "print(1)"]);
		assert.equal(command, "C:/venv/Scripts/python.exe");
	});
});

test("falls back to uv with the pinned interpreter and the probe dependencies", () => {
	withEnv({ HARNESS_PYTHON_BIN: undefined, SURE_EVAL_HARNESS_PYTHON_BIN: undefined }, () => {
		const [command, args] = pythonInvocation(["-c", "print(1)"]);
		assert.equal(command, "uv");
		assert.deepEqual(args.slice(0, 4), ["run", "--no-project", "--python", "3.11"]);
		for (const dependency of ["pyyaml", "pydantic", "structlog", "rich"]) {
			assert.ok(args.includes(dependency), `expected --with ${dependency} in: ${args.join(" ")}`);
		}
		assert.deepEqual(args.slice(-3), ["python", "-c", "print(1)"]);
	});
});
