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
  text/plain

Behavior:
  - Loads dataset.csv once at startup.
  - Normalized exact-match lookup.
  - Returns a deterministic static answer.
  - Unknown queries return FALLBACK_ANSWER.
  - No real LLM, retrieval, JWT, or streaming is implemented.
"""

import csv
import re
from pathlib import Path
from typing import List

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

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


@app.post("/chat", response_class=PlainTextResponse)
async def chat(payload: ChatRequest) -> str:
    key = _normalize(payload.query)
    return QA_LOOKUP.get(key, FALLBACK_ANSWER)
