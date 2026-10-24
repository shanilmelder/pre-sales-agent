// Users & roles (read-only since Story 1.9): roles are managed in Auth0. Safe on server and
// client.
import type { components } from "@/lib/api/client";

export type AdminUser = components["schemas"]["AdminUser"];

const AUTH0_DASHBOARD = "https://manage.auth0.com/";

/** The Auth0 dashboard's user list for the tenant behind `domain` (e.g.
 * `psa.eu.auth0.com` -> `.../dashboard/eu/psa/users`). A custom or missing domain can't be
 * mapped to a tenant, so it links to the dashboard home. */
export function auth0UsersUrl(domain: string | undefined): string {
  const host = (domain ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "")
    .toLowerCase();
  const match = /^([a-z0-9-]+)(?:\.([a-z0-9]+))?\.auth0\.com$/.exec(host);
  if (!match) return AUTH0_DASHBOARD;
  const [, tenant, region = "us"] = match;
  return `${AUTH0_DASHBOARD}dashboard/${region}/${tenant}/users`;
}

export const ROLES_AS_OF_NOTE =
  "Roles are managed in Auth0 and shown as of each person's last sign-in.";

export const ROLES_SHOWN_NOTE = "Roles are shown as of each person's last sign-in.";

export const NO_ROLES_YET = "No roles yet";

export const USERS_FOOTNOTE =
  "First sign-in creates a user with no roles. Roles are managed in Auth0, and Opportunity access is set on each Opportunity.";

// --- Agents (read-only registry) ---------------------------------------------------------------

export type RegistryAgent = components["schemas"]["RegistryAgent"];
export type AgentStatus = components["schemas"]["AgentStatus"];

export const NO_AGENTS = "No agents registered yet.";

export const AGENTS_FOOTNOTE =
  "No agent can send customer communication or approve. Disabled agents receive no tasks.";

const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  active: "Enabled",
  disabled: "Disabled",
  eval_only: "Eval only",
};

export function agentStatusLabel(status: AgentStatus): string {
  return AGENT_STATUS_LABELS[status];
}

/** The Agent's tool permissions as one line, "None" when it has none. */
export function toolPermissionsLabel(permissions: readonly string[]): string {
  return permissions.length > 0 ? permissions.join(", ") : "None";
}

// --- Agent config history (Story 7.3) -----------------------------------------------------------

export type AgentConfigVersion = components["schemas"]["AgentConfigVersion"];
export type AgentConfigOptions = components["schemas"]["AgentConfigOptions"];

/** The config fields an administrator edits, in display order, with their labels. */
export const CONFIG_FIELDS = [
  ["model_profile", "Model profile"],
  ["prompt_version", "Prompt version"],
  ["input_schema_version", "Input schema version"],
  ["output_schema_version", "Output schema version"],
  ["tool_permissions", "Tool permissions"],
  ["budgets", "Budgets"],
] as const;

export type ConfigField = (typeof CONFIG_FIELDS)[number][0];
type ConfigValues = Pick<AgentConfigVersion, ConfigField>;

export const AGENT_REASON_MAX = 500;
export const AGENT_BUDGET_KEYS_MAX = 20;

export const AGENT_STALE = "Changed by another administrator since you opened it.";

export const DISABLE_EFFECT =
  "Disabled Agents get no new tasks. A run that reaches this Agent waits for a person to continue without it; running tasks finish.";

export const EVAL_ONLY_NOTE = "Used by evaluations only; never planned into runs.";

export const ENABLE_EFFECT = "Enabled Agents get new tasks from the next run.";

export const SAME_VERSION = "Pick two different versions.";

export const NO_REASON = "—";

