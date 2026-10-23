import { act, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNarrowViewport } from "./use-narrow-viewport";

function Probe() {
  return <p data-testid="narrow">{String(useNarrowViewport())}</p>;
}

afterEach(() => vi.unstubAllGlobals());

describe("useNarrowViewport", () => {
  it("follows the (max-width: 1023.98px) media query", () => {
    let matches = true;
    const listeners = new Set<() => void>();
    const query = vi.fn((q: string) => ({
      get matches() {
        return matches;
      },
      media: q,
      addEventListener: (_: string, l: () => void) => listeners.add(l),
      removeEventListener: (_: string, l: () => void) => listeners.delete(l),
    }));
    vi.stubGlobal("matchMedia", query);
    const view = render(<Probe />);
    expect(query).toHaveBeenCalledWith("(max-width: 1023.98px)");
    expect(screen.getByTestId("narrow").textContent).toBe("true");

    matches = false;
    act(() => listeners.forEach((l) => l()));
    expect(screen.getByTestId("narrow").textContent).toBe("false");

    view.unmount();
    expect(listeners.size).toBe(0);
  });

  it("is false where matchMedia is missing and in the server render", () => {
    vi.stubGlobal("matchMedia", undefined);
    render(<Probe />);
    expect(screen.getByTestId("narrow").textContent).toBe("false");
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    }));
    expect(renderToString(<Probe />)).toContain("false");
  });
});
