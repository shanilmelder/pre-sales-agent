// Typed API client. The web app calls the backend only through this client (AD-16).
import createClient from "openapi-fetch";

import type { paths } from "./schema";

export type { components, paths } from "./schema";

export function createApiClient(baseUrl: string = process.env.PSA_API_URL ?? "http://localhost:8000") {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
