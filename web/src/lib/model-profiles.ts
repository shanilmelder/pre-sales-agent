// Admin → Model profiles display helpers and form rules. Safe on server and client.
import type { components } from "@/lib/api/client";
import type { PillTone } from "@/components/ui/pill";

export type ModelProfile = components["schemas"]["ModelProfileView"];
export type ApprovedModel = components["schemas"]["ApprovedModelView"];
export type ProfileState = ModelProfile["state"];
export type Provider = ModelProfile["provider"];

export const PROVIDERS: readonly Provider[] = ["ollama", "openai", "anthropic"];
export const REASONING_EFFORTS = ["low", "medium", "high"] as const;
export type ReasoningEffort = (typeof REASONING_EFFORTS)[number];
export const DEFAULT_ANTHROPIC_EFFORT: ReasoningEffort = "medium";

export const NAME_MAX = 64;
export const NUM_CTX_MIN = 16384;
export const NUM_CTX_MAX = 2097152;
export const DEFAULT_NUM_CTX = 32768;
export const DEFAULT_TEMPERATURE = 0.1;
export const TEMPERATURE_MAX = 2;

export const STATUS_POLL_MS = 2000;
/** Polling stops after this; a profile still `untested` stays shown as pending. */
export const STATUS_POLL_LIMIT_MS = 10 * 60 * 1000;

export const OFF_HOST_WARNING =
  "This profile sends prompt text off the host. Use it only with sample or anonymised " +
  "Opportunities until IT approves that data handling.";
export const OFF_HOST_NOTE = "Sends prompt text off the host";
export const NO_PROFILES = "No model profiles yet.";
export const NO_APPROVED_MODELS = "No approved models yet.";
export const NO_APPROVED_FOR_PROVIDER = "No model is approved for this provider yet.";

const STATES: Readonly<Record<ProfileState, { label: string; tone: PillTone }>> = {
  untested: { label: "Pending test", tone: "agent" },
  verified: { label: "Verified", tone: "resolved" },
  failed: { label: "Failed", tone: "blocker" },
  retired: { label: "Retired", tone: "neutral" },
};

export function stateLabel(state: ProfileState): string {
  return STATES[state].label;
}

export function stateTone(state: ProfileState): PillTone {
  return STATES[state].tone;
}

/** A test is queued or running: the list is re-read until it finishes. */
export function isPending(profile: ModelProfile): boolean {
  return profile.state === "untested";
}

/** `pollStopped`: polling gave up, so a pending test may have died with its job. */
export function canRetest(profile: ModelProfile, pollStopped = false): boolean {
  return profile.state === "failed" || (profile.state === "untested" && pollStopped);
}

export function canRetire(profile: ModelProfile): boolean {
  return profile.state !== "retired";
}

/** The temperature or the reasoning effort, whichever the profile sends. */
export function samplingLabel(profile: ModelProfile): string {
  return profile.reasoning_effort
    ? `Reasoning effort ${profile.reasoning_effort}`
    : `Temperature ${profile.temperature ?? DEFAULT_TEMPERATURE}`;
}

/** The latest test result in plain words, or null before one. Codes and timings only. */
export const SEEDED_RESULT = "Seeded, not tested";

/** The latest live test's outcome. A `verified` profile with no test (one a migration seeds)
 * says so; null when there is no result yet. */
export function testResult(profile: ModelProfile): string | null {
  if (profile.state === "verified" && profile.latency_ms === null) return SEEDED_RESULT;
  if (profile.state === "untested" || profile.latency_ms === null) return null;
  const took = `${profile.latency_ms.toLocaleString("en-GB")} ms`;
  return profile.error_code ? `${profile.error_code} after ${took}` : `Passed in ${took}`;
}

export function modelsFor(models: readonly ApprovedModel[], provider: Provider): string[] {
  return models.filter((m) => m.provider === provider).map((m) => m.model);
}

export function upsertProfile(
  profiles: readonly ModelProfile[],
  next: ModelProfile,
): ModelProfile[] {
  return profiles.some((p) => p.id === next.id)
    ? profiles.map((p) => (p.id === next.id ? next : p))
    : [next, ...profiles];
}

/** The reason a field can't be saved, or null. Mirrors the API's rules; the API decides. */
export function nameError(value: string): string | null {
  const name = value.trim();
  if (!name) return "The name is required.";
  if (name.length > NAME_MAX) return `The name must be at most ${NAME_MAX} characters.`;
  if (!/^[a-z0-9][a-z0-9._-]*$/.test(name)) {
    return "Use lowercase letters, digits, dots, hyphens or underscores.";
  }
  return null;
}

export function numCtxError(value: string): string | null {
  const size = Number(value);
  if (!Number.isInteger(size) || size < NUM_CTX_MIN || size > NUM_CTX_MAX) {
    return `The context size must be a whole number from ${NUM_CTX_MIN} to ${NUM_CTX_MAX}.`;
  }
  return null;
}

export function temperatureError(value: string): string | null {
  const temperature = Number(value);
  if (value.trim() === "" || Number.isNaN(temperature)) return "The temperature is required.";
  if (temperature < 0 || temperature > TEMPERATURE_MAX) {
    return `The temperature must be from 0 to ${TEMPERATURE_MAX}.`;
  }
  return null;
}
