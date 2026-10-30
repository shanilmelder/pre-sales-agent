import { describe, expect, it } from "vitest";

import { authorizationParameters, DEFAULT_SCOPE } from "@/lib/auth-params";

describe("authorizationParameters", () => {
  it("keeps the Auth0 behaviour by default: audience and the standard scopes", () => {
    expect(authorizationParameters({ AUTH0_AUDIENCE: "https://api.example" })).toEqual({
      audience: "https://api.example",
      scope: DEFAULT_SCOPE,
    });
  });

  it("omits the audience when it is unset or blank (Zitadel)", () => {
    expect(authorizationParameters({})).toEqual({ scope: DEFAULT_SCOPE });
    expect(authorizationParameters({ AUTH0_AUDIENCE: "  " })).toEqual({ scope: DEFAULT_SCOPE });
  });

  it("takes the scopes from AUTH_SCOPE", () => {
    const scope = `${DEFAULT_SCOPE} urn:zitadel:iam:org:project:roles`;
    expect(authorizationParameters({ AUTH_SCOPE: ` ${scope} ` }).scope).toBe(scope);
  });
});
