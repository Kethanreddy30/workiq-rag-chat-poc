# WorkIQ RAG Chat POC

A lightweight Python automation project for testing and benchmarking a protected RAG chat API before connecting the full Microsoft Work IQ reference-answer and evaluation pipeline.

The project currently focuses on this stage:

```text
Benchmark Dataset
      |
      v
Python Dispatcher
      |
      | POST /chat
      | Authorization: Bearer <token>
      v
Target RAG API
      |
      | StreamingResponse
      v
Stream Parser
      |
      v
Collected Answers
      |
      +----------------------+
      |                      |
      v                      v
rag_results.json    evaluation_input.json
```

The current POC does not yet perform answer scoring. It prepares clean results so a later evaluation layer can calculate metrics such as accuracy, relevance, faithfulness, groundedness, and retrieval quality.

---

## 1. What This Project Does

The POC validates the infrastructure around a future Work IQ + RAG evaluation workflow.

It currently answers these questions:

1. Can benchmark questions be loaded and validated?
2. Can every benchmark question be sent automatically to the target `/chat` endpoint?
3. Can the protected endpoint be called using a Bearer token?
4. Can a streaming response be consumed correctly?
5. Can multiple benchmark questions be sent concurrently?
6. Can transient failures be retried?
7. Can one failed question be isolated without stopping the rest of the batch?
8. Can latency, HTTP status, retries, errors, and answers be recorded?
9. Can the target URL and token remain outside source code?
10. Can a clean evaluation-ready file be generated for the next phase?

---

## 2. Current Scope

This repository is an API dispatch and response-capture POC.

It is intentionally not a complete RAG evaluator yet.

### Current flow

```text
benchmark_dataset.csv
        |
        v
Validate Dataset
        |
        v
Load .env configuration
        |
        v
Create concurrent workers
        |
        v
POST /chat
        |
        v
Read StreamingResponse
        |
        v
Extract text chunks
        |
        v
Build complete answer
        |
        v
Store result
        |
        +--------------------------+
        |                          |
        v                          v
rag_results.json          evaluation_input.json
```

### Planned architecture

```text
                    Golden QA Dataset
                           |
             +-------------+-------------+
             |                           |
             v                           v
      Microsoft Work IQ             Real RAG API
      Reference Answer                 /chat
             |                           |
             +-------------+-------------+
                           |
                           v
                       Evaluator
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
       Accuracy        Relevance       Faithfulness
          |                |                |
          +----------------+----------------+
                           |
                           v
                    Evaluation Report
```

---

## 3. Repository Structure

```text
workiq-rag-chat-poc/
|
├── benchmark_dataset.csv
├── dispatch_to_target.py
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
└── LICENSE
```

### `benchmark_dataset.csv`

Benchmark input containing:

```text
question_id
query
answer
```

The `answer` column is preserved for the later comparison/evaluation stage.

Example:

```csv
question_id,query,answer
Q001,What is the opening time?,The attraction opens at 9:00 AM.
Q002,Is the attraction open after midnight?,No, the attraction closes before midnight.
```

### `dispatch_to_target.py`

Main automation script.

Responsibilities:

- load benchmark questions
- validate input data
- load environment variables
- authenticate requests
- generate unique request IDs
- call the target `/chat` API
- consume streaming responses
- extract answer text
- retry transient failures
- execute requests concurrently
- isolate per-question failures
- record operational metadata
- write JSON outputs

### `.env.example`

Safe configuration template showing the required variables without exposing real credentials.

### `.env`

Local-only runtime configuration containing the real endpoint and token.

This file must never be committed.

### `.gitignore`

Prevents local secrets and generated result files from being committed.

### `requirements.txt`

Current Python dependencies:

```text
requests
python-dotenv
```

---

# 4. Environment Configuration

The target URL and bearer token are not hardcoded in Python.

The application loads them from `.env`.

The important configuration is:

