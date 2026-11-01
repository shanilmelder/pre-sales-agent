import { describe, expect, it } from "vitest";

import {
  canRetest,
  canRetire,
  isPending,
  modelsFor,
  nameError,
  numCtxError,
  samplingLabel,
  stateLabel,
  temperatureError,
  testResult,
  upsertProfile,
  type ApprovedModel,
  type ModelProfile,
} from "@/lib/model-profiles";

function profile(over: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "00000000-0000-7000-8000-000000000001",
    name: "custom",
    provider: "ollama",
    model: "gpt-oss:120b-cloud",
    num_ctx: 32768,
    temperature: 0.1,
    reasoning_effort: null,
    state: "verified",
    error_code: null,
    latency_ms: 1200,
    tested_at: "2026-11-02T10:00:00Z",
    created_at: "2026-11-02T09:00:00Z",
    ...over,
  };
}

describe("model profile states", () => {
  it("shows a queued test as pending, not failed", () => {
    const queued = profile({ state: "untested", latency_ms: null, tested_at: null });
    expect(isPending(queued)).toBe(true);
    expect(stateLabel(queued.state)).toBe("Pending test");
    expect(testResult(queued)).toBeNull();
  });

  it("offers a retest only after a failure and retiring until retired", () => {
    expect(canRetest(profile({ state: "failed" }))).toBe(true);
    expect(canRetest(profile())).toBe(false);
    expect(canRetire(profile())).toBe(true);
    expect(canRetire(profile({ state: "retired" }))).toBe(false);
  });

  it("describes the test result with codes and timings only", () => {
    expect(testResult(profile())).toBe("Passed in 1,200 ms");
    expect(testResult(profile({ state: "failed", error_code: "timeout" }))).toBe(
      "timeout after 1,200 ms",
    );
  });

  it("names the temperature or the reasoning effort", () => {
    expect(samplingLabel(profile())).toBe("Temperature 0.1");
    expect(samplingLabel(profile({ temperature: null, reasoning_effort: "high" }))).toBe(
      "Reasoning effort high",
    );
  });
});

describe("model profile form rules", () => {
  it("checks the name", () => {
    expect(nameError("openai-gpt-5")).toBeNull();
    expect(nameError(" ")).toBe("The name is required.");
    expect(nameError("Has Spaces")).not.toBeNull();
  });

  it("checks the context size and temperature", () => {
    expect(numCtxError("32768")).toBeNull();
    expect(numCtxError("1000")).not.toBeNull();
    expect(numCtxError("abc")).not.toBeNull();
    expect(temperatureError("0.2")).toBeNull();
    expect(temperatureError("")).not.toBeNull();
    expect(temperatureError("3")).not.toBeNull();
  });
});

describe("lists", () => {
  it("offers only the provider's approved models", () => {
    const approved: ApprovedModel[] = [
      { id: "1", provider: "ollama", model: "a", created_at: "2026-11-02T09:00:00Z" },
      { id: "2", provider: "openai", model: "b", created_at: "2026-11-02T09:00:00Z" },
    ];
    expect(modelsFor(approved, "openai")).toEqual(["b"]);
  });

  it("puts a new profile first and replaces a known one", () => {
    const first = profile();
    const second = profile({ id: "00000000-0000-7000-8000-000000000002" });
    expect(upsertProfile([first], second).map((p) => p.id)).toEqual([second.id, first.id]);
    expect(upsertProfile([first], { ...first, state: "retired" })[0].state).toBe("retired");
  });
});
