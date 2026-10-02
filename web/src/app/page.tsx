import { AccessGate, SignedInHeader, hasAccess } from "@/components/access-gate";
import { getMe } from "@/lib/api/server";

// Placeholder home until the app shell (Story 1.5).
export default async function Home() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <>
      <SignedInHeader me={result.me} />
      <main className="flex flex-1 flex-col items-center justify-center gap-2 p-8">
        <h1 className="text-xl font-semibold">Pre-Sales Agent</h1>
        <p className="text-sm text-muted-foreground">Signed in as {result.me.name}</p>
      </main>
    </>
  );
}
