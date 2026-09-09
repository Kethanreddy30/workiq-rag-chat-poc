# WorkIQ RAG Benchmark Dispatcher

Sends a set of benchmark questions to the real target RAG `/chat` API and
records what comes back, keyed by `question_id`.

It does **not** compare answers or score anything. It only sends
requests and writes down what happened, so a later comparison phase can
consume the results without re-hitting the API.

---

## Repository structure

```text
workiq_rag_mock_poc/
│
├── benchmark_dataset.csv
├── dispatch_to_target.py
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

---

## Target API contract

This is the contract `dispatch_to_target.py` sends against, taken from
the target's own OpenAPI docs:

```text
POST /chat
Authorization: Bearer <token>   (required by the target)

Body:
{
  "message_id": "Q001",
  "query": "What is the maximum operating speed of the attraction?",
  "chat_history": []
}

Response: text/plain, StreamingResponse (NOT JSON)
```

`message_id` must match `^[a-zA-Z0-9_-]+$`, 1-100 chars. `query` is
1-5000 chars. `chat_history` defaults to `[]` and isn't used by this
script.

The real endpoint doesn't exist yet - `TARGET_API_URL` is a placeholder
until it does.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

Environment-variable driven, no code changes needed once the real
endpoint exists:

| Variable | Default | Purpose |
|---|---|---|
| `TARGET_API_URL` | `https://your-api-url.com/chat` | Placeholder until the real target exists. |
| `TARGET_API_TOKEN` | *(empty)* | Sent as `Authorization: Bearer <token>` only if set. |
| `MAX_WORKERS` | `5` | Requests in flight at once. |
| `SLEEP_AFTER_REQUEST_SECONDS` | `1.0` | Each worker sleeps this long after its response, before taking the next question. |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Per-request timeout. |
| `MAX_ATTEMPTS` | `3` | Total attempts per question. |
| `RETRY_BASE_DELAY_SECONDS` | `1.0` | Exponential backoff base between retries. |

## Running it

```bash
export TARGET_API_URL="https://real-endpoint-once-it-exists.example.com/chat"
export TARGET_API_TOKEN="<real token, once one exists>"
python3 dispatch_to_target.py
```

---

## Dataset

```text
benchmark_dataset.csv
```

Columns: `question_id, query, answer` - 50 rows.

`answer` is the golden/reference answer. It is **never sent to the
target** - only `query` is. `answer` is stored purely so a later
comparison phase can check it against what the target actually
returned.

---

## Output

```text
rag_results.json
```

One record per question:

```json
{
  "question_id": "Q001",
  "query": "What is the maximum operating speed of the attraction?",
  "dataset_answer": "The maximum operating speed is 80 km/h.",
  "target_response": "<whatever the real target actually returned>",
  "status": "success",
  "http_status": 200,
  "error": null,
  "attempts": 1,
  "latency_seconds": 0.42,
  "timestamp_utc": "2026-09-09T04:03:34Z"
}
```

`dataset_answer` and `target_response` are intentionally both present
and intentionally not compared here - that's the next phase.

`rag_results.json` is a runtime artifact and is git-ignored.

---

## Design decisions

**Concurrency + throttling, together, not in tension.** A thread pool
of `MAX_WORKERS` workers sends requests in parallel. Each worker sleeps
`SLEEP_AFTER_REQUEST_SECONDS` after its own response before picking up
the next question. This bounds simultaneous requests to `MAX_WORKERS`
and paces each worker's own rate, without the two goals fighting each
other.

**Bounded retry, not a production retry schedule.** This is a one-shot
batch script, not a long-lived service - it should finish 50 rows in
roughly a minute, not block for minutes on one failing row. Only
transient failures are retried:

```text
retryable:      timeout, connection error, 5xx, 429
not retryable:  4xx other than 429 (e.g. 401, 422) - identical bad
                input will fail identically on retry
```

**Text, not JSON.** The target returns `text/plain` via
`StreamingResponse`. The script reads it with `stream=True` +
`response.text` instead of `response.json()`, which would throw
against this response type.

---

## What this has and hasn't been verified against

The real target doesn't exist yet, so this script has only been run
against a throwaway local stub matching the same contract, with
deliberately injected `503`/`429`/`401` responses to confirm retry and
auth-failure handling work correctly:

- concurrent dispatch across all 50 rows completes correctly
- a transient `5xx` is retried and eventually succeeds
- a persistent `429` exhausts all attempts and is recorded as an
  error, not silently dropped
- an invalid/missing token fails in one attempt, not three
- the streamed `text/plain` body is correctly captured as
  `target_response`

Point `TARGET_API_URL` at the real endpoint and re-verify once it
exists - real-world concurrency limits, timeout behavior, and response
shape may differ from what's assumed here.

---

## Current limitations

- not yet run against the real target (it doesn't exist yet)
- no comparison/scoring of `target_response` vs `dataset_answer` -
  that's the next phase
- `TARGET_API_TOKEN` is a plain environment variable, not loaded from
  a `.env` file - export it in your shell before running

---

## Next phase (not implemented)

Compare `target_response` to `dataset_answer` per `question_id` from
`rag_results.json`. Not built yet - intentionally out of scope for
this phase.
