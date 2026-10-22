"use client";

import { useId, useRef, useState, useTransition, type ReactNode } from "react";

import { savePreferences } from "@/app/settings/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Card, CardFooter } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
// Types only: the preferences module imports next/headers.
import type { Density, Preferences, Theme } from "@/lib/preferences";

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const DENSITY_OPTIONS: { value: Density; label: string; hint: string }[] = [
  { value: "comfortable", label: "Comfortable", hint: "56px rows" },
  { value: "compact", label: "Compact", hint: "44px rows" },
];

/** A radio group drawn as option cards. The native radio stays in the DOM (visually hidden)
 * so arrow keys, Tab and screen readers behave as for any radio group. */
function RadioGroup<T extends string>({
  legend,
  description,
  name,
  value,
  options,
  onChange,
}: {
  legend: string;
  description: string;
  name: string;
  value: T;
  options: { value: T; label: string; hint?: string }[];
  onChange: (value: T) => void;
}) {
  const descriptionId = useId();
  return (
    <fieldset className="flex flex-col gap-3" aria-describedby={descriptionId}>
      <legend className="text-section">{legend}</legend>
      <p id={descriptionId} className="text-meta text-text-secondary">
        {description}
      </p>
      <div className="flex flex-wrap gap-3">
        {options.map((option) => (
          <label
            key={option.value}
            className="flex min-w-36 cursor-pointer flex-col gap-0.5 rounded-lg border border-border-strong bg-surface px-4 py-3 has-checked:border-primary has-checked:bg-primary-tint has-focus-visible:ring-2 has-focus-visible:ring-ring has-focus-visible:ring-offset-2 has-focus-visible:ring-offset-background"
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            <span className="text-body-strong">{option.label}</span>
            {option.hint ? (
              <span className="text-meta text-text-secondary">{option.hint}</span>
            ) : null}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Section({ children }: { children: ReactNode }) {
  return <div className="p-6">{children}</div>;
}

const SAVE_FAILED = "Your settings could not be saved. Try again.";

export function SettingsForm({ initial }: { initial: Preferences }) {
  const announce = useAnnounce();
  const [preferences, setPreferences] = useState<Preferences>(initial);
  const [failed, setFailed] = useState(false);
  const [, startTransition] = useTransition();
  const lastSaved = useRef<Preferences>(initial);
  const shortcutsId = useId();
  const shortcutsDescriptionId = useId();

  function update(change: Partial<Preferences>) {
    const next = { ...preferences, ...change };
    setPreferences(next);
    startTransition(async () => {
      let ok = false;
      try {
        ok = (await savePreferences(next)).ok;
      } catch {
        ok = false;
      }
      if (ok) {
        lastSaved.current = next;
      } else {
        // Show what is actually stored, not the choice that failed to save.
        setPreferences(lastSaved.current);
      }
      setFailed(!ok);
      if (!ok) announce(SAVE_FAILED);
    });
  }

  return (
    <form onSubmit={(event) => event.preventDefault()}>
      <Card className="w-settings-width max-w-full">
        <Section>
          <RadioGroup
            legend="Theme"
            description="System follows your operating system's light or dark setting."
            name="theme"
            value={preferences.theme}
            options={THEME_OPTIONS}
            onChange={(theme) => update({ theme })}
          />
        </Section>
        <Section>
          <RadioGroup
            legend="Density"
            description="Row height in lists and tables."
            name="density"
            value={preferences.density}
            options={DENSITY_OPTIONS}
            onChange={(density) => update({ density })}
          />
        </Section>
        <Section>
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-col gap-1">
              <span id={shortcutsId} className="text-section">
                Single-key shortcuts
              </span>
              <p id={shortcutsDescriptionId} className="text-meta text-text-secondary">
                Shortcuts such as c to create and j or k to move. Off by default. Ctrl+K works
                either way.
              </p>
            </div>
            <Switch
              aria-labelledby={shortcutsId}
              aria-describedby={shortcutsDescriptionId}
              checked={preferences.singleKeyShortcuts}
              onCheckedChange={(singleKeyShortcuts) => update({ singleKeyShortcuts })}
            />
          </div>
        </Section>
        <CardFooter className="rounded-b-xl bg-surface-alt px-6 py-4">
          <p className="text-meta text-text-secondary">
            Saved in this browser.
          </p>
        </CardFooter>
      </Card>
      {/* Screen readers hear this through the shell's single live region. */}
      <p className="mt-3 text-meta text-destructive">{failed ? SAVE_FAILED : ""}</p>
    </form>
  );
}
