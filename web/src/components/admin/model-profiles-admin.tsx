"use client";

import { useEffect, useRef, useState } from "react";

import { loadProfiles } from "@/app/admin/model-profiles/actions";
import { ModelProfileCreateForm } from "@/components/admin/model-profile-create-form";
import { ModelProfileTable } from "@/components/admin/model-profile-table";
import { RightPaneContent, useShell } from "@/components/shell/shell-context";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  isPending,
  STATUS_POLL_LIMIT_MS,
  STATUS_POLL_MS,
  upsertProfile,
  type ApprovedModel,
  type ModelProfile,
} from "@/lib/model-profiles";
import { cn } from "@/lib/utils";

/** Admin → Model profiles: the list in the main pane and the create form in the right pane.
 * While a test is pending the list is re-read every couple of seconds, for a bounded time; a
 * profile whose test hasn't started stays shown as pending, never as failed. */
export function ModelProfilesAdmin({
  initialProfiles,
  approved,
}: {
  initialProfiles: readonly ModelProfile[];
  approved: readonly ApprovedModel[];
}) {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [profiles, setProfiles] = useState<readonly ModelProfile[]>(initialProfiles);
  const [creating, setCreating] = useState(false);
  const [pollRun, setPollRun] = useState(0);
  const [stoppedKey, setStoppedKey] = useState<string | null>(null);
  const localWrites = useRef(0);
  const focusRow = useRef<string | null>(null);
  const newRow = useRef<HTMLButtonElement>(null);
  const pendingKey = profiles
    .filter(isPending)
    .map((profile) => profile.id)
    .sort()
    .join(",");

  // A new pending profile, or a local change, starts a fresh polling window.
  useEffect(() => {
    if (!pendingKey) return;
    const startedAt = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - startedAt > STATUS_POLL_LIMIT_MS) {
        clearInterval(timer);
        setStoppedKey(pendingKey);
        return;
      }
      const writes = localWrites.current;
      loadProfiles()
        .then((result) => {
          // A read that began before a local change may not have it.
          if (result.kind === "ok" && writes === localWrites.current) {
            setProfiles(result.profiles);
          }
        })
        .catch(() => {});
    }, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [pendingKey, pollRun]);

  useEffect(() => {
    const id = focusRow.current;
    focusRow.current = null;
    if (id) document.querySelector<HTMLElement>(`[data-profile-id="${id}"]`)?.focus();
  }, [profiles]);

  function startCreate() {
    setCreating(true);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: ModelProfile) {
    localWrites.current += 1;
    setStoppedKey(null);
    setPollRun((n) => n + 1);
    setProfiles((current) => upsertProfile(current, next));
  }

  function created(profile: ModelProfile) {
    focusRow.current = profile.id;
    replace(profile);
    setCreating(false);
  }

  function cancelCreate() {
    setCreating(false);
    newRow.current?.focus();
  }

  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex items-center gap-4 px-5 py-[18px]">
          <div className="min-w-0 flex-1">
            <h2 className="text-section">Chat model profiles</h2>
            <p className="text-meta text-text-secondary">
              A profile can be pinned on an Agent once its live test passes. To change one, create
              another and retire it
            </p>
          </div>
          <button
            ref={newRow}
            type="button"
            onClick={startCreate}
            className={`${cn(buttonVariants({ variant: "outline" }))} text-control`}
          >
            New profile
          </button>
        </div>
        <ModelProfileTable
          profiles={profiles}
          pollStopped={pendingKey !== "" && stoppedKey === pendingKey}
          onChange={replace}
        />
      </Card>
      {creating ? (
        <RightPaneContent>
          <ModelProfileCreateForm approved={approved} onCreated={created} onCancel={cancelCreate} />
        </RightPaneContent>
      ) : null}
    </>
  );
}
