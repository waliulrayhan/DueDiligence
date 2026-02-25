# Testing & Evaluation — DueDiligence Questionnaire Agent

---

## Dataset Plan

Five PDF files are provided in `/data/`. Their roles in testing are:

| File | Role |
|---|---|
| `20260110_MiniMax_Global_Offering_Prospectus.pdf` | Primary reference document. Richest source of fund details, investment strategy, team bios, fee structure. Used to answer the majority of ILPA questions. |
| `20260110_MiniMax_Audited_Consolidated_Financial_Statements.pdf` | Financial reference. Used for questions about AUM, returns, financial controls, and audit procedures. |
| `20260110_MiniMax_Accountants_Report.pdf` | Supporting financial evidence. Used to validate answers about accounting practices and independent oversight. |
| `20260110_MiniMax_Industry_Report.pdf` | Market context document. Used for questions about market opportunity, competitive positioning, and sector outlook. |
| `ILPA_Due_Diligence_Questionnaire_v1.2.pdf` | **Questionnaire input only** — not indexed as a reference document. Parsed to extract ~80–90 structured questions across sections (Fund Overview, Investment Strategy, Risk Management, etc.). |

### Recommended Test Setup
1. Index all four MiniMax PDFs as reference documents (scope=`ALL_DOCS`).
2. Create a project using the ILPA PDF as the questionnaire document.
3. Generate all answers.
4. Index one additional document to confirm `OUTDATED` transition triggers.

---

## QA Checklist

### Upload & Indexing
- [ ] 1. Upload a valid PDF — confirm `202 Accepted` and `AsyncRequest` created with status=`PENDING`.
- [ ] 2. Poll `GET /api/requests/{id}` — status progresses `PENDING → RUNNING → COMPLETED`.
- [ ] 3. After completion, document status=`READY` and `chunk_count > 0`.
- [ ] 4. Upload an unsupported file type (e.g. `.txt`) — confirm `400` error returned.
- [ ] 5. Upload a second document when a `READY/ALL_DOCS` project exists — confirm that project transitions to `OUTDATED`.

### Project Setup
- [ ] 6. Create a project with the ILPA questionnaire — confirm `AsyncRequest` resolves to `COMPLETED` and project status=`READY`.
- [ ] 7. Confirm question count matches expected (~80–90 for ILPA v1.2).
- [ ] 8. Attempt to create a project pointing to a non-existent doc — confirm `404`.

### Answer Generation
- [ ] 9. `POST /api/answers/generate-all` — confirm `202 Accepted` and all PENDING answers eventually become `GENERATED` or `MISSING_DATA`.
- [ ] 10. Inspect at least 3 generated answers — each must have `answer_text`, `confidence_score`, and at least one `Citation` with `page_number`.
- [ ] 11. `POST /api/answers/generate-single` — confirm single answer returned synchronously with citations.

### Review
- [ ] 12. Confirm an answer — status becomes `CONFIRMED`; `AnswerAuditLog` entry created.
- [ ] 13. Reject an answer without a note — confirm `422` validation error.
- [ ] 14. Reject with a note — status becomes `REJECTED`; note saved.
- [ ] 15. Manual-update an answer — `manual_answer_text` saved; `answer_text` updated to manual text; status=`MANUAL_UPDATED`.

### Evaluation
- [ ] 16. `POST /api/evaluation` with 3 ground truth pairs — confirm each result has `similarity_score`, `keyword_overlap`, `overall_score`, `explanation`.
- [ ] 17. `GET /api/evaluation/{project_id}` — confirm saved results returned with correct aggregates.
- [ ] 18. Re-run evaluation with updated human answers — confirm results are upserted (not duplicated).

### Health & Edge Cases
- [ ] 19. `GET /health` — confirm `database: ok` and `pinecone: ok`.
- [ ] 20. Generate answers with no documents indexed — confirm `MISSING_DATA` answers (not errors).

---

## Evaluation Metric Explanation

The evaluation module compares an AI-generated answer against a human-written ground truth answer using two complementary metrics.

### 1. TF-Vector Cosine Similarity (`similarity_score`)

Measures **lexical co-occurrence** weighting by term frequency.

Steps:
1. Tokenize both strings: lowercase, extract `[a-z0-9]+` tokens.
2. Build term-frequency (TF) count vectors for each string.
3. Compute cosine similarity between the two vectors:

