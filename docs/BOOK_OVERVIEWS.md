# Short book overviews

Generic requests such as “Summarize this book,” “What is this book about?”, or “Give me a short summary and tell me the story” use a dedicated overview path. Specific questions and chapter/topic summaries continue through semantic search.

The backend reads at most 17 chunk positions from the signed-in owner's selected book and current processing run. It samples opening context and later sections, excludes obvious publication/license pages, and fits the chosen excerpts within the configured answer context budget. It does not require another migration or reprocessing an already indexed book.

The backend extracts complete source sentences. The local or configured hosted model selects two or three sentence IDs; the application constructs their text and quotes directly from those immutable source sentences. Every statement still passes the existing source-ID, exact-quote, number, and vocabulary checks; the database independently checks ownership and derives physical PDF page citations. Publication-only evidence or an empty selection still produces an insufficient-evidence response. A provider that returns an unknown ID produces a safe provider error.

Successful overviews display a coverage note that is saved with the answer and restored with conversation history. This is a short extractive overview of sampled passages. It can omit important events, includes excerpts from later sections that may reveal plot details, and does not claim a complete plot or chapter-by-chapter summary. A comprehensive long-book summary needs a separate process that reviews every section.

To verify:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
$env:PHASE3_LIVE_TEST = '1'
.\.venv\Scripts\python.exe -m scripts.verify_overviews
```

The live check creates confirmed temporary accounts without sending email, uploads a synthetic story, verifies citations and saved coverage, checks cross-owner rejection and an unrelated topic, then removes its accounts and files. The normal API, worker, embedding model, and answer provider must be running.

The implementation passes 137 offline backend tests. The live synthetic-story check verifies cited answers, retained history notes, owner isolation, and unrelated-topic abstention. A read-only check of the existing Pickwick Papers index also returns verified source extracts for the reported question; its book and existing conversation are unchanged.