/** JSON with object keys sorted, so equal budgets compare equal whatever their key order. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function sameField(field: ConfigField, a: ConfigValues, b: ConfigValues): boolean {
  if (field === "tool_permissions") {
    return canonical([...a.tool_permissions].sort()) === canonical([...b.tool_permissions].sort());
  }
  return canonical(a[field]) === canonical(b[field]);
}

/** The config fields that differ between two versions, in display order. Pure. */
export function changedFields(a: ConfigValues, b: ConfigValues): ConfigField[] {
  return CONFIG_FIELDS.map(([field]) => field).filter((field) => !sameField(field, a, b));
}

export function fieldLabel(field: ConfigField): string {
  return CONFIG_FIELDS.find(([key]) => key === field)?.[1] ?? field;
}

/** "Changed: model profile, prompt version" against the version before; null for the first. */
export function changedSummary(version: ConfigValues, previous: ConfigValues | null): string {
  if (!previous) return "First version";
  const fields = changedFields(previous, version);
  if (fields.length === 0) return "No config changes";
  return `Changed: ${fields.map((f) => fieldLabel(f).toLowerCase()).join(", ")}`;
}

/** Who created the version: its author, "System" for a seeded version. */
export function authorLabel(version: AgentConfigVersion): string {
  if (version.created_by_id === null) return "System";
  return version.created_by_name ?? "Unknown user";
}

/** A field's value as text. */
export function configValue(field: ConfigField, values: ConfigValues): string {
  switch (field) {
    case "tool_permissions":
      return toolPermissionsLabel(values.tool_permissions);
    case "budgets":
      return Object.keys(values.budgets).length > 0 ? canonical(values.budgets) : "None";
    case "model_profile":
      return values.model_profile;
    default:
      return `v${values[field]}`;
  }
}

// --- Tool permission categories (Story 7.4) ----------------------------------------------------

export type ToolPermissionOption = components["schemas"]["ToolPermissionOption"];
export type PermissionCategory = ToolPermissionOption["category"];

const CATEGORY_LABELS: Record<PermissionCategory, string> = {
  read: "Read",
  write: "Write",
  delete: "Delete",
  send: "Send",
  approve: "Approve",
};

export function categoryLabel(category: PermissionCategory): string {
  return CATEGORY_LABELS[category];
}

/** The options the permission picker offers: `read` actions only, by action name. */
export function grantableTools(options: readonly ToolPermissionOption[]): ToolPermissionOption[] {
  return options
    .filter((option) => option.category === "read")
    .sort((a, b) => (a.action < b.action ? -1 : a.action > b.action ? 1 : 0));
}

/** A permission with its category, as the diff shows it: "knowledge.chunk.read (read)".
 * Every stored permission is a `read` action: the registry refuses any other (Story 7.4). */
export function permissionWithCategory(
  action: string,
  category: PermissionCategory = "read",
): string {
  return `${action} (${category})`;
}

/** Permissions granted (in `after`, not `before`) and removed, each sorted. */
export function permissionChanges(
  before: readonly string[],
  after: readonly string[],
): { granted: string[]; removed: string[] } {
  return {
    granted: after.filter((p) => !before.includes(p)).sort(),
    removed: before.filter((p) => !after.includes(p)).sort(),
  };
}

/** The next patch version of a MAJOR.MINOR.PATCH semver ("0.2.3" -> "0.2.4"); unchanged when
 * it isn't one. */
