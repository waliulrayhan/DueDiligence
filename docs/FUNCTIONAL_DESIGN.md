# Functional Design — DueDiligence Questionnaire Agent

---

## User Flows

### Flow 1: Upload Reference Document

1. User navigates to the Documents section of the UI.
2. User selects a PDF or DOCX file (max supported types: `.pdf`, `.docx`).
3. Frontend calls `POST /api/documents` with the file as multipart form data.
4. API validates the file extension. If unsupported → 400 error shown in UI.
5. File is saved to `uploads/` with a UUID prefix to avoid collisions.
6. A `Document` record is created (status=`UPLOADING`) and an `AsyncRequest` (status=`PENDING`) is created in the DB.
7. API returns `202 Accepted` with `{ request_id }`.
8. Frontend polls `GET /api/requests/{request_id}` every 2 seconds.
9. Background task: parse → chunk → embed → upsert to Pinecone.
10. On success: Document status → `READY`. All `ALL_DOCS` projects in `READY` state → `OUTDATED`.
11. `AsyncRequest` → `COMPLETED`. Frontend stops polling and refreshes document list.

---

### Flow 2: Create Project

1. User clicks "New Project".
2. User enters name, optional description, selects a questionnaire document, and chooses scope (`ALL_DOCS` or `SELECTED_DOCS`).
3. If `SELECTED_DOCS`: user selects which documents to include.
4. Frontend calls `POST /api/projects`.
5. Validation: questionnaire doc must exist and have status=`READY`. → 404/422 otherwise.
6. `Project` record created (status=`CREATED`), `AsyncRequest` created.
7. Background task `setup_project_background` starts:
   - Parses questionnaire PDF using `QuestionnairePDFParser` (regex section/question extraction).
   - Bulk-inserts `Question` rows and seeds `Answer` stubs (status=`PENDING`).
   - Project → `READY`.
8. Frontend polls `AsyncRequest` → shows "Processing…" banner.
9. On `COMPLETED`: frontend navigates to project detail page.

---

### Flow 3: Generate All Answers

1. User opens project (status=`READY` or `OUTDATED`).
2. User clicks "Generate All Answers".
3. Frontend calls `POST /api/answers/generate-all` with `{ project_id }`.
4. Validation: project must exist; questionnaire doc must be `READY`; at least one `PENDING` answer must exist.
5. `AsyncRequest` created; background task `generate_all_answers_background` fires.
6. For each `PENDING` answer (up to 5 concurrent via semaphore):
   a. Retrieve top-8 matching chunks from Pinecone (filtered by scope if `SELECTED_DOCS`).
   b. Build RAG prompt with question + retrieved context.
   c. Call Groq API (LLaMA 3.3 70B). Parse JSON response.
   d. Save `Answer` (status=`GENERATED`), `Citation` rows, `AnswerAuditLog` entry.
7. `AsyncRequest` → `COMPLETED`. Frontend refreshes answers list.

---

### Flow 4: Review Answers

1. User browses the answer list on the project page.
2. Each answer shows status badge, confidence score, and AI-generated text.
3. User opens the review drawer for a specific answer.
4. User can:
   - **Confirm**: calls `POST /api/answers/update` with `{ status: "CONFIRMED" }`.
   - **Reject**: calls `POST /api/answers/update` with `{ status: "REJECTED", reviewer_note: "..." }` (note required).
   - **Edit & Save**: sends `{ status: "MANUAL_UPDATED", manual_answer_text: "..." }`.
5. An `AnswerAuditLog` entry is appended for every transition.
6. The active `answer_text` is updated: `CONFIRMED` keeps AI text; `MANUAL_UPDATED` uses the manual text.

---

### Flow 5: Run Evaluation

1. User provides ground truth answers (human-written) for a subset of questions.
2. User navigates to the Evaluation page and submits ground truth pairs.
3. Frontend calls `POST /api/evaluation` with `{ project_id, ground_truth: [{question_id, human_answer_text}] }`.
4. For each pair, the API scores the AI answer vs human answer:
   - TF-vector cosine similarity
   - Jaccard keyword overlap (stopwords removed)
   - Weighted average → `overall_score`
5. `EvaluationResult` rows are upserted (delete-then-insert per question).
6. API returns aggregates + per-question results.
7. User can re-run evaluation with updated human answers at any time.

---

## API Endpoints

### Documents

#### `POST /api/documents` — Upload Document
**Request:** `multipart/form-data`, field `file` (PDF or DOCX)

**Response (202):**
```json
{
  "request_id": "c3d4e5f6-...",
  "status": "PENDING",
  "error_message": null,
  "completed_at": null
}
```

**Errors:** `400` unsupported file type

---

#### `GET /api/documents` — List Documents
**Response (200):**
```json
[
  {
    "id": "a1b2c3d4-...",
    "original_name": "MiniMax_Prospectus.pdf",
    "status": "READY",
    "chunk_count": 312,
    "created_at": "2026-02-25T10:00:00Z"
  }
]
```

---

### Projects

#### `POST /api/projects` — Create Project
**Request:**
```json
{
  "name": "MiniMax DDQ Q1 2026",
  "description": "ILPA questionnaire for MiniMax IPO",
  "questionnaire_doc_id": "uuid-of-ilpa-doc",
  "scope": "ALL_DOCS",
  "document_ids": []
}
```

