# Work IQ + Python RAG Evaluation POC

A deterministic FastAPI mock used to validate the client-side contract and
initial automation flow for a future RAG evaluation system.

The intended production architecture is:

```text
Golden / reference question
          |
          +----------------------+
          |                      |
          v                      v
      Work IQ                RAG /chat API
   reference side           system under test
          |                      |
          +----------+-----------+
                     v
               Python evaluator
                     |
               metrics / decision
```

This repository intentionally implements **only the RAG endpoint mock** for the
first proof of concept. The mock returns static answers from `dataset.csv` so
that HTTP integration and evaluation orchestration can be tested without an
LLM, vector database, Semantic Kernel, SharePoint, Work IQ, or cloud service.

---

## 1. What this POC proves

The POC validates the complete basic request/response path:

```text
CSV dataset
   |
   v
Python client
   |
   | POST /chat
   v
FastAPI mock
   |
   v
Static query -> answer lookup
   |
   v
RAG answer returned to Python
   |
   v
Persist result
   |
   v
Compare reference vs candidate
   |
   v
PASS / FAIL
```

Validated behaviors include:

- FastAPI application startup
- `/health` endpoint
- `POST /chat` request validation
- `message_id` validation
- query validation
- chat history schema validation
- normalized exact-match lookup
- deterministic fallback answer for unknown questions
- Python HTTP client integration
- sequential batch-style execution over the CSV dataset
- answer persistence to JSON
- basic golden-vs-RAG comparison
- intentional failure detection

See [`docs/POC_VALIDATION.md`](docs/POC_VALIDATION.md) for the recorded test
results.

---

## 2. Repository structure

```text
.
├── dataset.csv              # deterministic mock QA source
├── main.py                  # FastAPI /chat mock server
├── smoke_test.py            # small Python client smoke test
├── requirements.txt         # pinned dependency ranges
├── README.md                # project documentation
├── LICENSE                  # MIT license
├── docs/
│   └── POC_VALIDATION.md    # tests actually performed
├── tests/
│   └── test_main.py         # local unit tests for mock logic
├── examples/                # safe place for future sanitized examples
└── .gitignore               # excludes runtime artifacts and secrets
```

Runtime outputs such as `rag_results.json`, `evaluation_results.json`, logs,
checkpoints, virtual environments, and credentials are intentionally ignored
from Git.

---

## 3. API contract

### `GET /health`

Returns server status and the number of loaded QA pairs.

Example:

```json
{
  "status": "ok",
  "loaded_qa_pairs": 16
}
```

### `POST /chat`

Request:

```json
{
  "message_id": "Q001",
  "query": "What is the maximum operating speed of the attraction?",
  "chat_history": []
}
```

Validation implemented by Pydantic:

| Field | Rule |
|---|---|
| `message_id` | 1-100 chars, `^[a-zA-Z0-9_-]+$` |
| `query` | 1-5000 chars |
| `chat_history` | list, maximum 50 items |
| history `query` | 1-5000 chars |
| history `answer` | 1-5000 chars |

Successful responses are returned as `text/plain`.

---

## 4. Dataset contract

`dataset.csv` contains:

```text
id,category,query,answer
```

The mock server loads the file once at startup and constructs a normalized
lookup table:

```text
normalized(query) -> answer
```

Normalization performs:

1. `strip()`
2. lowercase conversion
3. whitespace collapsing

No fuzzy matching, semantic matching, embeddings, or LLM reasoning is used.

Unknown queries return the fixed fallback response:

```text
I don't have information on that. Please contact a maintenance supervisor for
further assistance.
```

---

## 5. Local setup from scratch

### Step 1: enter the repository

WSL example:

```bash
cd /mnt/c/Users/Kethan/Downloads/workiq_rag_mock_poc
```

### Step 2: create the virtual environment

```bash
python3 -m venv .venv
```

### Step 3: activate it

```bash
source .venv/bin/activate
```

You should see `(.venv)` in the shell prompt.

### Step 4: install dependencies

```bash
python -m pip install -r requirements.txt
```

### Step 5: start the server

```bash
uvicorn main:app --reload --port 8000
```

Keep this terminal running.

---

## 6. Test the server manually

Open a second WSL terminal and activate the same environment.

### Health check

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","loaded_qa_pairs":16}
```

### Known question

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message_id":"Q001","query":"What is the maximum operating speed of the attraction?","chat_history":[]}'
```

Expected:

```text
The maximum operating speed is 80 km/h.
```

### Unknown question

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message_id":"Q999","query":"What is the color of the operator uniform?","chat_history":[]}'
```

Expected: the configured fallback answer.

---

## 7. Test through the Python client

With the server running:

```bash
python3 smoke_test.py
```

The client sends three requests:

- known single-hop case
- known negative case
- unknown/fallback case

This validates that a Python process can consume the API programmatically.

---

## 8. Run unit tests

The local tests use Python's standard-library `unittest` framework:

```bash
python3 -m unittest discover -s tests -v
```

These tests cover normalization, dataset loading, known-query lookup,
fallback behavior, and invalid dataset schema handling.

---

## 9. Batch-style collection test

The POC was also tested by loading all 16 CSV questions and sending them to
`POST /chat` automatically.

Conceptually:

```text
for every CSV row:
    send query to /chat
    capture response