```env
TARGET_API_URL=your-endpoint-url-here
TARGET_API_TOKEN=your-bearer-token-here

MAX_WORKERS=5
SLEEP_AFTER_REQUEST_SECONDS=1.0
REQUEST_TIMEOUT_SECONDS=30
STREAM_IDLE_TIMEOUT_SECONDS=60
MAX_ATTEMPTS=3
RETRY_BASE_DELAY_SECONDS=1.0
```

The code uses:

```python
from dotenv import load_dotenv

load_dotenv()
```

and then:

```python
TARGET_API_URL = os.environ.get("TARGET_API_URL", "").strip()
TARGET_API_TOKEN = os.environ.get("TARGET_API_TOKEN", "").strip()
```

The script fails fast if the required URL or token is missing.

This creates a clean separation:

```text
Source Code
    |
    +-- application logic
    +-- no real URL
    +-- no real token

.env
    |
    +-- actual endpoint
    +-- actual bearer token
```

---

# 5. Authentication

The target API expects a Bearer token:

```http
Authorization: Bearer <token>
```

The dispatcher creates the header from the environment variable:

```python
headers["Authorization"] = f"Bearer {TARGET_API_TOKEN}"
```

The dispatcher does not implement the external identity provider.

It assumes the caller already has a valid token.

This is useful for testing a protected endpoint while keeping authentication credentials outside the source code.

---

# 6. Target API Contract

The current target contract is:

```http
POST /chat
Authorization: Bearer <token>
Content-Type: application/json
```

Request body:

```json
{
  "message_id": "unique-message-id",
  "query": "What is the opening time?",
  "chat_history": []
}
```

## `message_id`

A unique ID is generated with:

```python
uuid.uuid4()
```

The benchmark `question_id` and the actual API `message_id` represent different concepts.

- `question_id` identifies the benchmark case.
- `message_id` identifies the individual API request.

Separating them avoids accidental request reuse across runs.

---

# 7. Streaming Response Integration

The target endpoint returns a streaming response.

The response should not be treated as one normal JSON object.

The observed format is one JSON object per line.

Example:

```json
{"type":"text","content":"The attraction "}
{"type":"text","content":"opens at "}
{"type":"text","content":"9:00 AM."}
{"type":"followups","items":[]}
```

The dispatcher keeps only objects where:

```text
type == "text"
```

The content fragments are concatenated in order:

```text
"The attraction "
+
"opens at "
+
"9:00 AM."
```

Result:

```text
The attraction opens at 9:00 AM.
```

Follow-up objects are ignored because they are not part of the answer being evaluated.

The dispatcher therefore does not use:

```python
response.json()
```

for this endpoint.

Instead, it reads the response as a stream and reconstructs the complete answer.

---

# 8. UTF-8 Handling

The stream may contain non-ASCII content such as:

- smart quotes
- en dashes
- international names
- other Unicode characters

The dispatcher explicitly handles the streamed body as UTF-8 so answer text is not corrupted by an incorrect encoding assumption.

---

# 9. Dataset Validation

The benchmark is validated before any API request is made.

Required columns:

```text
question_id
query
answer
```

Validation includes:

### Missing dataset

Fails immediately if `benchmark_dataset.csv` does not exist.

### Missing columns

Fails if any required column is absent.

### Empty dataset

Fails if the file contains a header but no data rows.

### Empty question ID

Fails because every result needs a stable identifier.

### Empty question

Fails because there is no valid request to send.

### Duplicate question IDs

Fails before the first API request.

This prevents a bad input dataset from creating a partially processed benchmark run.

---

# 10. Excel / BOM Handling

CSV files saved by Excel may contain a UTF-8 Byte Order Mark.

The dispatcher uses:

```python
encoding="utf-8-sig"
```

This allows both normal UTF-8 CSV files and BOM-prefixed files to work correctly.

Without this, the first column name can be corrupted and validation may fail unexpectedly.

---

# 11. Concurrency

The dispatcher uses:

```python
concurrent.futures.ThreadPoolExecutor
```

to process multiple benchmark questions concurrently.

Default configuration:

```env
MAX_WORKERS=5
```

