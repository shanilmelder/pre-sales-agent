import { redirect } from "next/navigation";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { getMe } from "@/lib/api/server";
import { landingFor } from "@/lib/navigation";

// Landing: presales engineers start on My Opportunities, everyone else on Inbox.
export default async function Home() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  redirect(landingFor(result.me.roles));
}
