"use client";

import { createClient } from "@/lib/supabase/client";

export type Book = {
  id: string;
  filename: string;
  title: string | null;
  author: string | null;
  processing_attempts?: number;
  processing_max_attempts?: number;
  processing_next_attempt_at?: string | null;
  status: "queued" | "processing" | "ready" | "failed";
  page_count: number | null;
  created_at: string;
  processing_error: string | null;
  processing_stage: string | null;
  chunk_count: number;
  processed_at: string | null;
};

export class SignInRequired extends Error {}

export class ApiError extends Error {
  constructor(message: string, public status: number, public retryAfter: number | null) { super(message); }
}

export type Usage = { books: number; max_books: number; storage_bytes: number; max_storage_bytes: number;
  questions_today: number; max_questions_per_day: number; pending_deletions: number };

// API authentication: the server derives ownership from this verified session.
export async function bookRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const supabase = createClient();
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.access_token) throw new SignInRequired("Sign in to continue.");
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl) throw new Error("The book service is not configured. Please try again later.");
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${data.session.access_token}`);
  let response: Response;
  try {
    response = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, { ...options, cache: "no-store", headers });
  } catch (caught) {
    if (options.signal?.aborted) throw caught;
    throw new Error("Could not connect to the book service. Check your connection and try again.");
  }
  if (response.status === 401) {
    await supabase.auth.signOut();
    throw new SignInRequired("Your session expired. Sign in again.");
  }
  if (response.status === 204) return undefined as T;
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error("The book service returned an unexpected response. Please try again."); }
  if (!response.ok) throw new ApiError(typeof payload.detail === "string" ? payload.detail : "The request could not be completed. Please try again.", response.status,
    response.headers.has('Retry-After') ? Number(response.headers.get('Retry-After')) : null);
  return payload as T;
}
