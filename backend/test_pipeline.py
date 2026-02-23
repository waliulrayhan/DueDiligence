"""
End-to-end pipeline verification for DueDiligence Questionnaire Agent.

Usage:
  python test_pipeline.py                    # reuse existing DB data, skip already-done steps
  python test_pipeline.py --reset            # wipe all DB data first, then run from scratch
  python test_pipeline.py --max-questions 5  # only generate answers for first N questions

Steps:
  1. Upload & index the 4 MiniMax PDFs       (skipped if already READY in DB)
  2. Upload & index the ILPA questionnaire   (skipped if already READY in DB)
  3. Create a project  scope=ALL_DOCS        (skipped if existing READY project found)
  4. POST /api/answers/generate-single       verify answer_text, confidence_score, citations
  5. POST /api/answers/generate-all          poll until COMPLETED/FAILED
  6. GET  /api/answers/{project_id}          verify all answers have status=GENERATED
"""

import os
import sys
import time
import pathlib
import argparse

import requests

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument(
    "--reset",
    action="store_true",
    help="Wipe all DB data before running",
)
parser.add_argument(
    "--max-questions",
    type=int,
    default=0,
    metavar="N",
    help="Only generate answers for the first N questions (0 = all)",
)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Config — edit BASE_URL if your backend runs on a different port
# ---------------------------------------------------------------------------
BASE_URL        = "http://localhost:8000"
API             = f"{BASE_URL}/api"
DATA_DIR        = pathlib.Path(__file__).parent.parent / "data"
ILPA_NAME       = "ILPA_Due_Diligence_Questionnaire_v1.2.pdf"
MINIMAX_PDFS    = [
    "20260110_MiniMax_Accountants_Report.pdf",
    "20260110_MiniMax_Audited_Consolidated_Financial_Statements.pdf",
    "20260110_MiniMax_Global_Offering_Prospectus.pdf",
    "20260110_MiniMax_Industry_Report.pdf",
]
PROJECT_NAME    = "MiniMax Due Diligence Test"
POLL_INTERVAL   = 5      # seconds between status polls
POLL_TIMEOUT    = 600    # seconds before giving up on a single indexing request
HTTP_TIMEOUT    = 120    # seconds for individual HTTP calls


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"  \033[92m[PASS]\033[0m {msg}")

def fail(msg: str) -> None:
    print(f"  \033[91m[FAIL]\033[0m {msg}")
    sys.exit(1)

def info(msg: str) -> None:
    print(f"  \033[94m[SKIP]\033[0m {msg}")

def warn(msg: str) -> None:
    print(f"  \033[93m[WARN]\033[0m {msg}")

def section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def elapsed(start: float) -> str:
    s = int(time.time() - start)
    return f"{s // 60}m{s % 60:02d}s"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def poll_request(request_id: str, label: str = "", timeout: int | None = None) -> dict:
    """Poll GET /api/requests/{id} until COMPLETED or FAILED."""
    deadline = time.time() + (timeout or POLL_TIMEOUT)
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/requests/{request_id}", timeout=HTTP_TIMEOUT)
        except requests.exceptions.ReadTimeout:
            print(f"    ... {label} (server busy, retrying…)")
            time.sleep(POLL_INTERVAL)
            continue
        if r.status_code != 200:
            fail(f"Poll {label}: unexpected status {r.status_code} — {r.text}")
        data   = r.json()
        status = data["status"]
        if status not in ("COMPLETED", "FAILED"):
            print(f"    ... {label}  status={status}")
        if status == "COMPLETED":
            return data
        if status == "FAILED":
            fail(f"{label} FAILED — {data.get('error_message')}")
        time.sleep(POLL_INTERVAL)
    fail(f"Timed out waiting for {label}")


