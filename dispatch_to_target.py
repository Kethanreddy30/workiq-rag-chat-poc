import concurrent.futures

import csv

import json

import os

import signal

import sys

import time

import uuid

from dataclasses import asdict, dataclass

from datetime import datetime, timezone

from pathlib import Path

from typing import Optional



from dotenv import load_dotenv

import requests



# Load local environment variables from .env (which must remain git-ignored).

load_dotenv()



# ---------------------------------------------------------------------------

# Config - all values come from environment variables.

# No target URL or bearer token is hardcoded in source code.

# ---------------------------------------------------------------------------

TARGET_API_URL = os.environ.get("TARGET_API_URL", "").strip()

TARGET_API_TOKEN = os.environ.get("TARGET_API_TOKEN", "").strip()



if not TARGET_API_URL:

    raise ValueError(

        "TARGET_API_URL is not set. Add it to your local .env file."

    )



if not TARGET_API_TOKEN:

    raise ValueError(

        "TARGET_API_TOKEN is not set. Add it to your local .env file."

    )



if not TARGET_API_URL.startswith(("http://", "https://")):

    raise ValueError(

        f"TARGET_API_URL doesn't look like a URL: {TARGET_API_URL!r}. "

        f"Check it's set correctly (missing http:// or https://?)."

    )



DATASET_PATH = Path(__file__).resolve().parent / "benchmark_dataset.csv"

# Full operational record - includes status/latency/retries/etc.

# Matches an existing .gitignore pattern.

RESULTS_PATH = Path(__file__).resolve().parent / "rag_results.json"

# Clean evaluation input - just the dataset's own shape plus app_answer,

# no operational metadata. Derived from the same run, no extra requests.

EVALUATION_INPUT_PATH = Path(__file__).resolve().parent / "evaluation_input.json"



# How many requests can be in flight at once. Kept modest by default since

# the target's real rate limits are unknown. Clamped to >=1 with a clear

# message here rather than letting ThreadPoolExecutor raise its own

# less obvious ValueError later.

MAX_WORKERS = max(1, int(os.environ.get("MAX_WORKERS", "5")))



# Every worker sleeps this long after EACH response (success or failure)

# before it's free to pick up the next question - throttles each

# worker's own rate without giving up concurrency across workers.

# Clamped to >=0 - a negative value would otherwise reach time.sleep()

# and raise ValueError deep inside a request, not at startup.

SLEEP_AFTER_REQUEST_SECONDS = max(0.0, float(os.environ.get("SLEEP_AFTER_REQUEST_SECONDS", "1.0")))



# Connect timeout.

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))



# Read/idle timeout while streaming - "no bytes received for this many

# seconds", re-armed after every chunk. Not a cap on total stream

# duration. Real responses take ~7-10s; 60s gives comfortable margin

# without leaving a worker hung forever on a truly dead connection.

STREAM_IDLE_TIMEOUT_SECONDS = float(os.environ.get("STREAM_IDLE_TIMEOUT_SECONDS", "60"))





# Bounded retry, NOT a 30s/2min/10min production schedule - this is a

# one-shot batch script, a failed question gets recorded and the batch

# moves on. Only transient failures are retried (timeout, connection

# error, 5xx, 429, or a 200 that produced no usable text); a 401/422

# fails identically on retry, so those are recorded immediately instead.

MAX_ATTEMPTS = max(1, int(os.environ.get("MAX_ATTEMPTS", "3")))

RETRY_BASE_DELAY_SECONDS = max(0.0, float(os.environ.get("RETRY_BASE_DELAY_SECONDS", "1.0")))





class EmptyStreamResponseError(Exception):

    """Target returned 200 OK but no "text" chunks came out of the

    stream (e.g. a followups-only response, or a genuinely empty body).

    This is a failure to get an answer, even though the HTTP call

    itself didn't error - treated as one: retried, then recorded as

    status="error" if retries run out, never as a silent success."""





class _GracefulShutdownRequested(BaseException):

    """Raised from the SIGTERM handler so a killed batch job (e.g. a CI

    timeout, a container being stopped) gets the same partial-results

    handling as Ctrl+C (KeyboardInterrupt), instead of losing every

    result collected so far.



    Inherits from BaseException, not Exception - same as KeyboardInterrupt

    does - so it can never be accidentally swallowed by send_one's broad

    `except Exception` safety net. In practice signals only ever fire in

    the main thread (never inside a worker thread's send_one call), so

    this is correctness-by-construction rather than a fix for something

    currently reachable."""





def _handle_sigterm(signum, frame) -> None:

    raise _GracefulShutdownRequested()





try:

    signal.signal(signal.SIGTERM, _handle_sigterm)

