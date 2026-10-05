import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EstimateDraft, EstimateVersion } from "@/lib/estimates";
import { axeViolations } from "@/test/axe";

vi.mock("@/app/opportunities/actions", () => ({
  startEstimateDraft: vi.fn(),
  loadEstimate: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/estimate",
}));

import { ShellProviders } from "../shell/shell-context";
import { EstimateExport } from "./estimate-export";
import { EstimateHeader } from "./estimate-grid";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const fetchMock = vi.fn<typeof fetch>();
const clicked: { href: string; download: string }[] = [];

beforeEach(() => {
  fetchMock.mockReset();
  clicked.length = 0;
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:export");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push({ href: this.href, download: this.download });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function file(name = "acme-estimate-v2.xlsx"): Response {
  return new Response(new Blob(["PK"]), {
    status: 200,
    headers: { "Content-Type": XLSX, "Content-Disposition": `attachment; filename="${name}"` },
  });
}

function problem(status: number, code: string): Response {
  return new Response(JSON.stringify({ status, code, title: code, type: code }), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

function renderExport() {
  return render(
    <ShellProviders singleKeyShortcuts={false}>
      <EstimateExport opportunityId={OPP_ID} />
    </ShellProviders>,
  );
}

const exportButton = () => screen.getByRole("button", { name: /Export/ });

describe("EstimateExport", () => {
  it("offers Excel and Word from a keyboard-operable list, with no axe violations", async () => {
    const user = userEvent.setup();
    const { container } = renderExport();
    expect(exportButton().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("group", { name: "Export format" })).toBeNull();

    exportButton().focus();
    await user.keyboard("{Enter}");

    expect(exportButton().getAttribute("aria-expanded")).toBe("true");
    const excel = screen.getByRole("button", { name: "Excel (.xlsx)" });
    const word = screen.getByRole("button", { name: "Word (.docx)" });
    expect(document.activeElement).toBe(excel);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(word);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(excel);
    expect(await axeViolations(container)).toEqual([]);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Export format" })).toBeNull();
    expect(document.activeElement).toBe(exportButton());
  });

  it("downloads the chosen format with the server's file name", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(file());
    renderExport();

    await user.click(exportButton());
    await user.click(screen.getByRole("button", { name: "Excel (.xlsx)" }));

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/opportunities/${OPP_ID}/estimate-export?format=xlsx`,
      { credentials: "same-origin" },
    );
    expect(clicked[0]).toEqual({ href: "blob:export", download: "acme-estimate-v2.xlsx" });
    expect(screen.queryByText(/Export failed/)).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(exportButton()));
    expect((exportButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it("ArrowUp with no format focused goes to the last one", async () => {
    const user = userEvent.setup();
    renderExport();
    await user.click(exportButton());
    const group = screen.getByRole("group", { name: "Export format" });
    (document.activeElement as HTMLElement).blur();

    fireEvent.keyDown(group, { key: "ArrowUp" });

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Word (.docx)" }));
  });

  it("says why an export failed and retries the same format", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(problem(500, "internal_error"));
    const { container } = renderExport();

    await user.click(exportButton());
    await user.click(screen.getByRole("button", { name: "Word (.docx)" }));

    expect(await screen.findByText("Export failed: the file couldn't be created")).toBeTruthy();
    expect(clicked).toHaveLength(0);
    expect(await axeViolations(container)).toEqual([]);

    fetchMock.mockResolvedValueOnce(file("acme-estimate-v2.docx"));
    await user.click(screen.getByRole("button", { name: "Retry export" }));

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/opportunities/${OPP_ID}/estimate-export?format=docx`,
      { credentials: "same-origin" },
    );
    expect(container.querySelector("[data-export-failed]")).toBeNull();
  });

  it.each([
    [problem(403, "forbidden"), "only the owner and collaborators, except sales representatives, can export the Estimate"],
    [problem(409, "estimate_not_found"), "there is no Estimate to export yet"],
    [problem(502, "api_unavailable"), "the export service couldn't be reached"],
    [problem(404, "not_found"), "you no longer have access to this Opportunity"],
    [new Response("<html></html>", { headers: { "Content-Type": "text/html" } }), "your session has expired; reload the page"],
  ])("names the reason (%#)", async (response, reason) => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(response);
    renderExport();

    await user.click(exportButton());
    await user.click(screen.getByRole("button", { name: "Excel (.xlsx)" }));

    expect(await screen.findByText(`Export failed: ${reason}`)).toBeTruthy();
    expect(clicked).toHaveLength(0);
  });

  it("names an unreachable service", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    renderExport();

    await user.click(exportButton());
    await user.click(screen.getByRole("button", { name: "Excel (.xlsx)" }));

    expect(
      await screen.findByText("Export failed: the export service couldn't be reached"),
    ).toBeTruthy();
  });
});

describe("EstimateHeader's Export", () => {
  const succeeded: EstimateDraft = { status: "succeeded", error_code: null };
  const version = {
    id: "00000000-0000-7000-8000-000000000002",
    version: 2,
    status: "draft",
    uncovered_count: 0,
  } as EstimateVersion;

  it("shows Export when the caller may export a version", () => {
    render(
      <EstimateHeader version={version} draft={succeeded} opportunityId={OPP_ID} canExport />,
    );
    expect(screen.getByRole("button", { name: /Export/ })).toBeTruthy();
  });

  it.each([
    ["may not export", version, false],
    ["there is no version", null, true],
  ])("hides Export when %s", (_, v, canExport) => {
    render(
      <EstimateHeader
        version={v}
        draft={{ status: "failed", error_code: "model_unavailable" }}
        opportunityId={OPP_ID}
        canExport={canExport}
      />,
    );
    expect(screen.queryByRole("button", { name: /Export/ })).toBeNull();
  });
});
