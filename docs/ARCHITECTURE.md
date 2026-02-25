# Architecture — DueDiligence Questionnaire Agent

## System Overview

DueDiligence is a full-stack AI system that automates the completion of institutional due diligence questionnaires (DDQs). Analysts upload reference documents (annual reports, prospectuses, financial statements) and a questionnaire PDF. The system parses the questionnaire, retrieves relevant context from the indexed documents via vector search, generates AI answers with citations, and lets reviewers confirm, reject, or manually edit each answer. A separate evaluation module scores AI answers against human ground truth.

**Stack:** FastAPI · Neon Postgres · Pinecone · Groq (LLaMA 3.3 70B) · sentence-transformers (all-MiniLM-L6-v2) · Next.js 15 · SQLAlchemy (async) · Alembic

---

## Component Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Browser (Next.js 15)                          │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  Upload Docs  │  │  Projects UI │  │ Review Drawer│  │ Eval Page │  │
│  └───────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  │
└──────────┼─────────────────┼─────────────────┼────────────────┼─────────┘
           │ HTTP/REST        │                 │                │
           ▼                  ▼                 ▼                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        FastAPI  (app.py)                                  │
│                                                                           │
│  /api/documents   /api/projects   /api/answers   /api/evaluation         │
│  /api/requests    /health                                                 │
│                                                                           │
│  ┌──────────────────┐  ┌─────────────────────────────┐                  │
│  │  BackgroundTasks  │  │   Sync request handlers     │                  │
│  │  (FastAPI built-  │  │   (projects, answers review,│                  │
│  │   in)             │  │    evaluation)              │                  │
│  └────────┬─────────┘  └─────────────────────────────┘                  │
└───────────┼──────────────────────────────────────────────────────────────┘
            │
   ┌────────┴────────────────────────────────────────┐
   │                                                  │
   ▼                                                  ▼
┌──────────────────┐   ┌──────────────────────────────────────────────────┐
│  Neon Postgres    │   │  Pinecone (Serverless)                           │
│                   │   │                                                  │
│  • documents      │   │  index: duediligence-chunks                      │
│  • projects       │   │  dimension: 384 (MiniLM-L6-v2)                  │
│  • questions      │   │  metric: cosine                                  │
│  • answers        │   │  metadata: document_id, chunk_id,               │
│  • citations      │   │            page_number, text (≤1000 chars),      │
│  • async_requests │   │            word_start, word_end                  │
│  • evaluation_    │   │                                                  │
│    results        │   └──────────────────────────────────────────────────┘
│  • answer_audit_  │
│    log            │   ┌──────────────────────────────────────────────────┐
└──────────────────┘   │  Groq API  (LLaMA 3.3 70B Versatile)             │
                        │  — generates answers from retrieved chunks       │
                        └──────────────────────────────────────────────────┘
```

---

## Data Flow

### Document Indexing Pipeline
```
1. User uploads PDF/DOCX  →  POST /api/documents
2. File saved to disk (uploads/)
3. AsyncRequest record created (PENDING)
4. FastAPI BackgroundTask fires: process_document_background()
5.   Document status: UPLOADING → INDEXING
6.   DocumentParser.parse_file()  →  list[{page_number, text}]
7.   DocumentParser.chunk_pages() →  list[{chunk_id, text, page_number, word_start, word_end}]
8.   SentenceTransformer.encode() →  384-dim float vectors
9.   Pinecone.upsert()           →  vectors stored with metadata
10.  Document status: INDEXING → READY
11.  All READY/ALL_DOCS projects → OUTDATED  (new document available)
12.  AsyncRequest → COMPLETED
```

### Questionnaire Setup Pipeline
```
1. User creates project with questionnaire doc + scope  →  POST /api/projects
2. AsyncRequest created (PENDING)
3. BackgroundTask fires: setup_project_background()
4.   Project status: CREATED → INDEXING
5.   QuestionnairePDFParser extracts section headings + question texts
6.   Bulk INSERT questions + seed PENDING answers in one DB round-trip
7.   Project status: INDEXING → READY
8.   AsyncRequest → COMPLETED
```

### Answer Generation Pipeline (RAG)
```
1. User triggers  →  POST /api/answers/generate-all
2. AsyncRequest created; background task fires: generate_all_answers_background()
3. For each PENDING answer (semaphore: 5 concurrent):
   a. Retrieve top-8 chunks from Pinecone matching question text
      (optionally filtered by document_ids if scope=SELECTED_DOCS)
   b. LLM prompt: question + chunks context → Groq API
   c. Parse JSON response: {answer, citations, confidence_score, can_answer}
   d. Save Answer (GENERATED), Citations, AnswerAuditLog entry
4. AsyncRequest → COMPLETED
```

### Review Flow
```
POST /api/answers/update
  status=CONFIRMED     → answer_text kept, reviewer_note optional
  status=REJECTED      → reviewer_note required
  status=MANUAL_UPDATED → manual_answer_text saved; answer_text = manual_answer_text
  AnswerAuditLog entry appended for every transition
