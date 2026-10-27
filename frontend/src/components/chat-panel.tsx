"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { bookRequest, SignInRequired, type Book } from "@/lib/book-api";
import type { AnswerResponse, ChatMessage, Citation, Conversation, ConversationPage, PendingQuestion } from "@/lib/chat-api";

function sourceLabel(source: Citation) {
  if (source.source_kind === "metadata") return "PDF metadata";
  return source.page_start === source.page_end ? `Page ${source.page_start}` : `Pages ${source.page_start}–${source.page_end}`;
}

// Evidence display: render plain text and use only server-issued source ranks.
function AssistantMessage({ message }: { message: ChatMessage }) {
  const answer = message.answer_payload;
  function openSource(rank: number) {
    const element = document.getElementById(`source-${message.id}-${rank}`);
    if (element instanceof HTMLDetailsElement) {
      element.open = true;
      element.scrollIntoView({ block: "nearest", behavior: "smooth" });
      element.querySelector("summary")?.focus();
    }
  }
  return <article className={`chat-message chat-assistant${answer?.status === "insufficient_evidence" ? " chat-insufficient" : ""}`}>
    <p className="chat-speaker">Bookwise {answer?.status === "insufficient_evidence" && <span>· More evidence needed</span>}</p>
    {answer?.statements.length ? answer.statements.map((statement, index) => <p className="chat-answer-text" key={index}>{statement.text} {statement.citation_ranks.map((rank) => <button className="citation-link" key={rank} onClick={() => openSource(rank)} aria-label={`Open source ${rank}`}>[{rank}]</button>)}</p>) : <p className="chat-answer-text">{message.content}</p>}
    {!!answer?.citations.length && <div className="chat-sources" aria-label="Answer sources"><p className="chat-source-heading">Check the sources</p>{answer.citations.map((source) => <details className="chat-source" id={`source-${message.id}-${source.rank}`} key={source.rank}>
      <summary><span className="source-rank">{source.rank}</span><span>{sourceLabel(source)}</span><span className="source-filename">{source.filename}</span></summary>
      <blockquote>{source.quote}</blockquote><p className="chat-excerpt-label">Source excerpt</p><p className="chat-source-excerpt">{source.excerpt}</p>
    </details>)}</div>}
  </article>;
}