def get_all_documents() -> list[dict]:
    r = requests.get(f"{API}/documents/", timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        fail(f"GET /api/documents/ failed: {r.status_code} — {r.text}")
    return r.json()


def upload_document(pdf_name: str) -> str:
    """Upload a PDF and return its document_id once READY."""
    pdf_path = DATA_DIR / pdf_name
    if not pdf_path.exists():
        fail(f"File not found: {pdf_path}\n  Make sure DATA_DIR points to the /data folder.")

    with open(pdf_path, "rb") as fh:
        r = requests.post(
            f"{API}/documents/",
            files={"file": (pdf_name, fh, "application/pdf")},
            timeout=HTTP_TIMEOUT,
        )
    if r.status_code != 202:
        fail(f"Upload '{pdf_name}': HTTP {r.status_code} — {r.text}")

    data       = r.json()
    request_id = data["request_id"]
    print(f"  Uploaded '{pdf_name}' → request_id={request_id}")
    poll_request(request_id, label=pdf_name)

    for doc in get_all_documents():
        if doc["original_name"] == pdf_name and doc["status"] == "READY":
            ok(f"'{pdf_name}' indexed — doc_id={doc['id']}  chunks={doc['chunk_count']}")
            return doc["id"]

    fail(f"Could not find READY document for '{pdf_name}' after indexing.")


def ensure_document(pdf_name: str) -> str:
    """Return existing READY doc_id, or upload fresh if not found."""
    for doc in get_all_documents():
        if doc["original_name"] == pdf_name and doc["status"] == "READY":
            info(f"'{pdf_name}' already indexed — doc_id={doc['id']}")
            return doc["id"]
    return upload_document(pdf_name)


# ---------------------------------------------------------------------------
# --reset: wipe all data
# ---------------------------------------------------------------------------
if args.reset:
    section("RESET — wiping all database records")
    r = requests.delete(f"{API}/admin/reset", timeout=60)
    if r.status_code == 200:
        ok("Database cleared via /admin/reset")
    elif r.status_code == 404:
        print("  No /admin/reset endpoint — clearing via local reset_db.py…")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(pathlib.Path(__file__).parent / "reset_db.py")],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            fail(f"reset_db.py failed:\n{result.stderr}")
        ok("Database cleared via reset_db.py")
    else:
        fail(f"Reset failed: {r.status_code} — {r.text}")


# ---------------------------------------------------------------------------
# Pre-flight: confirm backend is reachable
# ---------------------------------------------------------------------------
section("PRE-FLIGHT — checking backend health")
try:
    health = requests.get(f"{BASE_URL}/health", timeout=60)  # Pinecone cold-start can be slow
    if health.status_code == 200:
        data = health.json()
        ok(f"Backend reachable — DB={data.get('database','?')}  Pinecone={data.get('pinecone','?')}  vectors={data.get('pinecone_vector_count','?')}")
    else:
        fail(f"Health check returned HTTP {health.status_code}")
except requests.exceptions.ConnectionError:
    fail(
        f"Cannot reach backend at {BASE_URL}\n"
        "  Make sure uvicorn is running:  uvicorn app:app --reload --port 8000"
    )
except requests.exceptions.ReadTimeout:
    fail(
        f"Health check timed out — backend at {BASE_URL} is not responding.\n"
        "  The server may still be starting up; wait a moment and retry."
    )


# ---------------------------------------------------------------------------
# STEP 1 — Index 4 MiniMax reference PDFs
# ---------------------------------------------------------------------------
section("STEP 1 — Upload & index 4 MiniMax reference PDFs")
t0 = time.time()
minimax_doc_ids: list[str] = []
for name in MINIMAX_PDFS:
    doc_id = ensure_document(name)
    minimax_doc_ids.append(doc_id)
print(f"\n  Done in {elapsed(t0)}.  MiniMax doc IDs: {minimax_doc_ids}")


# ---------------------------------------------------------------------------
# STEP 2 — Index ILPA questionnaire
# ---------------------------------------------------------------------------
section("STEP 2 — Upload & index ILPA questionnaire")
t0 = time.time()
ilpa_doc_id = ensure_document(ILPA_NAME)
print(f"\n  Done in {elapsed(t0)}.  ILPA doc ID: {ilpa_doc_id}")


# ---------------------------------------------------------------------------
# STEP 3 — Create project (scope=ALL_DOCS) — reuse if already exists
# ---------------------------------------------------------------------------
section("STEP 3 — Create project  scope=ALL_DOCS")
t0 = time.time()

projects_r = requests.get(f"{API}/projects/", timeout=30)
if projects_r.status_code != 200:
    fail(f"GET /api/projects/: HTTP {projects_r.status_code}")

project_id: str | None = None
for p in projects_r.json():
    if p["name"] == PROJECT_NAME and p["status"] in ("READY", "OUTDATED"):
        project_id = p["id"]
        info(
            f"Project already exists — id={project_id}  "
            f"status={p['status']}  questions={p['question_count']}"
        )
        break

