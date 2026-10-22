import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./dialog";

function Example() {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" />}>Open</DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Cancel run</DialogTitle>
          <DialogDescription>This stops the agent run.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline">Keep running</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

describe("Dialog", () => {
  it("opens a flat, scrimmed 520px dialog with a labelled title", async () => {
    render(<Example />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog", { name: "Cancel run" });
    expect(dialog.className).toContain("w-dialog-width");
    expect(dialog.className).toContain("p-6");
    expect(dialog.className).toContain("rounded-xl");
    expect(dialog.className).toContain("border");
    expect(dialog.className).toContain("shadow-overlay");
    expect(dialog.className).not.toMatch(/animate-|zoom-|fade-/);
    expect(dialog.getAttribute("aria-describedby")).toBeTruthy();
    const overlay = document.querySelector("[data-slot=dialog-overlay]");
    expect(overlay?.className).toContain("bg-scrim");
    expect(overlay?.className).not.toMatch(/blur|animate-/);
    expect(screen.getByText("Cancel run").className).toContain("text-xl");
    expect(document.querySelector("[data-slot=dialog-footer]")?.className).toContain("-mx-6 -mb-6 ");
  });

  it("closes on Escape", async () => {
    render(<Example />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("has no axe violations while open", async () => {
    render(<Example />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog");
    expect(await axeViolations(dialog)).toEqual([]);
  });
});
