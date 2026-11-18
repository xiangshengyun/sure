import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";

const script = resolve(import.meta.dirname, "check-evaluation-lock.mjs");

// The check reads four fixed paths, so every case writes all four and overrides the one it
// is about. Contents are minimal: names and exact `==` pins are what the check compares.
const COMPLETE = {
	evaluationIn: "pydantic>=2.0.0\npyyaml>=6.0.0\n",
	evaluationLock: "pydantic==2.0.0 \\\n    --hash=sha256:aa\npyyaml==6.0.3 \\\n    --hash=sha256:bb\n",
	harnessIn: "pyyaml>=6.0.0\n",
	harnessLock: "pyyaml==6.0.3 \\\n    --hash=sha256:bb\n",
};

function makeRepo(overrides) {
	const repo = mkdtempSync(join(tmpdir(), "sure-lock-check-"));
	for (const [relative, content] of Object.entries({ ...COMPLETE, ...overrides })) {
		const kind = relative.startsWith("evaluation") ? "evaluation" : "harness";
		const name = relative.endsWith("Lock") ? "requirements.lock.txt" : "requirements.in";
		const path = join(repo, "sure", "runtime", kind, name);
		mkdirSync(dirname(path), { recursive: true });
		writeFileSync(path, content);
	}
	return repo;
}

function run(repo) {
	return spawnSync(process.execPath, [script], { cwd: repo, encoding: "utf8" });
}

test("passes when every requirement is locked", () => {
	const repo = makeRepo({});
	try {
		const result = run(repo);
		assert.equal(result.status, 0, result.stderr);
		assert.match(result.stdout, /cover every requirement/);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("fails and names the pin the lock does not carry", () => {
	const repo = makeRepo({ evaluationLock: "pydantic==2.0.0 \\\n    --hash=sha256:aa\n" });
	try {
		const result = run(repo);
		assert.equal(result.status, 1);
		assert.match(result.stderr, /does not lock: pyyaml/);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("ignores comments and treats _ . - in a name as the same package", () => {
	const repo = makeRepo({
		evaluationIn: "# a comment line\npydantic_settings>=2  # inline comment\n",
		evaluationLock: "pydantic-settings==2.0 \\\n    --hash=sha256:aa\n",
	});
	try {
		const result = run(repo);
		assert.equal(result.status, 0, result.stderr);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("reports a missing lock file instead of passing", () => {
	const repo = mkdtempSync(join(tmpdir(), "sure-lock-check-"));
	try {
		const result = run(repo);
		assert.equal(result.status, 1);
		assert.match(result.stderr, /is missing/);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("fails when the lock pins a different version than requirements.in", () => {
	// A bump in requirements.in without a recompile keeps the name check green while the
	// runtime installs the old version: the same gap as a missing pin (#163).
	const repo = makeRepo({
		evaluationIn: "pydantic==2.13.3\npyyaml>=6.0.0\n",
		evaluationLock: "pydantic==2.0.0 \\\n    --hash=sha256:aa\npyyaml==6.0.3 \\\n    --hash=sha256:bb\n",
	});
	try {
		const result = run(repo);
		assert.equal(result.status, 1);
		assert.match(result.stderr, /wrong version: pydantic==2\.13\.3 \(lock has 2\.0\.0\)/);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("ignores option lines", () => {
	const repo = makeRepo({
		evaluationIn: "--extra-index-url https://mirror.example\n-r base.in\npydantic>=2.0.0\npyyaml>=6.0.0\n",
	});
	try {
		const result = run(repo);
		assert.equal(result.status, 0, result.stderr);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});

test("names a direct reference by its package name", () => {
	const repo = makeRepo({
		evaluationIn: "librosa @ git+https://github.com/example/librosa\npydantic>=2.0.0\npyyaml>=6.0.0\n",
		evaluationLock: "librosa==0.10.0 \\\n    --hash=sha256:cc\npydantic==2.0.0 \\\n    --hash=sha256:aa\npyyaml==6.0.3 \\\n    --hash=sha256:bb\n",
	});
	try {
		const result = run(repo);
		assert.equal(result.status, 0, result.stderr);
	} finally {
		rmSync(repo, { recursive: true, force: true });
	}
});
