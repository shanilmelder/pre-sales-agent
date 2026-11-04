import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";
import {
  NO_PROFILES,
  OFF_HOST_NOTE,
  OFF_HOST_WARNING,
  STATUS_POLL_LIMIT_MS,
  STATUS_POLL_MS,
  type ApprovedModel,
  type ModelProfile,
} from "@/lib/model-profiles";

const actions = vi.hoisted(() => ({
  loadProfiles: vi.fn(),
  createProfile: vi.fn(),
  retestProfile: vi.fn(),
  retireProfile: vi.fn(),
  addApprovedModel: vi.fn(),
  removeApprovedModel: vi.fn(),
}));
vi.mock("@/app/admin/model-profiles/actions", () => actions);

import { LiveRegionProvider } from "../shell/live-region";
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders } from "../shell/shell-context";
import { ModelProfileApproved } from "./model-profile-approved";
import { ModelProfilesAdmin } from "./model-profiles-admin";

const APPROVED: ApprovedModel[] = [
  { id: "a1", provider: "ollama", model: "gpt-oss:120b-cloud", created_at: "2026-11-02T09:00:00Z" },
  { id: "a2", provider: "openai", model: "gpt-4.1-mini", created_at: "2026-11-02T09:00:00Z" },
  { id: "a3", provider: "anthropic", model: "claude-opus-5-5", created_at: "2026-11-02T09:00:00Z" },
  {
    id: "a4",
    provider: "anthropic",
    model: "claude-sonnet-5-5",
    created_at: "2026-11-02T09:00:00Z",
  },
];

function profile(over: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "00000000-0000-7000-8000-000000000001",
    name: "custom-chat",
    provider: "ollama",
    model: "gpt-oss:120b-cloud",
    num_ctx: 32768,
    temperature: 0.1,
    reasoning_effort: null,
    state: "verified",
    error_code: null,
    latency_ms: 900,
    tested_at: "2026-11-02T10:00:00Z",
    created_at: "2026-11-02T09:00:00Z",
    ...over,
  };
}

function ui(profiles: ModelProfile[] = [profile()]) {
  return (
    <ShellProviders singleKeyShortcuts>
      <LiveRegionProvider>
        <button type="button" id={RIGHT_PANE_TOGGLE_ID}>
          Toggle
        </button>
        <ModelProfilesAdmin initialProfiles={profiles} approved={APPROVED} />
        <RightPane />
      </LiveRegionProvider>
    </ShellProviders>
  );
}

beforeEach(() => {
  Object.values(actions).forEach((mock) => mock.mockReset());
});

