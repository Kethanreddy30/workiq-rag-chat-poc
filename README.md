# WorkIQ RAG Chat POC

A small, deterministic FastAPI proof of concept used to validate the request/response contract of a RAG-style chat API before connecting a real retrieval system, Microsoft Work IQ, or an LLM evaluator.

The current POC intentionally uses a CSV file as its answer source. This makes the behavior predictable and lets us test the surrounding API and evaluation workflow independently from model quality.

## Purpose

The POC answers four practical questions:

1. Can we expose the expected `POST /chat` API contract?
2. Can a client send a question and receive a deterministic answer?
3. Can we run a batch of benchmark questions automatically?
4. Can we compare returned answers against expected answers and detect failures?

This is a **mock RAG service**, not a production RAG implementation.

It currently does **not** connect to:

- Microsoft Work IQ
- SharePoint or OneDrive
- Microsoft Graph
- a vector database
- an embedding model
- an LLM
- Semantic Kernel
- a real (external) JWT identity provider — `/chat` is now gated by a
  self-contained mock HS256 check, not a real IdP; see [Authentication](#authentication)
- no external streaming provider; the mock `/chat` endpoint streams its deterministic response

Those integrations can be added later without changing the basic benchmark idea.

---

## Architecture

The current POC is intentionally simple:

```text
Benchmark / Client
        |
        | HTTP POST /chat
        | Authorization: Bearer <token>
        v
   FastAPI server
        |
        v
   JWT verification (mock, HS256)
        |
        v
    dataset.csv
        |
        v
 deterministic answer
```

The later evaluation architecture is expected to look more like:

```text
                     +----------------------+
                     |   Golden QA Dataset  |
                     +----------+-----------+
                                |
                         same benchmark
                         question / case_id
                                |
                +---------------+---------------+
                |                               |
                v                               v
        Microsoft Work IQ                 Real RAG API
        reference answer                    /chat
                |                               |
                +---------------+---------------+
                                |
                                v
                         Python Evaluator
                                |
                +---------------+---------------+
                |                               |
                v                               v
          Metrics / Gates                Review / Report
```

The Work IQ side can provide a reference answer during dataset-generation experiments. The real RAG API is the system being evaluated.

---

## Repository structure

```text
workiq_rag_mock_poc/
│
├── main.py
├── auth.py
├── dataset.csv
├── requirements.txt
├── smoke_test.py
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── .env                    (local only, git-ignored, not in the repo)
│
├── docs/
│   └── POC_VALIDATION.md
│
└── tests/
    └── test_main.py
```

Runtime-only files such as virtual environments, generated result JSON files, caches, and local/private data are intentionally excluded from Git.

---

# Installation

## Development environment used

This project was developed and tested in:

- Windows
- WSL2
- Ubuntu/Linux shell inside WSL2
- Python 3.14.x
- `venv`
- FastAPI
- Uvicorn

The Windows project folder is:

```text
C:\Users\Kethan\Downloads\workiq_rag_mock_poc
```

The same folder from WSL2 is:

```text
/mnt/c/Users/Kethan/Downloads/workiq_rag_mock_poc
```

### WSL2 path vs Windows path

When working inside the WSL terminal, use the Linux/WSL path:

```bash
cd /mnt/c/Users/Kethan/Downloads/workiq_rag_mock_poc
```

When working in Windows tools such as File Explorer, PowerShell, or Windows editors, use:

```text
C:\Users\Kethan\Downloads\workiq_rag_mock_poc
```

They refer to the same project directory on the Windows filesystem.

---

## Python command differences

Inside WSL/Linux, the usual command is:

```bash
python3
```

On many Windows installations, Python may instead be invoked with:

```powershell
python
```

or:

```powershell
py
```

This repository was tested from WSL using `python3`.

Therefore the examples below use:

```bash
python3
```

Do not assume that `python` and `python3` are interchangeable on every machine.

---

## Create and activate the virtual environment

From the project directory in WSL:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

After activation, your terminal should show something similar to:

```text
(.venv) kethan@K2:...
```

To leave the environment:

```bash
deactivate
```

The `.venv/` directory is ignored by Git and should not be committed.

---

## Install dependencies

With the virtual environment activated:

```bash
python3 -m pip install -r requirements.txt
```

The dependency set is intentionally small because this POC is only validating the API contract and deterministic behavior.

---

## Configure environment variables

The API will not start without `JWT_SECRET_KEY` set. Copy the template and generate your own secret:

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the generated value into `.env` as `JWT_SECRET_KEY`. Do not reuse a secret that has appeared anywhere outside your own machine.

`.env.example`:

```text
JWT_SECRET_KEY=replace-with-your-own-generated-secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
MOCK_ENV=dev
```

`.env` is listed in `.gitignore` and must never be committed. See [Authentication](#authentication) for what each variable does.

---

# Running the API

Start the FastAPI application:

```bash
uvicorn main:app --reload --port 8000
```

The API will normally be available at:

```text
http://127.0.0.1:8000
```

FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

---

# Health check

In a second terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","loaded_qa_pairs":16}
```

The exact number may change if `dataset.csv` is intentionally expanded later.

`/health` does not require a token.

---

# Authentication

`/chat` requires a Bearer JWT. `/health` and `/dev/token` do not.

## Why a mock JWT layer, and why HS256 specifically

This is not a real identity provider. It exists to prove one narrow thing: that the API correctly gates on token presence, signature validity, and expiry - not to model production auth.

The eventual Work IQ integration is expected to use delegated, user-context tokens issued by a real IdP (see "Work IQ integration plan" below), verified with RS256 against a rotating JWKS endpoint. That is a different, later piece of work with a different failure surface (key rotation, issuer/audience checks, clock skew). This mock intentionally does not try to imitate that shape, because a wrong imitation would create false confidence rather than real coverage. HS256 with a shared local secret is enough to validate the gate behavior itself.

## Environment variables

| Variable | Purpose |
|---|---|
| `JWT_SECRET_KEY` | HS256 signing secret. Required - `main.py` raises on startup if it's unset. |
| `JWT_ALGORITHM` | Signing algorithm. `HS256` unless you have a specific reason to change it. |
| `JWT_EXPIRE_MINUTES` | Lifetime of tokens minted by `/dev/token`. |
| `MOCK_ENV` | Set to `dev` to enable `/dev/token`. Any other value makes that route return `404`. |

See "Configure environment variables" above for setup.

## Getting a token

```bash
curl http://127.0.0.1:8000/dev/token
```

```json
{"access_token": "eyJ...", "token_type": "bearer", "expires_in_minutes": 60}
```

This route only exists to make local testing possible without a real IdP. It mints a token signed with your own `JWT_SECRET_KEY` - it does not authenticate against anything external, and it is gated behind `MOCK_ENV=dev` so it doesn't stay silently reachable if this code is ever deployed somewhere that isn't a local dev/POC run.

## Calling /chat with a token

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/dev/token | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message_id":"Q001","query":"What is the opening time?","chat_history":[]}'
```

## Failure behavior

| Request | Response |
|---|---|
| No `Authorization` header | `401` |
| Header present without `Bearer ` prefix | `401` |
| Malformed token / bad signature | `401` |
| Expired token | `401` |
| Valid token | `200` + normal `/chat` response |

All failures return `401`. The response body text differs slightly between cases (missing header vs. expired vs. invalid signature) to make local debugging easier - this is a POC auth gate, not a hardened boundary, so no attempt is made to hide which check failed from an unauthenticated caller. A production auth layer in front of a real IdP would generally want to avoid that distinction to prevent token enumeration; that tradeoff doesn't apply here.

---

# Chat API

## Endpoint

```text
POST /chat
Authorization: Bearer <token>   (required - see Authentication above)
```

## Request format

The POC accepts:

```json
{
  "message_id": "Q001",
  "query": "What is the opening time?",
  "chat_history": []
}
```

### Fields

`message_id`

A caller-supplied identifier for the request.

`query`

The benchmark question or user question.

`chat_history`

An array reserved for conversational context. The current mock implementation does not use chat history to generate the answer.

---

## Response

The current mock returns a streamed plain-text response.

Example:

```text
The attraction opens at 9:00 AM.
```

The implementation intentionally keeps this response simple so the benchmark client can focus on answer content.

---

# Basic request/response path

The complete basic request/response path is:

```text
1. Client creates a question
           |
           v
2. Client sends HTTP POST /chat
           |
           v
3. FastAPI receives the request
           |
           v
4. Request is validated
           |
           v
5. The query is normalized
   (for the mock lookup)
           |
           v
6. dataset.csv is searched
           |
           +--------------------+
           |                    |
        match                no match
           |                    |
           v                    v
7a. Expected answer      7b. Fallback answer
           |                    |
           +---------+----------+
                     |
                     v
8. FastAPI streams the text/plain response
                     |
                     v
9. Client records the response
```

The key point is that this is a **deterministic lookup service**.

It is not performing semantic retrieval.

---

# Deterministic mock behavior

The mock uses the question text as the lookup key after normalization.

The intended normalization makes differences such as case and surrounding whitespace harmless.

For example, these can resolve to the same normalized query:

```text
What is the opening time?
what is the opening time?
  What is the opening time?
```

This is useful for API testing because it avoids introducing an LLM or vector search system while we verify the surrounding pipeline.

---

# Unknown queries

When the incoming query does not match a known dataset question, the API returns a deterministic fallback rather than inventing an answer.

This is deliberate.

For an evaluation system, an unknown or invalid case should be visible as a controlled failure rather than silently becoming a fabricated answer.

---

# Dataset

The benchmark source is:

```text
dataset.csv
```

Current columns:

```text
id, category, query, answer
```

Example:

```csv
id,category,query,answer
Q001,single-hop,What is the opening time?,The attraction opens at 9:00 AM.
```

The dataset currently contains 16 synthetic QA rows used for the POC tests.

The current categories include examples for:

- single-hop
- negative
- factual
- quantitative

The dataset is intentionally small and synthetic. It is infrastructure test data, not an authoritative real-world knowledge base.

---

# Smoke test

The repository contains:

```text
smoke_test.py
```

With the API running, execute:

```bash
python3 smoke_test.py
```

The smoke test first calls `/dev/token` to get a bearer token, then sends representative known and unknown questions to `/chat` using that token.

A successful run verifies that:

- the API is reachable
- `/dev/token` mints a usable token
- known questions return the expected mock answer
- unknown questions return the fallback behavior

---

# Batch test

The POC was also exercised against the full CSV dataset.

The test flow is:

```text
dataset.csv
    |
    v
read all benchmark questions
    |
    v
POST each question to /chat
    |
    v
collect returned answers
    |
    v
write evaluation input/results
```

This demonstrates that the API can be driven automatically rather than tested manually one request at a time.

Generated result files are local runtime artifacts and are ignored by Git.

---

# Evaluation

A deterministic evaluator can compare:

```text
expected answer
       vs
actual RAG answer
```

For the current mock:

```text
dataset.csv
     |
     +---- query
     +---- expected answer
               |
               v
         POST /chat
               |
               v
          actual answer
               |
               v
          evaluator
               |
               v
        PASS / FAIL
```

An intentional negative test was also performed by changing one returned answer.

The evaluator correctly detected:

```text
15 PASS
1 FAIL
```

That is an important validation because an evaluator is only useful if it can detect a known bad result.

---

# Unit tests

The repository contains:

```text
tests/test_main.py
```

Run:

```bash
python3 -m unittest discover -s tests -v
```

The POC test suite covers behavior such as:

- missing dataset columns are rejected
- known query lookup works
- expected dataset size is loaded
- query normalization handles case and whitespace
- unknown queries return the fallback
- `/chat` without a token is rejected (401)
- `/chat` with a malformed `Authorization` header is rejected (401)
- `/chat` with an invalid token is rejected (401)
- `/dev/token` followed by `/chat` with that token succeeds (200)
- `/dev/token` returns 404 when `MOCK_ENV` is not `dev`

The validated test run completed successfully with:

```text
Ran 10 tests
OK
```

---

# What has been validated

The following POC behavior has been tested successfully:

## 1. Server startup

```bash
uvicorn main:app --reload --port 8000
```

The FastAPI service starts successfully.

## 2. Health endpoint

```bash
curl http://127.0.0.1:8000/health
```

Returns a healthy status and loaded dataset count.

## 3. Known query

A known benchmark question, sent with a valid bearer token, returns its expected static answer.

## 4. Unknown query

An unknown question, sent with a valid bearer token, returns the controlled fallback.

## 5. Smoke test

```bash
python3 smoke_test.py
```

Representative requests succeed.

## 6. Full dataset request run

All current dataset questions were sent through `/chat`.

## 7. Basic evaluation

The normal result set produced:

```text
PASS: 16
FAIL: 0
```

## 8. Negative evaluation test

One result was intentionally made incorrect.

The evaluator produced:

```text
PASS: 15
FAIL: 1
```

The failed case was the intentionally corrupted case.

## 9. Unit tests

```bash
python3 -m unittest discover -s tests -v
```

Result:

```text
Ran 10 tests
OK
```

## 10. Secret scanning

Gitleaks was run before committing the GitHub-ready changes.

The scan reported no leaks in the scanned commits.

## 11. Auth gate

Verified directly against the running server:

- no `Authorization` header → `401`
- malformed header (no `Bearer ` prefix) → `401`
- garbage/invalid token → `401`
- valid token from `/dev/token` → `200` with the correct answer

## 12. Dev token endpoint gating

With `MOCK_ENV` patched to a non-`dev` value, `/dev/token` returns `404` instead of minting a token.

---

# Why build a mock before the real RAG system?

A real RAG system has many moving pieces:

```text
documents
   |
   v
document ingestion
   |
   v
chunking
   |
   v
embeddings
   |
   v
vector/index storage
   |
   v
retrieval
   |
   v
reranking
   |
   v
prompt/context construction
   |
   v
LLM
   |
   v
answer
```

If the evaluation harness is built at the same time, failures become difficult to localize.

For example:

```text
"Was the evaluator wrong?"
"Was the API wrong?"
"Was retrieval wrong?"
"Was the prompt wrong?"
"Was the LLM wrong?"
"Was the source document wrong?"
```

The mock isolates the outer contract first.

Once the request/response path, dataset format, result collection, and evaluator are known to work, we can replace the mock answer source with the real RAG system.

---

# Planned real evaluation architecture

The target evaluation setup is expected to compare two answer providers using the same question:

```text
                Golden QA Case
                      |
                  case_id
                      |
               benchmark query
                      |
          +-----------+-----------+
          |                       |
          v                       v
      Work IQ                  Real RAG
   reference side              /chat
          |                       |
          v                       v
      reference               candidate
       answer                  answer
          |                       |
          +-----------+-----------+
                      |
                      v
                 Evaluator
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
      metrics       gates        human review
```

The important design principle is that the same canonical `case_id` should join the records.

Do not use row order as the identity of an evaluation case.

---

# Benchmark dataset design

The planned attraction benchmark uses:

```text
160 source documents
20 QA cases per document
```

Per document:

```text
5 Single-hop
5 Negative
5 Factual
5 Quantitative
```

Therefore:

```text
160 × 20 = 3,200 QA cases
```

For an initial batch size of five documents:

```text
5 × 20 = 100 QA cases per batch
```

Across 160 documents:

```text
160 / 5 = 32 batches
```

The final production dataset is expected to contain a canonical record similar to:

```text
case_id
attraction_name
question_type
question
golden_answer
keywords
citations
source_document
source_location
```

The `case_id` is the primary join key.

---

# Work IQ integration plan

The eventual Work IQ flow is conceptually:

```text
User
  |
  v
Frontend
  |
  v
Backend API
  |
  | delegated user token / OBO
  v
Microsoft Work IQ REST API
  |
  v
reference answer
```

For source-grounded benchmark generation, web grounding should be explicitly disabled for source-only cases so that the reference answer is based on the intended source context rather than unrelated web information.

Work IQ remains user-delegated; this project should not assume an app-only Work IQ authentication model.

---

# File context vs folder enumeration

A known individual SharePoint/OneDrive document can be supplied as context to the Work IQ request.

The Work IQ benchmark generator does not need Microsoft Graph merely to reason over an already-known individual file URI.

Graph becomes relevant when automation itself needs to do things such as:

```text
list files in a folder
download files
upload files
edit files
enumerate documents
```

That distinction keeps the initial integration smaller.

---

# Evaluation metrics

The eventual evaluator should not depend on only one opaque score.

Useful deterministic metrics include:

- exact match
- normalized exact match
- token precision
- token recall
- token F1
- keyword recall
- numeric match
- entity match
- required-fact coverage
- forbidden-term detection
- answer length checks
- negative/abstention correctness

For RAG systems, retrieval metrics may also be added when retrieval context is available:

- Precision@K
- Recall@K
- MRR
- Hit@K
- context coverage
- context duplication

Operational metrics should also be collected:

- latency
- P50/P95/P99
- throughput
- timeout rate
- error rate
- retry rate

Semantic or LLM-judge metrics may be added later where organizational policy permits them.

---

# Evaluation result statuses

The evaluator should distinguish quality failures from infrastructure failures.

Recommended statuses include:

```text
PASS
FAIL
REVIEW_REQUIRED
NOT_SCORED
```

For example:

```text
RAG_TIMEOUT
RAG_HTTP_ERROR
JUDGE_TIMEOUT
```

should not automatically become:

```text
quality score = 0
```

They are operational failures and should be recorded separately.

---

# Failure classes

A robust evaluator can classify failures such as:

```text
INPUT_ERROR
SCHEMA_ERROR
JOIN_ERROR
RAG_HTTP_ERROR
RAG_TIMEOUT
RAG_RATE_LIMIT
EMPTY_RESPONSE
NORMALIZATION_ERROR
METRIC_ERROR
JUDGE_ERROR
JUDGE_TIMEOUT
JUDGE_CONFLICT
GOLDEN_DATA_ERROR
HUMAN_REVIEW_REQUIRED
```

Transient failures should be retried with bounded exponential backoff and jitter.

The original failure event should still be preserved.

---

# Human-in-the-loop review

Automatic evaluation should escalate cases when:

- evaluator signals conflict
- the golden answer may be incorrect
- the result is borderline
- the question has semantic ambiguity
- a critical hallucination is suspected
- an evaluator itself fails

Human review should be a controlled exception path rather than silently changing the score.

---

# Reference answer strategy

Work IQ-generated answers should not automatically be assumed to be perfect golden truth.

A safer workflow is:

```text
source document
      |
      v
Work IQ generation
      |
      v
reference candidate
      |
      v
human / validation step
      |
      v
approved golden answer
```

Once approved, save the reference answer in the benchmark dataset rather than calling Work IQ every time the RAG system is evaluated.

This improves:

- repeatability
- cost control
- stability
- auditability

A separate reference-stability experiment can call Work IQ again later to see whether answers drift.

---

# Concurrency and batch execution

For a batch containing several independent source documents, one conversation per document is the preferred isolation model.

For example:

```text
Document A -> Work IQ conversation A
Document B -> Work IQ conversation B
Document C -> Work IQ conversation C
...
```

This avoids accidentally mixing source context across attractions.

Concurrency should be introduced gradually:

```text
start with 1
then test 2
then test 3
then test 5
```

Measure:

- latency
- errors
- timeouts
- throttling
- stability

Do not assume an arbitrary concurrency limit without testing the actual service behavior and current platform guidance.

---

# Security

## Never commit secrets

Do not commit:

```text
.env
client secrets
API keys
access tokens
refresh tokens
private keys
certificates
credential files
```

The `.gitignore` is designed to exclude common secret and local-runtime patterns, including `JWT_SECRET_KEY`'s home in `.env`. Only `.env.example` (placeholder values) is meant to be committed.

## Public repository safety

This repository is public, so assume everything tracked in Git is intentionally public.

Before every push, verify that the staged changes do not contain:

- credentials
- private documents
- internal source material
- local paths containing sensitive information
- customer data
- generated benchmark data that should remain private

The real source PDFs and private benchmark data should not be placed into this public repository.

---

# Git workflow

The repository uses normal Git checkpoints.

Example:

```bash
git status
```

Review changes:

```bash
git diff
```

Stage changes:

```bash
git add .
```

Create a checkpoint:

```bash
git commit -m "Update README"
```

Push:

```bash
git push origin main
```

A clean working tree should look like:

```text
nothing to commit, working tree clean
```

The current project already has a baseline commit for the mock RAG chat POC and a GitHub remote.

---

# Development workflow

A practical local workflow is:

```text
1. Open WSL2
       |
2. cd into project
       |
3. activate .venv
       |
4. start FastAPI
       |
5. run smoke tests
       |
6. run unit tests
       |
7. inspect git diff
       |
8. commit a checkpoint
       |
9. push to GitHub
```

This creates small, reversible milestones instead of making one very large change.

---

# Current limitations

This repository is intentionally not a production RAG implementation.

Current limitations include:

- static CSV lookup
- no semantic retrieval
- no embeddings
- no vector database
- no LLM generation
- no real identity provider (mock HS256 JWT gate only - see [Authentication](#authentication))
- no SharePoint integration
- no Microsoft Graph integration
- no Work IQ integration
- no real external streaming provider
- no production observability
- no distributed execution
- no production rate-limit handling

These are expected limitations of the mock POC.

---

# Next engineering stage

The logical next stages are:

```text
Stage 1
Mock API contract
        |
        v
Stage 2
Benchmark dataset + evaluator
        |
        v
Stage 3
Real RAG /chat integration
        |
        v
Stage 4
Work IQ reference generation
        |
        v
Stage 5
3,200-case benchmark
        |
        v
Stage 6
automated reports / dashboards
        |
        v
Stage 7
production hardening
```

The objective is to avoid coupling all of these pieces together at the same time.

---

# Summary

This POC proves the basic infrastructure required for an automated RAG evaluation workflow:

```text
question
   |
   v
HTTP API
   |
   v
answer
   |
   v
stored result
   |
   v
comparison
   |
   v
PASS / FAIL
```

The mock is intentionally deterministic so that the surrounding system can be validated before introducing the complexity of retrieval, Work IQ, SharePoint, Graph, real identity-provider authentication, and LLM-based evaluation.

Once the contract and evaluation harness are stable, the static answer lookup can be replaced by the real RAG service without redesigning the entire benchmark workflow.
