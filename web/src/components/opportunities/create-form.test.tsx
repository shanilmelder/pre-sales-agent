import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { utcToday } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const createOpportunity = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({ createOpportunity }));
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
