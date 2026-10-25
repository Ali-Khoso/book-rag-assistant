"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UploadBook } from "@/components/upload-book";
import { createClient } from "@/lib/supabase/client";

type Book = { id: string; filename: string; status: "queued" | "processing" | "ready" | "failed"; page_count: number | null; created_at: string };

export function LibraryDashboard() {
  const router = useRouter();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadBooks = useCallback(async () => {
    setError("");
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    if (!data.session?.access_token) { router.push("/login"); return; }
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!apiUrl) { setError("Set NEXT_PUBLIC_API_URL in frontend/.env.local."); setLoading(false); return; }
    try {
      const response = await fetch(`${apiUrl}/api/documents`, { headers: { Authorization: `Bearer ${data.session.access_token}` }, cache: "no-store" });
      const payload = await response.json();
      if (response.status === 401) { await supabase.auth.signOut(); router.push("/login"); return; }
      if (!response.ok) throw new Error(payload.detail || "Could not load your library.");
      setBooks(payload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load your library.");
    } finally { setLoading(false); }
  }, [router]);

  useEffect(() => { void loadBooks(); }, [loadBooks]);

  async function signOut() {
    await createClient().auth.signOut(); router.push("/login"); router.refresh();
  }

  async function deleteBook(book: Book) {
    if (!window.confirm(`Delete “${book.filename}” from your library?`)) return;
    setError("");
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    if (!data.session?.access_token) { router.push("/login"); return; }
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!apiUrl) { setError("Set NEXT_PUBLIC_API_URL in frontend/.env.local."); return; }
    try {
      const response = await fetch(`${apiUrl.replace(/\/$/, "")}/api/documents/${book.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${data.session.access_token}` },
      });
      if (response.status === 401) { await supabase.auth.signOut(); router.push("/login"); return; }
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail || "Could not delete this book.");
      }
      setBooks((current) => current.filter((item) => item.id !== book.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete this book.");
    }
  }

  return (
    <main className="library-page page-enter">
      <header className="library-topbar glass-panel">
        <Link className="brand brand-dark" href="/" aria-label="Bookwise home"><span className="brand-mark">B</span><span>Bookwise</span></Link>
        <div className="library-top-actions"><span className="privacy-pill"><span className="privacy-dot" /> Private library</span><button className="button button-quiet" onClick={() => void signOut()}>Sign out</button></div>
      </header>
      <section className="library-heading">
        <div><p className="eyebrow">Your reading space</p><h1>Books, ready to explore.</h1><p className="muted-copy">Add a PDF now. In the next phase, we’ll make every page searchable.</p></div>
        <div className="library-count"><strong>{books.length.toString().padStart(2, "0")}</strong><span>books in your library</span></div>
      </section>
      <UploadBook onUploaded={() => void loadBooks()} />
      <section className="library-list-section">
        <div className="section-heading-row"><div><p className="eyebrow">Collection</p><h2>Your books</h2></div><span className="collection-count">{books.length} total</span></div>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        {loading ? <div className="library-empty"><span className="loading-dot" /><p>Loading your library…</p></div> : books.length === 0 ? (
          <div className="library-empty"><div className="empty-book-icon">▤</div><h3>Your shelf is waiting</h3><p>Upload your first PDF to begin.</p></div>
        ) : (
          <div className="book-list">{books.map((book) => <article className="book-row glass-panel" key={book.id}>
            <div className="book-row-cover" aria-hidden="true"><span>PDF</span></div>
            <div className="book-row-info"><h3>{book.filename}</h3><p>Added {new Date(book.created_at).toLocaleDateString()}</p></div>
            <span className={`book-status status-${book.status}`}><span />{book.status}</span>
            <button className="button button-quiet book-delete" type="button" onClick={() => void deleteBook(book)} aria-label={`Delete ${book.filename}`}>Delete</button>
          </article>)}</div>
        )}
      </section>
      <footer className="library-footer">Your books are stored privately and belong to your account.</footer>
    </main>
  );
}
