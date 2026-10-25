# RAG Concepts and Interview Questions

A beginner-friendly guide to the ideas behind the Book-Based RAG Assistant. Answers are short enough to review before an interview, but include the reasoning needed to explain the concepts clearly.

## RAG in one minute

**Retrieval-Augmented Generation (RAG)** gives a language model relevant information from an external source when it answers. For this project, the source is an uploaded book. The app searches the book for useful passages, gives those passages to the model, and asks it to answer using that evidence. RAG is a way to provide current or private reference material without retraining the language model on every document.

## Key concepts

| Concept | Plain-language meaning |
| --- | --- |
| Ingestion | Preparing an uploaded document so the system can search it. |
| Text extraction | Reading text from the PDF, ideally keeping page numbers and structure. |
| Chunk | A smaller section of a document stored and searched as one unit. |
| Chunk overlap | Repeating a small amount of text between neighboring chunks so a sentence or idea split at a boundary is less likely to lose context. |
| Embedding | A list of numbers representing the meaning of a piece of text. Similar meanings tend to have nearby vectors. |
| Vector search | Finding stored text chunks whose embeddings are close to the question's embedding. |
| Metadata | Descriptive fields such as user ID, book ID, page number, chapter, and chunk index. |
| Retrieval | Selecting the document passages most likely to help answer a question. |
| Top-k | The number of candidate passages returned by search. It is a setting to tune, not a universal constant. |
| Context window | The amount of text the model can consider in a single request. |
| Grounded answer | An answer that is supported by the retrieved source passages. |
| Citation | A reference connecting an answer claim to its source page or passage. |
| Reranker | A second-stage model or method that reorders retrieved candidates by relevance to the question. |
| Hybrid search | Search that combines semantic similarity with keyword matching. |
| Evaluation | Measuring whether retrieval and answers work on reviewed examples. |

## Interview questions and sample answers

### 1. What is RAG?

RAG stands for Retrieval-Augmented Generation. It retrieves relevant information from an external knowledge source and gives that information to a language model as context for an answer. In my project, it retrieves passages from an uploaded book.

### 2. Why use RAG for this project?

Books can be large, and users need answers tied to their contents. RAG lets the application search the relevant parts of a book and provide citations, without sending the entire book with every question or retraining the model for each upload.

### 3. Does RAG train the language model?

No. In a typical RAG application, the model's weights are not changed. The document is processed and indexed, and relevant passages are supplied at answer time. Fine-tuning is a separate process that changes model behavior through training.

### 4. What happens when a book is uploaded?

The application validates the file, extracts text and page information, divides the text into chunks, creates embeddings for those chunks, and stores the vectors with metadata. The document becomes searchable after processing succeeds.

### 5. Why split a book into chunks?

Searching and passing a whole book to a model is inefficient and may exceed the model's context limit. Smaller chunks make it possible to retrieve just the sections related to a question.

### 6. How do you choose chunk size?

I would start with a reasonable size based on the document and embedding model, then evaluate retrieval on representative questions. Very small chunks can lose context; very large chunks can include irrelevant text and make retrieval less precise. There is no single best size for every book.

### 7. Why use chunk overlap?

An important sentence or idea can cross a chunk boundary. A small overlap repeats boundary text in the next chunk, which can help retrieval preserve that context. Too much overlap creates duplicate content and extra storage, so it should be measured.

### 8. What is an embedding?

An embedding is a numerical representation of text meaning. The application creates embeddings for both document chunks and user questions, then compares them to find passages with similar meaning.

### 9. What is a vector database?

A vector database stores embeddings and supports similarity search over them. For this project, it also needs to store metadata such as document ID and page number so results can be filtered and cited.

### 10. How does semantic search differ from keyword search?

Keyword search looks for matching words. Semantic search looks for similar meaning, even when the question uses different words from the book. Hybrid search can combine both, which may improve results for names, technical terms, and paraphrased questions.

### 11. What is top-k retrieval?

