"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { bookRequest, SignInRequired, type Book } from "@/lib/book-api";

type Passage = {
  id: string;
  document_id: string;
  content: string;
  page_start: number;
  page_end: number;
  chunk_index: number;
  similarity: number;
};
type SearchResult = { document_id: string; question: string; passages: Passage[] };

// Vector storage and search: display actual retrieved text and physical PDF pages.
export function BookSearch({ book, onClose }: { book: Book; onClose: () => void }) {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!question.trim()) { setError("Enter a question to search this book."); return; }
    setBusy(true); setError(""); setResult(null);
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      const payload = await bookRequest<SearchResult>(`/api/documents/${book.id}/search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), top_k: topK }), signal: controller.signal,
      });
      setResult(payload);
    } catch (caught) {
      if (controller.signal.aborted) return;
      if (caught instanceof SignInRequired) { router.push("/login"); return; }
      setError(caught instanceof Error ? caught.message : "Could not search this book.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return (
    <section className="book-search glass-panel" aria-labelledby="book-search-heading">
      <div className="search-heading"><div><p className="eyebrow">Find it in your book</p><h2 id="book-search-heading">Search passages</h2><p className="search-book-name">{book.filename}</p></div><button className="button button-quiet" type="button" onClick={onClose} aria-label="Close passage search">Close</button></div>
      <form className="passage-search-form" onSubmit={search}>
        <label htmlFor="book-question">What would you like to find?</label>
        <textarea id="book-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={2000} rows={3} required placeholder="For example: What does the author say about friendship?" />
        <div className="search-controls"><label htmlFor="passage-count">Passages <select id="passage-count" value={topK} onChange={(event) => setTopK(Number(event.target.value))}><option value={3}>3</option><option value={5}>5</option><option value={10}>10</option></select></label><button className="button button-dark" type="submit" disabled={busy || !question.trim()}>{busy ? "Finding passages…" : "Search this book"}</button></div>
      </form>
      <p className="search-hint">Find relevant passages with their source page numbers. Results show the book’s original text.</p>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <div aria-live="polite" aria-busy={busy}>
        {busy && <p className="search-hint">Searching your book…</p>}
        {result && <><p className="search-result-summary">{result.passages.length} passages for “{result.question}”</p>{result.passages.length === 0 ? <p className="search-hint">No passages were found. Try a more specific question.</p> : <div className="passage-results">{result.passages.map((passage, index) => <article className="passage-card" key={passage.id}><header><span>Passage {index + 1}</span><span className="passage-pages">{passage.page_start === passage.page_end ? `Page ${passage.page_start}` : `Pages ${passage.page_start}–${passage.page_end}`}</span></header><p>{passage.content}</p></article>)}</div>}</>}
      </div>
    </section>
  );
}