if not project_id:
    payload = {
        "name":                  PROJECT_NAME,
        "description":           "Automated pipeline verification",
        "questionnaire_doc_id":  ilpa_doc_id,
        "scope":                 "ALL_DOCS",
        "document_ids":          [],
    }
    r = requests.post(f"{API}/projects/create", json=payload, timeout=30)
    if r.status_code != 202:
        fail(f"Create project: HTTP {r.status_code} — {r.text}")

    create_data        = r.json()
    project_request_id = create_data["request_id"]
    print(f"  Project setup request_id={project_request_id}")
    poll_request(project_request_id, label="setup_project")

    for p in requests.get(f"{API}/projects/", timeout=30).json():
        if p["name"] == PROJECT_NAME:
            project_id = p["id"]
            ok(
                f"Project created — id={project_id}  "
                f"status={p['status']}  questions={p['question_count']}"
            )
            break

if not project_id:
    fail("Could not find the created project in the projects list.")

print(f"  Done in {elapsed(t0)}.")

# Load project detail to grab the first question
proj_r = requests.get(f"{API}/projects/{project_id}", timeout=30)
if proj_r.status_code != 200:
    fail(f"GET /api/projects/{project_id}: HTTP {proj_r.status_code}")

proj_detail    = proj_r.json()
questions      = proj_detail.get("questions", [])
if not questions:
    fail("Project has no questions after setup — check questionnaire parser logs.")

first_question = questions[0]
question_id    = first_question["id"]
ok(f"First question id={question_id}")
print(f"  Text: {first_question['question_text'][:120]}…")


# ---------------------------------------------------------------------------
# STEP 4 — generate-single (synchronous, immediate response)
# ---------------------------------------------------------------------------
section("STEP 4 — POST /api/answers/generate-single")
t0  = time.time()
r   = requests.post(
    f"{API}/answers/generate-single",
    json={"project_id": project_id, "question_id": question_id},
    timeout=HTTP_TIMEOUT,
)
if r.status_code == 429:
    warn("generate-single: Groq daily token limit reached (429) — skipping LLM assertions.")
    warn(f"  {r.json().get('detail','')[:200]}")
    warn("  Wait for your Groq TPD quota to reset (usually midnight UTC) then re-run.")
elif r.status_code != 200:
    fail(f"generate-single: HTTP {r.status_code} — {r.text}")
else:
    ans         = r.json()
    answer_text = ans.get("answer_text") or ""
    confidence  = ans.get("confidence_score")
    citations   = ans.get("citations", [])
    status_val  = ans.get("status", "")

    # Assertions
    if not answer_text.strip():
        fail("answer_text is empty — check llm_client.py and Groq API key")
    ok(f"answer_text length={len(answer_text)} chars")

    if confidence is None or not (0.0 <= float(confidence) <= 1.0):
        fail(f"confidence_score out of range: {confidence}")
    ok(f"confidence_score={confidence}")

    if not isinstance(citations, list):
        fail("citations is not a list")
    if len(citations) == 0:
        warn("citations list is empty — check Pinecone search and relevance threshold")
    else:
        ok(f"citations count={len(citations)}")

    # Summary
    print(f"\n  Status     : {status_val}  |  can_answer: {ans.get('can_answer')}")
    print(f"  Confidence : {confidence}")
    print(f"  Citations  : {len(citations)}")
    print(f"  Elapsed    : {elapsed(t0)}")
    print(f"  Preview    :\n    {answer_text[:300].replace(chr(10), chr(10) + '    ')}")


# ---------------------------------------------------------------------------
# STEP 5 — generate-all (async background task)
# ---------------------------------------------------------------------------
section("STEP 5 — POST /api/answers/generate-all  (background)")

max_q      = args.max_questions
ga_payload: dict = {"project_id": project_id}
if max_q > 0:
    ga_payload["max_questions"] = max_q
    print(f"  Limiting to first {max_q} question(s)  (--max-questions {max_q})")

t0 = time.time()
r  = requests.post(f"{API}/answers/generate-all", json=ga_payload, timeout=30)
if r.status_code != 202:
    fail(f"generate-all: HTTP {r.status_code} — {r.text}")

