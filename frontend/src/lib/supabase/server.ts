import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !publishableKey) {
    throw new Error("Set the Supabase URL and publishable key in frontend/.env.local.");
  }

  const cookieStore = await cookies();
  return createServerClient(url, publishableKey, {
    cookieOptions: { secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/' },
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
        } catch {
          // Server Components cannot write cookies. The Next.js proxy refreshes sessions.
        }
      },
    },
  });
}
