"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatPanel } from "@/components/chat-panel";
import { bookRequest, SignInRequired, type Book } from "@/lib/book-api";

export function BookChat({ bookId }: { bookId: string }) {
  const router = useRouter();
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    bookRequest<Book>(`/api/documents/${encodeURIComponent(bookId)}`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setBook(result); })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        if (caught instanceof SignInRequired) { router.push("/login"); return; }
        setError(caught instanceof Error ? caught.message : "Could not load this book.");
      });
    return () => controller.abort();
  }, [bookId, router]);

  return <main className="library-page chat-page page-enter">
    <header className="library-topbar glass-panel">
      <Link className="brand brand-dark" href="/library"><span className="brand-mark">B</span><span>Bookwise</span></Link>
      <Link className="button button-quiet" href="/library">← Your library</Link>
    </header>
    <section className="chat-heading">
      <p className="eyebrow">A conversation with your book</p>
      <h1>{book?.title || book?.filename || "Your reading space"}</h1>
      {book?.author && <p className="chat-author">By {book.author}</p>}
      <p className="muted-copy">Ask a question. Follow the sources back to the text.</p>
    </section>
    {error ? <p className="notice notice-error" role="alert">{error} <Link href="/library">Return to your library</Link></p> : !book ? <div className="library-empty"><span className="loading-dot" /><p>Opening your book…</p></div> : book.status !== "ready" ? <div className="chat-empty glass-panel"><h2>Your book is {book.status}</h2><p>{book.processing_error || book.processing_stage || "It needs to finish processing before you can ask questions."}</p><Link className="button button-dark" href="/library">Check your library</Link></div> : <ChatPanel book={book} />}
    <footer className="library-footer">Answers can make mistakes. Check the quoted sources, especially for important details. Page numbers refer to physical PDF pages.</footer>
  </main>;
}
