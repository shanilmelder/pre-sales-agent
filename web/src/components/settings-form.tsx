"use client";

import { useId, useRef, useState, useTransition, type ReactNode } from "react";

import { savePreferences } from "@/app/settings/actions";
// Types only: the preferences module imports next/headers.
import type { Density, Preferences, Theme } from "@/lib/preferences";

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const DENSITY_OPTIONS: { value: Density; label: string; hint: string }[] = [
  { value: "comfortable", label: "Comfortable", hint: "32px rows" },
  { value: "compact", label: "Compact", hint: "28px rows" },
];

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
    <fieldset className="flex flex-col gap-2" aria-describedby={descriptionId}>
      <legend className="text-section">{legend}</legend>
      <p id={descriptionId} className="text-meta text-muted-foreground">
        {description}
      </p>
      <div className="flex gap-2">
        {options.map((option) => (
          <label
            key={option.value}
            className="flex h-row cursor-pointer items-center gap-2 rounded-md border border-border px-3 has-checked:border-primary has-focus-visible:ring-3 has-focus-visible:ring-primary"
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="accent-primary outline-none"
            />
            <span className="text-body-strong">{option.label}</span>
            {option.hint ? (
              <span className="text-meta text-muted-foreground">{option.hint}</span>
            ) : null}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Section({ children }: { children: ReactNode }) {
  return <div className="border-b border-border py-4 last:border-b-0">{children}</div>;
}

export function SettingsForm({ initial }: { initial: Preferences }) {
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
    });
  }

  return (
    <form className="flex flex-col" onSubmit={(event) => event.preventDefault()}>
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
            <label htmlFor={shortcutsId} className="text-section">
              Single-key shortcuts
            </label>
            <p id={shortcutsDescriptionId} className="text-meta text-muted-foreground">
              Shortcuts such as c to create and j or k to move. Ctrl+K works either way.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* One label (above). The transparent input covers the track, so clicking the
                track toggles it without a second, wrapping label. */}
            <span className="relative flex">
              <input
                id={shortcutsId}
                type="checkbox"
                role="switch"
                aria-describedby={shortcutsDescriptionId}
                checked={preferences.singleKeyShortcuts}
                onChange={(event) => update({ singleKeyShortcuts: event.target.checked })}
                className="peer absolute inset-0 z-10 m-0 cursor-pointer opacity-0"
              />
              <span
                aria-hidden="true"
                className="relative h-5 w-9 rounded-full bg-muted-foreground transition-colors peer-checked:bg-primary peer-focus-visible:ring-3 peer-focus-visible:ring-primary after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-background after:transition-transform peer-checked:after:translate-x-4"
              />
            </span>
            <span aria-hidden="true" className="w-6 text-body-strong">
              {preferences.singleKeyShortcuts ? "On" : "Off"}
            </span>
          </div>
        </div>
      </Section>
      <p role="status" aria-live="polite" className="text-meta text-destructive">
        {failed ? "Your settings could not be saved. Try again." : ""}
      </p>
    </form>
  );
}
