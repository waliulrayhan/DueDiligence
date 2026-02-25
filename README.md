# DueDiligence Questionnaire Agent

An AI-powered full-stack application that automates the completion of institutional due diligence questionnaires (DDQs). Analysts upload reference documents — annual reports, prospectuses, financial statements — alongside a questionnaire PDF. The system parses the questionnaire into structured questions, retrieves relevant evidence from the indexed documents via semantic vector search (Pinecone + sentence-transformers), and generates cited answers using a large language model. Reviewers can confirm, reject, or rewrite each answer through a structured review workflow with full audit logging. An evaluation module scores AI responses against human ground truth using TF-cosine similarity and Jaccard keyword overlap.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (async), Python 3.11+, Uvicorn |
| Frontend | Next.js 16, React 19, TanStack Query, Zustand, Radix UI |
| Database | Neon Postgres (SQLAlchemy async + Alembic migrations) |
| Vector DB | Pinecone Serverless (cosine, 384-dim) |
| LLM | xAI Grok / Groq — OpenAI-compatible endpoint |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (384-dim, CPU-friendly) |

---

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # fill in your keys (see Environment Variables below)
alembic upgrade head
uvicorn app:app --reload --port 8000
```

API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
# Create local env file:
echo NEXT_PUBLIC_API_URL=http://localhost:8000/api > .env.local
npm run dev
```

UI will be available at `http://localhost:3000`.

### Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Description |
|---|---|
| `DATABASE_URL` | Neon Postgres pooled connection string (`postgresql+asyncpg://...`) |
| `DATABASE_URL_UNPOOLED` | Neon Postgres unpooled string for Alembic (`postgresql+psycopg2://...`) |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX_NAME` | Index name (e.g. `duediligence-chunks`) |
| `PINECONE_CLOUD` | Cloud provider (`aws` or `gcp`) |
| `PINECONE_REGION` | Region (e.g. `us-east-1`) |
| `GROQ_API_KEY` | API key for your LLM provider (Groq or xAI) |
| `GROQ_BASE_URL` | Base URL (e.g. `https://api.groq.com/openai/v1`) |
| `LLM_MODEL` | Model name (e.g. `llama-3.3-70b-versatile` or `grok-4-latest`) |
| `FRONTEND_URL` | Frontend origin for CORS (e.g. `http://localhost:3000`) |

---

## Demo Walkthrough

1. **Upload reference documents** — Upload the four MiniMax PDFs from `/data/` via the Documents section. Wait for each to reach status=`READY` (poll the async request).

2. **Upload the questionnaire** — Upload `ILPA_Due_Diligence_Questionnaire_v1.2.pdf` from `/data/`. This is also indexed so it can be parsed as a questionnaire.

3. **Create a project** — Click "New Project", enter a name, select the ILPA document as the questionnaire, set scope=`ALL_DOCS`, and submit.

4. **Wait for setup** — The system parses the questionnaire and seeds ~80–90 structured questions. Wait for the project to reach status=`READY`.

5. **Generate All Answers** — Click "Generate All Answers" and wait for the background task to complete. Each question is answered via RAG (Pinecone retrieval + LLM generation).

6. **Review answers** — Open each answer in the review drawer. Confirm, reject (with note), or manually edit. All changes are audit-logged.

7. **Run evaluation** — Navigate to the Evaluation tab. Provide human-written answers for 3–5 representative questions and submit. Review similarity scores, keyword overlap, and the overall score.

8. **Test OUTDATED trigger** — Upload a new document while the project is `READY`. Observe the project transitions to `OUTDATED`, prompting re-generation with the new document included.

---

## Documentation

| Document | Description |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System overview, component diagram, data flow, storage layout, async task model, status transitions |
| [docs/FUNCTIONAL_DESIGN.md](docs/FUNCTIONAL_DESIGN.md) | User flows, all API endpoints with request/response examples, edge cases |
| [docs/TESTING_EVALUATION.md](docs/TESTING_EVALUATION.md) | Dataset plan, QA checklist, evaluation metrics, scoring formula, sample output |

---

## Known Tradeoffs

- **Sync embeddings in async context:** `sentence-transformers` uses synchronous inference. Embedding calls are wrapped in `asyncio.to_thread()` for Pinecone health checks; bulk indexing runs in a `BackgroundTask` so the event loop is not blocked during request handling.
- **Vercel serverless constraints:** FastAPI `BackgroundTasks` require a long-lived process. On Vercel's serverless runtime, background tasks complete only if the function stays warm. For production workloads requiring reliable async processing, deploy the backend to Railway, Render, or a VPS.
- **Model download on first run:** `all-MiniLM-L6-v2` (~90MB) is downloaded once by `sentence-transformers` and cached. First startup is slower; subsequent restarts use the local cache.
- **Pinecone free tier:** Free tier supports one index with up to 100K vectors. The four MiniMax PDFs produce ~800–1200 vectors total — well within limits.
- **No authentication:** The API has no user authentication. All projects and documents are globally accessible. Add OAuth2/JWT before any production deployment.