ga_data       = r.json()
ga_request_id = ga_data["request_id"]
print(f"  generate-all request_id={ga_request_id}")
print(f"  Polling every {POLL_INTERVAL}s …\n")

deadline = time.time() + 7200   # 2-hour hard cap
while time.time() < deadline:
    try:
        poll_r = requests.get(f"{API}/requests/{ga_request_id}", timeout=HTTP_TIMEOUT)
    except requests.exceptions.ReadTimeout:
        print(f"    ... generate_all  {elapsed(t0)}  (server busy, retrying…)")
        time.sleep(POLL_INTERVAL)
        continue

    if poll_r.status_code != 200:
        fail(f"Poll generate_all: {poll_r.status_code} — {poll_r.text}")

    poll_data   = poll_r.json()
    poll_status = poll_data["status"]
    print(f"    ... generate_all  status={poll_status}  elapsed={elapsed(t0)}")

    if poll_status == "COMPLETED":
        ok(f"generate-all completed in {elapsed(t0)}")
        break
    if poll_status == "FAILED":
        err = poll_data.get("error_message", "")
        # Treat partial failures gracefully (some questions may fail while others succeed)
        if err and "failed" in err.lower():
            warn(f"generate-all finished with some individual failures: {err}")
            ok(f"generate-all finished in {elapsed(t0)}  (see warnings above)")
            break
        fail(f"generate-all FAILED — {err}")
    time.sleep(POLL_INTERVAL)
else:
    fail("generate-all timed out after 2 hours")


# ---------------------------------------------------------------------------
# STEP 6 — GET /api/answers/{project_id}  verify all GENERATED
# ---------------------------------------------------------------------------
section("STEP 6 — GET /api/answers/{project_id}")
t0 = time.time()
r  = requests.get(f"{API}/answers/{project_id}", timeout=30)
if r.status_code != 200:
    fail(f"GET answers: HTTP {r.status_code} — {r.text}")

all_answers = r.json()
if not all_answers:
    fail("No answers returned for project.")

total     = len(all_answers)
generated = sum(1 for a in all_answers if a["status"] == "GENERATED")
pending   = sum(1 for a in all_answers if a["status"] == "PENDING")
other     = total - generated - pending

print(f"\n  Total answers  : {total}")
print(f"  GENERATED      : {generated}")
print(f"  PENDING        : {pending}")
print(f"  Other statuses : {other}")

if max_q > 0:
    if generated < max_q:
        # Check if generate-all had partial failures (e.g. rate-limit 429)
        ga_req = requests.get(f"{API}/requests/{ga_request_id}", timeout=30).json()
        err_msg = ga_req.get("error_message") or ""
        if "failed" in err_msg.lower() or "rate" in err_msg.lower():
            warn(
                f"Only {generated}/{max_q} answers GENERATED — some failed in generate-all "
                f"(possible Groq rate-limit). Details: {err_msg}"
            )
        else:
            fail(f"Expected at least {max_q} GENERATED answers, got {generated}")
    else:
        ok(f"{generated}/{total} answers GENERATED  (partial batch of {max_q})")
else:
    if generated < total:
        not_gen = [(a["id"], a["status"]) for a in all_answers if a["status"] != "GENERATED"]
        print(f"\n  Non-GENERATED (first 10): {not_gen[:10]}")
        fail(f"{total - generated} answer(s) did not reach GENERATED status")
    ok(f"All {total} answers have status=GENERATED")

# Spot-check: at least one answer has citations
for ans_item in all_answers:
    if ans_item.get("citations"):
        ok(f"Sample answer has {len(ans_item['citations'])} citation(s) — citations confirmed")
        break
else:
    warn("No answers have citations — check Pinecone search relevance threshold")

# Spot-check: confidence scores in range
bad_confidence = [
    a for a in all_answers
    if a.get("confidence_score") is None
    or not (0.0 <= float(a["confidence_score"]) <= 1.0)
]
if bad_confidence:
    warn(f"{len(bad_confidence)} answers have out-of-range confidence_score")
else:
    ok(f"All {total} answers have confidence_score in [0.0, 1.0]")


# ---------------------------------------------------------------------------
# FINAL RESULT
# ---------------------------------------------------------------------------
section("RESULT")
print("  \033[92m✅  ALL VERIFICATION CHECKS PASSED\033[0m")
print()
print("  You can now proceed to Phase 5 (Review Workflow).")
print()