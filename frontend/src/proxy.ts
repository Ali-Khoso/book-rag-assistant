import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  const development = process.env.NODE_ENV === 'development';
  const origins = [url, process.env.NEXT_PUBLIC_API_URL].flatMap((value) => {
    try { return value ? [new URL(value).origin] : []; } catch { return []; }
  });
  const csp = ["default-src 'self'", `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ''}`,
    "style-src 'self' 'unsafe-inline'", `connect-src 'self' ${origins.join(' ')}${development ? ' ws://localhost:* ws://127.0.0.1:*' : ''}`,
    "img-src 'self' data: blob:", "font-src 'self'", "object-src 'none'", "base-uri 'self'",
    "form-action 'self'", "frame-ancestors 'none'"].join('; ');

  function forward() {
    const headers = new Headers(request.headers);
    headers.set('x-nonce', nonce); headers.set('Content-Security-Policy', csp);
    return NextResponse.next({ request: { headers } });
  }
  function secure(result: NextResponse) {
    result.headers.set('Content-Security-Policy', csp);
    result.headers.set('X-Content-Type-Options', 'nosniff');
    result.headers.set('X-Frame-Options', 'DENY');
    result.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    result.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    result.headers.set('Cache-Control', 'private, no-store');
    return result;
  }
  let response = forward();

  if (!url || !publishableKey) return secure(response);

  const supabase = createServerClient(url, publishableKey, {
    cookieOptions: { secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/' },
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = forward();
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  // Verify the signed token claims; do not trust a session object from cookies alone.
  const { data } = await supabase.auth.getClaims();
  const isLibraryRoute = request.nextUrl.pathname.startsWith("/library");

  if (isLibraryRoute && !data?.claims) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return secure(NextResponse.redirect(loginUrl));
  }

  return secure(response);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