```

### Evaluation Flow
```
POST /api/evaluation
  ground_truth: [{question_id, human_answer_text}, ...]
  → For each pair: cosine TF similarity + Jaccard keyword overlap
  → EvaluationResult upserted (delete-then-insert per question)
  → Returns aggregates + per-question scores

GET /api/evaluation/{project_id}
  → Returns saved EvaluationResult rows joined with current answer texts
```

---

## Storage Layout

### Neon Postgres Tables

| Table | Primary Responsibility |
|---|---|
| `documents` | File metadata, indexing status (`UPLOADING → INDEXING → READY / FAILED`), chunk count |
| `projects` | Project name, linked questionnaire doc, scope (`ALL_DOCS` / `SELECTED_DOCS`), status, selected document IDs (JSONB) |
| `questions` | Parsed questions: section name, text, order, number; FK → project |
| `answers` | AI-generated text, manual text, active `answer_text`, status, confidence score, reviewer note; FK → question + project |
| `citations` | Source evidence per answer: document_id, chunk_id, page number, excerpt text, relevance score; FK → answer + document |
| `async_requests` | Background task tracker: type, status (`PENDING → RUNNING → COMPLETED / FAILED`), project FK, error message, timestamps |
| `evaluation_results` | Per-question scores: similarity_score, keyword_overlap, overall_score, explanation, human_answer_text; FK → project + question + answer |
| `answer_audit_log` | Immutable audit trail: old/new status, changed_by, change_note, timestamp; FK → answer |

### Pinecone Vector Index

| Property | Value |
|---|---|
| Index name | `duediligence-chunks` (configurable via `PINECONE_INDEX_NAME`) |
| Dimension | 1024 |
| Metric | cosine |
| Embedding model | `multilingual-e5-large` via Pinecone Inference API (server-side, no local model) |
| Cloud / Region | Configurable via `PINECONE_CLOUD` / `PINECONE_REGION` |
| Vector ID | `chunk_id` (e.g. `{document_id}__p{page}_c{n}`) |
| Metadata fields | `document_id` (UUID string), `chunk_id`, `page_number` (int), `text` (first 1000 chars), `word_start`, `word_end` (optional word offsets) |

---

## Async Task Model

FastAPI's built-in `BackgroundTasks` is used to run I/O-heavy operations (PDF parsing, embedding, LLM calls) outside the HTTP request–response cycle. Each task:

1. Creates an `AsyncRequest` record (status=`PENDING`) before launching.
2. Opens its own `AsyncSessionLocal` DB session (never shares the request session).
3. Updates its own status to `RUNNING` on start, `COMPLETED`/`FAILED` on finish.
4. The HTTP response returns `202 Accepted` with the `request_id` immediately.
5. The frontend polls `GET /api/requests/{request_id}` until status is terminal.

### Three Async Task Types

| Task function | Triggered by | What it does |
|---|---|---|
| `process_document_background` | `POST /api/documents` | Parse → chunk → embed → Pinecone upsert; marks ALL_DOCS projects OUTDATED |
| `setup_project_background` | `POST /api/projects` (create/update) | Parse questionnaire PDF → bulk-insert questions + seed answers |
| `generate_all_answers_background` | `POST /api/answers/generate-all` | RAG loop over all PENDING answers (semaphore=5); saves answers + citations |

### Frontend Polling Pattern
```
POST /api/documents        → { request_id }
  loop:
    GET /api/requests/{id} → { status: PENDING | RUNNING | COMPLETED | FAILED }
  until status ∈ { COMPLETED, FAILED }
  then refresh document/project list
```

---

## Status Transitions

### Project Status
```
CREATED ──(setup_project_background starts)──► INDEXING
INDEXING ──(questions parsed OK)──────────────► READY
INDEXING ──(error)────────────────────────────► ERROR
READY ──(new document indexed w/ scope=ALL_DOCS)► OUTDATED
OUTDATED ──(update project / re-parse)─────────► INDEXING → READY
```

### Answer Status
```
PENDING ──(generate-all / generate-single runs)──► GENERATED
GENERATED ──(reviewer confirms)─────────────────► CONFIRMED
GENERATED ──(reviewer rejects)──────────────────► REJECTED
GENERATED ──(reviewer writes own text)──────────► MANUAL_UPDATED
REJECTED  ──(reviewer writes own text)──────────► MANUAL_UPDATED
PENDING   ──(LLM says no data available)─────────► MISSING_DATA
```

### AsyncRequest Status
```
PENDING ──(task starts)──► RUNNING ──(success)──► COMPLETED
                        │
                        └──(exception)──────────► FAILED
```

### Document Status
```
UPLOADING ──(indexing starts)──► INDEXING ──(success)──► READY
                                          └──(error)───► FAILED
```
