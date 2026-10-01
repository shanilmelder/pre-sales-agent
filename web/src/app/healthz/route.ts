// Liveness for the web container (compose healthcheck). Does not call the API.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", version: process.env.PSA_VERSION ?? "0.0.0-dev" });
}
