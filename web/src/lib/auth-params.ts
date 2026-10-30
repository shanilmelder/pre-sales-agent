// Authorization parameters for the OIDC client, kept apart from the client itself so they can
// be tested without constructing it (the SDK reads its environment on construction).
export const DEFAULT_SCOPE = "openid profile email offline_access";

export function authorizationParameters(
  env: Record<string, string | undefined> = process.env,
) {
  const audience = env.AUTH0_AUDIENCE?.trim();
  return {
    ...(audience ? { audience } : {}),
    scope: env.AUTH_SCOPE?.trim() || DEFAULT_SCOPE,
  };
}
