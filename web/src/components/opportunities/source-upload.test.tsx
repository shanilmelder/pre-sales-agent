import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AddSourceResult } from "@/app/opportunities/actions";
import type { Source } from "@/lib/sources";
import { axeViolations } from "@/test/axe";

const addSource = vi.hoisted(() => vi.fn<(form: FormData) => Promise<AddSourceResult>>());
vi.mock("@/app/opportunities/actions", () => ({ addSource }));

import { LiveRegionProvider } from "../shell/live-region";
import { SourceUpload } from "./source-upload";
import { SourcesSection } from "./sources-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const UPLOADER = { id: "00000000-0000-7000-8000-0000000000a1", name: "[UPLOADER]" };

function source(name: string, overrides: Partial<Source> = {}): Source {
  return {
    id: `00000000-0000-7000-8000-${String(name.length).padStart(12, "0")}`,
    kind: name.endsWith(".vtt") ? "transcript" : "document",
    filename: name,
    version: 1,
    version_count: 1,
    size_bytes: 10,
    uploaded_by: UPLOADER,
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T13:05:00Z",
    ...overrides,
  };
}

/** The API's answer per file name: `.exe` is rejected, everything else is added. */
function apiAnswers() {
  addSource.mockImplementation(async (form: FormData) => {
    const file = form.get("file") as File;
    if (file.name.endsWith(".exe")) {
      return { kind: "rejected", reason: "Rejected: .exe files aren't allowed" };
    }
    return { kind: "ok", source: source(file.name) };
  });
}

const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);

function dropZone() {
  return screen.getByText("Drop emails, notes, transcripts or documents here").parentElement!;
}

function drop(files: File[]) {
  fireEvent.drop(dropZone(), { dataTransfer: { files } });
}

function rowFor(name: string) {
  return within(screen.getByRole("list", { name: "Uploads" }))
    .getByText(name)
    .closest("li")!;
}

beforeEach(() => {
  addSource.mockReset();
});