except ValueError:

    # signal.signal() only works from the main thread - if this module

    # is ever imported from a worker thread (some test runners do this),

    # skip SIGTERM handling rather than crashing the import. Ctrl+C

    # (KeyboardInterrupt) handling in main() is unaffected either way.

    pass





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

    if not DATASET_PATH.exists():

        raise FileNotFoundError(

            f"Could not find {DATASET_PATH.name} at {DATASET_PATH}. "

            f"Run this script from the repo directory, or check the file wasn't renamed/moved."

        )



    # utf-8-sig, not utf-8: strips a leading BOM if present (common in

    # CSVs saved from Excel), and behaves identically to utf-8 when

    # there's no BOM. Without this, a BOM silently corrupts the first

    # column name (question_id becomes \ufeffquestion_id), which then

    # fails the "missing columns" check below with a confusing error

    # that doesn't mention the real cause.

    with open(DATASET_PATH, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)

        required = {"question_id", "query", "answer"}

        missing = required - set(reader.fieldnames or [])

        if missing:

            raise ValueError(f"{DATASET_PATH.name} missing columns: {sorted(missing)}")

        rows = list(reader)



    if not rows:

        raise ValueError(f"{DATASET_PATH.name} has a header but no data rows")



    # Fail before any API calls, not partway through the batch - a bad

    # question_id (blank/duplicate) is a data problem, not something

    # retrying or dispatching would fix.

    seen_ids: set[str] = set()

    for line_num, row in enumerate(rows, start=2):  # +1 header, 1-indexed

        qid = (row.get("question_id") or "").strip()

        query = (row.get("query") or "").strip()

        if not qid:

            raise ValueError(f"{DATASET_PATH.name} line {line_num}: empty question_id")

        if not query:

            raise ValueError(f"{DATASET_PATH.name} line {line_num}: empty query for question_id={qid!r}")

        if qid in seen_ids:

            raise ValueError(f"{DATASET_PATH.name} has duplicate question_id: {qid!r}")

        seen_ids.add(qid)



    return rows





def _is_retryable(exc: Exception) -> bool:

    if isinstance(exc, EmptyStreamResponseError):

        return True

    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:

        return exc.response.status_code >= 500 or exc.response.status_code == 429

    return isinstance(

        exc,

        (

            requests.exceptions.Timeout,

            requests.exceptions.ConnectionError,

            requests.exceptions.ChunkedEncodingError,  # stream cut off mid-transfer

        ),

    )





def _extract_answer_text(response: requests.Response) -> str:

    """Assembles the answer from the target's streamed body.



    Confirmed format: one JSON object per line. Only {"type": "text",

    "content": "<fragment>"} lines matter - their "content" values are

    concatenated in order. Anything else (the trailing "followups" line,

    a malformed line, an unrecognized shape) is silently skipped, not

    appended - we were told followups don't need to be captured, and a

    malformed line here is noise, not signal.



    requests defaults text/plain responses with no explicit charset to

    ISO-8859-1, not UTF-8. Forced to UTF-8 here since the body is JSON

    (UTF-8 by spec) and real answers contain non-ASCII characters

    (smart quotes, en dashes).

    """

    response.encoding = "utf-8"



    parts: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):

        if not raw_line:

            continue

        try:

            obj = json.loads(raw_line)

        except (json.JSONDecodeError, ValueError):

            continue

        if isinstance(obj, dict) and obj.get("type") == "text":

            parts.append(str(obj.get("content", "")))



    return "".join(parts)





def send_one(row: dict) -> QuestionResult:

    """Never raises - always returns a QuestionResult, even for a bug

    or edge case _send_one_inner doesn't anticipate. Proven necessary,

    not just defensive: without this wrapper, one unexpected exception

    on a single question propagates through the thread pool and crashes

    the entire batch, losing every other result already collected -

    verified this actually happens before adding the fix."""

    try:

        return _send_one_inner(row)

    except Exception as exc:  # noqa: BLE001 - intentionally broad, see docstring

        return QuestionResult(

            question_id=str(row.get("question_id", "UNKNOWN")),

            query=str(row.get("query", "")),

            dataset_answer=str(row.get("answer", "")),

            target_response=None,

            status="error",

            http_status=None,

            error=f"unexpected error (not a normal API failure): {type(exc).__name__}: {exc}",

            attempts=0,

            latency_seconds=None,

            timestamp_utc=datetime.now(timezone.utc).isoformat(),

        )





def _send_one_inner(row: dict) -> QuestionResult:

    question_id = row["question_id"]

    query = row["query"]



    # Generated once per question, reused across retry attempts - a

    # retry is the same logical request going out again, not a new one.

    message_id = str(uuid.uuid4())

    payload = {"message_id": message_id, "query": query, "chat_history": []}

    headers = {}

    if TARGET_API_TOKEN:

        headers["Authorization"] = f"Bearer {TARGET_API_TOKEN}"



    start = time.monotonic()

    last_exc: Optional[Exception] = None

    last_http_status: Optional[int] = None

    attempt = 0



    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            response = requests.post(

                TARGET_API_URL,

                json=payload,

                headers=headers,

                timeout=(REQUEST_TIMEOUT_SECONDS, STREAM_IDLE_TIMEOUT_SECONDS),

                stream=True,

            )

            last_http_status = response.status_code

            response.raise_for_status()

            text = _extract_answer_text(response)

            if not text.strip():

                # 200 OK but no usable answer text - a failure to get an

                # answer, not a real success. Caught below, retried like

                # any other transient failure.

                raise EmptyStreamResponseError(

                    "target returned 200 OK but no 'text' chunks were found in the stream"

                )



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

        except (requests.exceptions.RequestException, EmptyStreamResponseError) as exc:

            last_exc = exc

            if attempt < MAX_ATTEMPTS and _is_retryable(exc):

                time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))

                continue

            break



    # Every attempt failed - record it as an error, never as a silent

    # success. HTTPError carries its own .response; EmptyStreamResponseError

    # doesn't, but last_http_status still holds the real 200 that failed

    # to parse into anything usable.

    latency = time.monotonic() - start

    time.sleep(SLEEP_AFTER_REQUEST_SECONDS)

    status_code = getattr(getattr(last_exc, "response", None), "status_code", None) or last_http_status

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