export function nextPatch(semver: string): string {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(semver.trim());
  if (!match) return semver;
  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`;
}

/** The reason's error, or null when it is valid (required, at most 500 characters after
 * trimming, counted as the API counts them). */
export function reasonError(reason: string): string | null {
  const length = Array.from(reason.trim()).length;
  if (length === 0) return "Give a reason for this version.";
  if (length > AGENT_REASON_MAX) return `The reason can be at most ${AGENT_REASON_MAX} characters.`;
  return null;
}

const BUDGETS_NOT_OBJECT = 'Budgets must be a JSON object, e.g. {"max_tokens_per_run": 20000}.';

/** Budgets typed as JSON: an object of at most 20 keys. */
export function parseBudgets(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, value: {} };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { ok: false, error: BUDGETS_NOT_OBJECT };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: BUDGETS_NOT_OBJECT };
  }
  if (Object.keys(parsed).length > AGENT_BUDGET_KEYS_MAX) {
    return { ok: false, error: `A config can set at most ${AGENT_BUDGET_KEYS_MAX} budgets.` };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

/** Budgets as the textarea shows them: indented JSON, empty for none. */
export function budgetsText(budgets: Record<string, unknown>): string {
  return Object.keys(budgets).length > 0 ? JSON.stringify(budgets, null, 2) : "";
}

// --- Denied tool calls (Story 7.4) --------------------------------------------------------------

export type ToolDenial = components["schemas"]["ToolDenial"];
export type ToolDenialPage = components["schemas"]["ToolDenialPage"];
export type DenialReason = ToolDenial["reason"];

export const DENIALS_PATH = "/admin/agents/denials";

export const NO_DENIALS = "No denied tool calls.";

export const NO_MATCHING_DENIALS = "No denied tool calls match these filters.";

export const THRESHOLD_EXCEEDED = "Threshold exceeded";

export const DENIALS_FOOTNOTE =
  "Denied calls are blocked, audited and never retried. Ids only: no Opportunity names, prompts or Source text.";

const DENIAL_REASON_LABELS: Record<DenialReason, string> = {
  tool_not_permitted: "Not permitted",
  out_of_scope: "Out of scope",
  unknown_tool: "Unknown tool",
  not_allowlisted: "Not allowlisted",
};

export function denialReasonLabel(reason: DenialReason): string {
  return DENIAL_REASON_LABELS[reason];
}

/** "pm_agent@0.1.0", or the agent id alone when the calling version is unknown. */
export function agentAtVersion(denial: Pick<ToolDenial, "agent_id" | "semver">): string {
  return denial.semver ? `${denial.agent_id}@${denial.semver}` : denial.agent_id;
}

/** An id's first 8 characters, as the denial list shows it. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** The denial list filters in the URL query: all optional, combined with AND. */
export type DenialFilters = { agent_id?: string; from?: string; to?: string };

const DENIAL_FILTER_KEYS = ["agent_id", "from", "to"] as const;
const AGENT_ID_RE = /^[a-z][a-z0-9_]{0,63}$/;

/** A real calendar date as `YYYY-MM-DD`. */
export function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [, y, m, d] = match.map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

type SearchParams = Record<string, string | string[] | undefined>;

function firstParam(params: SearchParams | undefined, key: string): string | undefined {
  const value = params?.[key];
  return Array.isArray(value) ? value[0] : value;
}

/** The filters in `params`. Invalid values are dropped, so a hand-edited URL never gets a 422
 * from the API; a reversed range drops both dates. */
export function parseDenialFilters(params: SearchParams | undefined): DenialFilters {
  const filters: DenialFilters = {};
  const agent = firstParam(params, "agent_id")?.trim();
  if (agent && AGENT_ID_RE.test(agent)) filters.agent_id = agent;
  const from = firstParam(params, "from");
  const to = firstParam(params, "to");
  const validFrom = from && isCalendarDate(from) ? from : undefined;
  const validTo = to && isCalendarDate(to) ? to : undefined;
  if (!(validFrom && validTo && validFrom > validTo)) {
    if (validFrom) filters.from = validFrom;
    if (validTo) filters.to = validTo;
  }
  return filters;
}

export function hasDenialFilters(filters: DenialFilters): boolean {
  return DENIAL_FILTER_KEYS.some((key) => filters[key] !== undefined);
}

/** The denial list's URL with the filters (in a fixed order) and the page past the first. */
export function denialsHref(filters: DenialFilters, page = 1): string {
  const query = new URLSearchParams();
  for (const key of DENIAL_FILTER_KEYS) {
    const value = filters[key];
    if (value) query.set(key, value);
  }
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return text ? `${DENIALS_PATH}?${text}` : DENIALS_PATH;
}
