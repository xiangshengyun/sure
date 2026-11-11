/**
 * Skill scripts that a bash command actually runs.
 *
 * Two things the old per-skill `command.match(...)` could not do: it stopped at
 * the first name, so `python3 scripts/allowed.py && python3 scripts/other.py`
 * was judged entirely on the first one; and it could not tell running a script
 * from reading it, so `cat scripts/other.py` was blocked as an out-of-order
 * call.
 *
 * This raises the cost of running another unit's script. It cannot stop a
 * determined caller — cd into the directory, or build the path in a variable,
 * and no name matches.
 */
const READ_ONLY_HEAD = /^(?:cat|head|tail|less|more|grep|rg|sed|awk|wc|ls|stat|file|diff|md5sum|sha256sum|nl|od|xxd)$/;
const SHELL_SPLIT = /\|\||&&|[;&|\n]/;
const UNBOUNDED_ROOT = /^(?:\/$|~(?:\/|$)|\/mnt\/?$|\/hpc_stor\d*\/?$)/;
/** Mount roots whose paths are as broad as a filesystem root; subpaths stay allowed. */
const UNBOUNDED_MOUNT_ROOTS = new Set(["/mnt/lustre"]);

function isUnboundedRoot(token: string): boolean {
	return UNBOUNDED_ROOT.test(token) || UNBOUNDED_MOUNT_ROOTS.has(token);
}

export function invokedSkillScripts(command: string, prefix = "scripts"): string[] {
	const pattern = new RegExp(`${prefix}/([A-Za-z0-9_]+\\.py)\\b`, "g");
	const names = new Set<string>();
	// A PowerShell or cmd caller spells the same script scripts\x.py; fold the
	// separators together so one path shape cannot slip past the gate.
	for (const segment of command.replace(/\\/g, "/").split(/\|\||&&|[;&|\n]/)) {
		const head = segment.trim().split(/\s+/)[0] ?? "";
		if (READ_ONLY_HEAD.test(head)) {
			continue;
		}
		for (const match of segment.matchAll(pattern)) {
			names.add(`${prefix}/${match[1]}`);
		}
	}
	return [...names];
}

function normalizedTokens(segment: string): string[] {
	return segment
		.trim()
		.split(/\s+/)
		.map((token) => token.replace(/^['"]|['"]$/g, ""))
		.filter(Boolean);
}

/**
 * Detect searches that can traverse an uncontrolled filesystem scope.
 * Project-relative recursive searches remain allowed; this only blocks root,
 * mount-root, home-root, and ripgrep/grep calls without an explicit path.
 */
export function isUnboundedFilesystemSearch(command: string): boolean {
	for (const rawSegment of command.replace(/\\/g, "/").split(SHELL_SPLIT)) {
		const tokens = normalizedTokens(rawSegment);
		const executable = tokens[0]?.split("/").pop();
		if (!executable) {
			continue;
		}
		if (executable === "find") {
			const rootPath = tokens.slice(1).find((token) => isUnboundedRoot(token));
			if (rootPath) {
				return true;
			}
		}
		if (
			executable === "grep" &&
			tokens.some((token) => token === "-r" || token === "-R" || token === "--recursive")
		) {
			const rootPath = tokens.slice(1).some((token) => isUnboundedRoot(token));
			if (rootPath) {
				return true;
			}
		}
		if (executable === "rg") {
			const nonOptions = tokens.slice(1).filter((token) => !token.startsWith("-"));
			if (nonOptions.length <= 1 || nonOptions.slice(1).some((token) => isUnboundedRoot(token))) {
				return true;
			}
		}
	}
	return false;
}