```

Observed behavior:

```text
16 questions sent
16 answers received
```

A JSON persistence test then stored the returned records in:

```text
rag_results.json
```

That file is intentionally ignored by Git because it is a runtime artifact.

---

## 10. Basic evaluation behavior

The first evaluator implementation intentionally uses a simple normalized
exact comparison:

```text
golden_answer == rag_answer
        |
        +-- equal -> PASS
        +-- different -> FAIL
```

The successful test produced:

```text
PASS: 16
FAIL: 0
```

A separate negative fixture intentionally changed Q001 to an incorrect answer.
The evaluator correctly produced:

```text
PASS: 15
FAIL: 1
Failed case: Q001
```

This demonstrates that the evaluation path can detect a known bad response.

---

## 11. Why the mock is deliberately simple

This is a **contract POC**, not a production RAG implementation.

Deliberately not implemented:

- LLM inference
- retrieval/vector search
- Semantic Kernel orchestration
- Work IQ integration
- SharePoint integration
- Microsoft Graph integration
- JWT authentication enforcement
- streaming/chunked response behavior
- semantic similarity
- LLM-as-a-judge

Adding these components at this stage would make the POC harder to reason about
without improving the specific question being validated: can our Python
orchestrator reliably call a RAG-style API, capture answers, persist them, and
compare them with reference answers?

---

## 12. How this becomes the real evaluation pipeline

The mock is a replaceable adapter boundary.

Today:

```text
Python evaluator
      |
      v
POST /chat
      |
      v
static CSV answer
```

Later:

```text
Python evaluator
      |
      v
POST /chat
      |
      v
real RAG application
```

Separately, Work IQ can become the reference-answer provider during golden-data
creation:

```text
SharePoint/OneDrive attraction PDF
              |
              v
           Work IQ
              |
              v
question + answer + citation + keywords
```

The persisted golden/reference dataset can then be reused while evaluating the
real RAG application.

---

## 13. Intended next architecture

For a larger evaluation system, the repository can evolve toward:

```text
                    Golden Dataset
                          |
              +-----------+-----------+
              |                       |
              v                       v
         Work IQ Provider        RAG Provider
         reference side         system under test
              |                       |
              +-----------+-----------+
                          |
                          v
                   Python Runner
                          |
                 +--------+--------+
                 |                 |
                 v                 v
             Metrics            Decisions
                 |                 |
                 +--------+--------+
                          |
                          v
                    Reports / DB
```

Each provider should be implemented behind an adapter interface so Work IQ,
the real RAG endpoint, and the mock can be swapped without rewriting the
comparison engine.

---

## 14. Security and public-repository rules

Before making this repository public:

1. Never commit client secrets, certificates, access tokens, `.env` files, or
   real JWTs.
2. Never commit real SharePoint/OneDrive URLs that reveal internal resources.
3. Never commit company documents or proprietary RAG responses.
4. Keep runtime logs and checkpoints outside Git unless they have been reviewed
   and sanitized.
5. Use placeholders in documentation, for example:

```text
https://example.sharepoint.com/sites/example/...
```

6. Keep mock/test data synthetic or otherwise explicitly safe for publication.

The included `.gitignore` excludes common runtime and credential artifacts.

---

## 15. Git workflow for the public repository

Initialize the repository:

```bash
git init
git branch -M main
```

Review what will be committed:

```bash
git status
```

Verify ignored files are not accidentally included:

```bash
git status --ignored
```

Add the source files:

```bash
git add .
```

Review the staged content before committing:

```bash
git diff --cached --stat
git diff --cached
```

Create the initial commit:

```bash
git commit -m "feat: add deterministic RAG chat POC"
```

---

## 16. Create the public GitHub repository

On GitHub:

1. Sign in to your GitHub account.
2. Click **New repository**.
3. Choose a repository name, for example:

```text
workiq-rag-evaluation-poc
```

4. Set **Visibility** to **Public**.
5. Do **not** initialize it with another README, `.gitignore`, or license,
   because this local repository already contains them.
6. Create the repository.

GitHub will show the repository URL. Use that URL for the `origin` remote.

---

## 17. Connect the local repository to GitHub

Example:

```bash
git remote add origin https://github.com/<YOUR_USERNAME>/workiq-rag-evaluation-poc.git
```

Verify:

```bash
git remote -v
```

Push the initial commit:

```bash
git push -u origin main
```

After the push, refresh the public GitHub repository and verify the file list,
README rendering, and commit history.

---

## 18. Recommended commit history

Keep commits small and meaningful. For example:

```text
feat: add deterministic FastAPI chat mock
feat: add Python smoke-test client
test: validate mock lookup and fallback behavior
feat: add result persistence POC
feat: add evaluation comparison POC
docs: document validation and architecture
```

Do not commit generated runtime outputs just to demonstrate that they exist.
Use `docs/POC_VALIDATION.md` for the verified behavior and keep actual runtime
artifacts local unless they have a strong reason to be public.

---

## 19. Current POC status

```text
FastAPI mock                     ✅
CSV-backed deterministic data    ✅
Request validation               ✅
Health check                     ✅
Known-answer test                ✅
Fallback test                    ✅
Python client                    ✅
16-question automated loop       ✅
JSON persistence                 ✅
Basic PASS/FAIL evaluator        ✅
Intentional failure detection   ✅
Unit-test coverage               ✅ (local logic)
Real RAG integration             ⏳ future
Work IQ integration              ⏳ future
Streaming validation             ⏳ future
JWT validation                   ⏳ future
Semantic evaluation              ⏳ future
```

## License

MIT. See [`LICENSE`](LICENSE).
