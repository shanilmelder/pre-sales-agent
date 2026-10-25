import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AGENT_STALE,
  DISABLE_EFFECT,
  ENABLE_EFFECT,
  EVAL_ONLY_NOTE,
  SAME_VERSION,
  type AgentConfigVersion,
  type RegistryAgent,
} from "@/lib/admin";
import { configVersion, OPTIONS, registryAgent } from "@/test/agent-fixtures";
import { axeViolations } from "@/test/axe";

const actions = vi.hoisted(() => ({
  loadAgent: vi.fn(),
  loadConfigOptions: vi.fn(),
  createConfigVersion: vi.fn(),
  setAgentStatus: vi.fn(),
}));
vi.mock("@/app/admin/agents/actions", () => actions);

import { LiveRegionProvider } from "../shell/live-region";
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders } from "../shell/shell-context";
import { AgentsAdmin } from "./agents-admin";

const V1 = configVersion(1);
const V2 = configVersion(2, { model_profile: "local-chat", prompt_version: 2 });
const PM = registryAgent(1, "PM Agent", V2, { row_version: 2 });
const INTAKE = registryAgent(2, "Intake Agent", configVersion(1, {}, "intake_agent"));
const SECURITY = registryAgent(3, "Security Agent", configVersion(1, {}, "security_agent"));

/** What `loadAgent` returns per agent id: the Agent and its versions, newest first. */
let stored: Record<string, { agent: RegistryAgent; versions: AgentConfigVersion[] }>;

function ui(agents: RegistryAgent[] = [PM, INTAKE, SECURITY]) {
  return (
    <ShellProviders singleKeyShortcuts>
      <LiveRegionProvider>
        <button type="button" id={RIGHT_PANE_TOGGLE_ID}>
          Toggle
        </button>
        <AgentsAdmin initialAgents={agents} />
        <RightPane />
      </LiveRegionProvider>
    </ShellProviders>
  );
}

const pane = () => screen.getByRole("complementary", { name: "Details" });
const rowButton = (name: string) =>
  within(screen.getByRole("table", { name: "Agents" })).getByRole("button", { name });
const rowOf = (name: string) => rowButton(name).closest('[role="row"]') as HTMLElement;
const historyItems = () =>
  within(within(pane()).getByRole("region", { name: "Config history" })).getAllByRole("listitem");

async function openPm(u: ReturnType<typeof userEvent.setup>) {
  await u.click(rowButton("PM Agent"));
  await waitFor(() => expect(historyItems().length).toBeGreaterThan(0));
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  stored = {
    pm_agent: { agent: PM, versions: [V2, V1] },
    intake_agent: { agent: INTAKE, versions: [INTAKE.current_config] },
    security_agent: { agent: SECURITY, versions: [SECURITY.current_config] },
  };
  actions.loadAgent.mockImplementation(async (id: string) => ({ kind: "ok", ...stored[id] }));
  actions.loadConfigOptions.mockResolvedValue({ kind: "ok", options: OPTIONS });
});

