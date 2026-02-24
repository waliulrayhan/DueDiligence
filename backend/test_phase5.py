"""
Phase 5 verification — Review Workflow & Manual Override

Usage:
  python test_phase5.py

Requires:
  - Backend running at http://localhost:8000
  - At least 1 answer with status=GENERATED in the DB
    (run test_pipeline.py --max-questions 3 first if needed)

Tests:
  1. CONFIRMED  — POST /update with status=CONFIRMED returns 200
  2. CONFIRMED → GENERATED (undo) — returns 200
  3. REJECTED without note — returns 400
  4. REJECTED with note   — returns 200
  5. MANUAL_UPDATED without text — returns 400
  6. MANUAL_UPDATED with text    — returns 200, ai_answer_text preserved
  7. MISSING_DATA — returns 200
"""

import sys
import requests

BASE_URL     = "http://localhost:8000"
API          = f"{BASE_URL}/api"
HTTP_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"  \033[92m[PASS]\033[0m {msg}")

def fail(msg: str) -> None:
    print(f"  \033[91m[FAIL]\033[0m {msg}")
    sys.exit(1)

def section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def update_answer(answer_id: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{API}/answers/update",
        json={"answer_id": answer_id, **payload},
        timeout=HTTP_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
section("PRE-FLIGHT — find a GENERATED answer to test with")

try:
    health = requests.get(f"{BASE_URL}/health", timeout=10)
    if health.status_code != 200:
        fail(f"Backend not healthy: {health.status_code}")
except requests.exceptions.ConnectionError:
    fail("Cannot reach backend — run: uvicorn app:app --reload --port 8000")

# Get all projects
projects = requests.get(f"{API}/projects/", timeout=HTTP_TIMEOUT).json()
if not projects:
    fail("No projects found. Run test_pipeline.py --max-questions 3 first.")

project_id = projects[0]["id"]
print(f"  Using project_id={project_id}")

# Get answers for the project
answers_r = requests.get(f"{API}/answers/{project_id}", timeout=HTTP_TIMEOUT)
if answers_r.status_code != 200:
    fail(f"GET /answers/{project_id} failed: {answers_r.status_code}")

all_answers = answers_r.json()
generated   = [a for a in all_answers if a["status"] == "GENERATED"]

if not generated:
    fail(
        "No GENERATED answers found.\n"
        "  Run: python test_pipeline.py --max-questions 3"
    )

# Use the first GENERATED answer for all tests
answer      = generated[0]
answer_id   = answer["id"]
ai_answer   = answer.get("ai_answer_text") or answer.get("answer_text") or ""
print(f"  Using answer_id={answer_id}")
print(f"  ai_answer_text preview: {ai_answer[:80]}…")
ok("Found GENERATED answer — ready to test")


# ---------------------------------------------------------------------------
# TEST 1 — CONFIRMED
# ---------------------------------------------------------------------------
section("TEST 1 — CONFIRMED (no extra fields needed)")

r = update_answer(answer_id, {"status": "CONFIRMED"})
if r.status_code != 200:
    fail(f"Expected 200, got {r.status_code} — {r.text}")
data = r.json()
if data["status"] != "CONFIRMED":
    fail(f"status should be CONFIRMED, got {data['status']}")
ok("CONFIRMED — status=CONFIRMED returned correctly")


# ---------------------------------------------------------------------------
# TEST 2 — CONFIRMED → GENERATED (undo)
# ---------------------------------------------------------------------------
section("TEST 2 — CONFIRMED → GENERATED (reviewer can undo)")

r = update_answer(answer_id, {"status": "GENERATED"})
if r.status_code != 200:
    fail(f"Expected 200, got {r.status_code} — {r.text}")
if r.json()["status"] != "GENERATED":
    fail(f"status should be GENERATED, got {r.json()['status']}")
ok("CONFIRMED → GENERATED undo works correctly")


# ---------------------------------------------------------------------------
# TEST 3 — REJECTED without reviewer_note → must return 400
# ---------------------------------------------------------------------------
section("TEST 3 — REJECTED without reviewer_note (expect 400)")

r = update_answer(answer_id, {"status": "REJECTED"})
if r.status_code != 400:
    fail(f"Expected 400, got {r.status_code} — validation missing in answers.py")
ok(f"Correctly rejected with 400 — {r.json()}")


# ---------------------------------------------------------------------------
# TEST 4 — REJECTED with reviewer_note → must return 200
# ---------------------------------------------------------------------------
section("TEST 4 — REJECTED with reviewer_note (expect 200)")

r = update_answer(answer_id, {
    "status":        "REJECTED",
    "reviewer_note": "Answer is incomplete and missing key financial figures.",
})
if r.status_code != 200:
    fail(f"Expected 200, got {r.status_code} — {r.text}")
data = r.json()
if data["status"] != "REJECTED":
    fail(f"status should be REJECTED, got {data['status']}")
ok("REJECTED with note — status=REJECTED saved correctly")

# Reset back to GENERATED for next tests
update_answer(answer_id, {"status": "GENERATED"})


# ---------------------------------------------------------------------------
# TEST 5 — MANUAL_UPDATED without manual_answer_text → must return 400
# ---------------------------------------------------------------------------
section("TEST 5 — MANUAL_UPDATED without manual_answer_text (expect 400)")

r = update_answer(answer_id, {"status": "MANUAL_UPDATED"})
if r.status_code != 400:
    fail(f"Expected 400, got {r.status_code} — validation missing in answers.py")
ok(f"Correctly rejected with 400 — {r.json()}")


# ---------------------------------------------------------------------------
# TEST 6 — MANUAL_UPDATED with text → ai_answer_text must be preserved
# ---------------------------------------------------------------------------
section("TEST 6 — MANUAL_UPDATED — ai_answer_text must NOT be overwritten")

human_answer = "MiniMax is an AI company founded in 2021, headquartered in Shanghai."
r = update_answer(answer_id, {
    "status":             "MANUAL_UPDATED",
    "manual_answer_text": human_answer,
    "reviewer_note":      "Provided a more accurate and concise answer.",
})
if r.status_code != 200:
    fail(f"Expected 200, got {r.status_code} — {r.text}")

data = r.json()

if data["status"] != "MANUAL_UPDATED":
    fail(f"status should be MANUAL_UPDATED, got {data['status']}")
ok("status=MANUAL_UPDATED saved correctly")

if data.get("manual_answer_text") != human_answer:
    fail(f"manual_answer_text not saved correctly.\n  Got: {data.get('manual_answer_text')}")
ok("manual_answer_text saved correctly")

if data.get("answer_text") != human_answer:
    fail("answer_text should equal manual_answer_text (active answer)")
ok("answer_text = manual_answer_text (active answer updated)")

# CRITICAL: ai_answer_text must never be overwritten
returned_ai = data.get("ai_answer_text") or ""
if not returned_ai.strip():
    fail("ai_answer_text is now empty — it was overwritten! Fix answers.py immediately.")
ok(f"ai_answer_text preserved ({len(returned_ai)} chars) — NOT overwritten ✅")

print(f"\n  ai_answer_text  : {returned_ai[:80]}…")
print(f"  answer_text     : {data.get('answer_text','')[:80]}…")
print(f"  manual_answer   : {data.get('manual_answer_text','')[:80]}…")


# ---------------------------------------------------------------------------
# TEST 7 — MISSING_DATA
# ---------------------------------------------------------------------------
section("TEST 7 — MISSING_DATA (no citations error expected)")

# Use a different answer if available, else reuse current
missing_candidates = [a for a in all_answers if a["status"] == "GENERATED"]
target_id = missing_candidates[0]["id"] if missing_candidates else answer_id

r = update_answer(target_id, {
    "status":        "MISSING_DATA",
    "reviewer_note": "No relevant information found in the indexed documents.",
})
if r.status_code != 200:
    fail(f"Expected 200, got {r.status_code} — {r.text}")
if r.json()["status"] != "MISSING_DATA":
    fail(f"status should be MISSING_DATA, got {r.json()['status']}")
ok("MISSING_DATA — status saved correctly with no errors")


# ---------------------------------------------------------------------------
# AUDIT LOG CHECK
# ---------------------------------------------------------------------------
section("AUDIT LOG — checking audit trail was recorded")

audit_r = requests.get(f"{API}/answers/{answer_id}/audit", timeout=HTTP_TIMEOUT)
if audit_r.status_code == 200:
    audit_log = audit_r.json()
    if isinstance(audit_log, list) and len(audit_log) > 0:
        ok(f"Audit log has {len(audit_log)} entries")
        for entry in audit_log[-3:]:  # show last 3
            print(f"    {entry.get('old_status')} → {entry.get('new_status')}  by {entry.get('changed_by')}")
    else:
        print("  [WARN] Audit log empty or unexpected format — check AnswerAuditLog inserts")
elif audit_r.status_code == 404:
    print("  [WARN] GET /answers/{id}/audit not implemented yet — add it if missing")
else:
    print(f"  [WARN] Audit endpoint returned {audit_r.status_code}")


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------
section("RESULT")
print("  \033[92m✅  ALL PHASE 5 CHECKS PASSED\033[0m")
print()
print("  Next step:")
print("  git add . && git commit -m 'Phase 5: Review workflow and audit trail'")
print("  Then move to Phase 6 — Next.js Frontend.")
print()
