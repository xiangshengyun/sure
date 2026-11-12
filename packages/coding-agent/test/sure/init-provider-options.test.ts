import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthStorage } from "../../src/core/auth-storage.ts";
import { needsCapabilityProbe } from "../../src/core/sure/init.ts";
import { listBuiltInProviderModels } from "../../src/core/sure/init-model-listing.ts";
import type { SureInitProviderOption } from "../../src/core/sure/init-types.ts";
import { createInMemoryModelRegistry } from "../model-runtime-test-utils.ts";

// Local override: /sure_init offers no built-in providers, so these tests carry their own fixture.
const deepseek: SureInitProviderOption = {
	id: "deepseek",
	name: "DeepSeek",
	provider: "deepseek",
	defaultModel: "deepseek-v4-flash",
	authType: "api_key",
	description: "Standard DeepSeek API",
};

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("SURE init provider options", () => {
	it("resolves the DeepSeek catalog default without a capability probe", () => {
		expect(needsCapabilityProbe(deepseek.provider, deepseek.defaultModel)).toBe(false);
	});

	it("queries the official DeepSeek model list when auth is configured", async () => {
		const authStorage = AuthStorage.inMemory({ deepseek: { type: "api_key", key: "sk-live" } });
		const registry = await createInMemoryModelRegistry(authStorage);
		const fetchMock = vi.fn(async () => Response.json({ data: [{ id: "deepseek-v4-flash" }] }));
		vi.stubGlobal("fetch", fetchMock);

		const listing = await listBuiltInProviderModels(deepseek, registry);

		expect(listing).toEqual({ source: "live", models: [{ id: "deepseek-v4-flash" }] });
		expect(fetchMock).toHaveBeenCalledWith(
			"https://api.deepseek.com/v1/models",
			expect.objectContaining({
				headers: expect.objectContaining({ Authorization: "Bearer sk-live" }),
			}),
		);
	});
});
