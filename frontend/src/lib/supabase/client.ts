import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !publishableKey) {
    throw new Error("Set the Supabase URL and publishable key in frontend/.env.local.");
  }

  return createBrowserClient(url, publishableKey, {
    cookieOptions: { secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/' },
  });
}
