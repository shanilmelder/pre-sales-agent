import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { utcToday } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const createOpportunity = vi.hoisted(() => vi.fn());
const importFile = vi.hoisted(() => vi.fn());
const loadImport = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({ createOpportunity, importFile, loadImport }));
vi.mock("@/lib/opportunity-import", async (original) => ({
  ...(await original<typeof import("@/lib/opportunity-import")>()),
  IMPORT_POLL_MS: 10,
  IMPORT_POLL_LIMIT_MS: 1_000,
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

import { LiveRegionProvider } from "../shell/live-region";
import { CreateOpportunityForm, parseProducts, validate } from "./create-form";

const NEW_ID = "00000000-0000-7000-8000-000000000042";

function renderForm() {
  const utils = render(
    <LiveRegionProvider>
      <CreateOpportunityForm />
    </LiveRegionProvider>,
  );
  return { user: userEvent.setup(), ...utils };
}

function future(days = 30): string {
  return utcToday(new Date(Date.now() + days * 86_400_000));
}

const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  {
    customer = "Example Customer",
    products = "AutoStore\nPick station",
    industry = "Retail",
    date = future(),
    title = "",
  } = {},
) {
  if (customer) await user.type(field("Customer name"), customer);
  if (title) await user.type(field("Title (optional)"), title);
  if (products) await user.type(field("Products in scope"), products);
  if (industry) await user.type(field("Industry"), industry);
  // jsdom's date input does not take typed keys; set its value the way a picker would.
  if (date) fireEvent.change(field("Target proposal date"), { target: { value: date } });
}

const submit = () => screen.getByRole("button", { name: "Create Opportunity" });

beforeEach(() => {
  createOpportunity.mockReset();
  importFile.mockReset();
  loadImport.mockReset();
  push.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("parseProducts and validate", () => {
  it("trims, drops blank lines and de-duplicates ignoring case", () => {
    expect(parseProducts(" AutoStore \n\nautostore\nPick station\r\nAUTOSTORE")).toEqual([
      "AutoStore",
      "Pick station",
    ]);
  });

  it("flags every rule the API enforces", () => {
    const today = "2026-10-04";
    const ok = {
      title: "",
      customer_name: "[CUSTOMER]",
      products: ["A"],
      industry: "Retail",
      target_proposal_date: today,
    };
    expect(validate(ok, today)).toEqual({});
    expect(Object.keys(validate({ ...ok, target_proposal_date: "2026-10-03" }, today))).toEqual([
      "target_proposal_date",
    ]);
    expect(Object.keys(validate({ ...ok, products: [] }, today))).toEqual(["products"]);
    const many = Array.from({ length: 21 }, (_, i) => `P${i}`);
    expect(Object.keys(validate({ ...ok, products: many }, today))).toEqual(["products"]);
    expect(Object.keys(validate({ ...ok, products: ["x".repeat(101)] }, today))).toEqual([
      "products",
    ]);
    expect(
      Object.keys(
        validate(
          { ...ok, title: "x".repeat(201), customer_name: "x".repeat(201), industry: "x".repeat(101) },
          today,
        ),
      ),
    ).toEqual(["title", "customer_name", "industry"]);
    expect(Object.keys(validate({ ...ok, customer_name: " ", industry: "" }, today))).toEqual([
      "customer_name",
      "industry",
    ]);
  });
});

describe("lengths and dates as the API counts them", () => {
  const ok = {
    title: "",
    customer_name: "[CUSTOMER]",
    products: ["A"],
    industry: "Retail",
    target_proposal_date: "2026-10-04",
  };

  it("counts code points, so emoji count once", () => {
    const emoji = (n: number) => "😀".repeat(n);
    expect(
      validate(
        {
          ...ok,
          title: emoji(200),
          customer_name: emoji(200),
          products: [emoji(100)],
          industry: emoji(100),
        },
        "2026-10-04",
      ),
    ).toEqual({});
    expect(
      Object.keys(
        validate(
          {
            ...ok,
            title: emoji(201),
            customer_name: emoji(201),
            products: [emoji(101)],
            industry: emoji(101),
          },
          "2026-10-04",
        ),
      ),
    ).toEqual(["title", "customer_name", "products", "industry"]);
  });

  it("uses the UTC date: just after UTC midnight, yesterday's local date is in the past", async () => {
    // 00:30 UTC on 5 Oct is still 4 Oct anywhere west of UTC (e.g. 20:30 in New York).
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-05T00:30:00Z"));
    const { user } = renderForm();
    expect(field("Target proposal date").min).toBe("2026-10-05");
    await fill(user, { date: "2026-10-04" });
    await user.click(submit());
    expect(screen.getByText("Choose a date that is not in the past.")).toBeTruthy();
    expect(createOpportunity).not.toHaveBeenCalled();
  });
});

describe("CreateOpportunityForm", () => {
  it("creates the Opportunity and opens it", async () => {
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await fill(user, { products: "AutoStore\nautostore\nPick station" });
    await user.click(submit());

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/opportunities/${NEW_ID}`));
    expect(createOpportunity).toHaveBeenCalledWith({
      title: "",
      customer_name: "Example Customer",
      products: ["AutoStore", "Pick station"],
      industry: "Retail",
      target_proposal_date: future(),
    });
  });

  it("shows field errors, focuses the first one and sends nothing", async () => {
    const { user } = renderForm();
    await fill(user, { customer: "", products: "", date: "" });
    await user.click(submit());

    expect(createOpportunity).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field("Customer name"));
    expect(field("Customer name").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Enter the customer name.")).toBeTruthy();
    expect(screen.getByText("Enter at least one product.")).toBeTruthy();
    expect(screen.getByText("Choose the target proposal date.")).toBeTruthy();
    expect(field("Products in scope").getAttribute("aria-describedby")).toContain("-error");
  });

  it("rejects a past date and more than 20 products", async () => {
    const { user } = renderForm();
    const many = Array.from({ length: 21 }, (_, i) => `P${i}`).join("\n");
    await fill(user, { products: many, date: future(-2) });
    await user.click(submit());
    expect(createOpportunity).not.toHaveBeenCalled();
    expect(screen.getByText("Enter at most 20 products.")).toBeTruthy();
    expect(screen.getByText("Choose a date that is not in the past.")).toBeTruthy();
    expect(field("Target proposal date").min).toBe(utcToday());
  });

  it("shows the fields the API rejected (422)", async () => {
    createOpportunity.mockResolvedValue({ kind: "invalid", fields: ["target_proposal_date"] });
    const { user } = renderForm();
    await fill(user);
    await user.click(submit());
    expect(await screen.findByText("Choose a date that is not in the past.")).toBeTruthy();
    expect(document.activeElement).toBe(field("Target proposal date"));
    expect(push).not.toHaveBeenCalled();
  });

  it("says so when the user may not create (403) or the call fails", async () => {
    createOpportunity.mockResolvedValueOnce({ kind: "forbidden" });
    const { user } = renderForm();
    await fill(user);
    await user.click(submit());
    expect(await screen.findByText("You don't have access to create Opportunities.")).toBeTruthy();
    createOpportunity.mockRejectedValueOnce(new Error("network"));
    await user.click(submit());
    expect(
      await screen.findByText("The Opportunity could not be created. Try again."),
    ).toBeTruthy();
  });

  it("has no WCAG 2.1 AA violations, empty or with errors", async () => {
    const { user, container } = renderForm();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(submit());
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Import from file", () => {
  const IMPORT_ID = "00000000-0000-7000-8000-0000000000e1";
  const queued = {
    id: IMPORT_ID,
    filename: "follow-up.eml",
    size_bytes: 10,
    status: "queued",
    error_code: null,
    suggestions: null,
    created_at: "2026-10-06T10:00:00Z",
  };
  const succeeded = {
    ...queued,
    status: "succeeded",
    suggestions: {
      title: { value: "Riverside DC automation", quote: "Riverside DC" },
      customer_name: { value: "Meridian Fresh Foods", quote: "IT Manager, Meridian Fresh Foods" },
      industry: { value: "Food distribution", quote: "fresh food distribution" },
      products: [
        { value: "Goods-to-person picking", quote: "a goods-to-person picking system" },
        { value: "WMS integration", quote: "your system replacing the WMS" },
      ],
      target_proposal_date: null,
    },
  };

  async function chooseFile(user: ReturnType<typeof userEvent.setup>, name = "follow-up.eml") {
    await user.upload(screen.getByTestId("import-file-input"), new File(["From: x"], name));
  }

  it("fills only the empty fields, marks them From file with the quote, and sends the import", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport
      .mockResolvedValueOnce({ kind: "ok", import: { ...queued, status: "running" } })
      .mockResolvedValue({ kind: "ok", import: succeeded });
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await user.type(field("Customer name"), "Typed Customer");
    await chooseFile(user);

    expect(await screen.findByText(/Filled 3 fields from follow-up.eml/)).toBeTruthy();
    expect(loadImport).toHaveBeenCalledWith(IMPORT_ID);
    // The typed customer wins; the other empty fields fill.
    expect(field("Customer name").value).toBe("Typed Customer");
    expect(field("Title (optional)").value).toBe("Riverside DC automation");
    expect(field("Industry").value).toBe("Food distribution");
    expect(field("Products in scope").value).toBe("Goods-to-person picking\nWMS integration");
    // No deadline in the file: the default date, marked as such.
    expect(field("Target proposal date").value).toBe(future(30));
    expect(screen.getByText("Default: 30 days from today, not in the file")).toBeTruthy();

    const title = field("Title (optional)");
    expect(screen.getAllByText("From file")).toHaveLength(3);
    const quoteId = title.getAttribute("aria-describedby")?.split(" ")[0] ?? "";
    expect(document.getElementById(quoteId)?.textContent).toBe("From the file: “Riverside DC”");
    expect(field("Customer name").getAttribute("aria-describedby")).toBeNull();

    // Editing a filled field makes it the user's own value.
    await user.type(field("Industry"), " and retail");
    expect(screen.getAllByText("From file")).toHaveLength(2);

    fireEvent.change(field("Target proposal date"), { target: { value: future() } });
    await user.click(submit());
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/opportunities/${NEW_ID}`));
    expect(createOpportunity).toHaveBeenCalledWith({
      title: "Riverside DC automation",
      customer_name: "Typed Customer",
      products: ["Goods-to-person picking", "WMS integration"],
      industry: "Food distribution and retail",
      target_proposal_date: future(),
      importId: IMPORT_ID,
    });
  });

  it("Clear import removes the suggestions and the file", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({ kind: "ok", import: succeeded });
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Filled 4 fields/);
    await user.click(screen.getByRole("button", { name: "Clear import" }));

    expect(field("Customer name").value).toBe("");
    expect(field("Title (optional)").value).toBe("");
    expect(screen.queryByText("From file")).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear import" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Import from file" }));
    await fill(user);
    await user.click(submit());
    await waitFor(() => expect(createOpportunity).toHaveBeenCalled());
    expect(createOpportunity.mock.calls[0][0]).not.toHaveProperty("importId");
  });

  it("says it couldn't read the file and the form still works", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({
      kind: "ok",
      import: { ...queued, status: "failed", error_code: "unreadable" },
    });
    const { user } = renderForm();
    await chooseFile(user, "rfp.pdf");
    expect(
      await screen.findByText(/Couldn't read the file — fill the form in by hand/),
    ).toBeTruthy();
    expect(field("Customer name").value).toBe("");
    await user.type(field("Customer name"), "By hand");
    expect(field("Customer name").value).toBe("By hand");
  });

  it("gives up after the polling limit", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({ kind: "ok", import: queued });
    const { user } = renderForm();
    await chooseFile(user);
    expect(
      await screen.findByText(/Couldn't read the file/, undefined, { timeout: 3_000 }),
    ).toBeTruthy();
  });

  it("shows the API's reason for a rejected file under the button", async () => {
    importFile.mockResolvedValue({ kind: "rejected", reason: "Rejected: .exe files aren't allowed" });
    renderForm();
    // The picker filters by `accept`; a dropped or forced file can still be anything.
    fireEvent.change(screen.getByTestId("import-file-input"), {
      target: { files: [new File(["MZ"], "setup.exe")] },
    });
    expect(await screen.findByText("Rejected: .exe files aren't allowed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear import" })).toBeNull();
    expect(loadImport).not.toHaveBeenCalled();
  });

  it("says so when the import can't be used any more on create", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({ kind: "ok", import: succeeded });
    createOpportunity.mockResolvedValue({ kind: "import-unusable" });
    const { user } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Filled 4 fields/);
    fireEvent.change(field("Target proposal date"), { target: { value: future() } });
    await user.click(submit());
    expect(
      await screen.findByText(
        "The imported file can't be used any more. Clear the import and try again.",
      ),
    ).toBeTruthy();
  });

  it("has no WCAG 2.1 AA violations with suggestions shown", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({ kind: "ok", import: succeeded });
    const { user, container } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Filled 4 fields/);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Import from file: edge cases", () => {
  const IMPORT_ID = "00000000-0000-7000-8000-0000000000e1";
  const SECOND_ID = "00000000-0000-7000-8000-0000000000e2";
  const queued = {
    id: IMPORT_ID,
    filename: "follow-up.eml",
    size_bytes: 10,
    status: "queued",
    error_code: null,
    suggestions: null,
    created_at: "2026-10-06T10:00:00Z",
  };
  const succeeded = {
    ...queued,
    status: "succeeded",
    suggestions: {
      title: { value: "Riverside DC automation", quote: "Riverside DC" },
      customer_name: { value: "Meridian Fresh Foods", quote: "Meridian Fresh Foods" },
      industry: null,
      products: [],
      target_proposal_date: null,
    },
  };

  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => {
      resolve = r;
    });
    return { promise, resolve };
  }

  async function chooseFile(user: ReturnType<typeof userEvent.setup>, name = "follow-up.eml") {
    await user.upload(screen.getByTestId("import-file-input"), new File(["From: x"], name));
  }

  it("Create does nothing while the file uploads", async () => {
    const upload = deferred<unknown>();
    importFile.mockReturnValue(upload.promise);
    const { user } = renderForm();
    await fill(user);
    await chooseFile(user);
    expect(await screen.findByText("Uploading follow-up.eml…")).toBeTruthy();
    expect(submit().getAttribute("aria-disabled")).toBe("true");
    await user.click(submit());
    await user.type(field("Industry"), "{Enter}");
    expect(createOpportunity).not.toHaveBeenCalled();
    upload.resolve({ kind: "ok", import: queued });
    await waitFor(() => expect(submit().getAttribute("aria-disabled")).toBeNull());
  });

  it("an import that is gone is dropped: the file isn't attached", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({ kind: "gone" });
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await chooseFile(user);
    expect(
      await screen.findByText(
        "The import is no longer available: follow-up.eml won't be attached. Choose it again or continue by hand.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear import" })).toBeNull();
    await fill(user);
    await user.click(submit());
    await waitFor(() => expect(createOpportunity).toHaveBeenCalled());
    expect(createOpportunity.mock.calls[0][0]).not.toHaveProperty("importId");
  });

  it("a second file replaces the first one's suggestions but keeps what the user typed", async () => {
    const second = deferred<unknown>();
    importFile
      .mockResolvedValueOnce({ kind: "ok", import: queued })
      .mockReturnValueOnce(second.promise);
    loadImport.mockImplementation(async (id: string) =>
      id === IMPORT_ID
        ? { kind: "ok", import: succeeded }
        : {
            kind: "ok",
            import: {
              ...succeeded,
              id: SECOND_ID,
              filename: "call.vtt",
              suggestions: { ...succeeded.suggestions, title: null, industry: { value: "Grocery", quote: "grocery" } },
            },
          },
    );
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await user.type(field("Products in scope"), "Typed product");
    await chooseFile(user);
    await screen.findByText(/Filled 2 fields from follow-up.eml/);

    await chooseFile(user, "call.vtt");
    expect(await screen.findByText("Uploading call.vtt…")).toBeTruthy();
    expect(field("Title (optional)").value).toBe("");
    expect(field("Customer name").value).toBe("");
    expect(field("Products in scope").value).toBe("Typed product");
    expect(screen.queryByText("From file")).toBeNull();
    expect(screen.getByRole("button", { name: "Clear import" })).toBeTruthy();

    second.resolve({ kind: "ok", import: { ...queued, id: SECOND_ID, filename: "call.vtt" } });
    await screen.findByText(/Filled 2 fields from call.vtt/);
    expect(field("Title (optional)").value).toBe("");
    expect(field("Industry").value).toBe("Grocery");
    fireEvent.change(field("Target proposal date"), { target: { value: future() } });
    await user.click(submit());
    await waitFor(() => expect(createOpportunity).toHaveBeenCalled());
    expect(createOpportunity.mock.calls[0][0].importId).toBe(SECOND_ID);
  });

  it("says so when no field could be read", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({
      kind: "ok",
      import: { ...succeeded, suggestions: { products: [] } },
    });
    const { user } = renderForm();
    await chooseFile(user);
    expect(
      await screen.findByText(
        "No fields could be read from follow-up.eml; it still becomes the first Source.",
      ),
    ).toBeTruthy();
  });

  it("after a failed read, Create still sends the import id", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({
      kind: "ok",
      import: { ...queued, status: "failed", error_code: "unreadable" },
    });
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Couldn't read the file/);
    await fill(user);
    await user.click(submit());
    await waitFor(() => expect(createOpportunity).toHaveBeenCalled());
    expect(createOpportunity.mock.calls[0][0].importId).toBe(IMPORT_ID);
  });

  it("a read that answers after Clear import fills nothing", async () => {
    const read = deferred<unknown>();
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockReturnValue(read.promise);
    const { user } = renderForm();
    await chooseFile(user);
    await waitFor(() => expect(loadImport).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Clear import" }));
    read.resolve({ kind: "ok", import: succeeded });
    await new Promise((r) => setTimeout(r, 50));
    expect(field("Customer name").value).toBe("");
    expect(field("Title (optional)").value).toBe("");
    expect(screen.queryByText("From file")).toBeNull();
  });

  it("an upload that answers after Clear import is ignored", async () => {
    const upload = deferred<unknown>();
    importFile.mockReturnValue(upload.promise);
    loadImport.mockResolvedValue({ kind: "ok", import: succeeded });
    const { user } = renderForm();
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: "Clear import" }));
    upload.resolve({ kind: "ok", import: queued });
    await new Promise((r) => setTimeout(r, 50));
    expect(loadImport).not.toHaveBeenCalled();
    expect(field("Customer name").value).toBe("");
    expect(screen.queryByText("From file")).toBeNull();
  });
});