Conceptually:

```text
Q001 -> Worker 1 -> API
Q002 -> Worker 2 -> API
Q003 -> Worker 3 -> API
Q004 -> Worker 4 -> API
Q005 -> Worker 5 -> API
```

Concurrency is configurable.

A modest value is used initially because the target API's real rate limits should be measured before increasing the number of simultaneous requests.

---

# 12. Per-Request Throttling

The dispatcher also supports:

```env
SLEEP_AFTER_REQUEST_SECONDS=1.0
```

Each worker pauses after completing a request.

This provides simple client-side throttling.

Concurrency and throttling are separate concepts:

```text
MAX_WORKERS
    =
number of requests allowed to be processed concurrently

SLEEP_AFTER_REQUEST_SECONDS
    =
delay before the worker starts another request
```

---

# 13. Retry Strategy

Not all failures should be retried.

The dispatcher retries transient failures such as:

```text
Timeout
Connection error
HTTP 429
HTTP 5xx
```

Normal client-side errors such as:

```text
401
404
422
```

are not repeatedly retried because sending the same invalid request again is unlikely to fix it.

Configuration:

```env
MAX_ATTEMPTS=3
RETRY_BASE_DELAY_SECONDS=1.0
```

The retry delay uses exponential backoff:

```text
Attempt 1
   |
   +-- wait 1s
   |
Attempt 2
   |
   +-- wait 2s
   |
Attempt 3
```

This reduces unnecessary pressure on an already-failing service.

---

# 14. Stream Idle Timeout

Streaming APIs require a different timeout approach from a normal single-response request.

The dispatcher uses:

```env
STREAM_IDLE_TIMEOUT_SECONDS=60
```

This is the maximum allowed period with no incoming stream data.

It is intended to detect a stalled stream rather than enforcing a strict total response duration.

---

# 15. Error Isolation

A single failed question should not terminate the whole benchmark.

Example:

```text
Q001 -> success
Q002 -> success
Q003 -> 500 -> retry -> success
Q004 -> timeout -> retry -> error
Q005 -> success
```

The result for `Q004` is recorded as an error.

The other questions still complete.

This is important for larger benchmark runs because isolated API failures are expected to happen.

---

# 16. Result Model

Each question produces a structured result containing information such as:

```text
question_id
query
dataset_answer
target_response
status
http_status
error
attempts
latency_seconds
timestamp_utc
```

Example:

```json
{
  "question_id": "Q001",
  "query": "What is the opening time?",
  "dataset_answer": "The attraction opens at 9:00 AM.",
  "target_response": "The attraction opens at 9:00 AM.",
  "status": "success",
  "http_status": 200,
  "error": null,
  "attempts": 1,
  "latency_seconds": 8.42,
  "timestamp_utc": "2026-09-12T10:00:00+00:00"
}
```

---

# 17. `rag_results.json`

This file contains the full operational record of the run.

It is useful for:

- debugging
- latency analysis
- retry analysis
- failure investigation
- HTTP status analysis
- operational monitoring

The file can contain:

```text
question
answer
status
HTTP status
attempts
latency
error
timestamp
```

Generated runtime results are not intended to be committed to Git.

---

# 18. `evaluation_input.json`

This is the clean evaluation-facing output.

Example:

```json
[
  {
    "question_id": "Q001",
    "query": "What is the opening time?",
    "answer": "The attraction opens at 9:00 AM.",
    "app_answer": "The attraction opens at 9:00 AM."
  }
]
```

Fields:

```text
question_id
query
answer
app_answer
```

Meaning:

- `question_id` = benchmark case ID
- `query` = benchmark question
- `answer` = reference/dataset answer
- `app_answer` = answer returned by the RAG application

The evaluation layer can consume this file without calling the target API again.

This is intentional:

> Call the API once, store the response, and evaluate the stored result.

---

# 19. Separation of Dispatch and Evaluation

The current project intentionally separates API execution from scoring.

## Stage A — Dispatch