**Response (202):**
```json
{
  "request_id": "f1e2d3c4-...",
  "status": "PENDING",
  "error_message": null,
  "completed_at": null
}
```

**Errors:** `404` questionnaire doc not found; `422` doc not yet READY

---

#### `GET /api/projects` — List Projects
**Response (200):**
```json
[
  {
    "id": "proj-uuid-...",
    "name": "MiniMax DDQ Q1 2026",
    "status": "READY",
    "scope": "ALL_DOCS",
    "question_count": 87,
    "created_at": "2026-02-25T10:05:00Z"
  }
]
```

---

#### `GET /api/projects/{project_id}` — Get Project Detail
**Response (200):** Full project object with questions array.

---

### Answers

#### `POST /api/answers/generate-all` — Bulk Generate
**Request:**
```json
{ "project_id": "proj-uuid-..." }
```

**Response (202):**
```json
{
  "request_id": "g5h6i7j8-...",
  "status": "PENDING",
  "error_message": null,
  "completed_at": null
}
```

**Errors:** `404` project not found; `422` no PENDING answers; `422` questionnaire doc not READY

---

#### `POST /api/answers/generate-single` — Single Answer
**Request:**
```json
{
  "project_id": "proj-uuid-...",
  "question_id": "q-uuid-..."
}
```

**Response (200):** Full `AnswerResponse` with citations and confidence score.

---

#### `POST /api/answers/update` — Review Answer
**Request:**
```json
{
  "answer_id": "ans-uuid-...",
  "status": "CONFIRMED",
  "reviewer_note": null,
  "manual_answer_text": null
}
```

**Response (200):** Updated `AnswerResponse`.

**Errors:** `422` REJECTED requires `reviewer_note`; `422` MANUAL_UPDATED requires `manual_answer_text`

---

#### `GET /api/answers/{project_id}` — All Answers for Project
**Response (200):** Array of `AnswerResponse` objects ordered by `question_order`.

---

### Evaluation

#### `POST /api/evaluation` — Run Evaluation
**Request:**
```json
{
  "project_id": "proj-uuid-...",
  "ground_truth": [
    {
      "question_id": "q-uuid-1",
      "human_answer_text": "The fund targets institutional LPs with a minimum commitment of $5M."
    },
    {
      "question_id": "q-uuid-2",
      "human_answer_text": "The management team has 15+ years of combined experience in private equity."
    }
  ]
}
```

**Response (200):**
```json
{
  "aggregates": {
    "avg_score": 0.74,
    "count_excellent": 1,
    "count_good": 1,
    "count_poor": 0,
    "total": 2
  },
  "results": [
    {
      "question_id": "q-uuid-1",
      "question_text": "What is the minimum LP commitment?",
      "ai_answer_text": "The fund requires a minimum commitment of $5 million from institutional investors.",
      "human_answer_text": "The fund targets institutional LPs with a minimum commitment of $5M.",
      "similarity_score": 0.8821,
      "keyword_overlap": 0.5714,
      "overall_score": 0.8268,
      "explanation": "Strong semantic and keyword alignment."
    }
  ]
}
```

---

#### `GET /api/evaluation/{project_id}` — Get Evaluation Report
**Response (200):** Same shape as POST response, loaded from saved `EvaluationResult` rows.

---

### Requests

#### `GET /api/requests/{request_id}` — Poll Async Task
**Response (200):**
```json
{
  "request_id": "c3d4e5f6-...",
  "status": "COMPLETED",
  "error_message": null,
  "completed_at": "2026-02-25T10:02:15Z"
}
```

Status values: `PENDING` · `RUNNING` · `COMPLETED` · `FAILED`

---

## Edge Cases

### No Documents Indexed
- `POST /api/answers/generate-all` proceeds but each LLM call receives empty context.
- The LLM returns `{ "can_answer": false }` for every question.
- All answers are saved with status=`MISSING_DATA` and a note explaining no relevant chunks were found.

### API Key Invalid / Groq Unreachable
- `generate_all_answers_background` catches the exception per-question.
- Failed questions are skipped; successfully answered questions are saved.
- `AsyncRequest` is marked `FAILED` with `error_message` containing the exception string.
- Frontend shows the error message in the status banner.

### Parse Failure (Questionnaire)
- If `QuestionnairePDFParser` raises an exception (corrupted PDF, password-protected, etc.):
- `setup_project_background` catches it, sets Project → `ERROR`, AsyncRequest → `FAILED`.
- The project page shows a persistent error banner with the message.
- The user must delete the project and retry with a valid questionnaire file.

### Empty Questionnaire
- If the parser extracts 0 questions (unrecognised format):
- `setup_project_background` completes successfully and sets Project → `READY`.
- Project detail shows 0 questions and a warning.
- "Generate All" returns 422 ("no PENDING answers").

### OUTDATED Transition
Exact trigger: a new document is successfully indexed (status reaches `READY`) AND at least one project exists with:
- `scope = ALL_DOCS`
- `status = READY`

All matching projects are atomically set to `OUTDATED` within the same DB transaction that completes the document indexing.

The OUTDATED state is purely informational — existing answers remain valid. It prompts the user to re-generate answers so the new document's content is included.

To resolve `OUTDATED`: call `PUT /api/projects/{id}` (re-triggers `setup_project_background` which re-parses the questionnaire and re-seeds PENDING answers), then generate answers again.
