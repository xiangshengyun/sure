#!/usr/bin/env node
/**
 * The interpreter every repository check uses for its Python probes.
 *
 * A bare `python3` is not portable: Windows installs usually expose only
 * `python`, and the host interpreter does not carry the checks' dependencies
 * (pyyaml). Prefer the harness interpreter a caller already exported; otherwise
 * run through uv with a pinned 3.11 and pyyaml, both of which the README
 * requires. `--no-project` keeps uv out of whatever project it is invoked from
 * (the public-export tree has no root project of its own).
 */

/**
 * Packages every probe needs when uv is the interpreter.
 *
 * The probes import `sure_eval`: its package `__init__` pulls structlog and rich, and
 * its config imports pydantic. pyyaml alone reached the probe and then died with
 * `ModuleNotFoundError: No module named 'pydantic'`, which the public-export path never
 * showed because it skips these probes entirely.
 */
const PROBE_DEPENDENCIES = ["pyyaml", "pydantic", "structlog", "rich"];

export function pythonInvocation(args) {
	const harness = process.env.HARNESS_PYTHON_BIN || process.env.SURE_EVAL_HARNESS_PYTHON_BIN;
	if (harness) {
		return [harness, args];
	}
	return [
		"uv",
		[
			"run",
			"--no-project",
			"--python",
			"3.11",
			...PROBE_DEPENDENCIES.flatMap((dependency) => ["--with", dependency]),
			"python",
			...args,
		],
	];
}