```text
Benchmark
   |
   v
Target RAG API
   |
   v
Collected Answers
   |
   v
evaluation_input.json
```

## Stage B — Evaluation

```text
evaluation_input.json
        |
        v
Evaluation Engine
        |
        +-- Accuracy
        +-- Relevance
        +-- Faithfulness
        +-- Groundedness
        +-- Context Precision
        +-- Context Recall
        +-- Similarity
        +-- Hard validation rules
        |
        v
Evaluation Report
```

This separation makes the system easier to test and prevents repeated API calls when experimenting with different evaluators.

---

# 20. Why the Dataset Answer Is Preserved

The benchmark contains:

```text
answer
```

The target RAG API produces:

```text
app_answer
```

The eventual evaluation compares these or uses them as part of a richer evaluator workflow:

```text
Reference / Golden Answer
          vs
RAG Application Answer
```

The current dispatcher does not make the final quality decision.

That is deliberate.

The first stage should prove that:

- the correct questions were sent
- authentication worked
- responses were received
- streamed text was reconstructed
- errors were handled correctly
- results were stored correctly

Only then should scoring be added.

---

# 21. Graceful Shutdown

The dispatcher handles:

```text
Ctrl+C
SIGTERM
```

Already-completed results are written before the process exits.

For a long benchmark run this helps prevent useful completed work from being lost if execution is interrupted.

Conceptually:

```text
Completed results
       |
       v
Write results
       |
       v
Exit
```

---

# 22. Empty Successful Stream Handling

A successful HTTP response does not always mean that a usable answer was received.

Example:

```text
HTTP 200
but no text chunks
```

The dispatcher treats this as an error rather than silently recording an empty answer as success.

This prevents false-positive operational results such as:

```text
HTTP 200
answer = ""
status = success
```

---

# 23. Example End-to-End Run

From WSL:

```bash
cd /mnt/c/Users/Kethan/Downloads/workiq-rag-chat-poc-current
```

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Make sure `.env` contains the real local configuration.

Then run:

```bash
python3 dispatch_to_target.py
```

The process is:

```text
1. Load benchmark_dataset.csv
2. Validate the dataset
3. Load .env
4. Validate URL/token
5. Create worker threads
6. Send POST /chat requests
7. Authenticate with Bearer token
8. Read streaming response
9. Reconstruct answer text
10. Retry transient failures
11. Record success/error
12. Store operational results
13. Store evaluation-ready results
```

---

# 24. Example Console Output

A successful run can look like:

```text
Loaded 50 questions from benchmark_dataset.csv
Target: https://... | concurrency=5 | sleep/request=1.0s | max_attempts=3 | auth=yes

[OK ] Q001  8.214s  attempts=1
[OK ] Q002  7.942s  attempts=1
[OK ] Q003  9.182s  attempts=1
[ERR] Q004  31.004s attempts=3
[OK ] Q005  8.771s  attempts=1
```

At the end:

```text
49/50 succeeded.
Results written to rag_results.json
Evaluation-ready file written to evaluation_input.json
No comparison against dataset_answer performed - that's a later phase.
```

---

# 25. Security Principles

## Never hardcode the bearer token

Do not write:

```python
TARGET_API_TOKEN = "eyJ..."
```

Use:

```python
TARGET_API_TOKEN = os.environ.get("TARGET_API_TOKEN", "")
```

## Never commit the real `.env`

The local `.env` should contain real credentials.

The repository contains only `.env.example` with placeholders.

## Never put production credentials into `.env.example`

Use:

```env
TARGET_API_TOKEN=your-bearer-token-here
```

not the real token.

## Never print the real token

Logging should indicate whether authentication is configured, not reveal the credential.

---

# 26. Testing Strategy

The project is designed to support multiple levels of testing.

## Unit testing

Test isolated logic such as:

- dataset validation
- environment configuration
- retry classification
- stream parsing
- error handling
- output creation

## Integration testing

Test the Python dispatcher against a running API endpoint:

```text
Python
   |
   v
POST /chat
   |
   v
Target API
   |
   v
Streaming response
```

