// Chat contracts: source pages and excerpts come from verified server snapshots.
export type Citation = {
  rank: number;
  source_kind: "passage" | "metadata";
  chunk_id: string | null;
  document_id: string;
  filename: string;
  page_start: number | null;
  page_end: number | null;
  excerpt: string;
  quote: string;
};
export type Answer = {
  status: "answered" | "insufficient_evidence";
  method: "metadata" | "model";
  content: string;
  scope_note?: string | null;
  statements: { text: string; citation_ranks: number[] }[];
  citations: Citation[];
};
export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence_number: number;
  created_at: string;
  answer_payload: Answer | null;
};
export type Conversation = {
  id: string;
  document_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
export type ConversationPage = {
  conversation: Conversation;
  messages: ChatMessage[];
  earlier_messages_available: boolean;
  oldest_sequence: number | null;
};
export type AnswerResponse = {
  conversation_id: string;
  request_id: string;
  user_message_id: string;
  message_id: string;
  document_id: string;
  question: string;
  created_at: string;
  answer: Answer;
};
export type PendingQuestion = { question: string; request_id: string; conversation_id: string | null };