def _write_outputs(results: list[QuestionResult]) -> None:

    """Writes both output files. If a write itself fails (disk full,

    permissions, whatever), the results already cost real API calls -

    losing them silently on top of that would compound the failure, so

    they're dumped to stdout as a fallback instead of just raising."""

    results = sorted(results, key=lambda r: r.question_id)



    try:

        with open(RESULTS_PATH, "w", encoding="utf-8") as f:

            json.dump([asdict(r) for r in results], f, indent=2)

    except OSError as exc:

        print(f"WARNING: failed to write {RESULTS_PATH.name}: {exc}")

        print(f"Dumping {RESULTS_PATH.name} contents to stdout so the run's results aren't lost:")

        print(json.dumps([asdict(r) for r in results], indent=2))



    # Evaluation-ready view: the dataset's own shape (question_id, query,

    # answer) plus app_answer. No status/latency/timestamp - that stays

    # in rag_results.json for debugging this run, not for scoring it.

    # app_answer is explicitly null (not omitted) for a failed question,

    # so a missing answer is visible to whatever scores this later,

    # not silently absent.

    evaluation_rows = [

        {

            "question_id": r.question_id,

            "query": r.query,

            "answer": r.dataset_answer,

            "app_answer": r.target_response,

        }

        for r in results

    ]

    try:

        with open(EVALUATION_INPUT_PATH, "w", encoding="utf-8") as f:

            json.dump(evaluation_rows, f, indent=2, ensure_ascii=False)

    except OSError as exc:

        print(f"WARNING: failed to write {EVALUATION_INPUT_PATH.name}: {exc}")

        print(f"Dumping {EVALUATION_INPUT_PATH.name} contents to stdout so the run's results aren't lost:")

        print(json.dumps(evaluation_rows, indent=2, ensure_ascii=False))





def main() -> None:

    rows = load_questions()

    print(f"Loaded {len(rows)} questions from {DATASET_PATH.name}")

    print(

        f"Target: {TARGET_API_URL} | concurrency={MAX_WORKERS} | "

        f"sleep/request={SLEEP_AFTER_REQUEST_SECONDS}s | max_attempts={MAX_ATTEMPTS} | "

        f"auth={'yes' if TARGET_API_TOKEN else 'no (TARGET_API_TOKEN not set)'}"

    )



    results: list[QuestionResult] = []

    try:

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:

            # A plain list, not a dict keyed by question_id - correlation

            # doesn't happen here. It happens inside send_one, where each

            # QuestionResult already carries its own question_id alongside

            # the response that same call received.

            futures = [pool.submit(send_one, row) for row in rows]

            for future in concurrent.futures.as_completed(futures):

                # send_one is guaranteed to never raise (see its

                # docstring), so future.result() is not expected to

                # raise here either - nothing further to guard.

                result = future.result()

                results.append(result)

                marker = "OK " if result.status == "success" else "ERR"

                print(f"[{marker}] {result.question_id}  {result.latency_seconds}s  attempts={result.attempts}")

    except (KeyboardInterrupt, _GracefulShutdownRequested) as exc:

        # In-flight requests (up to MAX_WORKERS of them) are allowed to

        # finish before this point - the executor's own shutdown waits

        # for currently-running tasks rather than abandoning open HTTP

        # connections mid-request. Anything not yet started is dropped.

        reason = "Ctrl+C" if isinstance(exc, KeyboardInterrupt) else "SIGTERM"

        print(f"\nInterrupted ({reason}) - {len(results)}/{len(rows)} questions completed.")

        print("Writing partial results so completed work isn't lost...")

        _write_outputs(results)

        raise



    _write_outputs(results)



    succeeded = sum(1 for r in results if r.status == "success")

    print(f"\n{succeeded}/{len(results)} succeeded. Results written to {RESULTS_PATH.name}")

    print(f"Evaluation-ready file written to {EVALUATION_INPUT_PATH.name}")

    print("No comparison against dataset_answer performed - that's a later phase.")





if __name__ == "__main__":

    try:

        main()

    except (KeyboardInterrupt, _GracefulShutdownRequested):

        # Already logged and partial results already written inside

        # main() - this just avoids a scary raw traceback for what's

        # meant to be a clean, expected shutdown path, while still

        # exiting non-zero so a caller (shell, CI) can tell the run

        # didn't finish normally.

        sys.exit(130)
