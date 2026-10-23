import { redirect } from "next/navigation";

import { MY_OPPORTUNITIES_HREF } from "@/lib/navigation";

/** The old My Opportunities page: now the Mine view of the Opportunities list. */
export default function MyOpportunitiesPage() {
  redirect(MY_OPPORTUNITIES_HREF);
}
