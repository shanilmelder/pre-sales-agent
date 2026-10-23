import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PersonChip } from "./header-parts";

function avatarText(name: string): string {
  const { container } = render(<PersonChip name={name} role="Collaborator" />);
  return container.querySelector('[data-slot="avatar-fallback"]')?.textContent ?? "";
}

describe("PersonChip initials", () => {
  it.each([
    ["Ada Lovelace", "AL"],
    ["Ada Byron Lovelace", "AL"],
    ["Ada", "A"],
    ["  ada   lovelace ", "AL"],
    ["😀 Smith", "😀S"],
    ["   ", "?"],
  ])("%j shows %j", (name, initials) => {
    expect(avatarText(name)).toBe(initials);
  });
});
