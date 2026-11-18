#!/usr/bin/env node
/**
 * npm entry point for the repository's Python probes.
 *
 * `check:task-capabilities` and `sure:tasks` used to call `uv run …` directly in
 * package.json, which ignored HARNESS_PYTHON_BIN — a caller that had already
 * materialized the harness interpreter got a second, different one. Routing every
 * entry point through pythonInvocation keeps one rule: harness interpreter when the
 * environment names it, uv with the probe dependencies otherwise.
 */
import { spawnSync } from "node:child_process";
import { pythonInvocation } from "./python-runner.mjs";

const [command, args] = pythonInvocation(process.argv.slice(2));
const result = spawnSync(command, args, { stdio: "inherit" });
if (result.error) {
	console.error(`${command} could not be started: ${result.error.message}`);
	process.exit(127);
}
process.exit(result.status ?? 1);
