"""
Deterministic mock RAG /chat server for POC testing.

Contract:
  POST /chat
  Request body:
    {
      "message_id": "Q001",
      "query": "What is ...?",
      "chat_history": []
    }

Response:
    streamed text/plain

Behavior:
  - Loads dataset.csv once at startup.
  - Normalized exact-match lookup.
  - Returns a deterministic static answer.
  - Unknown queries return FALLBACK_ANSWER.
  - /chat requires a Bearer JWT (mock HS256 auth - see auth.py).
  - Streams the deterministic answer to the client.
  - No real LLM or retrieval is implemented.
"""

import csv
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()  # must run before importing auth, which reads env at import time
import auth  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = APP_DIR / "dataset.csv"

FALLBACK_ANSWER = (
    "I don't have information on that. Please contact a maintenance "
    "supervisor for further assistance."
)

app = FastAPI(title="Maintenance Chat Mock (POC)", version="1.0.0")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def load_dataset() -> dict[str, str]:
    lookup: dict[str, str] = {}

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATA_PATH}")

    with DATA_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"id", "category", "query", "answer"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"dataset.csv missing columns: {sorted(missing)}")

        for row in reader:
            query = (row.get("query") or "").strip()
            answer = (row.get("answer") or "").strip()
            if not query:
                continue
            if not answer:
                raise ValueError(f"Blank answer for query: {query!r}")
            lookup[_normalize(query)] = answer

    return lookup


QA_LOOKUP = load_dataset()


class ChatHistoryItem(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    answer: str = Field(..., min_length=1, max_length=5000)


class ChatRequest(BaseModel):
    message_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    query: str = Field(..., min_length=1, max_length=5000)
    chat_history: List[ChatHistoryItem] = Field(
        default_factory=list,
        max_length=50,
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "loaded_qa_pairs": len(QA_LOOKUP),
    }


@app.get("/dev/token")
async def dev_token():
    """Mints a mock bearer token for local testing.

    Gated on MOCK_ENV=dev (see auth.py) so this doesn't quietly stay live
    if this code is ever deployed anywhere that isn't a local dev/POC run.
    """
    if auth.MOCK_ENV != "dev":
        raise HTTPException(status_code=404)
    return {
        "access_token": auth.create_mock_token(),
        "token_type": "bearer",
        "expires_in_minutes": auth.JWT_EXPIRE_MINUTES,
    }


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    claims: dict = Depends(auth.require_auth),
):
    key = _normalize(payload.query)
    answer = QA_LOOKUP.get(key, FALLBACK_ANSWER)

    async def generate():
        # Mock streaming: send the deterministic answer in small chunks.
        chunk_size = 20
        for i in range(0, len(answer), chunk_size):
            yield answer[i : i + chunk_size]

    return StreamingResponse(
        generate(),
        media_type="text/plain",
    )
