import { AccessGate, SignedInHeader, hasAccess } from "@/components/access-gate";
import { getMe } from "@/lib/api/server";

// Unknown pages are gated too: a user without roles sees only the no-access message.
export default async function NotFound() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <>
      <SignedInHeader me={result.me} />
      <main className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
        <p>This page does not exist.</p>
      </main>
    </>
  );
}
