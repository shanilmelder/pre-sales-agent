import { AccessGate, hasAccess } from "@/components/access-gate";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";

// Unknown pages are gated too: a user without roles sees only the no-access message.
export default async function NotFound() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      <div className="p-gutter">
        <p>This page does not exist.</p>
      </div>
    </AppShell>
  );
}
