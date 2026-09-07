# POC Validation Record

## Scope

This repository validates the contract and orchestration shape of a mock RAG
`POST /chat` endpoint. It does **not** implement a real LLM, retrieval layer,
Semantic Kernel orchestration, JWT verification, or streaming response.

## Environment validated

- Python 3.14.4 in WSL2
- FastAPI 0.141.1
- Pydantic 2.13.5
- Uvicorn 0.52.4
- 16 CSV-backed mock QA records

## Tests completed

### 1. Virtual environment creation

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Passed.

### 2. Dependency installation

```bash
python -m pip install -r requirements.txt
```

Passed.

### 3. Server startup

```bash
uvicorn main:app --reload --port 8000
```

Passed; application startup completed successfully.

### 4. Health endpoint

```bash
curl http://127.0.0.1:8000/health
```

Observed:

```json
{"status":"ok","loaded_qa_pairs":16}
```

Passed.

### 5. Known query

`Q001` returned the expected static answer.

Passed.

### 6. Unknown query

An unknown query returned the configured fallback response with HTTP 200.

Passed.

### 7. Python client

```bash
python3 smoke_test.py
```

Passed for `Q001`, `Q007`, and an unknown `Q999` fallback case.

### 8. Batch-style request loop

A Python loop loaded all 16 CSV rows and called `POST /chat` for all 16 cases.

Observed: 16 successful responses.

Passed.

### 9. Result persistence

The request loop persisted all 16 returned answers to `rag_results.json`.

Passed.

### 10. Basic comparison

Golden/reference answer and returned RAG answer were compared using
case-insensitive, whitespace-trimmed exact string equality.

Observed: 16 PASS, 0 FAIL.

Passed.

### 11. Failure detection

`Q001` was intentionally changed to an incorrect answer in a separate test
fixture. The comparison produced 15 PASS and 1 FAIL, correctly identifying Q001.

Passed.

## Important limitation

The POC proves HTTP contract, deterministic lookup, Python orchestration, answer
collection, persistence, and basic comparison behavior. It does not prove the
behavior of the future real RAG application or Work IQ integration.
