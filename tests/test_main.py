import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class MockServerLogicTests(unittest.TestCase):
    def test_normalize_case_and_whitespace(self):
        self.assertEqual(
            main._normalize("  Hello   WORLD  "),
            "hello world",
        )

    def test_loaded_dataset_has_expected_size(self):
        self.assertEqual(len(main.QA_LOOKUP), 16)

    def test_known_query_lookup(self):
        answer = main.QA_LOOKUP[main._normalize(
            "What is the maximum operating speed of the attraction?"
        )]
        self.assertEqual(answer, "The maximum operating speed is 80 km/h.")

    def test_unknown_query_uses_fallback(self):
        key = main._normalize("Unknown question")
        self.assertEqual(main.QA_LOOKUP.get(key, main.FALLBACK_ANSWER), main.FALLBACK_ANSWER)

    def test_dataset_loader_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("id,query\nQ1,Hello\n", encoding="utf-8")
            with patch.object(main, "DATA_PATH", path):
                with self.assertRaises(ValueError):
                    main.load_dataset()


class AuthGateTests(unittest.TestCase):
    """Covers the behavior added when JWT auth was put in front of /chat.
    These hit the real HTTP layer (via TestClient) rather than internal
    functions, since the thing being tested is the Depends() wiring
    itself, not just the token-verification logic in isolation."""

    def setUp(self):
        self.client = TestClient(main.app)
        self.payload = {
            "message_id": "Q001",
            "query": "What is the maximum operating speed of the attraction?",
            "chat_history": [],
        }

    def test_chat_without_token_is_rejected(self):
        response = self.client.post("/chat", json=self.payload)
        self.assertEqual(response.status_code, 401)

    def test_chat_with_malformed_header_is_rejected(self):
        response = self.client.post(
            "/chat", json=self.payload, headers={"Authorization": "not-a-bearer-token"}
        )
        self.assertEqual(response.status_code, 401)

    def test_chat_with_garbage_token_is_rejected(self):
        response = self.client.post(
            "/chat", json=self.payload, headers={"Authorization": "Bearer garbage.token.value"}
        )
        self.assertEqual(response.status_code, 401)

    def test_dev_token_then_chat_succeeds(self):
        token_response = self.client.get("/dev/token")
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["access_token"]

        chat_response = self.client.post(
            "/chat", json=self.payload, headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(chat_response.text, "The maximum operating speed is 80 km/h.")

    def test_dev_token_endpoint_disabled_outside_dev(self):
        with patch.object(main.auth, "MOCK_ENV", "prod"):
            response = self.client.get("/dev/token")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