describe("SourcesSection with uploads", () => {
  it("dropping three files incl. an .exe: two Sources appear, the .exe row says why", async () => {
    apiAnswers();
    const { container } = render(
      <LiveRegionProvider>
        <SourcesSection opportunityId={OPP_ID} canAdd initial={[]} />
      </LiveRegionProvider>,
    );
    expect(screen.getByText("No Sources yet.")).toBeTruthy();

    drop([file("call.vtt"), file("setup.exe"), file("rfp.pdf")]);

    await waitFor(() => expect(within(rowFor("rfp.pdf")).getByText("Added")).toBeTruthy());
    expect(within(rowFor("call.vtt")).getByText("Added")).toBeTruthy();
    expect(
      within(rowFor("setup.exe")).getByText("Rejected: .exe files aren't allowed"),
    ).toBeTruthy();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    // Newest first.
    expect(within(rows[0]).getByText("rfp.pdf")).toBeTruthy();
    expect(within(rows[1]).getByText("call.vtt")).toBeTruthy();
    expect(within(rows[1]).getByText("Transcript")).toBeTruthy();
    expect(screen.queryByText("No Sources yet.")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a new version of a listed Source replaces its row", async () => {
    const first = source("call.vtt");
    addSource.mockResolvedValue({
      kind: "ok",
      source: { ...first, filename: "call-again.vtt", version: 2, version_count: 2 },
    });
    render(
      <LiveRegionProvider>
        <SourcesSection opportunityId={OPP_ID} canAdd initial={[first]} />
      </LiveRegionProvider>,
    );

    drop([file("call-again.vtt")]);

    await waitFor(() => expect(screen.getByText("v2")).toBeTruthy());
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    // The row says it became a new version, not a new Source.
    expect(within(rowFor("call-again.vtt")).getByText("Added as version 2")).toBeTruthy();
    expect(within(rowFor("call-again.vtt")).queryByText("Added")).toBeNull();
  });

  it("without can_add_sources there is no upload area, and the list still shows", async () => {
    const { container } = render(
      <SourcesSection opportunityId={OPP_ID} canAdd={false} initial={[source("rfp.pdf")]} />,
    );
    expect(screen.queryByRole("button", { name: "Choose files" })).toBeNull();
    expect(screen.queryByText("Drop emails, notes, transcripts or documents here")).toBeNull();
    const row = within(screen.getByRole("table")).getAllByRole("row")[1];
    expect(within(row).getByText("Document")).toBeTruthy();
    expect(within(row).getByText("rfp.pdf")).toBeTruthy();
    expect(within(row).getByText("v1")).toBeTruthy();
    expect(within(row).getByText("[UPLOADER]")).toBeTruthy();
    expect(within(row).getByText("4 Oct 2026, 13:05 UTC")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("SourceUpload", () => {
  function renderUpload(onAdded = vi.fn()) {
    render(
      <LiveRegionProvider>
        <SourceUpload opportunityId={OPP_ID} onAdded={onAdded} />
      </LiveRegionProvider>,
    );
    return { user: userEvent.setup(), onAdded };
  }

  it("uploads one file at a time, each row showing Uploading until it settles", async () => {
    const pending: Array<(result: AddSourceResult) => void> = [];
    addSource.mockImplementation(
      () => new Promise<AddSourceResult>((resolve) => pending.push(resolve)),
    );
    const { onAdded } = renderUpload();

    drop([file("a.txt"), file("b.txt")]);

    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(1));
    expect(within(rowFor("a.txt")).getByText("Uploading")).toBeTruthy();
    expect(within(rowFor("b.txt")).getByText("Uploading")).toBeTruthy();
    const sent = addSource.mock.calls[0][0];
    expect(sent.get("opportunityId")).toBe(OPP_ID);
    expect((sent.get("file") as File).name).toBe("a.txt");

    pending[0]({ kind: "ok", source: source("a.txt") });
    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(2));
    expect(within(rowFor("a.txt")).getByText("Added")).toBeTruthy();
    expect(within(rowFor("b.txt")).getByText("Uploading")).toBeTruthy();
    expect(onAdded).toHaveBeenCalledTimes(1);

    pending[1]({ kind: "error" });
    await waitFor(() =>
      expect(within(rowFor("b.txt")).getByText("The upload failed. Try again.")).toBeTruthy(),
    );
    expect(onAdded).toHaveBeenCalledTimes(1);
  });

  it("a throwing upload settles its row as failed and the queue goes on", async () => {
    apiAnswers();
    const onAdded = vi.fn().mockImplementationOnce(() => {
      throw new Error("boom");
    });
    renderUpload(onAdded);

    drop([file("a.txt"), file("b.txt")]);

    await waitFor(() => expect(within(rowFor("b.txt")).getByText("Added")).toBeTruthy());
    expect(within(rowFor("a.txt")).getByText("The upload failed. Try again.")).toBeTruthy();
    expect(addSource).toHaveBeenCalledTimes(2);
  });

  it("Choose files opens the picker; chosen files upload", async () => {
    apiAnswers();
    const { user, onAdded } = renderUpload();
    const input = screen.getByTestId("source-file-input") as HTMLInputElement;
    const click = vi.spyOn(input, "click");

    await user.click(screen.getByRole("button", { name: "Choose files" }));
    expect(click).toHaveBeenCalled();
    expect(input.accept).toBe(".eml,.msg,.txt,.vtt,.docx,.pdf");
    expect(input.multiple).toBe(true);

    await user.upload(input, [file("notes.txt")]);
    await waitFor(() => expect(within(rowFor("notes.txt")).getByText("Added")).toBeTruthy());
    expect(onAdded).toHaveBeenCalledWith(source("notes.txt"));
  });

  it("shows the reasons for forbidden, hidden and too-large uploads", async () => {
    addSource
      .mockResolvedValueOnce({ kind: "forbidden" })
      .mockResolvedValueOnce({ kind: "not-found" })
      .mockResolvedValueOnce({ kind: "rejected", reason: "Rejected: larger than 50 MB" });
    renderUpload();

    drop([file("a.txt"), file("b.txt"), file("c.pdf")]);

    await waitFor(() =>
      expect(within(rowFor("c.pdf")).getByText("Rejected: larger than 50 MB")).toBeTruthy(),
    );
    expect(
      within(rowFor("a.txt")).getByText("Only the owner and collaborators can add Sources."),
    ).toBeTruthy();
    expect(
      within(rowFor("b.txt")).getByText("You don't have access to this Opportunity"),
    ).toBeTruthy();
  });

  it("a file the web server can't carry is rejected without sending it", async () => {
    renderUpload();
    const huge = file("huge.pdf");
    Object.defineProperty(huge, "size", { value: 60 * 1024 * 1024 });

    drop([huge]);

    await waitFor(() =>
      expect(within(rowFor("huge.pdf")).getByText("Rejected: larger than 50 MB")).toBeTruthy(),
    );
    expect(addSource).not.toHaveBeenCalled();
  });
});