$$\text{cosine}(A, B) = \frac{\vec{v_A} \cdot \vec{v_B}}{|\vec{v_A}| \cdot |\vec{v_B}|}$$

Where $\vec{v}$ is the TF vector over the joint vocabulary. Range: $[0, 1]$.

This is a pure-Python, zero-dependency implementation — no sentence-transformers model required at evaluation time.

### 2. Jaccard Keyword Overlap (`keyword_overlap`)

Measures **set-level vocabulary overlap** after removing stopwords.

Steps:
1. Tokenize both strings (same as above).
2. Remove a curated set of 45+ stopwords (`the`, `a`, `is`, `are`, `to`, `of`, …).
3. Compute Jaccard similarity on the resulting word sets:

$$\text{Jaccard}(S_A, S_B) = \frac{|S_A \cap S_B|}{|S_A \cup S_B|}$$

Special cases: if both sets are empty → 1.0; if only one is empty → 0.0.

### 3. Weighted Overall Score

$$\text{overall\_score} = \frac{\text{similarity\_score} + \text{keyword\_overlap}}{2}$$

Both metrics are weighted equally (0.5 / 0.5). This balances fluency/context (cosine) against domain keyword coverage (Jaccard).

> **Note:** The phase specification suggested `0.7 × semantic + 0.3 × keyword` using a neural sentence-transformer model. The implemented approach uses equal weighting with a pure TF-cosine function, eliminating the ~90MB model download and making the scoring fast, deterministic, and serverless-compatible.

---

## Score Interpretation Table

| Range | Label | Meaning |
|---|---|---|
| ≥ 0.80 | **Excellent** | Strong semantic and keyword alignment. AI answer closely matches human ground truth. |
| 0.60 – 0.79 | **Good** | Good alignment with minor gaps. Most key points covered. |
| 0.40 – 0.59 | **Partial** | Partial overlap; some key points missing. Review recommended. |
| < 0.40 | **Poor** | Low similarity; answers diverge significantly. Manual rewrite required. |

---

## Sample Evaluation Output

```json
POST /api/evaluation
{
  "project_id": "3f2a1b9c-0d4e-4f8a-b2c3-d4e5f6a7b8c9",
  "ground_truth": [
    {
      "question_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "human_answer_text": "The fund targets institutional limited partners with a minimum commitment of $5 million USD."
    },
    {
      "question_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "human_answer_text": "The investment team comprises 12 professionals with over 20 years of combined private equity experience."
    },
    {
      "question_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "human_answer_text": "Management fees are 2% per annum on committed capital during the investment period, stepping down to 1.5% thereafter."
    }
  ]
}

Response:
{
  "aggregates": {
    "avg_score": 0.7156,
    "count_excellent": 1,
    "count_good": 1,
    "count_poor": 0,
    "total": 3
  },
  "results": [
    {
      "question_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "question_text": "What is the minimum LP commitment amount?",
      "ai_answer_text": "According to the prospectus, the fund requires a minimum commitment of $5 million from institutional investors. Smaller commitments may be accepted at the general partner's discretion.",
      "human_answer_text": "The fund targets institutional limited partners with a minimum commitment of $5 million USD.",
      "similarity_score": 0.8934,
      "keyword_overlap": 0.6,
      "overall_score": 0.7967,
      "explanation": "Good alignment with minor gaps."
    },
    {
      "question_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "question_text": "Describe the investment team's experience.",
      "ai_answer_text": "The investment team has extensive backgrounds across private equity, venture capital, and public markets, with the core team members holding senior positions for over two decades.",
      "human_answer_text": "The investment team comprises 12 professionals with over 20 years of combined private equity experience.",
      "similarity_score": 0.7412,
      "keyword_overlap": 0.5556,
      "overall_score": 0.6484,
      "explanation": "Good alignment with minor gaps."
    },
    {
      "question_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "question_text": "What are the management fee terms?",
      "ai_answer_text": "The fund charges management fees as described in the offering documents. Specific fee terms are subject to individual LP negotiations.",
      "human_answer_text": "Management fees are 2% per annum on committed capital during the investment period, stepping down to 1.5% thereafter.",
      "similarity_score": 0.5123,
      "keyword_overlap": 0.3571,
      "overall_score": 0.4347,
      "explanation": "Partial overlap; some key points missing."
    }
  ]
}
```
