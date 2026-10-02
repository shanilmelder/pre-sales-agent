import type { ReactNode } from "react";

import { AvatarMenu } from "@/components/avatar-menu";
import type { Me, MeResult } from "@/lib/api/server";

const NO_ACCESS_MESSAGE =
  "You're signed in, but you don't have access yet. Ask an administrator to assign a role.";

function Notice({ children }: { children: ReactNode }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
      {children}
    </main>
  );
}

export function SignedInHeader({ me }: { me: Me }) {
  return (
    <header className="flex h-12 items-center justify-between border-b border-border px-4">
      <span className="text-sm font-semibold">Pre-Sales Agent</span>
      <AvatarMenu name={me.name} email={me.email} />
    </header>
  );
}

/** True when the user may see page content: signed in and holding at least one role. */
export function hasAccess(result: MeResult): result is { kind: "ok"; me: Me } {
  return result.kind === "ok" && result.me.roles.length > 0;
}

/** What a page renders instead of its content when `hasAccess` is false.
 *
 * Gate in each page (or not-found), never in a layout: Next.js renders a page alongside
 * its layout, so a layout that hides `children` still ships the page in the payload. */
export function AccessGate({ result }: { result: MeResult }) {
  if (result.kind === "signed-out") {
    return (
      <Notice>
        <p>Your session has ended.</p>
        <a href="/auth/login" className="text-primary underline-offset-4 hover:underline">
          Sign in again
        </a>
      </Notice>
    );
  }
  if (result.kind === "unavailable") {
    return (
      <Notice>
        <p>The platform is not reachable right now. Try again in a moment.</p>
      </Notice>
    );
  }
  return (
    <>
      <SignedInHeader me={result.me} />
      <Notice>
        <p>{NO_ACCESS_MESSAGE}</p>
      </Notice>
    </>
  );
}
