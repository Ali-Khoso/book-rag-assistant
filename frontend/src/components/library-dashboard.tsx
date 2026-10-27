"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UploadBook } from "@/components/upload-book";
import { BookSearch } from "@/components/book-search";
import { bookRequest, SignInRequired, type Book } from "@/lib/book-api";
import { createClient } from "@/lib/supabase/client";

export function LibraryDashboard() {
  const router = useRouter();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyBook, setBusyBook] = useState<string | null>(null);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
  const backgroundLoading = useRef(false);
  const loadGeneration = useRef(0);
  const hasPendingBooks = books.some((book) => book.status === "queued" || book.status === "processing");
  const selectedBook = books.find((book) => book.id === selectedBookId);

  const loadBooks = useCallback(async (background = false, signal?: AbortSignal) => {
    if (background && backgroundLoading.current) return;
    if (background) backgroundLoading.current = true;
    const generation = ++loadGeneration.current;
    if (!background) setError("");
    try {
      const payload = await bookRequest<Book[]>("/api/documents", { signal });
      if (!signal?.aborted && generation === loadGeneration.current) setBooks(payload);
    } catch (caught) {
      if (signal?.aborted) return;
      if (caught instanceof SignInRequired) { router.push("/login"); return; }
      setError(caught instanceof Error ? caught.message : "Could not load your library.");
    } finally { if (background) backgroundLoading.current = false; if (!signal?.aborted) setLoading(false); }
  }, [router]);

  useEffect(() => {
    const controller = new AbortController();
    void loadBooks(false, controller.signal);
    return () => controller.abort();
  }, [loadBooks]);

  // Processing status and retry: poll active books without resetting the whole page.
  useEffect(() => {
    if (!hasPendingBooks) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadBooks(true, controller.signal);
    }, 4000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [hasPendingBooks, loadBooks]);

  async function signOut() {
    await createClient().auth.signOut(); router.push("/login"); router.refresh();
  }

  async function retryBook(book: Book) {
    setError(""); setBusyBook(book.id);
    try {
      const updated = await bookRequest<Book>("/api/documents/" + book.id + "/retry", { method: "POST" });
      loadGeneration.current += 1;
      setBooks((current) => current.map((item) => item.id === book.id ? updated : item));
    } catch (caught) {
      if (caught instanceof SignInRequired) { router.push("/login"); return; }
      setError(caught instanceof Error ? caught.message : "Could not retry this book.");
    } finally { setBusyBook(null); }
  }

  async function deleteBook(book: Book) {
    if (!window.confirm("Delete “" + book.filename + "” from your library?")) return;
    setError(""); setBusyBook(book.id);
    try {
      await bookRequest<void>("/api/documents/" + book.id, { method: "DELETE" });
      loadGeneration.current += 1;
      setBooks((current) => current.filter((item) => item.id !== book.id));
      if (selectedBookId === book.id) setSelectedBookId(null);
    } catch (caught) {
      if (caught instanceof SignInRequired) { router.push("/login"); return; }
      setError(caught instanceof Error ? caught.message : "Could not delete this book.");
    } finally { setBusyBook(null); }
  }

  return (
    <main className="library-page page-enter">
      <header className="library-topbar glass-panel">
        <Link className="brand brand-dark" href="/" aria-label="Bookwise home"><span className="brand-mark">B</span><span>Bookwise</span></Link>
        <div className="library-top-actions"><span className="privacy-pill"><span className="privacy-dot" /> Private library</span><button className="button button-quiet" onClick={() => void signOut()}>Sign out</button></div>
      </header>
      <section className="library-heading">
        <div><p className="eyebrow">Your reading space</p><h1>Books, ready to explore.</h1><p className="muted-copy">Upload a PDF, ask questions, and explore the sources behind each answer.</p></div>
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
            <div className="book-row-info"><h3>{book.title || book.filename}</h3>{book.title && <p>{book.filename}{book.author && " · " + book.author}</p>}<p>Added {new Date(book.created_at).toLocaleDateString()}{book.status === "ready" && " · " + book.page_count + " pages · " + book.chunk_count + " passages"}</p>
              {book.status === "processing" && <p className="book-progress">{book.processing_stage || "Processing your book…"}</p>}
              {book.status === "queued" && <p className="book-progress">Waiting to process</p>}
              {book.status === "failed" && <p className="book-processing-error">{book.processing_error || "Processing failed. Please retry."}</p>}
            </div>
            <span className={"book-status status-" + book.status}><span />{book.status}</span>
            <div className="book-actions">
              {book.status === "ready" && <Link className="button button-dark" href={`/library/books/${book.id}`}>Ask book</Link>}
              {book.status === "ready" && <button className="button button-quiet" type="button" aria-pressed={selectedBookId === book.id} onClick={() => setSelectedBookId(book.id)}>Search book</button>}
              {(book.status === "failed" || book.status === "ready") && <button className="button button-quiet" type="button" disabled={busyBook !== null} onClick={() => void retryBook(book)}>{busyBook === book.id ? "Please wait…" : book.status === "failed" ? "Retry" : "Reprocess"}</button>}
              <button className="button button-quiet book-delete" type="button" disabled={busyBook !== null} onClick={() => void deleteBook(book)} aria-label={"Delete " + book.filename}>Delete</button>
            </div>
          </article>)}</div>
        )}
      </section>
      {selectedBook?.status === "ready" && <BookSearch key={selectedBook.id} book={selectedBook} onClose={() => setSelectedBookId(null)} />}
      <footer className="library-footer">Your books are stored privately and belong to your account.</footer>
    </main>
  );
}