export function ChatPanel({ book }: { book: Book }) {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const [failed, setFailed] = useState<PendingQuestion | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [error, setError] = useState("");
  const [more, setMore] = useState(false);
  const [oldest, setOldest] = useState<number | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const lastMessageId = messages.at(-1)?.id;

  const showError = useCallback((caught: unknown) => {
    if (caught instanceof SignInRequired) { router.push("/login"); return; }
    setError(caught instanceof Error ? caught.message : "Could not complete this request.");
  }, [router]);

  const fetchHistory = useCallback(async (id: string, signal: AbortSignal) => {
    const page = await bookRequest<ConversationPage>(`/api/conversations/${id}`, { signal });
    if (!signal.aborted) {
      setMessages(page.messages); setMore(page.earlier_messages_available); setOldest(page.oldest_sequence); setHistoryError(false);
    }
  }, []);

  // Conversation history: reload persisted messages, including immutable sources.
  useEffect(() => {
    const controller = new AbortController();
    requestRef.current = controller;
    (async () => {
      try {
        const list = await bookRequest<Conversation[]>(`/api/documents/${book.id}/conversations`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setConversations(list);
        if (list.length) { setConversationId(list[0].id); await fetchHistory(list[0].id, controller.signal); }
      } catch (caught) { if (!controller.signal.aborted) { setHistoryError(true); showError(caught); } }
      finally { if (!controller.signal.aborted) setLoading(false); }
    })();
    return () => controller.abort();
  }, [book.id, fetchHistory, showError]);

  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => { if (pending || lastMessageId) endRef.current?.scrollIntoView({ block: "nearest" }); }, [pending, lastMessageId]);

  async function selectConversation(id: string | null) {
    if (inFlight.current) return;
    requestRef.current?.abort();
    const controller = new AbortController(); requestRef.current = controller;
    setConversationId(id); setMessages([]); setFailed(null); setError(""); setMore(false); setOldest(null); setHistoryError(false);
    if (!id) { setLoading(false); return; }
    setLoading(true);
    try { await fetchHistory(id, controller.signal); }
    catch (caught) { if (!controller.signal.aborted) { setHistoryError(true); showError(caught); } }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }

  async function earlierMessages() {
    if (!conversationId || !oldest || inFlight.current) return;
    setLoading(true); setError("");
    const controller = new AbortController(); requestRef.current = controller;
    try {
      const page = await bookRequest<ConversationPage>(`/api/conversations/${conversationId}?before_sequence=${oldest}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setMessages((current) => [...page.messages, ...current]); setMore(page.earlier_messages_available); setOldest(page.oldest_sequence);
    } catch (caught) { if (!controller.signal.aborted) showError(caught); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }

  async function send(turn: PendingQuestion) {
    if (inFlight.current) return;
    inFlight.current = true; setPending(turn); setFailed(null); setError(""); setQuestion("");
    const controller = new AbortController(); requestRef.current = controller;
    try {
      const response = await bookRequest<AnswerResponse>(`/api/documents/${book.id}/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(turn), signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setConversationId(response.conversation_id);
      setMessages((current) => {
        // A retried request can return its saved result; keep each message once.
        const unique = current.filter((item) => item.id !== response.user_message_id && item.id !== response.message_id);
        const next = (unique.at(-1)?.sequence_number || 0) + 1;
        return [...unique, { id: response.user_message_id, role: "user", content: response.question, sequence_number: next, created_at: response.created_at, answer_payload: null }, { id: response.message_id, role: "assistant", content: response.answer.content, sequence_number: next + 1, created_at: response.created_at, answer_payload: response.answer }];
      });
      const summary: Conversation = { id: response.conversation_id, document_id: book.id, title: turn.question.slice(0, 80), created_at: response.created_at, updated_at: response.created_at };
      setConversations((current) => [current.find((item) => item.id === summary.id) || summary, ...current.filter((item) => item.id !== summary.id)]);
    } catch (caught) {
      if (!controller.signal.aborted) { setFailed(turn); showError(caught); }
    } finally {
      inFlight.current = false;
      if (!controller.signal.aborted) setPending(null);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || loading || historyError) return;
    void send({ question: question.trim(), request_id: crypto.randomUUID(), conversation_id: conversationId });
  }

  async function deleteConversation() {
    if (!conversationId || inFlight.current || !window.confirm("Delete this conversation and its messages?")) return;
    const target = conversationId;
    setLoading(true); setError("");
    const controller = new AbortController(); requestRef.current = controller;
    try {
      await bookRequest<void>(`/api/conversations/${target}`, { method: "DELETE", signal: controller.signal });
      if (controller.signal.aborted) return;
      setConversations((current) => current.filter((item) => item.id !== target));
      await selectConversation(null);
    } catch (caught) { if (!controller.signal.aborted) showError(caught); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }

  const busy = pending !== null;
  return <section className="chat-shell glass-panel" aria-label="Book conversation">
    <div className="chat-toolbar">
      <div className="chat-conversation-picker"><label htmlFor="conversation-select">Conversation</label><select id="conversation-select" value={conversationId || ""} disabled={busy || loading} onChange={(event) => void selectConversation(event.target.value || null)}><option value="">New conversation</option>{conversations.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></div>
      <div className="chat-toolbar-actions"><button className="button button-quiet" disabled={busy || loading} onClick={() => void selectConversation(null)}>New conversation</button>{conversationId && <button className="button button-quiet book-delete" disabled={busy || loading} onClick={() => void deleteConversation()}>Delete conversation</button>}</div>
    </div>
    <div className="chat-transcript" aria-label="Messages" aria-busy={busy || loading}>
      {more && <button className="button button-quiet" disabled={loading || busy} onClick={() => void earlierMessages()}>Show earlier messages</button>}
      {loading && <p className="search-hint" role="status">Loading conversation…</p>}
      {!loading && !messages.length && !pending && !failed && <div className="chat-empty"><span className="chat-book-mark" aria-hidden="true">B</span><h2>What caught your curiosity?</h2><p>Ask about {book.title || "this book"}. Each supported answer includes sources you can check.</p><div className="chat-starters">{["What is the title?", "Who is the author?"].map((text) => <button className="button button-quiet" key={text} disabled={historyError} onClick={() => setQuestion(text)}>{text}</button>)}</div></div>}
      {messages.map((message) => message.role === "assistant" ? <AssistantMessage key={message.id} message={message} /> : <article className="chat-message chat-user" key={message.id}><p className="chat-speaker">You</p><p className="chat-answer-text">{message.content}</p></article>)}
      {(pending || failed) && <article className="chat-message chat-user"><p className="chat-speaker">You</p><p className="chat-answer-text">{(pending || failed)?.question}</p></article>}
      {busy && <p className="chat-thinking" role="status"><span className="loading-dot" /> Reading the passages and checking sources…</p>}
      <div ref={endRef} />
    </div>
    <div aria-live="polite">{error && <div className="notice notice-error" role="alert"><p>{error}</p>{failed && <button className="button button-quiet" disabled={busy} onClick={() => void send(failed)}>Retry answer</button>}{historyError && <button className="button button-quiet" onClick={() => window.location.reload()}>Reload conversation</button>}</div>}</div>
    <form className="chat-composer passage-search-form" onSubmit={submit}>
      <label htmlFor="chat-question">Ask this book</label>
      <textarea id="chat-question" value={question} onChange={(event) => setQuestion(event.target.value)} disabled={busy || loading || historyError} maxLength={2000} rows={3} required placeholder="What would you like to understand?" />
      <div className="chat-composer-bottom"><p className="search-hint">Answers use this book only. If the evidence is missing, we’ll say so.</p><button className="button button-dark" disabled={busy || loading || historyError || !question.trim()} type="submit">{busy ? "Preparing answer…" : "Ask book"}<span aria-hidden="true">↗</span></button></div>
    </form>
  </section>;
}