Top-k is the number of candidate chunks returned for a query. A small value may miss useful evidence; a large value may add irrelevant passages and consume more context. I would tune it with a reviewed question set.

### 12. What is a reranker, and when would you use one?

A reranker takes an initial set of search results and scores them again against the exact question. It can improve ordering when the first retrieval step finds plausible but uneven results. It adds processing time and cost, so I would add it if evaluation shows retrieval needs it.

### 13. How does the system reduce hallucinations?

It retrieves evidence, instructs the model to answer from that evidence, includes citations, and returns an “insufficient evidence” response when retrieval is weak. These steps reduce unsupported answers, but do not guarantee that every answer is correct, so the system also needs evaluation.

### 14. How do citations work?

Each stored chunk keeps its source document and page metadata. When a chunk is retrieved, that metadata travels with it. The answer can then display page references and source excerpts tied to the retrieved chunks.

### 15. How do you know an answer is supported by a citation?

The citation should point to a passage actually retrieved for that answer. To evaluate quality, I would check whether the cited page contains evidence for the associated claim, not merely whether a citation is present.

### 16. What if the PDF is scanned and has no selectable text?

The application needs OCR (Optical Character Recognition) to convert page images into text. OCR can misread characters or layout, so the product should detect extraction problems and communicate them rather than silently indexing empty or poor text.

### 17. How do you evaluate retrieval quality?

Create questions with known supporting pages, run them through the retrieval pipeline, and check whether the relevant passages appear near the top. Measures such as recall at k and mean reciprocal rank can help quantify retrieval, alongside manual review.

### 18. How do you evaluate generated answers?

Review whether the answer is correct, supported by the retrieved passages, complete enough for the question, and properly cited. A fixed test set makes it possible to compare changes to chunking, retrieval, prompts, or models.

### 19. What is the difference between RAG and fine-tuning?

RAG supplies reference information at query time and is useful when the knowledge source changes or needs citations. Fine-tuning changes model behavior using training examples and is more suited to consistent style, format, or task behavior. They address different needs and can sometimes be combined.

### 20. How do you protect one user's books from another user?

Associate every document and chunk with its owner, and enforce ownership filters in every read and search operation. The backend should verify authorization rather than trusting a document ID sent by the browser.

### 21. Can text inside an uploaded book control the AI assistant?

No. Retrieved book text is reference data, not an instruction source. The application should keep system instructions separate, treat document text as untrusted, and test against passages that try to manipulate the model.

### 22. What happens when a user deletes a book?

Deletion should remove the document and its associated chunks, embeddings, and related stored data according to the product's retention policy. The user interface should confirm the document is no longer searchable.

### 23. What would you monitor in production?

I would monitor upload and extraction failures, processing duration, retrieval results, answer latency, model errors, token usage or cost, and user feedback. Logs should avoid exposing book contents or personal information unnecessarily.

### 24. What are common RAG failure points?

Poor text extraction, bad chunk boundaries, weak retrieval, missing metadata, irrelevant context, and unclear prompts can all produce bad answers. Debugging should inspect the pipeline stage by stage, starting with the extracted text and retrieved passages.

### 25. How would you improve this project after the MVP?

I would build a reviewed evaluation set, measure retrieval and citation quality, then use the results to guide improvements such as hybrid search, better chunking, or reranking. I would also add chapter summaries and quizzes only after the core answers are reliable.

## A clear project explanation for interviews

> I am building a book question-answering application using RAG. It extracts text and page metadata from uploaded PDFs, splits the text into chunks, embeds and indexes those chunks, and retrieves relevant passages for each user question. A language model uses those passages to generate an answer with page citations. The system is designed to say when the book does not contain enough evidence, and I plan to evaluate retrieval and citation quality with questions that have known supporting pages.

## Suggested practical demo

1. Upload a short, text-based PDF.
2. Ask a question whose answer is clearly stated in the document.
3. Show the answer, citation, and source excerpt.
4. Ask a question the document does not answer and show the insufficient-evidence response.
5. Ask for a chapter summary and inspect its cited pages.
