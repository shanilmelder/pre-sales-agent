// Authentication boundary (Next.js 16 proxy). Mounts the Auth0 routes under /auth/* and
// sends visitors without a session to Universal Login, returning them to the page they
// asked for. /healthz stays public; static assets are excluded by the matcher.
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { NextResponse, type NextRequest } from "next/server";

import { auth0 } from "@/lib/auth0";

const PUBLIC_PATHS = new Set(["/healthz"]);

function redirectToLogin(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const login = new URL("/auth/login", request.nextUrl);
  login.search = new URLSearchParams({ returnTo: pathname + search }).toString();
  return NextResponse.redirect(login, 307);
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const authResponse = await auth0.middleware(request);
  if (pathname === "/auth" || pathname.startsWith("/auth/")) {
    return authResponse;
  }

  const session = await auth0.getSession(request);
  if (!session) {
    return redirectToLogin(request);
  }
  try {
    // Server Components can't write cookies, so refresh an expired access token here,
    // where the SDK can persist the new token set on the response.
    await auth0.getAccessToken(request, authResponse);
  } catch (error) {
    if (error instanceof AccessTokenError) return redirectToLogin(request);
    throw error;
  }
  return authResponse;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt|.*\\..*).*)"],
};
