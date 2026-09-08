"""
Tiny smoke-test client for the mock /chat endpoint.

Run the mock server first:
    uvicorn main:app --reload --port 8000

Then:
    python smoke_test.py
"""

import json
from urllib import request


BASE_URL = "http://127.0.0.1:8000"
TOKEN_URL = f"{BASE_URL}/dev/token"
CHAT_URL = f"{BASE_URL}/chat"


def get_dev_token() -> str:
    with request.urlopen(TOKEN_URL, timeout=15) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["access_token"]


def call_chat(message_id: str, query: str, token: str) -> str:
    payload = {
        "message_id": message_id,
        "query": query,
        "chat_history": [],
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        CHAT_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    with request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8")


def main() -> None:
    cases = [
        ("Q001", "What is the maximum operating speed of the attraction?"),
        ("Q007", "Does the document state that riders below 120 cm are permitted?"),
        ("Q999", "What is the color of the operator uniform?"),
    ]

    token = get_dev_token()

    for case_id, question in cases:
        answer = call_chat(case_id, question, token)
        print(f"{case_id}")
        print(f"Q: {question}")
        print(f"A: {answer}")
        print("-" * 60)


if __name__ == "__main__":
    main()
