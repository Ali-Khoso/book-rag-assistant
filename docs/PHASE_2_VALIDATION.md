# Phase 2 validation — 27 October 2026

These results describe the checked local development setup and connected Supabase project. They are not a production load test or a general retrieval-quality benchmark.

## PDF text extraction and text chunking

- The existing uploaded book reached **Ready**, with **558 physical PDF pages** and **1,467 indexed passages**.
- Offline tests cover page numbering across blank pages, damaged/empty/scanned/encrypted PDFs, extraction limits, overlap, and page-range attribution.

## Embeddings and vector storage/search

- The pinned local Model2Vec model produces normalized, finite, nonzero 256-dimensional vectors.
- A synthetic four-page PDF contains reviewed facts about astronomy, geology, photosynthesis, and bird migration. All **4/4 questions** returned supporting text with the expected source page **at rank 1**, and therefore within the top three results.
- Spot checks against the actual uploaded book found a cricket passage on physical PDF page **67** and a Fleet prison passage on physical PDF page **414** within the top five results. These checks establish that the real book was indexed and searchable; they do not establish comprehensive answer quality.
- Reprocessing replaced the index with the same complete, sequential chunk set and no duplicates.

## Processing status, retry, and ownership

- Live uploads progressed to ready. A scanned PDF failed with OCR guidance and could be retried safely.
- A second user could not search, retry, delete, or list the first user's book through the API.
- Direct chunk reads under the second user's JWT returned no rows from the first user's book.
- Direct authenticated-client execution of a processing/search RPC with a forged owner was denied.
- Temporary test accounts and synthetic PDFs were removed after the checks. Original user books were retained.

## Browser and code checks

- **32 offline backend tests passed.**
- Frontend TypeScript checks passed, and `pip check` reported no broken requirements.
- An isolated headless browser verified sign-in, password visibility, inline validation, PDF upload, automatic processing, passage retrieval, reprocessing, and deletion without JavaScript page errors.
- Desktop (1,440 px) and mobile (390 px) layouts fit their viewports. Local screenshots are stored under ignored `backend/.cache`.

Repeatable commands and the limits of this implementation are documented in [Phase 2 Setup](PHASE_2_SETUP.md). Generated answers/citations remain Phase 3; OCR and production worker hardening remain future work.