describe("AgentsAdmin", () => {
  it("j and Enter open the second row's inspector; closing returns focus to the row", async () => {
    const u = userEvent.setup();
    render(ui());
    await u.tab(); // Toggle
    await u.tab(); // the first row
    expect(document.activeElement).toBe(rowButton("PM Agent"));
    await u.keyboard("j");
    expect(document.activeElement).toBe(rowButton("Intake Agent"));
    await u.keyboard("{Enter}");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(pane()).getByRole("heading", { name: "Intake Agent" }),
      ),
    );
    expect(rowButton("Intake Agent").getAttribute("aria-current")).toBe("true");
    expect(rowButton("PM Agent").getAttribute("aria-current")).toBe(null);
    await u.click(within(pane()).getByRole("button", { name: "Close right pane" }));
    await waitFor(() => expect(document.activeElement).toBe(rowButton("Intake Agent")));
  });

  it("the inspector shows the current config and the history newest first", async () => {
    const u = userEvent.setup();
    const { container } = render(ui());
    await openPm(u);
    const details = within(pane()).getByRole("region", { name: "Current config" });
    for (const text of ["pm_agent", "Enabled", "v2", "0.2.0", "local-chat", "None"]) {
      expect(within(details).getAllByText(text).length).toBeGreaterThan(0);
    }
    expect(within(details).getByText("Prompt version").nextSibling?.textContent).toBe("v2");
    const [newest, first] = historyItems();
    expect(newest.textContent).toContain("v2 · 0.2.0 (current)");
    expect(newest.textContent).toContain("[ADMIN]");
    expect(newest.textContent).toContain("Reason: Reason 2");
    expect(newest.textContent).toContain("Changed: model profile, prompt version");
    expect(first.textContent).toContain("System");
    expect(first.textContent).toContain("Reason: —");
    expect(within(first).getByRole("button", { name: "Restore this version (v1)" })).toBeTruthy();
    expect(within(newest).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("compares two picked versions: changed fields only, permissions granted/removed", async () => {
    const v1 = configVersion(1, { tool_permissions: ["gaps.gap.list"] });
    const v3 = configVersion(3, {
      prompt_version: 2,
      tool_permissions: ["intake.requirement.list"],
    });
    stored.pm_agent = {
      agent: { ...PM, current_config: v3 },
      versions: [v3, configVersion(2, { tool_permissions: ["gaps.gap.list"] }), v1],
    };
    const u = userEvent.setup();
    const { container } = render(ui([{ ...PM, current_config: v3 }]));
    await openPm(u);
    const compare = within(pane()).getByRole("region", { name: "Compare versions" });
    await u.selectOptions(within(compare).getByRole("combobox", { name: "From" }), "1");
    await u.selectOptions(within(compare).getByRole("combobox", { name: "To" }), "3");
    const diff = within(compare).getByTestId("agent-config-diff");
    expect(
      Array.from(diff.querySelectorAll("[data-changed]")).map((el) =>
        el.getAttribute("data-changed"),
      ),
    ).toEqual(["prompt_version", "tool_permissions"]);
    const prompt = diff.querySelector('[data-changed="prompt_version"]') as HTMLElement;
    expect(prompt.textContent).toBe("Prompt version−Before: v1+After: v2");
    const tools = diff.querySelector('[data-changed="tool_permissions"]') as HTMLElement;
    expect(tools.textContent).toBe(
      "Tool permissions−Removed: gaps.gap.list (read)+Granted: intake.requirement.list (read)",
    );
    for (const line of diff.querySelectorAll("p")) {
      expect(line.className).toContain("bg-diff-tint");
      expect(line.querySelector('[aria-hidden="true"]')?.textContent).toMatch(/^[−+]$/);
    }
    expect(await axeViolations(container)).toEqual([]);
    await u.selectOptions(within(compare).getByRole("combobox", { name: "From" }), "3");
    expect(within(compare).getByText(SAME_VERSION)).toBeTruthy();
    expect(within(compare).queryByTestId("agent-config-diff")).toBeNull();
  });

  it("saves a new version with a reason; the row and history show it", async () => {
    const v3 = configVersion(3, { semver: "0.2.1", prompt_version: 1, reason: "Back to v1" });
    // The API returns the effective model of the new current version.
    const saved = {
      ...PM,
      row_version: 3,
      current_config: v3,
      effective_model: { ...PM.effective_model, profile: v3.model_profile },
    };
    actions.createConfigVersion.mockImplementation(async () => {
      stored.pm_agent = { agent: saved, versions: [v3, V2, V1] };
      return { kind: "ok", agent: saved };
    });
    const u = userEvent.setup();
    const { container } = render(ui());
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "New version" }));
    const form = within(pane()).getByRole("form", { name: "New version" });
    // The profile picker lists the deployed profiles once the options are loaded.
    await waitFor(() =>
      expect(within(form).getByRole("option", { name: "demo-chat" })).toBeTruthy(),
    );
    const save = within(form).getByRole("button", { name: "Save version" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    const reason = within(form).getByRole("textbox", { name: "Reason (required)" });
    await u.type(reason, "x");
    await u.clear(reason);
    expect(within(form).getByText("Give a reason for this version.")).toBeTruthy();
    expect(reason.getAttribute("aria-invalid")).toBe("true");
    expect(save.disabled).toBe(true);
    expect(await axeViolations(container)).toEqual([]);

    expect(
      (within(form).getByRole("textbox", { name: "Semver" }) as HTMLInputElement).value,
    ).toBe("0.2.1");
    await u.selectOptions(within(form).getByRole("combobox", { name: "Prompt version" }), "1");
    await u.click(within(form).getByRole("checkbox", { name: "gaps.gap.list" }));
    await u.type(reason, "  Back to v1 ");
    expect(save.disabled).toBe(false);
    await u.click(save);

    await waitFor(() => expect(within(rowOf("PM Agent")).getByText("0.2.1")).toBeTruthy());
    expect(actions.createConfigVersion).toHaveBeenCalledWith({
      agentId: "pm_agent",
      rowVersion: 2,
      config: {
        semver: "0.2.1",
        model_profile: "local-chat",
        prompt_version: 1,
        input_schema_version: 1,
        output_schema_version: 1,
        tool_permissions: ["gaps.gap.list"],
        budgets: {},
      },
      reason: "  Back to v1 ",
      restoredFromVersion: null,
    });
    expect(within(rowOf("PM Agent")).getByText("demo-chat")).toBeTruthy();
    await waitFor(() => expect(historyItems()).toHaveLength(3));
    expect(historyItems()[0].textContent).toContain("v3 · 0.2.1 (current)");
    expect(within(pane()).queryByRole("form")).toBeNull();
  });

  it("the permission picker offers only read tools, each labelled Read", async () => {
    actions.loadConfigOptions.mockResolvedValue({
      kind: "ok",
      options: {
        ...OPTIONS,
        tool_permissions: [
          ...OPTIONS.tool_permissions,
          { action: "knowledge.chunk.read", category: "read" },
          // Never sent by the API (it lists read tools only); the picker drops it anyway.
          { action: "gaps.clarification_question.send", category: "send" },
        ],
      },
    });
    const u = userEvent.setup();
    const { container } = render(ui());
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "New version" }));
    const form = within(pane()).getByRole("form", { name: "New version" });
    const group = within(form).getByRole("group", { name: "Tool permissions (read actions only)" });
    await waitFor(() => expect(within(group).getAllByRole("checkbox")).toHaveLength(3));
    const boxes = within(group).getAllByRole("checkbox");
    expect(boxes.map((box) => box.closest("div")?.querySelector("label")?.textContent)).toEqual([
      "gaps.gap.list",
      "intake.requirement.list",
      "knowledge.chunk.read",
    ]);
    for (const box of boxes) {
      const described = document.getElementById(box.getAttribute("aria-describedby") ?? "");
      expect(described?.textContent).toBe("Read");
      expect(described?.getAttribute("data-category")).toBe("read");
      expect(described?.querySelector("svg")).toBeTruthy(); // an icon and a label
    }
    expect(within(group).queryByText("gaps.clarification_question.send")).toBeNull();
    for (const label of ["Write", "Delete", "Send", "Approve"]) {
      expect(within(group).queryByText(label)).toBeNull();
    }
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a 412 shows the concurrent-edit message with Reload and keeps the form's input", async () => {
    actions.createConfigVersion.mockResolvedValue({ kind: "stale" });
    const u = userEvent.setup();
    render(ui());
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "New version" }));
    const form = within(pane()).getByRole("form", { name: "New version" });
    const reason = within(form).getByRole("textbox", { name: "Reason (required)" });
    await waitFor(() => expect(actions.loadConfigOptions).toHaveBeenCalled());
    await u.type(reason, "Tighter prompt");
    await u.click(within(form).getByRole("button", { name: "Save version" }));
    const alert = await within(pane()).findByText(AGENT_STALE);
    expect(alert.closest('[data-slot="inline-alert"]')).toBeTruthy();
    const reload = within(pane()).getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    expect(
      (within(form).getByRole("button", { name: "Save version" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    // Meanwhile another administrator saved v3 (back on demo-chat).
    const v3 = configVersion(3, { semver: "0.3.0" });
    const theirs = { ...PM, row_version: 3, current_config: v3 };
    stored.pm_agent = { agent: theirs, versions: [v3, V2, V1] };
    const calls = actions.loadAgent.mock.calls.length;
    await u.click(reload);
    await waitFor(() => expect(within(pane()).queryByText(AGENT_STALE)).toBeNull());
    expect(actions.loadAgent.mock.calls.length).toBeGreaterThan(calls);
    expect((reason as HTMLTextAreaElement).value).toBe("Tighter prompt");
    // The form starts again from their version, so saving can't revert it.
    expect(
      (within(form).getByRole("combobox", { name: "Model profile" }) as HTMLSelectElement).value,
    ).toBe("demo-chat");
    expect((within(form).getByRole("textbox", { name: "Semver" }) as HTMLInputElement).value).toBe(
      "0.3.1",
    );
  });

  it("an eval-only Agent has no Enable or Disable, only a note", async () => {
    const evalOnly = { ...PM, status: "eval_only" as const };
    stored.pm_agent = { agent: evalOnly, versions: [V2, V1] };
    const u = userEvent.setup();
    render(ui([evalOnly]));
    await openPm(u);
    expect(within(pane()).getByText(EVAL_ONLY_NOTE)).toBeTruthy();
    expect(within(pane()).queryByRole("button", { name: "Enable" })).toBeNull();
    expect(within(pane()).queryByRole("button", { name: "Disable" })).toBeNull();
  });

  it("a failed history load shows an error with Retry, which loads it again", async () => {
    actions.loadAgent.mockResolvedValueOnce({ kind: "error" });
    const u = userEvent.setup();
    render(ui());
    await u.click(rowButton("PM Agent"));
    const history = within(pane()).getByRole("region", { name: "Config history" });
    const failed = "The config history could not be loaded.";
    expect(await within(history).findByText(failed)).toBeTruthy();
    expect(within(history).queryByText("Loading…")).toBeNull();
    await u.click(within(history).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(historyItems()).toHaveLength(2));
    expect(within(history).queryByText(failed)).toBeNull();
  });

  it("j/k and the arrow keys move between rows", async () => {
    const u = userEvent.setup();
    render(ui());
    await u.tab(); // Toggle
    await u.tab(); // the first row
    expect(document.activeElement).toBe(rowButton("PM Agent"));
    await u.keyboard("k"); // stays on the first row
    expect(document.activeElement).toBe(rowButton("PM Agent"));
    await u.keyboard("j");
    expect(document.activeElement).toBe(rowButton("Intake Agent"));
    await u.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(rowButton("Security Agent"));
    await u.keyboard("k");
    expect(document.activeElement).toBe(rowButton("Intake Agent"));
    await u.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(rowButton("PM Agent"));
  });

  it("a restore prefills the form from the version; the API's 422 shows inline", async () => {
    const detail = "Not in the deployed manifest for pm_agent: prompt v1.";
    actions.createConfigVersion.mockResolvedValue({ kind: "invalid", detail });
    const u = userEvent.setup();
    render(ui());
    await openPm(u);
    await u.click(within(historyItems()[1]).getByRole("button", { name: /Restore this version/ }));
    const form = within(pane()).getByRole("form", { name: "Restore version 1" });
    await waitFor(() => expect(actions.loadConfigOptions).toHaveBeenCalled());
    expect((within(form).getByRole("textbox", { name: "Semver" }) as HTMLInputElement).value).toBe(
      "0.2.1",
    );
    expect(
      (within(form).getByRole("combobox", { name: "Model profile" }) as HTMLSelectElement).value,
    ).toBe("demo-chat");
    expect(
      (within(form).getByRole("combobox", { name: "Prompt version" }) as HTMLSelectElement).value,
    ).toBe("1");
    for (const name of ["Model profile", "Prompt version", "Output schema version"]) {
      expect((within(form).getByRole("combobox", { name }) as HTMLSelectElement).disabled).toBe(
        true,
      );
    }
    await u.type(within(form).getByRole("textbox", { name: "Reason (required)" }), "Roll back");
    await u.click(within(form).getByRole("button", { name: "Save restored version" }));
    expect(await within(form).findByRole("alert")).toHaveProperty("textContent", detail);
    expect(actions.createConfigVersion.mock.calls[0][0]).toMatchObject({
      restoredFromVersion: 1,
      reason: "Roll back",
      config: { model_profile: "demo-chat", prompt_version: 1 },
    });
    expect(within(rowOf("PM Agent")).getByText("0.2.0")).toBeTruthy();
  });

  it("a saved restore shows Restored from v1 in the history", async () => {
    const v3 = configVersion(3, { semver: "0.2.1", restored_from_version: 1, reason: "Roll back" });
    const saved = { ...PM, row_version: 3, current_config: v3 };
    actions.createConfigVersion.mockImplementation(async () => {
      stored.pm_agent = { agent: saved, versions: [v3, V2, V1] };
      return { kind: "ok", agent: saved };
    });
    const u = userEvent.setup();
    render(ui());
    await openPm(u);
    await u.click(within(historyItems()[1]).getByRole("button", { name: /Restore this version/ }));
    const form = within(pane()).getByRole("form", { name: "Restore version 1" });
    await waitFor(() => expect(actions.loadConfigOptions).toHaveBeenCalled());
    await u.type(within(form).getByRole("textbox", { name: "Reason (required)" }), "Roll back");
    await u.click(within(form).getByRole("button", { name: "Save restored version" }));
    await waitFor(() => expect(historyItems()).toHaveLength(3));
    expect(historyItems()[0].textContent).toContain("Restored from v1");
  });

  it("Disable states the effect in a confirm dialog, then shows Disabled", async () => {
    actions.setAgentStatus.mockResolvedValue({
      kind: "ok",
      agent: { ...PM, status: "disabled", row_version: 3 },
    });
    const u = userEvent.setup();
    render(ui());
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "Disable" }));
    const dialog = await screen.findByRole("dialog", { name: "Disable PM Agent?" });
    expect(within(dialog).getByText(DISABLE_EFFECT)).toBeTruthy();
    expect(await axeViolations(dialog)).toEqual([]);
    await u.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(within(rowOf("PM Agent")).getByText("Disabled")).toBeTruthy());
    expect(actions.setAgentStatus).toHaveBeenCalledWith({
      agentId: "pm_agent",
      rowVersion: 2,
      status: "disabled",
    });
    const pill = within(pane()).getAllByText("Disabled")[0].closest('[data-slot="pill"]');
    expect(pill?.querySelector("svg")).toBeTruthy();
  });

  it("Enable confirms with its effect, then shows Enabled", async () => {
    const disabled = { ...PM, status: "disabled" as const };
    stored.pm_agent = { agent: disabled, versions: [V2, V1] };
    actions.setAgentStatus.mockResolvedValue({
      kind: "ok",
      agent: { ...PM, status: "active", row_version: 3 },
    });
    const u = userEvent.setup();
    render(ui([disabled]));
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "Enable" }));
    const dialog = await screen.findByRole("dialog", { name: "Enable PM Agent?" });
    expect(within(dialog).getByText(ENABLE_EFFECT)).toBeTruthy();
    await u.click(within(dialog).getByRole("button", { name: "Enable" }));
    await waitFor(() => expect(within(rowOf("PM Agent")).getByText("Enabled")).toBeTruthy());
    expect(actions.setAgentStatus.mock.calls[0][0].status).toBe("active");
  });

  it("a 412 on Disable shows the concurrent-edit message and changes nothing", async () => {
    actions.setAgentStatus.mockResolvedValue({ kind: "stale" });
    const u = userEvent.setup();
    render(ui());
    await openPm(u);
    await u.click(within(pane()).getByRole("button", { name: "Disable" }));
    const dialog = await screen.findByRole("dialog", { name: "Disable PM Agent?" });
    await u.click(within(dialog).getByRole("button", { name: "Disable" }));
    expect(await within(pane()).findByText(AGENT_STALE)).toBeTruthy();
    expect(within(rowOf("PM Agent")).getByText("Enabled")).toBeTruthy();
  });
});
