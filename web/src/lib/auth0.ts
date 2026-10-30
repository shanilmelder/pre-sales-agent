// OIDC client (nextjs-auth0 v4). Written for Auth0 and works with any OIDC provider that
// publishes /.well-known/openid-configuration, such as Zitadel: set AUTH0_DOMAIN to the
// provider's host (no path), with AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_SECRET (the
// session cookie key) and APP_BASE_URL.
//
// Optional provider settings:
//   AUTH0_AUDIENCE  API identifier sent as `audience` (Auth0). Leave unset for providers that
//                   take the audience from the project instead (Zitadel).
//   AUTH_SCOPE      Space-separated scopes. The default suits Auth0. For Zitadel add
//                   `urn:zitadel:iam:org:project:roles` so the access token carries roles.
// Logout follows the provider's end_session_endpoint when it has one (the SDK's default).
import { Auth0Client } from "@auth0/nextjs-auth0/server";

import { authorizationParameters } from "@/lib/auth-params";

export const auth0 = new Auth0Client({
  authorizationParameters: authorizationParameters(),
});