describe("ModelProfilesAdmin", () => {
  it("warns on each profile that it sends prompt text off the host", async () => {
    const { container } = render(ui());
    expect(screen.getByText(OFF_HOST_NOTE)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the empty state", () => {
    render(ui([]));
    expect(screen.getByText(NO_PROFILES)).toBeTruthy();
  });

  it("warns on the form and creates a profile, shown as pending", async () => {
    const user = userEvent.setup();
    actions.createProfile.mockResolvedValue({
      kind: "ok",
      profile: profile({ id: "00000000-0000-7000-8000-000000000002", name: "new-one", state: "untested" }),
    });
    actions.loadProfiles.mockResolvedValue({ kind: "ok", profiles: [] });
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    expect(await screen.findByText(OFF_HOST_WARNING)).toBeTruthy();
    await user.type(screen.getByLabelText("Name"), "new-one");
    await user.click(screen.getByRole("button", { name: "Create and test" }));

    await waitFor(() => expect(actions.createProfile).toHaveBeenCalledTimes(1));
    expect(actions.createProfile).toHaveBeenCalledWith({
      name: "new-one",
      provider: "ollama",
      model: "gpt-oss:120b-cloud",
      num_ctx: 32768,
      temperature: 0.1,
      reasoning_effort: null,
    });
    expect(await screen.findByText("Pending test")).toBeTruthy();
  });

  it("sends a reasoning effort instead of a temperature", async () => {
    const user = userEvent.setup();
    actions.createProfile.mockResolvedValue({ kind: "invalid", detail: "Not approved." });
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    await user.type(await screen.findByLabelText("Name"), "reasoner");
    await user.selectOptions(screen.getByLabelText("Provider"), "openai");
    await user.selectOptions(screen.getByLabelText("Reasoning effort"), "high");
    expect(screen.queryByLabelText("Temperature")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Create and test" }));

    await waitFor(() =>
      expect(actions.createProfile).toHaveBeenCalledWith({
        name: "reasoner",
        provider: "openai",
        model: "gpt-4.1-mini",
        num_ctx: 32768,
        temperature: null,
        reasoning_effort: "high",
      }),
    );
    expect(await screen.findByText("Not approved.")).toBeTruthy();
  });

  it("sends a Claude profile's effort, default medium, with no temperature or None option", async () => {
    const user = userEvent.setup();
    actions.createProfile.mockResolvedValue({ kind: "invalid", detail: "Not approved." });
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    await user.type(await screen.findByLabelText("Name"), "claude");
    await user.selectOptions(screen.getByLabelText("Provider"), "anthropic");

    const effort = screen.getByLabelText("Reasoning effort") as HTMLSelectElement;
    expect(effort.value).toBe("medium");
    expect(within(effort).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "low",
      "medium",
      "high",
    ]);
    expect(screen.queryByLabelText("Temperature")).toBeNull();
    const models = screen.getByLabelText("Model ID");
    expect(within(models).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "claude-opus-5-5",
      "claude-sonnet-5-5",
    ]);

    await user.click(screen.getByRole("button", { name: "Create and test" }));

    await waitFor(() =>
      expect(actions.createProfile).toHaveBeenCalledWith({
        name: "claude",
        provider: "anthropic",
        model: "claude-opus-5-5",
        num_ctx: 32768,
        temperature: null,
        reasoning_effort: "medium",
      }),
    );
  });

  it("carries the effort across providers and clears it on ollama", async () => {
    const user = userEvent.setup();
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    const provider = await screen.findByLabelText("Provider");
    await user.selectOptions(provider, "openai");
    const effort = () => screen.getByLabelText("Reasoning effort") as HTMLSelectElement;
    expect(effort().value).toBe("");
    expect(screen.getByLabelText("Temperature")).toBeTruthy();

    await user.selectOptions(provider, "anthropic");
    expect(effort().value).toBe("medium");
    expect(screen.queryByLabelText("Temperature")).toBeNull();

    await user.selectOptions(provider, "ollama");
    expect(screen.queryByLabelText("Reasoning effort")).toBeNull();
    expect(screen.getByLabelText("Temperature")).toBeTruthy();

    await user.selectOptions(provider, "openai");
    expect(effort().value).toBe("");
  });

  it("clears the effort leaving Claude, so openai shows None and Temperature", async () => {
    const user = userEvent.setup();
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    const provider = await screen.findByLabelText("Provider");
    await user.selectOptions(provider, "anthropic");
    await user.selectOptions(provider, "openai");

    const effort = screen.getByLabelText("Reasoning effort") as HTMLSelectElement;
    expect(effort.value).toBe("");
    expect(effort.selectedOptions[0].textContent).toBe("None (use temperature)");
    expect(screen.getByLabelText("Temperature")).toBeTruthy();
  });

  it("keeps a chosen effort moving to Claude", async () => {
    const user = userEvent.setup();
    render(ui([]));

    await user.click(screen.getByRole("button", { name: "New profile" }));
    const provider = await screen.findByLabelText("Provider");
    await user.selectOptions(provider, "openai");
    await user.selectOptions(screen.getByLabelText("Reasoning effort"), "high");
    await user.selectOptions(provider, "anthropic");

    expect((screen.getByLabelText("Reasoning effort") as HTMLSelectElement).value).toBe("high");
  });

  it("re-reads the list while a test is pending and shows the result", async () => {
    vi.useFakeTimers();
    try {
      actions.loadProfiles.mockResolvedValue({
        kind: "ok",
        profiles: [profile({ state: "failed", error_code: "timeout" })],
      });
      render(ui([profile({ state: "untested", latency_ms: null, tested_at: null })]));
      expect(screen.getByText("Pending test")).toBeTruthy();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(STATUS_POLL_MS);
      });

      expect(screen.getByText("Failed")).toBeTruthy();
      expect(screen.getByText("timeout after 900 ms")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops polling at the limit, then offers a retest of the pending profile", async () => {
    vi.useFakeTimers();
    try {
      const pending = profile({ state: "untested", latency_ms: null, tested_at: null });
      actions.loadProfiles.mockResolvedValue({ kind: "ok", profiles: [pending] });
      render(ui([pending]));
      expect(screen.queryByRole("button", { name: "Test custom-chat again" })).toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(STATUS_POLL_LIMIT_MS + STATUS_POLL_MS);
      });
      const calls = actions.loadProfiles.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(STATUS_POLL_MS * 3);
      });

      expect(actions.loadProfiles.mock.calls.length).toBe(calls);
      expect(screen.getByRole("button", { name: "Test custom-chat again" })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not poll when nothing is pending", async () => {
    vi.useFakeTimers();
    try {
      render(ui());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(STATUS_POLL_MS * 3);
      });
      expect(actions.loadProfiles).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("tests a failed profile again", async () => {
    const user = userEvent.setup();
    const failed = profile({ state: "failed", error_code: "http_404" });
    actions.retestProfile.mockResolvedValue({
      kind: "ok",
      profile: { ...failed, state: "untested", error_code: null, latency_ms: null },
    });
    actions.loadProfiles.mockResolvedValue({ kind: "ok", profiles: [] });
    render(ui([failed]));

    await user.click(screen.getByRole("button", { name: "Test custom-chat again" }));

    expect(await screen.findByText("Pending test")).toBeTruthy();
    expect(actions.retestProfile).toHaveBeenCalledWith(failed.id);
  });

  it("confirms retiring and shows why a pinned profile can't be", async () => {
    const user = userEvent.setup();
    actions.retireProfile.mockResolvedValue({
      kind: "conflict",
      detail: "custom-chat is pinned by an Agent's current config version.",
    });
    render(ui());

    await user.click(screen.getByRole("button", { name: "Retire custom-chat" }));
    await user.click(screen.getByRole("button", { name: "Confirm retiring custom-chat" }));

    expect(await screen.findByText(/is pinned by an Agent/)).toBeTruthy();
    expect(screen.getByText("Verified")).toBeTruthy();
  });

  it("offers nothing on a retired profile", () => {
    render(ui([profile({ state: "retired" })]));
    const row = screen.getByRole("row", { name: /custom-chat/ });
    expect(within(row).queryByRole("button")).toBeNull();
  });
});

