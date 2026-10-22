import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { StreamStatus } from "@/lib/opportunity-events";
import { axeViolations } from "@/test/axe";

import { OFFLINE_MESSAGE, OfflineStrip } from "./offline-strip";
import { ShellProviders, usePublishStreamState } from "./shell-context";

function Publisher({ status, retry }: { status: StreamStatus; retry: () => void }) {
  usePublishStreamState(status, retry);
  return null;
}

function tree(status: StreamStatus, retry = vi.fn()) {
  return (
    <ShellProviders singleKeyShortcuts>
      <main id="main-content" tabIndex={-1}>
        <OfflineStrip />
        <Publisher status={status} retry={retry} />
      </main>
    </ShellProviders>
  );
}

describe("OfflineStrip", () => {
  it("stays mounted as an empty polite live region unless offline", () => {
    render(tree("reconnecting"));
    const strip = screen.getByTestId("offline-strip");
    expect(strip.getAttribute("aria-live")).toBe("polite");
    expect(strip.textContent).toBe("");
  });

  it("offline: shows the message and Retry; Retry calls the workspace and focuses main", async () => {
    const retry = vi.fn();
    const user = userEvent.setup();
    const { container } = render(tree("offline", retry));
    expect(screen.getByTestId("offline-strip").textContent).toContain(OFFLINE_MESSAGE);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(document.getElementById("main-content"));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is axe-clean in dark mode", async () => {
    document.documentElement.classList.add("dark");
    try {
      const { container } = render(tree("offline"));
      expect(await axeViolations(container)).toEqual([]);
    } finally {
      document.documentElement.classList.remove("dark");
    }
  });

  it("clears when the publisher unmounts", () => {
    const view = render(tree("offline"));
    expect(screen.getByTestId("offline-strip").textContent).toContain("Offline");
    act(() =>
      view.rerender(
        <ShellProviders singleKeyShortcuts>
          <OfflineStrip />
        </ShellProviders>,
      ),
    );
    expect(screen.getByTestId("offline-strip").textContent).toBe("");
  });
});
