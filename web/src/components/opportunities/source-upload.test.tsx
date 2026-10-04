import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AddSourceResult } from "@/app/opportunities/actions";
import type { Source } from "@/lib/sources";
import { axeViolations } from "@/test/axe";

const addSource = vi.hoisted(() => vi.fn<(form: FormData) => Promise<AddSourceResult>>());
const addTextSource = vi.hoisted(() =>
  vi.fn<(opportunityId: string, text: string) => Promise<AddSourceResult>>(),
);
const retryParse = vi.hoisted(() => vi.fn());
const loadSources = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({
  addSource,
  addTextSource,
  retryParse,
  loadSources,
}));

import { LiveRegionProvider } from "../shell/live-region";
import { SourceUpload } from "./source-upload";
import { SourcesSection } from "./sources-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const UPLOADER = { id: "00000000-0000-7000-8000-0000000000a1", name: "[UPLOADER]" };

function source(name: string, overrides: Partial<Source> = {}): Source {
  return {
    id: `00000000-0000-7000-8000-${String(name.length).padStart(12, "0")}`,
    kind: name.endsWith(".vtt") ? "transcript" : name === "Pasted text" ? "note" : "document",
    filename: name,
    version: 1,
    version_count: 1,
    size_bytes: 10,
    uploaded_by: UPLOADER,
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T13:05:00Z",
    parse: { status: "parsed", error_code: null },
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
  addTextSource.mockReset();
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

describe("Paste text", () => {
  const NOTE = "Call with [CUSTOMER]: they need SAP sync and 40 ports.";

  function renderSection(initial: Source[] = []) {
    const view = render(
      <LiveRegionProvider>
        <SourcesSection opportunityId={OPP_ID} canAdd initial={initial} />
      </LiveRegionProvider>,
    );
    return { ...view, user: userEvent.setup() };
  }

  const pasteButton = () => screen.getByRole("button", { name: "Paste text" });
  const textarea = () => screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Text to add" });
  const addButton = () => screen.getByRole<HTMLButtonElement>("button", { name: "Add" });

  it("a pasted call note shows Added and tops the list as a Note named Pasted text", async () => {
    addTextSource.mockResolvedValue({ kind: "ok", source: source("Pasted text") });
    const { user, container } = renderSection([source("rfp.pdf")]);

    await user.click(pasteButton());
    expect(pasteButton().getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(textarea());
    expect(await axeViolations(container)).toEqual([]);
    await user.paste(NOTE);
    await user.click(addButton());

    await waitFor(() => expect(within(rowFor("Pasted text")).getByText("Added")).toBeTruthy());
    expect(addTextSource).toHaveBeenCalledWith(OPP_ID, NOTE);
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Pasted text")).toBeTruthy();
    expect(within(rows[0]).getByText("Note")).toBeTruthy();
    // The area closes and clears; focus goes back to its button.
    expect(screen.queryByRole("textbox", { name: "Text to add" })).toBeNull();
    expect(document.activeElement).toBe(pasteButton());
    await user.click(pasteButton());
    expect(textarea().value).toBe("");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Add is disabled while the trimmed text is empty", async () => {
    const { user } = renderSection();
    await user.click(pasteButton());

    expect(addButton().disabled).toBe(true);
    await user.type(textarea(), "   ");
    expect(addButton().disabled).toBe(true);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(addTextSource).not.toHaveBeenCalled();
    await user.type(textarea(), "x");
    expect(addButton().disabled).toBe(false);
  });

  it.each([
    ["Ctrl+Enter", "{Control>}{Enter}{/Control}"],
    ["Cmd+Enter", "{Meta>}{Enter}{/Meta}"],
  ])("%s submits", async (_, keys) => {
    addTextSource.mockResolvedValue({ kind: "ok", source: source("Pasted text") });
    const { user } = renderSection();
    await user.click(pasteButton());
    await user.type(textarea(), "note");

    await user.keyboard(keys);

    await waitFor(() => expect(within(rowFor("Pasted text")).getByText("Added")).toBeTruthy());
    expect(addTextSource).toHaveBeenCalledWith(OPP_ID, "note");
  });

  it("plain Enter adds a new line, not a submit", async () => {
    const { user } = renderSection();
    await user.click(pasteButton());
    await user.type(textarea(), "a{Enter}b");
    expect(textarea().value).toBe("a\nb");
    expect(addTextSource).not.toHaveBeenCalled();
  });

  it("Esc cancels without reaching the shell, and Cancel does the same", async () => {
    const { user } = renderSection();
    const shell = vi.fn<(event: KeyboardEvent) => void>();
    document.addEventListener("keydown", shell);
    try {
      await user.click(pasteButton());
      await user.type(textarea(), "draft");
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("textbox", { name: "Text to add" })).toBeNull();
      expect(document.activeElement).toBe(pasteButton());
      expect(shell.mock.calls.some(([event]) => event.key === "Escape")).toBe(false);
    } finally {
      document.removeEventListener("keydown", shell);
    }

    await user.click(pasteButton());
    expect(textarea().value).toBe("");
    await user.type(textarea(), "draft");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Text to add" })).toBeNull();
    expect(addTextSource).not.toHaveBeenCalled();
  });

  it("a rejection shows the API's sentence and keeps the text", async () => {
    addTextSource.mockResolvedValue({
      kind: "rejected",
      reason: "Rejected: longer than 1,000,000 characters",
    });
    const { user } = renderSection();
    await user.click(pasteButton());
    await user.type(textarea(), "too long");

    await user.click(addButton());

    await waitFor(() =>
      expect(
        within(rowFor("Pasted text")).getByText("Rejected: longer than 1,000,000 characters"),
      ).toBeTruthy(),
    );
    expect(textarea().value).toBe("too long");
    expect(addButton().disabled).toBe(false);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("the same text again says Added as version 2", async () => {
    const first = source("Pasted text");
    addTextSource.mockResolvedValue({
      kind: "ok",
      source: { ...first, version: 2, version_count: 2 },
    });
    const { user } = renderSection([first]);
    await user.click(pasteButton());
    await user.type(textarea(), "same");

    await user.click(addButton());

    await waitFor(() =>
      expect(within(rowFor("Pasted text")).getByText("Added as version 2")).toBeTruthy(),
    );
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("v2")).toBeTruthy();
  });

  it("pastes and files share one ordered queue", async () => {
    const pending: Array<(result: AddSourceResult) => void> = [];
    addSource.mockImplementation(
      () => new Promise<AddSourceResult>((resolve) => pending.push(resolve)),
    );
    addTextSource.mockResolvedValue({ kind: "ok", source: source("Pasted text") });
    const { user } = renderSection();

    drop([file("a.txt")]);
    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(1));
    await user.click(pasteButton());
    await user.type(textarea(), "note");
    await user.click(addButton());

    expect(within(rowFor("Pasted text")).getByText("Uploading")).toBeTruthy();
    expect(addTextSource).not.toHaveBeenCalled();
    // No second submit while one is pending.
    expect(addButton().disabled).toBe(true);

    pending[0]({ kind: "ok", source: source("a.txt") });
    await waitFor(() => expect(within(rowFor("Pasted text")).getByText("Added")).toBeTruthy());
    expect(addTextSource).toHaveBeenCalledTimes(1);
    const names = within(screen.getByRole("list", { name: "Uploads" }))
      .getAllByRole("listitem")
      .map((li) => li.firstElementChild?.textContent);
    expect(names).toEqual(["a.txt", "Pasted text"]);
  });

  it("a failed call says the upload failed and keeps the text", async () => {
    addTextSource.mockRejectedValue(new Error("network"));
    const { user } = renderSection();
    await user.click(pasteButton());
    await user.type(textarea(), "note");

    await user.click(addButton());

    await waitFor(() =>
      expect(within(rowFor("Pasted text")).getByText("The upload failed. Try again.")).toBeTruthy(),
    );
    expect(textarea().value).toBe("note");
    expect(addButton().disabled).toBe(false);
  });

  it("while a paste is pending the area is locked, and success doesn't steal focus", async () => {
    let resolve: (result: AddSourceResult) => void = () => {};
    addTextSource.mockImplementation(
      () => new Promise<AddSourceResult>((done) => (resolve = done)),
    );
    const { user } = renderSection();
    await user.click(pasteButton());
    const controlled = document.getElementById(pasteButton().getAttribute("aria-controls")!);
    expect(controlled?.contains(textarea())).toBe(true);
    await user.type(textarea(), "note");

    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(addTextSource).toHaveBeenCalledTimes(1));

    expect(textarea().readOnly).toBe(true);
    const cancel = screen.getByRole<HTMLButtonElement>("button", { name: "Cancel" });
    expect(cancel.disabled).toBe(true);
    await user.keyboard("{Escape}");
    expect(textarea().value).toBe("note");

    const elsewhere = screen.getByRole("button", { name: "Choose files" });
    act(() => elsewhere.focus());
    await act(async () => resolve({ kind: "ok", source: source("Pasted text") }));

    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Text to add" })).toBeNull());
    expect(document.activeElement).toBe(elsewhere);
    expect(document.activeElement).not.toBe(pasteButton());
  });

  it("Esc during an IME composition keeps the area open", async () => {
    const { user } = renderSection();
    await user.click(pasteButton());
    await user.type(textarea(), "draft");

    fireEvent.keyDown(textarea(), { key: "Escape", isComposing: true });

    expect(textarea().value).toBe("draft");
  });

  it("without can_add_sources there is no Paste text", () => {
    render(<SourcesSection opportunityId={OPP_ID} canAdd={false} initial={[]} />);
    expect(screen.queryByRole("button", { name: "Paste text" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