describe("ModelProfileApproved", () => {
  function approved() {
    return (
      <ShellProviders singleKeyShortcuts>
        <LiveRegionProvider>
          <ModelProfileApproved initialModels={APPROVED} />
        </LiveRegionProvider>
      </ShellProviders>
    );
  }

  it("adds a model", async () => {
    const user = userEvent.setup();
    actions.addApprovedModel.mockResolvedValue({
      kind: "ok",
      model: { id: "a3", provider: "ollama", model: "llama4", created_at: "2026-11-02T09:00:00Z" },
    });
    render(approved());

    await user.type(screen.getByLabelText("Model ID"), "llama4");
    await user.click(screen.getByRole("button", { name: "Approve model" }));

    expect(await screen.findByText("llama4")).toBeTruthy();
    expect(actions.addApprovedModel).toHaveBeenCalledWith({ provider: "ollama", model: "llama4" });
  });

  it("offers anthropic", async () => {
    const user = userEvent.setup();
    actions.addApprovedModel.mockResolvedValue({
      kind: "ok",
      model: {
        id: "a5",
        provider: "anthropic",
        model: "claude-next",
        created_at: "2026-11-02T09:00:00Z",
      },
    });
    render(approved());

    await user.selectOptions(screen.getByLabelText("Provider"), "anthropic");
    await user.type(screen.getByLabelText("Model ID"), "claude-next");
    await user.click(screen.getByRole("button", { name: "Approve model" }));

    expect(await screen.findByText("claude-next")).toBeTruthy();
    expect(actions.addApprovedModel).toHaveBeenCalledWith({
      provider: "anthropic",
      model: "claude-next",
    });
  });

  it("shows the API's sentence for a duplicate", async () => {
    const user = userEvent.setup();
    actions.addApprovedModel.mockResolvedValue({ kind: "conflict", detail: "Already approved." });
    render(approved());

    await user.type(screen.getByLabelText("Model ID"), "gpt-4.1-mini");
    await user.click(screen.getByRole("button", { name: "Approve model" }));

    expect(await screen.findByText("Already approved.")).toBeTruthy();
  });

  it("removes a model", async () => {
    const user = userEvent.setup();
    actions.removeApprovedModel.mockResolvedValue({ kind: "ok" });
    render(approved());

    await user.click(screen.getByRole("button", { name: "Remove gpt-4.1-mini" }));

    await waitFor(() => expect(screen.queryByText("gpt-4.1-mini")).toBeNull());
  });
});
