"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setNotice(""); setError("");
    const supabase = createClient();
    try {
      if (mode === "signup") {
        const { data, error: authError } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: `${window.location.origin}/auth/callback` } });
        if (authError) throw authError;
        if (!data.session) { setNotice("Check your inbox to confirm your email, then come back to sign in."); setMode("signin"); return; }
      } else {
        const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
        if (authError) throw authError;
      }
      router.push("/library"); router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not complete sign-in.");
    } finally { setBusy(false); }
  }

  return (
    <main className="auth-page page-enter">
      <div className="auth-glow auth-glow-one" /><div className="auth-glow auth-glow-two" />
      <Link className="brand auth-brand" href="/"><span className="brand-mark">B</span><span>Bookwise</span></Link>
      <section className="auth-layout">
        <div className="auth-story"><p className="eyebrow">A library that listens</p><h1>Keep your place.<br /><em>Follow your curiosity.</em></h1><p>Bring your books into one private space and make it easier to find the ideas worth returning to.</p><div className="auth-story-note"><span>✦</span><span>Your notes begin with the source.</span></div></div>
        <div className="auth-card glass-panel">
          <div className="auth-card-top"><span className="auth-kicker">YOUR READING SPACE</span><span className="auth-lock">⌑</span></div>
          <h2>{mode === "signin" ? "Welcome back." : "Create your account."}</h2>
          <p className="auth-subtitle">{mode === "signin" ? "Sign in to return to your library." : "Your books will be private to your account."}</p>
          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            <label htmlFor="password">Password</label><input id="password" type="password" autoComplete={mode === "signin" ? "current-password" : "new-password"} minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" />
            {notice && <p className="notice notice-success" role="status">{notice}</p>}{error && <p className="notice notice-error" role="alert">{error}</p>}
            <button className="button button-dark auth-submit" disabled={busy} type="submit">{busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}<span aria-hidden="true">→</span></button>
          </form>
          <div className="auth-switch"><span>{mode === "signin" ? "New to Bookwise?" : "Already have an account?"}</span><button type="button" onClick={() => { setMode(mode === "signin" ? "signup" : "signin"); setError(""); setNotice(""); }}>{mode === "signin" ? "Create an account" : "Sign in"}</button></div>
          <p className="auth-privacy">Your sign-in is handled by Supabase Auth. Your password is never stored by Bookwise.</p>
        </div>
      </section>
      <Link className="auth-back" href="/">← Back to home</Link>
    </main>
  );
}