## Batch testing

Run the dispatcher against the complete benchmark:

```text
1 question
10 questions
50 questions
100+ questions
```

and measure:

- success rate
- failure rate
- latency
- retry count
- HTTP status distribution

## Evaluation testing

Later compare:

```text
reference answer
        vs
RAG application answer
```

and validate that intentionally incorrect answers are detected.

---

# 27. Future Evaluation Layer

The next major stage is to add an evaluator after `evaluation_input.json`.

Possible quality dimensions include:

```text
Accuracy / Correctness
Relevance
Faithfulness
Groundedness
Context Precision
Context Recall
Semantic Similarity
Exact Match
Numeric / Unit Consistency
Negative-case validation
```

Where retrieval context is available, retrieval-specific metrics can also be calculated.

Where the target API exposes only the final answer, evaluation should be limited to metrics that can be supported by the available evidence.

---

# 28. Planned Work IQ Integration

The planned full workflow is:

```text
SharePoint / OneDrive
        |
        v
Microsoft Work IQ
        |
        v
Generate / Validate Benchmark QA
        |
        v
Freeze Golden Dataset
        |
        +-------------------------+
        |                         |
        v                         v
Work IQ Reference Answer     RAG Application /chat
        |                         |
        +------------+------------+
                     |
                     v
                 Evaluator
                     |
                     v
              Metrics + Gates
                     |
                     v
              Evaluation Report
```

Important design principle:

A live Work IQ answer should not automatically be treated as absolute ground truth. Golden answers should be validated and frozen for reproducible benchmarking.

---

# 29. Recommended Future Result Contract

A future evaluation record can expand to include:

```text
case_id
question_id
question_type
question
golden_answer
app_answer
source_document
source_location
expected_facts
retrieved_context
retrieval_metadata
accuracy_score
relevance_score
faithfulness_score
groundedness_score
latency
http_status
decision
review_reason
```

This creates a richer evaluation record suitable for reporting and human review.

---

# 30. Current Limitations

The current POC does not yet implement:

- Microsoft Work IQ REST API
- Microsoft Entra ID / MSAL
- SharePoint / OneDrive discovery
- Microsoft Graph
- semantic retrieval
- vector database
- embeddings
- LLM generation
- automatic QA generation
- Work IQ golden-answer generation
- final quality scoring
- human review workflow
- evaluation dashboard

These are later stages of the overall project.

---

# 31. Current Status

Implemented and validated at the POC level:

```text
[OK] Benchmark dataset loading
[OK] Dataset validation
[OK] .env configuration
[OK] Protected endpoint authentication
[OK] Bearer token handling
[OK] POST /chat dispatch
[OK] Streaming response consumption
[OK] Stream text reconstruction
[OK] Concurrent request execution
[OK] Retry handling
[OK] Per-question failure isolation
[OK] Latency tracking
[OK] Operational result capture
[OK] Evaluation-ready output
```

Next stage:

```text
Microsoft Work IQ
        +
Golden QA dataset
        +
RAG answer collection
        +
Evaluation metrics
        +
Quality gates
        +
Final evaluation report
```

---

# 32. Quick Start

```bash
cd /mnt/c/Users/Kethan/Downloads/workiq-rag-chat-poc-current

python3 -m venv .venv

source .venv/bin/activate

python3 -m pip install -r requirements.txt
```

Create `.env`:

```env
TARGET_API_URL=https://your-real-target-endpoint
TARGET_API_TOKEN=your-real-bearer-token

MAX_WORKERS=5
SLEEP_AFTER_REQUEST_SECONDS=1.0
REQUEST_TIMEOUT_SECONDS=30
STREAM_IDLE_TIMEOUT_SECONDS=60
MAX_ATTEMPTS=3
RETRY_BASE_DELAY_SECONDS=1.0
```

Run:

```bash
python3 dispatch_to_target.py
```

Outputs:

```text
rag_results.json
evaluation_input.json
```

---

# License

See `LICENSE`.