describe("Import from file: inferred industry and the default date", () => {
  const IMPORT_ID = "00000000-0000-7000-8000-0000000000e1";
  const DEFAULT_LABEL = "Default: 30 days from today, not in the file";
  const queued = {
    id: IMPORT_ID,
    filename: "follow-up.eml",
    size_bytes: 10,
    status: "queued",
    error_code: null,
    suggestions: null,
    created_at: "2026-10-06T10:00:00Z",
  };

  function read(suggestions: Record<string, unknown>) {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({
      kind: "ok",
      import: {
        ...queued,
        status: "succeeded",
        suggestions: { products: [], industry_inferred: false, ...suggestions },
      },
    });
  }

  async function chooseFile(user: ReturnType<typeof userEvent.setup>) {
    await user.upload(screen.getByTestId("import-file-input"), new File(["From: x"], "follow-up.eml"));
  }

  it("marks an inferred industry 'Inferred from file' with its quote", async () => {
    read({
      industry: { value: "Food & grocery distribution", quote: "We ship chilled groceries" },
      industry_inferred: true,
      customer_name: { value: "Meridian Fresh Foods", quote: "Meridian Fresh Foods" },
    });
    const { user, container } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Filled 2 fields/);
    expect(field("Industry").value).toBe("Food & grocery distribution");
    expect(screen.getByText("Inferred from file")).toBeTruthy();
    expect(screen.getAllByText("From file")).toHaveLength(1); // the customer only
    const quoteId = field("Industry").getAttribute("aria-describedby")?.split(" ")[0] ?? "";
    expect(document.getElementById(quoteId)?.textContent).toBe(
      "Inferred from the file: “We ship chilled groceries”",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a deadline from the file beats the default", async () => {
    const due = future(17);
    read({ target_proposal_date: { value: due, quote: "Proposal due soon" } });
    const { user } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Filled 1 field from/);
    expect(field("Target proposal date").value).toBe(due);
    expect(screen.queryByText(DEFAULT_LABEL)).toBeNull();
  });

  it("a typed date beats the default", async () => {
    read({});
    const { user } = renderForm();
    fireEvent.change(field("Target proposal date"), { target: { value: future(60) } });
    await chooseFile(user);
    await screen.findByText(/No fields could be read/);
    expect(field("Target proposal date").value).toBe(future(60));
    expect(screen.queryByText(DEFAULT_LABEL)).toBeNull();
  });

  it("a failed read still proposes the default date, editable and sent on Create", async () => {
    importFile.mockResolvedValue({ kind: "ok", import: queued });
    loadImport.mockResolvedValue({
      kind: "ok",
      import: { ...queued, status: "failed", error_code: "unreadable" },
    });
    createOpportunity.mockResolvedValue({ kind: "ok", id: NEW_ID });
    const { user } = renderForm();
    await chooseFile(user);
    await screen.findByText(/Couldn't read the file/);
    expect(field("Target proposal date").value).toBe(future(30));
    expect(screen.getByText(DEFAULT_LABEL)).toBeTruthy();
    // Changing it makes it the user's own date.
    fireEvent.change(field("Target proposal date"), { target: { value: future(45) } });
    expect(screen.queryByText(DEFAULT_LABEL)).toBeNull();
    await fill(user, { date: "" });
    await user.click(submit());
    await waitFor(() => expect(createOpportunity).toHaveBeenCalled());
    expect(createOpportunity.mock.calls[0][0].target_proposal_date).toBe(future(45));
  });
});
