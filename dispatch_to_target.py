"""
Dispatches every question in benchmark_dataset.csv to the target /chat
endpoint and records what comes back, keyed by question_id.

This does NOT compare the target's answer to the dataset's `answer`
column - that's a later phase. Right now the only job is: send all 50
questions, capture what the target actually returns (or the error if it
didn't), and write it to results.json so a comparison step can consume
it later without re-hitting the API.

Target contract (from the target's own OpenAPI docs, not guessed):
  POST /chat
  Authorization: Bearer <token>   - required by the target; see
                                     TARGET_API_TOKEN below.
  Body: {"message_id": str, "query": str, "chat_history": []}
  Response: text/plain, StreamingResponse - NOT JSON. Calling
  response.json() on this will throw; this script reads it as text.

TARGET_API_URL is a placeholder (the real endpoint doesn't exist yet).
Set TARGET_API_URL / TARGET_API_TOKEN as environment variables once it
does - no code changes needed.
"""

import concurrent.futures
import csv
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import requests

load_dotenv()
# ---------------------------------------------------------------------------
# Config - all overridable via environment variables, defaults sized for a
# one-off 50-row batch against an endpoint whose real limits are unknown.
# ---------------------------------------------------------------------------
TARGET_API_URL = os.environ.get("TARGET_API_URL", "https://your-api-url.com/chat")
TARGET_API_TOKEN = os.environ.get("TARGET_API_TOKEN", "")  # blank until real auth exists

DATASET_PATH = Path(__file__).resolve().parent / "benchmark_dataset.csv"
# Matches an existing .gitignore pattern - keeps runtime output out of git
# without needing a .gitignore edit for one more one-off filename.
RESULTS_PATH = Path(__file__).resolve().parent / "rag_results.json"

# How many requests can be in flight at once. Kept modest by default since
# the target's real rate limits are unknown - raise this only once you've
# confirmed the target can take it.
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "5"))

# Every worker sleeps this long after EACH response (success or failure)
# before it's free to pick up the next question. This throttles the
# effective request rate per worker without giving up the concurrency
# across workers.
SLEEP_AFTER_REQUEST_SECONDS = float(os.environ.get("SLEEP_AFTER_REQUEST_SECONDS", "1.0"))

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))

# Bounded retry, NOT the 30s/2min/10min production schedule. A one-shot
# batch script shouldn't block for minutes on a single row - a failed
# question gets recorded and the batch moves on. Only transient failures
# (timeout, connection error, 5xx, 429) are retried; a 401/422/404 will
# fail identically on retry, so those are recorded immediately instead.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
RETRY_BASE_DELAY_SECONDS = float(os.environ.get("RETRY_BASE_DELAY_SECONDS", "1.0"))


@dataclass
class QuestionResult:
    question_id: str
    query: str
    dataset_answer: str
    target_response: Optional[str]
    status: str  # "success" | "error"
    http_status: Optional[int]
    error: Optional[str]
    attempts: int
    latency_seconds: Optional[float]
    timestamp_utc: str


def load_questions() -> list[dict]:
    with open(DATASET_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"question_id", "query", "answer"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{DATASET_PATH.name} missing columns: {sorted(missing)}")
        return list(reader)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))


def send_one(row: dict) -> QuestionResult:
    question_id = row["question_id"]
    query = row["query"]
    payload = {"message_id": question_id, "query": query, "chat_history": []}
    headers = {}
    if TARGET_API_TOKEN:
        headers["Authorization"] = f"Bearer {TARGET_API_TOKEN}"

    start = time.monotonic()
    last_exc: Optional[Exception] = None
    attempt = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # stream=True respects the target's documented StreamingResponse.
            # response.text below reads/decodes the full stream - correct
            # for this batch use case since we need the complete answer
            # before we can record it, not a progressive UI render.
            response = requests.post(
                TARGET_API_URL,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=True,
            )
            response.raise_for_status()
            text = response.text
            latency = time.monotonic() - start
            time.sleep(SLEEP_AFTER_REQUEST_SECONDS)
            return QuestionResult(
                question_id=question_id,
                query=query,
                dataset_answer=row["answer"],
                target_response=text,
                status="success",
                http_status=response.status_code,
                error=None,
                attempts=attempt,
                latency_seconds=round(latency, 3),
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < MAX_ATTEMPTS and _is_retryable(exc):
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                continue
            break

    latency = time.monotonic() - start
    time.sleep(SLEEP_AFTER_REQUEST_SECONDS)
    status_code = getattr(getattr(last_exc, "response", None), "status_code", None)
    return QuestionResult(
        question_id=question_id,
        query=query,
        dataset_answer=row["answer"],
        target_response=None,
        status="error",
        http_status=status_code,
        error=str(last_exc),
        attempts=attempt,
        latency_seconds=round(latency, 3),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )


def main() -> None:
    rows = load_questions()
    print(f"Loaded {len(rows)} questions from {DATASET_PATH.name}")
    print(
        f"Target: {TARGET_API_URL} | concurrency={MAX_WORKERS} | "
        f"sleep/request={SLEEP_AFTER_REQUEST_SECONDS}s | max_attempts={MAX_ATTEMPTS} | "
        f"auth={'yes' if TARGET_API_TOKEN else 'no (TARGET_API_TOKEN not set)'}"
    )

    results: list[QuestionResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(send_one, row): row["question_id"] for row in rows}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            marker = "OK " if result.status == "success" else "ERR"
            print(f"[{marker}] {result.question_id}  {result.latency_seconds}s  attempts={result.attempts}")

    results.sort(key=lambda r: r.question_id)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)

    succeeded = sum(1 for r in results if r.status == "success")
    print(f"\n{succeeded}/{len(results)} succeeded. Results written to {RESULTS_PATH.name}")
    print("No comparison against dataset_answer performed - that's a later phase.")


if __name__ == "__main__":
    main()
