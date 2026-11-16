import { describe, expect, it } from "vitest";
import { SURE_INIT_PROVIDER_OPTIONS } from "../../src/core/sure/init.ts";
import {
	buildInitMenu,
	findMenuEntry,
	isReservedProviderName,
	menuEntryLabel,
	NEW_GATEWAY_OPTION_ID,
} from "../../src/core/sure/init-menu.ts";
import type { SureInitProviderOption } from "../../src/core/sure/init-types.ts";

const relay = { name: "relay", baseUrl: "https://gw.example.com/v1", modelCount: 3, hasApiKey: true };
const clash = { name: "openai", baseUrl: "https://evil.example.com/v1", modelCount: 1, hasApiKey: false };

// Local override: the real menu ships no built-ins, so the mechanics tests use their own fixture.
const codex: SureInitProviderOption = {
	id: "codex",
	name: "OpenAI Codex",
	provider: "openai-codex",
	defaultModel: "gpt-5.5",
	authType: "oauth",
	description: "ChatGPT Plus/Pro subscription coding agent",
};
const kimi: SureInitProviderOption = {
	id: "kimi-code",
	name: "Kimi Code",
	provider: "kimi-coding",
	defaultModel: "kimi-for-coding",
	authType: "api_key",
	description: "Kimi dedicated coding endpoint",
};
const options = [codex, kimi];

describe("buildInitMenu", () => {
	it("keeps built-ins first, appends gateways, ends with the new-gateway entry", () => {
		const menu = buildInitMenu(options, [relay]);
		expect(menu.entries[0]).toEqual({ kind: "builtin", option: codex });
		expect(menu.entries[options.length]).toEqual({ kind: "gateway", gateway: relay });
		expect(menu.entries[menu.entries.length - 1]).toEqual({ kind: "new-gateway" });
		expect(menu.skippedGateways).toEqual([]);
	});

	it("skips gateways whose name collides with built-ins and reports them", () => {
		const menu = buildInitMenu(options, [clash, relay]);
		expect(menu.skippedGateways).toEqual(["openai"]);
		expect(menu.entries.filter((entry) => entry.kind === "gateway")).toEqual([{ kind: "gateway", gateway: relay }]);
	});

	it("local override: the real menu carries whatever built-ins the constant lists (currently none)", () => {
		const menu = buildInitMenu(SURE_INIT_PROVIDER_OPTIONS, [relay]);
		expect(menu.entries.filter((entry) => entry.kind === "builtin")).toHaveLength(SURE_INIT_PROVIDER_OPTIONS.length);
		expect(menu.entries[menu.entries.length - 1]).toEqual({ kind: "new-gateway" });
	});
});

describe("menuEntryLabel", () => {
	it("formats all three kinds", () => {
		expect(menuEntryLabel({ kind: "builtin", option: codex })).toBe(
			"OpenAI Codex: ChatGPT Plus/Pro subscription coding agent → openai-codex",
		);
		expect(menuEntryLabel({ kind: "gateway", gateway: relay })).toBe(
			"relay (custom): https://gw.example.com/v1, 3 models",
		);
		expect(menuEntryLabel({ kind: "new-gateway" })).toBe("Custom provider: add an OpenAI-compatible gateway");
	});
});

describe("findMenuEntry", () => {
	it("resolves built-in ids, gateway names, and the custom id", () => {
		const menu = buildInitMenu(options, [relay]);
		expect(findMenuEntry(menu, "codex")).toEqual({ kind: "builtin", option: codex });
		expect(findMenuEntry(menu, "relay")).toEqual({ kind: "gateway", gateway: relay });
		expect(findMenuEntry(menu, NEW_GATEWAY_OPTION_ID)).toEqual({ kind: "new-gateway" });
		expect(findMenuEntry(menu, "ghost")).toBeUndefined();
	});
});

describe("isReservedProviderName", () => {
	it("rejects the custom id, option ids, provider keys, and built-in providers", () => {
		expect(isReservedProviderName("custom", options)).toBe(true);
		expect(isReservedProviderName("codex", options)).toBe(true);
		expect(isReservedProviderName("openai-codex", options)).toBe(true);
		expect(isReservedProviderName("github-copilot", options)).toBe(true);
		expect(isReservedProviderName("relay", options)).toBe(false);
	});
});
