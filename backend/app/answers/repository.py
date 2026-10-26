"""Private chat persistence: atomic turns, idempotency, and source snapshots."""


class ChatRepository:
    def __init__(self, client):
        self.client = client

    def list_conversations(self, owner: str, document_id: str) -> list[dict]:
        """List only the selected book's recent owner-scoped conversations."""
        return self.client.table("conversations").select("id,document_id,title,created_at,updated_at")\
            .eq("user_id", owner).eq("document_id", document_id).order("updated_at", desc=True).limit(30).execute().data or []

    def get_conversation(self, owner: str, conversation_id: str) -> dict | None:
        result = self.client.table("conversations").select("id,document_id,title,created_at,updated_at")\
            .eq("user_id", owner).eq("id", conversation_id).maybe_single().execute()
        return result.data if result else None

    def message_page(self, conversation_id: str, *, before: int | None = None, limit: int = 100) -> tuple[list[dict], bool]:
        """Call only after checking conversation ownership; use stable turn ordering."""
        query = self.client.table("messages").select("id,role,content,sequence_number,created_at,answer_payload")\
            .eq("conversation_id", conversation_id)
        if before is not None:
            query = query.lt("sequence_number", before)
        rows = query.order("sequence_number", desc=True).limit(limit + 1).execute().data or []
        return list(reversed(rows[:limit])), len(rows) > limit

    def begin(self, owner: str, document_id: str, request_id: str, question: str, conversation_id: str | None) -> dict:
        """Reserve one conversation turn or return an already completed request."""
        return self.client.rpc("phase3_begin_turn", {"p_user_id": owner, "p_document_id": document_id,
            "p_request_id": request_id, "p_question": question, "p_conversation_id": conversation_id}).execute().data

    def finish(self, owner: str, document_id: str, request_id: str, payload: dict, sources: list[dict]) -> dict:
        """SQL validates source ownership, generation, quotes, and page snapshots."""
        return self.client.rpc("phase3_finish_turn", {"p_user_id": owner, "p_document_id": document_id,
            "p_request_id": request_id, "p_payload": payload, "p_sources": sources}).execute().data

    def abort(self, owner: str, request_id: str) -> None:
        """Release failed provider calls so retry does not leave the chat locked."""
        self.client.rpc("phase3_abort_turn", {"p_user_id": owner, "p_request_id": request_id}).execute()

    def delete_conversation(self, owner: str, conversation_id: str) -> None:
        """Remove the owner's conversation, turns, snapshots, and request records."""
        self.client.table("conversations").delete().eq("user_id", owner).eq("id", conversation_id).execute()
